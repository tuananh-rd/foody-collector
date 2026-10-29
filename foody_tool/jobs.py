"""One local background crawl, durable checkpoints and user controls."""
import copy
import importlib.util
import json
import math
import os
import re
import threading
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

from .collector import Collector, FINAL_STATUSES, normalize_restaurant_url
from .exporter import export_all

JOB_ID = re.compile(r"^[a-f0-9]{32}$")
ACTIVE_STATES = {"queued", "running", "paused"}
_BROWSER_CHECK = None
_BROWSER_CHECK_LOCK = threading.Lock()


def utcnow():
    return datetime.now(timezone.utc).isoformat()


def atomic_json(path, value):
    path = Path(path)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(temp, path)


class JobStopped(Exception):
    pass


def validate_config(config):
    if not isinstance(config, dict):
        raise ValueError("Cấu hình không hợp lệ.")
    mode = config.get("mode", "sample")
    if mode not in ("sample", "all"):
        raise ValueError("Chọn chạy thử hoặc quét danh sách Hà Nội.")
    limit = config.get("limit", 48) if mode == "sample" else None
    if mode == "sample" and (type(limit) is not int or not 1 <= limit <= 100000):
        raise ValueError("Số quán chạy thử phải từ 1 đến 100.000.")
    interval = config.get("interval", 3)
    if (isinstance(interval, bool) or not isinstance(interval, (int, float))
            or not math.isfinite(interval) or not 2 <= interval <= 120):
        raise ValueError("Khoảng chờ phải từ 2 đến 120 giây.")
    show = config.get("show_browser", True)
    if not isinstance(show, bool):
        raise ValueError("Lựa chọn hiển thị trình duyệt không hợp lệ.")
    return {"mode": mode, "limit": limit, "interval": float(interval), "show_browser": show}


def browser_readiness():
    global _BROWSER_CHECK
    if importlib.util.find_spec("playwright") is None:
        return False, "Cần cài thành phần trình duyệt. Mở lại bằng Start-Foody.cmd để thiết lập."
    with _BROWSER_CHECK_LOCK:
        if _BROWSER_CHECK is None or time.monotonic() - _BROWSER_CHECK[0] > 30:
            from .launcher import browser_available
            _BROWSER_CHECK = (time.monotonic(), browser_available())
        available = _BROWSER_CHECK[1]
    if not available:
        return False, "Chưa có trình duyệt tự động. Mở lại bằng Start-Foody.cmd để thiết lập."
    return True, "Sẵn sàng mở trình duyệt và lấy danh sách quán."


