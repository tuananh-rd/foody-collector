"""Local dashboard and small JSON API, using only Python's standard library."""
import argparse
import json
import mimetypes
import secrets
import threading
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from . import media as media_mod
from .jobs import JobManager, browser_readiness

WEB_ROOT = Path(__file__).parent / "web"


def make_server(manager, host="127.0.0.1", port=8765, web_root=None):
    if host != "127.0.0.1":
        raise ValueError("Giao diện chỉ mở trên máy hiện tại (127.0.0.1).")
    assets = Path(web_root or WEB_ROOT).resolve()
    csrf_token = secrets.token_urlsafe(32)

    class Handler(BaseHTTPRequestHandler):
        server_version = "FoodTourLocal/0.2"

        def log_message(self, fmt, *args):
            pass

        def reply(self, status, body, content_type="application/json; charset=utf-8", filename=None):
            if isinstance(body, (dict, list)):
                body = json.dumps(body, ensure_ascii=False).encode("utf-8")
            elif isinstance(body, str):
                body = body.encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Content-Security-Policy", "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data: https://*.susercontent.com; connect-src 'self'; frame-ancestors 'none'; base-uri 'self'")
            if filename:
                self.send_header("Content-Disposition", f'attachment; filename="{filename}"')
            self.end_headers()
            try:
                self.wfile.write(body)
            except (BrokenPipeError, ConnectionResetError):
                pass

        def valid_host(self):
            try:
                host = urlsplit("http://" + self.headers.get("Host", ""))
                return host.hostname in {"localhost", "127.0.0.1"} and host.port == self.server.server_port
            except ValueError:
                return False

        def validate_post(self):
            if not self.valid_host():
                return False
            origin = self.headers.get("Origin")
            if origin:
                try:
                    parsed = urlsplit(origin)
                    if (parsed.scheme != "http" or parsed.hostname not in {"localhost", "127.0.0.1"}
                            or parsed.port != self.server.server_port):
                        return False
                except ValueError:
                    return False
            return secrets.compare_digest(self.headers.get("X-CSRF-Token", ""), csrf_token)

        def media_get(self, mgr, route, query):
            job_id = query.get("job_id", [None])[0]
            job = mgr.get(job_id)
            store = media_mod.MediaStore(job.directory)
            ids = [v for v in query.get("venue_ids", [""])[0].split(",") if v] or None
            if route == "/api/media/status":
                return self.reply(200, dict(scanned=store.exists, summary=media_mod.coverage_summary(store),
                                            task=mgr.media.status(job_id), limits=media_mod.DEFAULT_LIMITS,
                                            hard_limits=media_mod.HARD_LIMITS))
            if route == "/api/media/venues":
                offset = max(0, int(query.get("offset", [0])[0]))
                limit = min(200, max(1, int(query.get("limit", [25])[0])))
                q = query.get("q", [""])[0].strip().lower()
                flt = query.get("filter", [""])[0]
                rows = []
                for vid in sorted(store.venues):
                    row = media_mod.venue_summary(store, vid)
                    if q and q not in (row["name"] or "").lower() and q != vid:
                        continue
                    if flt == "menu_images" and not (row["menu_image_count"] or 0) > 0:
                        continue
                    if flt == "menu_text" and not row["menu_text_items"]:
                        continue
                    if flt == "photos" and not row["photos_known"]:
                        continue
                    if flt == "downloaded" and not row["photos_downloaded"]:
                        continue
                    if flt == "delivery" and not row["delivery_listed"]:
                        continue
                    rows.append(row)
                return self.reply(200, {"venues": rows[offset:offset + limit], "total": len(rows)})
            if route == "/api/media/venue":
                vid = query.get("venue_id", [""])[0]
                if vid not in store.venues:
                    raise KeyError("Không tìm thấy quán.")
                return self.reply(200, dict(
                    venue=media_mod.venue_summary(store, vid), albums=store.venues[vid].get("albums", []),
                    albums_listed=store.venues[vid].get("albums_listed", {}),
                    photos=sorted((p for p in store.photos.values() if p["venue_id"] == vid),
                                  key=lambda p: p["photo_id"]),
                    menu_items=sorted((m for m in store.menu.values() if m["venue_id"] == vid),
                                      key=lambda m: m["item_id"])))
            if route == "/api/media/file":
                photo = store.photos.get(query.get("photo_id", [""])[0])
                rel = photo and photo.get("local_path")
                if not rel or photo.get("download_status") != "ok":
                    raise KeyError("Ảnh chưa được tải về.")
                target = (store.dir / rel).resolve()
                if store.images.resolve() not in target.parents or not target.is_file():
                    raise KeyError("Ảnh chưa được tải về.")
                return self.reply(200, target.read_bytes(), photo.get("mime") or "application/octet-stream")
            if route == "/api/media/download":
                fmt = query.get("format", [""])[0]
                if fmt == "archive":
                    data, count = media_mod.build_archive(store, ids)
                    if not count:
                        return self.reply(404, {"error": "Chưa có ảnh nào được tải về."})
                    return self.reply(200, data, "application/zip", "foody_photos.zip")
                name, mime, data = media_mod.export_bytes(store, fmt, ids)
                if not store.exists:
                    return self.reply(404, {"error": "Chưa quét menu/ảnh cho đợt này."})
                return self.reply(200, data, mime, name)
            return self.reply(404, {"error": "Không tìm thấy trang."})

        def media_post(self, mgr, route, config):
            job_id = config.get("job_id")
            if not job_id:
                raise ValueError("Thiếu mã phiên.")
            if route == "/api/media/scan":
                return {"summary": mgr.media.scan(job_id)}
            if route in ("/api/media/collect", "/api/media/images", "/api/media/ocr"):
                ids = config.get("venue_ids")
                if ids is not None and (not isinstance(ids, list) or len(ids) > 20000
                                        or not all(isinstance(i, (str, int)) for i in ids)):
                    raise ValueError("Danh sách quán không hợp lệ.")
                opts = {k: v for k, v in config.items() if k not in ("job_id", "venue_ids")}
                task = mgr.media.start(job_id, {"collect": "collect", "images": "download", "ocr": "ocr"}[route.rsplit("/", 1)[1]], ids, opts)
                return {"task": task.snapshot()}
            if route == "/api/media/control":
                action = config.get("action")
                if action not in ("stop", "pause", "resume"):
                    raise ValueError("Thao tác không hợp lệ.")
                return {"task": mgr.media.control(action).snapshot()}
            raise KeyError("Không tìm thấy thao tác.")

        def do_GET(self):
            if not self.valid_host():
                return self.reply(403, {"error": "Địa chỉ truy cập không hợp lệ."})
            mgr = getattr(self.server, "manager", manager)
            path = urlsplit(self.path)
            query = parse_qs(path.query)
            try:
                if path.path == "/api/status":
                    ready, message = browser_readiness()
                    return self.reply(200, dict(active_job=mgr.status(), browser_ready=ready,
                                                browser_message=message, csrf_token=csrf_token))
                if path.path == "/api/history":
                    return self.reply(200, {"jobs": mgr.history()})
                if path.path.startswith("/api/media/"):
                    return self.media_get(mgr, path.path, query)
                if path.path.startswith("/api/jobs/"):
                    return self.reply(200, {"job": mgr.get(path.path[len("/api/jobs/"):]).snapshot()})
                if path.path in {"/api/preview", "/api/download"}:
                    job = mgr.get(query.get("job_id", [None])[0])
                    if path.path == "/api/preview":
                        offset = max(0, int(query.get("offset", [0])[0]))
                        limit = min(500, max(1, int(query.get("limit", [20])[0])))
                        layer = query.get("layer", [None])[0]
                        if layer == "enriched":
                            target = "restaurants_enriched.json"
                        elif layer == "normalized":
                            target = "restaurants_normalized.json"
                        else:
                            target = "restaurants.json"
                        try:
                            records = json.loads(job.read_artifact(target))
                        except FileNotFoundError:
                            records = []
                        return self.reply(200, {"records": records[offset:offset + limit], "total": len(records), "layer": layer or "legacy"})
                    fmt = query.get("format", [""])[0]
                    formats = {
                        "csv": ("restaurants.csv", "text/csv; charset=utf-8"),
                        "json": ("restaurants.json", "application/json; charset=utf-8"),
                        "report": ("report.json", "application/json; charset=utf-8"),
                        "quality": ("quality_report.json", "application/json; charset=utf-8"),
                        "issues": ("issues.json", "application/json; charset=utf-8"),
                        "issues_csv": ("issues.csv", "text/csv; charset=utf-8"),
                        "normalized": ("restaurants_normalized.json", "application/json; charset=utf-8"),
                        "normalized_csv": ("restaurants_normalized.csv", "text/csv; charset=utf-8"),
                        "raw": ("restaurants_raw.json", "application/json; charset=utf-8"),
                        "enriched": ("restaurants_enriched.json", "application/json; charset=utf-8"),
                        "enriched_json": ("restaurants_enriched.json", "application/json; charset=utf-8"),
                        "enriched_csv": ("restaurants_enriched.csv", "text/csv; charset=utf-8"),
                        "restaurants_enriched.json": ("restaurants_enriched.json", "application/json; charset=utf-8"),
                        "restaurants_enriched.csv": ("restaurants_enriched.csv", "text/csv; charset=utf-8"),
                        "enrichment_report": ("enrichment_report.json", "application/json; charset=utf-8"),
                    }
                    if fmt not in formats:
                        raise ValueError("Định dạng tải xuống không hợp lệ.")
                    name, mime = formats[fmt]
                    try:
                        return self.reply(200, job.read_artifact(name), mime, name)
                    except FileNotFoundError:
                        if fmt in {"quality", "issues", "issues_csv", "normalized", "normalized_csv", "raw",
                                   "enriched", "enriched_json", "enriched_csv", "restaurants_enriched.json",
                                   "restaurants_enriched.csv", "enrichment_report"}:
                            return self.reply(404, {"error": "not_available"})
                        return self.reply(404, {"error": "Chưa có tệp dữ liệu để tải xuống."})
                static = {"/": "index.html", "/index.html": "index.html", "/style.css": "style.css",
                          "/app.js": "app.js"}
                if path.path == "/favicon.ico":
                    return self.reply(204, b"", "image/x-icon")
                if path.path in static:
                    name = static[path.path]
                    mime = mimetypes.guess_type(name)[0] or "application/octet-stream"
                    return self.reply(200, (assets / name).read_bytes(), mime + "; charset=utf-8")
                self.reply(404, {"error": "Không tìm thấy trang."})
            except KeyError as exc:
                self.reply(404, {"error": str(exc.args[0])})
            except FileNotFoundError:
                self.reply(404, {"error": "Chưa có tệp dữ liệu để tải xuống."})
            except (ValueError, OSError) as exc:
                self.reply(400, {"error": str(exc)})

        def do_POST(self):
            try:
                length = int(self.headers.get("Content-Length", "0"))
                limit = 262144 if self.path.startswith("/api/media/") else 8192
                if not 0 < length <= limit:
                    raise ValueError("Yêu cầu không hợp lệ.")
                # Drain the bounded body before replying, avoiding unread-body TCP resets on Windows.
                self.connection.settimeout(10)
                raw = self.rfile.read(length)
                if not self.validate_post():
                    return self.reply(403, {"error": "Hãy mở lại giao diện rồi thử lại."})
                if self.headers.get_content_type() != "application/json":
                    raise ValueError("Yêu cầu không đúng định dạng.")
                config = json.loads(raw)
                if not isinstance(config, dict):
                    raise ValueError("Yêu cầu không hợp lệ.")
                mgr = getattr(self.server, "manager", manager)
                route = urlsplit(self.path).path
                if route.startswith("/api/media/"):
                    return self.reply(200, self.media_post(mgr, route, config))
                if route == "/api/shutdown":
                    self.reply(200, {"message": "Đang lưu tiến độ và đóng ứng dụng."})
                    def shutdown():
                        mgr.shutdown()
                        self.server.shutdown()
                    threading.Thread(target=shutdown, daemon=True).start()
                    return
                if route == "/api/start":
                    job = mgr.start(config)
                    return self.reply(200, {"job_id": job.data["id"], "job": job.snapshot()})
                if route == "/api/quality":
                    job_id = config.get("job_id")
                    if not job_id:
                        raise ValueError("Thiếu mã phiên.")
                    job = mgr.reclassify_quality(job_id)
                    return self.reply(200, {"job": job.snapshot()})
                if route == "/api/enrich":
                    job_id = config.get("job_id")
                    if not job_id:
                        raise ValueError("Thiếu mã phiên.")
                    job, report = mgr.enrich_job(job_id)
                    res = dict(report)
                    res["job"] = job.snapshot()
                    res["report"] = report
                    return self.reply(200, res)
                job = mgr.get(config.get("job_id"))
                if route == "/api/pause":
                    job.pause()
                elif route == "/api/resume":
                    job = manager.resume(config.get("job_id"))
                elif route == "/api/stop":
                    job.stop()
                else:
                    return self.reply(404, {"error": "Không tìm thấy thao tác."})
                self.reply(200, {"job": job.snapshot()})
            except KeyError as exc:
                self.reply(404, {"error": str(exc.args[0])})
            except FileNotFoundError as exc:
                self.reply(404, {"error": str(exc)})
            except (ValueError, OSError) as exc:
                self.reply(400, {"error": str(exc)})

    server = ThreadingHTTPServer((host, port), Handler)
    server.daemon_threads = True
    server.manager = manager
    return server


def main(argv=None):
    parser = argparse.ArgumentParser(description="Giao diện thu thập dữ liệu FoodTour")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--data-dir", default="data/jobs")
    parser.add_argument("--no-open", action="store_true")
    args = parser.parse_args(argv)
    manager = JobManager(args.data_dir)
    server = make_server(manager, port=args.port)
    address = f"http://127.0.0.1:{server.server_port}"
    print(f"FoodTour đang mở tại {address}", flush=True)
    if not args.no_open:
        threading.Timer(0.5, webbrowser.open, args=(address,)).start()
    try:
        server.serve_forever(poll_interval=0.3)
    except KeyboardInterrupt:
        print("Đang lưu tiến độ và đóng ứng dụng...", flush=True)
    finally:
        manager.shutdown()
        server.server_close()


if __name__ == "__main__":
    main()