class CrawlJob:
    def __init__(self, directory, config=None, saved=None, *, discovery_factory=None,
                 collector_factory=Collector):
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._artifact_lock = threading.RLock()
        self._pause = threading.Event()
        self._stop = threading.Event()
        self.thread = None
        self._discovery_factory = discovery_factory
        self._collector_factory = collector_factory
        self._collector = None
        self._blocked_reason = None
        self._pending_since_export = 0
        self.urls = []
        urls_file = self.directory / "urls.json"
        if urls_file.exists():
            stored = json.loads(urls_file.read_text(encoding="utf-8"))
            if not isinstance(stored, list):
                raise ValueError("Tiến độ URL không hợp lệ.")
            self.urls = list(dict.fromkeys(normalize_restaurant_url(u) for u in stored))
        if saved:
            self.data = saved
            if self.data.get("state") in ACTIVE_STATES:
                self.data.update(state="paused", message="Phiên trước bị gián đoạn. Có thể tiếp tục.")
        else:
            config = validate_config(config or {})
            self.data = dict(id=self.directory.name, **config, state="queued", stage="discovering",
                             discovered=0, processed=0, success=0, duplicates=0, failed=0,
                             clicks=0, request_count=0, started_at=utcnow(), updated_at=utcnow(),
                             termination_reason=None, coverage_verified=False,
                             message="Đang chuẩn bị mở trình duyệt.", logs=[], report=None, attempts=0)
        self._persist()

    def snapshot(self):
        with self._lock:
            snap = copy.deepcopy(self.data)
            snap["has_enrichment"] = (self.directory / "restaurants_enriched.json").is_file()
            if "enrichment_summary" not in snap:
                rep_path = self.directory / "enrichment_report.json"
                if rep_path.is_file():
                    try:
                        en_rep = json.loads(rep_path.read_text(encoding="utf-8"))
                        snap["enrichment_summary"] = {
                            "pages_total": en_rep.get("pages_total", 0),
                            "pages_parsed": en_rep.get("pages_parsed", 0),
                            "pages_failed": en_rep.get("pages_failed", 0),
                            "field_presence_counts": en_rep.get("field_presence_counts", {}),
                            "amenity_status_counts": en_rep.get("amenity_status_counts", {}),
                        }
                    except Exception:
                        pass
            return snap

    def _persist(self):
        atomic_json(self.directory / "job.json", self.data)

    def update(self, **fields):
        with self._lock:
            self.data.update(fields, updated_at=utcnow())
            self._persist()

    def log(self, message):
        with self._lock:
            self.data["logs"] = (self.data.get("logs", []) + [
                {"time": utcnow(), "message": str(message)}])[-30:]
            self._persist()

    def launch(self):
        if self.thread and self.thread.is_alive():
            if self._pause.is_set():
                self._pause.clear()
                self.update(state="running", message="Đang tiếp tục.")
                return
            raise ValueError("Phiên này đang chạy.")
        self._pause.clear()
        self._stop.clear()
        self._blocked_reason = None
        self.update(state="queued", termination_reason=None, coverage_verified=False,
                    attempts=self.data.get("attempts", 0) + 1,
                    message="Đang chuẩn bị mở trình duyệt.")
        self.thread = threading.Thread(target=self._run, name=f"foody-{self.data['id'][:8]}", daemon=True)
        self.thread.start()

    def pause(self):
        if not self.thread or not self.thread.is_alive() or self._stop.is_set():
            raise ValueError("Phiên không đang chạy.")
        self._pause.set()
        self.update(state="paused", message="Tạm dừng sau khi yêu cầu hiện tại hoàn tất.")

    def stop(self):
        self._stop.set()
        self._pause.clear()
        if self.thread and self.thread.is_alive():
            self.update(message="Đang dừng và lưu tiến độ.")
        else:
            self.update(state="stopped", termination_reason="stopped", message="Đã dừng. Có thể tiếp tục.")

    def checkpoint(self):
        if self._stop.is_set():
            raise JobStopped()
        if self._pause.is_set():
            self._export()
        while self._pause.is_set():
            if self._stop.wait(0.2):
                raise JobStopped()
        if self._stop.is_set():
            raise JobStopped()

    def _counts(self):
        statuses = [self._collector.progress.get(u, {}).get("status", "pending") for u in self.urls]
        self.update(discovered=len(self.urls), processed=sum(s != "pending" for s in statuses),
                    success=statuses.count("ok"), duplicates=statuses.count("duplicate_id"),
                    failed=sum(s not in {"ok", "duplicate_id", "pending"} for s in statuses),
                    request_count=self._request_base + self._collector.request_count)

    def _wait(self, seconds):
        """Interrupt core pacing/backoff between network requests, not an in-flight GET."""
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline:
            self.checkpoint()
            if self._stop.wait(min(0.2, max(0, deadline - time.monotonic()))):
                raise JobStopped()

    def _export(self, result=None):
        if self._collector is None:
            return
        result = result or getattr(self, "_last_result", None) or {
            "reason": "in_progress", "coverage_verified": False,
            "source_url": "https://www.foody.vn/ha-noi/o-dau"}
        reason = result.get("reason")
        stopped_reason = None if reason in {"exhausted", "in_progress"} else reason
        with self._artifact_lock:
            report = export_all(str(self.directory), self._collector.progress,
                                self._collector.records(self.urls), self.urls,
                                stopped_reason=stopped_reason,
                                run_id=self.data["id"])
            report["discovery"] = {k: result.get(k) for k in
                                   ("reason", "clicks", "coverage_verified", "source_url", "error")}
            report["discovery"]["events"] = result.get("events", [])[-50:]
            report["discovery"]["event_time_basis"] = result.get("event_time_basis")
            report["discovery"]["evidence_error"] = result.get("evidence_error")
            report["source_coverage_note"] = "End of the public listing is not proof of every Hanoi restaurant."
            if self.data["mode"] == "all" and result.get("reason") != "exhausted":
                report["partial"] = True
            qpath = self.directory / "quality_report.json"
            if qpath.is_file():
                try:
                    q_rep = json.loads(qpath.read_text(encoding="utf-8"))
                    changed = False
                    if stopped_reason and q_rep.get("stopped_reason") != stopped_reason:
                        q_rep["stopped_reason"] = stopped_reason
                        changed = True
                    if report.get("partial") and not q_rep.get("partial"):
                        q_rep["partial"] = True
                        changed = True
                    if changed:
                        atomic_json(qpath, q_rep)
                        if "quality" in report and isinstance(report["quality"], dict):
                            report["quality"]["stopped_reason"] = q_rep.get("stopped_reason")
                            report["quality"]["partial"] = q_rep.get("partial")
                except Exception:
                    pass
            atomic_json(self.directory / "report.json", report)
        # Status polling need not duplicate a potentially large failure list.
        summary = {k: v for k, v in report.items() if k != "failures"}
        if "quality" in report and isinstance(report["quality"], dict):
            q = report["quality"]
            self.data["quality_summary"] = {
                "price_status_counts": q.get("price_status_counts"),
                "issue_counts_by_severity": q.get("issue_counts_by_severity"),
                "eligibility": q.get("eligibility"),
            }
        self.update(report=summary)
        self._pending_since_export = 0

    def reclassify_quality(self):
        if (self.thread and self.thread.is_alive()) or self.data.get("state") in ACTIVE_STATES:
            raise ValueError("Không thể đánh giá chất lượng khi phiên đang chạy hoặc tạm dừng.")
        with self._artifact_lock:
            json_path = self.directory / "restaurants.json"
            if not json_path.is_file():
                raise FileNotFoundError("Chưa có tệp dữ liệu để đánh giá chất lượng.")
            try:
                records = json.loads(json_path.read_text(encoding="utf-8"))
                if not isinstance(records, list):
                    raise ValueError("Tệp dữ liệu không hợp lệ.")
                if any(not isinstance(row, dict) for row in records):
                    raise ValueError("Tệp dữ liệu có bản ghi không đúng định dạng.")
            except json.JSONDecodeError:
                raise ValueError("Tệp dữ liệu không hợp lệ.")

            import io
            import csv
            import hashlib
            from .exporter import FIELDS, _JSON_COLS, _FORMULA_RE

            current_line = 2
            for r in records:
                if isinstance(r, dict):
                    r["_csv_line"] = current_line
                    row = []
                    for k in FIELDS:
                        v = r.get(k)
                        if v is None:
                            row.append("")
                        elif k in _JSON_COLS:
                            row.append(json.dumps(v, ensure_ascii=False))
                        elif isinstance(v, str) and _FORMULA_RE.match(v):
                            row.append("'" + v)
                        else:
                            row.append(v)
                    sio = io.StringIO()
                    sw = csv.writer(sio)
                    sw.writerow(row)
                    current_line += sio.getvalue().count("\n")

            prog_path = self.directory / "progress.json"
            progress = {}
            if prog_path.is_file():
                try:
                    p = json.loads(prog_path.read_text(encoding="utf-8"))
                    if isinstance(p, dict):
                        progress = p
                except Exception:
                    progress = {}

            cache_dir = self.directory / "cache"
            def html_for(url):
                if not url:
                    return None
                p = cache_dir / (hashlib.sha256(url.encode()).hexdigest()[:20] + ".html")
                if p.is_file():
                    try:
                        return p.read_text(encoding="utf-8")
                    except Exception:
                        return None
                return None

            stopped_reason = self.data.get("termination_reason")
            if stopped_reason in {"exhausted", "in_progress"}:
                stopped_reason = None

            rep_path = self.directory / "report.json"
            report = {}
            if rep_path.is_file():
                try:
                    report = json.loads(rep_path.read_text(encoding="utf-8"))
                except (ValueError, OSError) as exc:
                    raise ValueError(f"Không đọc được báo cáo cũ: {exc}") from exc
                if not isinstance(report, dict):
                    raise ValueError("Báo cáo cũ không đúng định dạng.")

            from .quality import export_quality
            q_rep = export_quality(
                str(self.directory),
                progress,
                records,
                self.urls,
                run_id=self.data["id"],
                stopped_reason=stopped_reason,
                html_for=html_for,
            )

            q_rep.update(execution_mode="offline_reclassification", detail_requests_this_operation=0)
            atomic_json(self.directory / "quality_report.json", q_rep)
            report["quality"] = q_rep
            atomic_json(rep_path, report)
            summary = {k: v for k, v in report.items() if k != "failures"}

            self.data["quality_summary"] = {
                "price_status_counts": q_rep.get("price_status_counts"),
                "issue_counts_by_severity": q_rep.get("issue_counts_by_severity"),
                "eligibility": q_rep.get("eligibility"),
            }
            self.update(report=summary, quality_summary=self.data["quality_summary"])
            return q_rep

    def enrich(self):
        if (self.thread and self.thread.is_alive()) or self.data.get("state") in ACTIVE_STATES:
            raise ValueError("Không thể làm giàu dữ liệu khi phiên đang chạy hoặc tạm dừng.")
        with self._artifact_lock:
            from .enrich_cache import enrich_job
            report = enrich_job(str(self.directory), network=False)
            self.data["enrichment_summary"] = {
                "pages_total": report.get("pages_total", 0),
                "pages_parsed": report.get("pages_parsed", 0),
                "pages_failed": report.get("pages_failed", 0),
                "field_presence_counts": report.get("field_presence_counts", {}),
                "amenity_status_counts": report.get("amenity_status_counts", {}),
            }
            self.update(enrichment_summary=self.data["enrichment_summary"])
            return report

    def read_artifact(self, name):
        whitelisted = {
            "restaurants.json", "restaurants.csv", "report.json",
            "quality_report.json", "issues.json", "issues.csv",
            "restaurants_normalized.json", "restaurants_normalized.csv",
            "restaurants_raw.json",
            "restaurants_enriched.json", "restaurants_enriched.csv",
            "enrichment_report.json",
        }
        if name not in whitelisted:
            raise ValueError("Định dạng tải xuống không hợp lệ.")
        with self._artifact_lock:
            path = self.directory / name
            if not path.is_file():
                raise FileNotFoundError(f"Artifact {name} not found")
            return path.read_bytes()

    def _collect_pending(self, urls):
        for url in urls:
            self.checkpoint()
            status = self._collector.progress.get(url, {}).get("status")
            if status in FINAL_STATUSES:
                continue
            self.update(stage="collecting", message="Đang lấy thông tin các quán đã tìm được.")
            # A user-requested resume rechecks failed/challenge pages instead of replaying stale error HTML.
            outcome = self._collector.process(url, refresh=status in {"blocked", "parse_error", "transient_failed"})
            self._counts()
            self._pending_since_export += 1
            if self._pending_since_export >= 5:
                self._export()
            if outcome == "blocked":
                self._blocked_reason = self._collector.progress[url].get("error") or "Nguồn chặn truy cập."
                self._stop.set()
                raise JobStopped()
        self._export()

    def _on_batch(self, urls, metadata):
        self.checkpoint()
        known = set(self.urls)
        disc_meta_path = self.directory / "discovery_metadata.json"
        disc_meta = {}
        if disc_meta_path.exists():
            try:
                disc_meta = json.loads(disc_meta_path.read_text(encoding="utf-8"))
            except Exception:
                disc_meta = {}
        for raw in urls:
            try:
                url = normalize_restaurant_url(raw)
            except ValueError:
                self.log("Bỏ qua một đường dẫn không phải trang quán hợp lệ.")
                continue
            if url not in known:
                if self.data["limit"] is not None and len(self.urls) >= self.data["limit"]:
                    break
                known.add(url)
                self.urls.append(url)
                if url not in disc_meta:
                    disc_meta[url] = {
                        "seed_source": metadata.get("source_url") or "https://www.foody.vn/ha-noi/o-dau",
                        "run_id": self.data["id"],
                        "rank_first_seen": len(self.urls),
                        "observed_at": utcnow(),
                        "clicks": metadata.get("clicks", 0),
                        "batch_index": metadata.get("batch_index", 0),
                    }
        atomic_json(disc_meta_path, disc_meta)
        atomic_json(self.directory / "urls.json", self.urls)
        self.update(discovered=len(self.urls), clicks=self._click_base + metadata.get("clicks", 0))
        self.log(f"Đã tìm thấy {len(self.urls)} đường dẫn quán riêng biệt.")
        self._collect_pending(self.urls)
        self.checkpoint()
        self.update(stage="discovering", message="Đang tải thêm danh sách quán.")

    def _run(self):
        self._request_base = self.data.get("request_count", 0)
        self._click_base = self.data.get("clicks", 0)
        self._last_result = None
        try:
            self.checkpoint()
            self.update(state="running", stage="discovering", message="Đang mở trình duyệt.")
            self._collector = self._collector_factory(str(self.directory), min_interval=self.data["interval"],
                                                       sleeper=self._wait)
            self._counts()
            self._collect_pending(self.urls)
            self.checkpoint()
            if self.data["limit"] is not None and len(self.urls) >= self.data["limit"]:
                result = {"reason": "limit", "clicks": 0, "coverage_verified": False,
                          "source_url": "https://www.foody.vn/ha-noi/o-dau", "error": None}
            else:
                if self._discovery_factory is None:
                    from .browser import BrowserDiscovery
                    factory = BrowserDiscovery
                else:
                    factory = self._discovery_factory
                engine = factory(str(self.directory), interval=self.data["interval"],
                                 headless=not self.data["show_browser"])
                result = engine.run(self._on_batch, should_stop=self._stop.is_set,
                                    checkpoint=self.checkpoint, max_urls=self.data["limit"])
            if self._stop.is_set():
                raise JobStopped()
            self._last_result = result
            reason = result.get("reason", "error")
            self._export(result)
            self._counts()
            success_end = reason == "exhausted" or (self.data["mode"] == "sample" and reason == "limit")
            state = "completed" if success_end and not self.data["failed"] else "partial"
            messages = {"exhausted": "Đã đến cuối danh sách nguồn trả về.",
                        "limit": "Đã đạt số quán của đợt chạy thử.",
                        "stalled": "Danh sách không tăng thêm. Chưa xác minh đã hết quán.",
                        "safety_limit": "Đã đạt giới hạn số lần tải thêm. Chưa quét hết danh sách.",
                        "timeout": "Nguồn phản hồi quá lâu. Tiến độ đã được lưu.",
                        "error": "Gặp lỗi khi mở hoặc đọc trình duyệt.",
                        "blocked": "Nguồn yêu cầu xác minh hoặc chặn truy cập. Tool đã dừng.",
                        "stopped": "Đã dừng và lưu tiến độ. Có thể tiếp tục."}
            if reason in {"blocked", "stopped", "error"}:
                state = {"blocked": "blocked", "stopped": "stopped", "error": "error"}[reason]
            message = messages.get(reason, "Đợt thu thập đã dừng; xem báo cáo để biết chi tiết.")
            if result.get("error"):
                self.log(result["error"])
            self.update(state=state, stage="finished", termination_reason=reason,
                        coverage_verified=bool(result.get("coverage_verified") and reason == "exhausted"),
                        clicks=self._click_base + result.get("clicks", 0), message=message)
            self.log(message)
        except JobStopped:
            reason = "blocked" if self._blocked_reason else "stopped"
            self._last_result = {"reason": reason, "coverage_verified": False,
                                 "error": self._blocked_reason, "clicks": self.data["clicks"] - self._click_base,
                                 "source_url": "https://www.foody.vn/ha-noi/o-dau"}
            try:
                self._export(self._last_result)
                self.update(state=reason, stage="finished", termination_reason=reason, coverage_verified=False,
                            message="Nguồn chặn truy cập. Đã lưu tiến độ." if self._blocked_reason
                            else "Đã dừng và lưu tiến độ. Có thể tiếp tục.")
            except Exception as exc:
                self._fail(exc)
        except Exception as exc:
            self._last_result = {"reason": "error", "coverage_verified": False, "error": str(exc)}
            try:
                self._export(self._last_result)
            except Exception:
                pass
            self._fail(exc)

    def _fail(self, exc):
        """Show the error in memory even when the disk can no longer save metadata."""
        with self._lock:
            self.data.update(state="error", stage="finished", termination_reason="error",
                             coverage_verified=False, updated_at=utcnow(),
                             message="Gặp lỗi. Kiểm tra nhật ký; phần đã lưu có thể dùng để tiếp tục.")
            self.data["logs"] = (self.data.get("logs", []) + [
                {"time": utcnow(), "message": f"Lỗi: {exc}"}])[-30:]
            try:
                self._persist()
            except OSError:
                pass


class JobManager:
    def __init__(self, root, *, discovery_factory=None, collector_factory=Collector):
        self.root = Path(root).resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self.jobs = {}
        self.active_id = None
        self.discovery_factory, self.collector_factory = discovery_factory, collector_factory
        from .media import MediaManager
        self.media = MediaManager(self)
        for path in self.root.glob("*/job.json"):
            if not JOB_ID.fullmatch(path.parent.name):
                continue
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                if data.get("id") != path.parent.name:
                    continue
                validate_config(data)
                job = CrawlJob(path.parent, saved=data, discovery_factory=discovery_factory,
                               collector_factory=collector_factory)
                self.jobs[data["id"]] = job
            except (OSError, ValueError, TypeError, KeyError):
                continue
        if self.jobs:
            self.active_id = max(self.jobs, key=lambda k: self.jobs[k].data.get("started_at", ""))

    def get(self, job_id):
        if not isinstance(job_id, str) or not JOB_ID.fullmatch(job_id):
            raise KeyError("Không tìm thấy đợt thu thập.")
        if job_id not in self.jobs:
            path = self.root / job_id / "job.json"
            if path.is_file():
                try:
                    data = json.loads(path.read_text(encoding="utf-8"))
                    job = CrawlJob(path.parent, saved=data, discovery_factory=self.discovery_factory,
                                   collector_factory=self.collector_factory)
                    self.jobs[job_id] = job
                except Exception:
                    raise KeyError("Không tìm thấy đợt thu thập.")
            else:
                raise KeyError("Không tìm thấy đợt thu thập.")
        return self.jobs[job_id]

    def _ensure_idle(self, except_id=None):
        if any(k != except_id and j.thread and j.thread.is_alive() for k, j in self.jobs.items()):
            raise ValueError("Một đợt khác đang chạy hoặc tạm dừng. Hãy dừng đợt đó trước.")

    def start(self, config):
        config = validate_config(config)
        with self._lock:
            self._ensure_idle()
            job_id = uuid.uuid4().hex
            job = CrawlJob(self.root / job_id, config, discovery_factory=self.discovery_factory,
                           collector_factory=self.collector_factory)
            self.jobs[job_id] = job
            self.active_id = job_id
            job.launch()
            return job

    def resume(self, job_id):
        with self._lock:
            job = self.get(job_id)
            self._ensure_idle(except_id=job_id)
            if job.data["state"] == "completed":
                raise ValueError("Đợt này đã hoàn tất. Tạo đợt mới nếu muốn lấy dữ liệu mới.")
            job.launch()
            self.active_id = job_id
            return job

    def reclassify_quality(self, job_id):
        # Serialize against start/resume so a saved job cannot start collecting mid-export.
        with self._lock:
            job = self.get(job_id)
            job.reclassify_quality()
            return job

    def enrich_job(self, job_id):
        # Serialize against start/resume so a saved job cannot start collecting mid-enrichment.
        with self._lock:
            job = self.get(job_id)
            report = job.enrich()
            return job, report

    def history(self):
        with self._lock:
            return sorted((j.snapshot() for j in self.jobs.values()),
                          key=lambda d: d.get("started_at", ""), reverse=True)

    def status(self):
        with self._lock:
            return self.get(self.active_id).snapshot() if self.active_id else None

    def shutdown(self):
        self.media.shutdown()
        active = [j for j in self.jobs.values() if j.thread and j.thread.is_alive()]
        for job in active:
            job.stop()
        for job in active:
            job.thread.join(timeout=35)
