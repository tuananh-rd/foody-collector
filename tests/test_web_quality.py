"""Tests for Vietnamese v0.3 Quality UI (foody_tool/web/{index.html,style.css,app.js}).

Compliant with Claude docs/QUALITY_V3.md section 13:
- Compact quality panel: price ok/unknown0/reversed, issue severities, eligibility
- Clear labels legacy vs normalized
- Normalized preview default if exists, old job fallback labeled not checked
- Reversed and 0 prices never usable in preview
- All raw shifts preserved with day mapping unknown note; unknown hours not closed
- Selected history quality must match selected job, not active job
- All new download links: quality, issues, issues_csv, normalized, normalized_csv, raw
- Pure CSP compliance, zero inline handlers, zero console/CSP errors, XSS safety
"""

import json
import os
import re
import socket
import tempfile
import threading
import time
import unittest
from http.server import HTTPServer, SimpleHTTPRequestHandler
from pathlib import Path
from urllib.parse import parse_qs, urlparse

WEB_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "foody_tool", "web")
HTML_PATH = os.path.join(WEB_DIR, "index.html")
CSS_PATH = os.path.join(WEB_DIR, "style.css")
JS_PATH = os.path.join(WEB_DIR, "app.js")


class TestWebQualityStatic(unittest.TestCase):
    """Static analysis and contract compliance tests for Quality v0.3 UI files."""

    @classmethod
    def setUpClass(cls):
        with open(HTML_PATH, "r", encoding="utf-8") as f:
            cls.html = f.read()
        with open(CSS_PATH, "r", encoding="utf-8") as f:
            cls.css = f.read()
        with open(JS_PATH, "r", encoding="utf-8") as f:
            cls.js = f.read()

    def test_quality_panel_dom_elements_exist(self):
        """Compact quality panel elements must exist in index.html."""
        self.assertIn('id="quality-section"', self.html)
        self.assertIn('id="heading-quality"', self.html)
        self.assertIn('id="quality-viewing-job"', self.html)
        self.assertIn('id="badge-quality-layer"', self.html)
        self.assertIn('id="badge-quality-fallback"', self.html)
        self.assertIn('id="quality-legacy-alert"', self.html)
        self.assertIn('id="btn-reclassify-quality"', self.html)

        # Price status metrics
        self.assertIn('id="stat-price-ok"', self.html)
        self.assertIn('id="stat-price-zero"', self.html)
        self.assertIn('id="stat-price-reversed"', self.html)
        self.assertIn('id="stat-price-other"', self.html)

        # Issue severities
        self.assertIn('id="badge-total-issues"', self.html)
        self.assertIn('id="stat-issues-error"', self.html)
        self.assertIn('id="stat-issues-warning"', self.html)
        self.assertIn('id="stat-issues-info"', self.html)

        # Eligibility metrics
        self.assertIn('id="stat-elig-search"', self.html)
        self.assertIn('id="stat-elig-location"', self.html)
        self.assertIn('id="stat-elig-price-filter"', self.html)
        self.assertIn('id="stat-elig-budget"', self.html)
        self.assertIn('id="stat-elig-hours"', self.html)

    def test_layer_controls_and_new_download_links_in_html(self):
        """Layer switcher and all 6 new v0.3 download links must exist in HTML."""
        # Layer controls
        self.assertIn('id="layer-normalized"', self.html)
        self.assertIn('id="layer-raw"', self.html)
        self.assertIn('id="badge-preview-layer"', self.html)

        # 6 New v0.3 download formats
        self.assertIn('id="btn-download-norm-csv"', self.html)
        self.assertIn('id="btn-download-norm-json"', self.html)
        self.assertIn('id="btn-download-issues-csv"', self.html)
        self.assertIn('id="btn-download-issues-json"', self.html)
        self.assertIn('id="btn-download-quality"', self.html)
        self.assertIn('id="btn-download-raw"', self.html)

        # Existing v1 downloads preserved
        self.assertIn('id="btn-download-csv"', self.html)
        self.assertIn('id="btn-download-json"', self.html)
        self.assertIn('id="btn-download-report"', self.html)

    def test_vietnamese_quality_phrasing_and_disclaimers(self):
        """HTML must contain truthful Vietnamese quality disclaimers required by Section 13."""
        # Venue range is not dish budget
        self.assertIn("Khoảng giá toàn quán, không phải ngân sách món ăn", self.html)

        # Unknown hours is not closed
        self.assertIn("không kết luận đóng cửa", self.html)
        self.assertIn("Chưa rõ quy ước thứ", self.html)

        # Old job fallback labeling
        self.assertIn("Chưa kiểm tra chất lượng (phiên cũ)", self.html)

        # Distinct labels for normalized vs legacy
        self.assertIn("Chuẩn hóa (v0.3)", self.html)
        self.assertIn("Dữ liệu gốc (v1)", self.html)

    def test_strict_csp_and_no_inline_handlers(self):
        """Web UI must strictly respect CSP with zero inline handlers and zero CDNs."""
        self.assertNotIn("onclick=", self.html)
        self.assertNotIn("onsubmit=", self.html)
        self.assertNotIn("onload=", self.html)
        self.assertNotIn("javascript:", self.html)
        self.assertNotIn("<script>", self.html)

        # External stylesheets/fonts must not be linked
        links = re.findall(r'<link\s+[^>]*href=["\']([^"\']+)["\']', self.html, re.IGNORECASE)
        for link in links:
            self.assertFalse(link.startswith("http://") or link.startswith("https://") or link.startswith("//"))
            self.assertNotIn("fonts.googleapis.com", link)
            self.assertNotIn("cdnjs", link)
            self.assertNotIn("unpkg", link)

        scripts = re.findall(r'<script\s+[^>]*src=["\']([^"\']+)["\']', self.html, re.IGNORECASE)
        for script in scripts:
            self.assertFalse(script.startswith("http://") or script.startswith("https://") or script.startswith("//"))

    def test_js_xss_protection_and_safe_dom(self):
        """app.js must use textContent and createElement rather than unsafe innerHTML with data."""
        self.assertNotIn("innerHTML = record.", self.js)
        self.assertNotIn("innerHTML = item.", self.js)
        self.assertNotIn("innerHTML = job.", self.js)
        self.assertNotIn("innerHTML = price", self.js)
        self.assertIn("textContent", self.js)
        self.assertIn("document.createElement", self.js)

    def test_js_layer_and_quality_endpoints(self):
        """app.js must call layer=normalized and /api/quality."""
        self.assertIn("layer=normalized", self.js)
        self.assertIn("/api/quality", self.js)
        self.assertIn("format=quality", self.js)
        self.assertIn("format=issues_csv", self.js)
        self.assertIn("format=issues", self.js)
        self.assertIn("format=normalized_csv", self.js)
        self.assertIn("format=normalized", self.js)
        self.assertIn("format=raw", self.js)


# --- Mock HTTP Server for Playwright Quality E2E Testing ---

class MockQualityBackendHandler(SimpleHTTPRequestHandler):
    """Mock HTTP handler implementing docs/QUALITY_V3.md section 13 contract."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=WEB_DIR, **kwargs)

    def log_message(self, format, *args):
        pass

    def _send_json(self, status_code, data):
        payload = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(status_code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path
        qs = parse_qs(parsed.query)
        server_state = getattr(self.server, "state_store", {})

        if path == "/favicon.ico":
            self.send_response(204)
            self.end_headers()
            return
        elif path.startswith("/api/media/"):
            # v0.5 panel polls this on job view; the mock has no media store.
            self._send_json(200, {"scanned": False, "summary": {}, "task": None})
        elif path == "/api/status":
            self._send_json(200, {
                "active_job": server_state.get("active_job"),
                "browser_ready": True,
                "browser_message": "Microsoft Edge tự động sẵn sàng",
                "csrf_token": server_state.get("csrf_token", "csrf-token-xyz"),
            })
        elif path == "/api/history":
            self._send_json(200, {
                "jobs": server_state.get("history_jobs", [])
            })
        elif path.startswith("/api/jobs/"):
            job_id = path[len("/api/jobs/"):]
            jobs_map = server_state.get("jobs_snapshots", {})
            if job_id in jobs_map:
                self._send_json(200, {"job": jobs_map[job_id]})
            else:
                self._send_json(404, {"error": "Job not found"})
        elif path == "/api/preview":
            job_id = qs.get("job_id", [None])[0]
            layer = qs.get("layer", [None])[0]
            previews = server_state.get("previews", {})
            job_previews = previews.get(job_id, {})
            records = job_previews.get(layer, [])
            self._send_json(200, {
                "records": records,
                "total": len(records),
            })
        elif path == "/api/download":
            job_id = qs.get("job_id", [""])[0]
            fmt = qs.get("format", ["csv"])[0]
            jobs_map = server_state.get("jobs_snapshots", {})
            job = jobs_map.get(job_id, {})

            # For legacy jobs without quality files, return 404 not_available
            if fmt in {"quality", "issues", "issues_csv", "normalized", "normalized_csv", "raw"}:
                if not job.get("quality_summary") and not (job.get("report") and job["report"].get("quality")):
                    self._send_json(404, {"error": "not_available"})
                    return

            content = f"sample download for {job_id} format {fmt}".encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/octet-stream")
            self.send_header("Content-Disposition", f'attachment; filename="data_{job_id}.{fmt}"')
            self.send_header("Content-Length", str(len(content)))
            self.end_headers()
            self.wfile.write(content)
        else:
            super().do_GET()

    def do_POST(self):
        parsed = urlparse(self.path)
        path = parsed.path
        server_state = getattr(self.server, "state_store", {})

        csrf_received = self.headers.get("X-CSRF-Token")
        expected_csrf = server_state.get("csrf_token", "csrf-token-xyz")
        if csrf_received != expected_csrf:
            self._send_json(403, {"error": "Invalid CSRF token"})
            return

        content_length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(content_length).decode("utf-8") if content_length > 0 else "{}"
        try:
            req_data = json.loads(body)
        except Exception:
            req_data = {}

        if path == "/api/quality":
            job_id = req_data.get("job_id")
            server_state["quality_reclassify_called_for"] = job_id
            jobs_map = server_state.get("jobs_snapshots", {})
            if job_id in jobs_map:
                # Upgrade legacy job to have quality summary
                job = jobs_map[job_id]
                job["quality_summary"] = {
                    "price_status_counts": {"ok": 10, "unknown_zero": 1, "invalid_range": 1, "partial_zero": 0, "missing": 0, "nonfinite": 0},
                    "issue_counts_by_severity": {"error": 1, "warning": 1, "info": 0},
                    "eligibility": {
                        "search_eligible": {"num": 12, "den": 12, "rate": 1.0},
                        "location_eligible": {"num": 12, "den": 12, "rate": 1.0},
                        "price_filter_eligible": {"num": 10, "den": 12, "rate": 0.833},
                        "budget_eligible": {"num": 0, "den": 12, "rate": 0.0},
                        "hours_eligible": {"num": 0, "den": 12, "rate": 0.0},
                    },
                }
                # Also provide normalized records for preview
                previews = server_state.get("previews", {})
                if job_id in previews:
                    previews[job_id]["normalized"] = previews[job_id].get(None, [])
                self._send_json(200, {"job": job})
            else:
                self._send_json(404, {"error": "Job not found"})
        elif path == "/api/start":
            self._send_json(200, {"job_id": "job_new_001", "job": {"id": "job_new_001", "state": "running"}})
        elif path == "/api/shutdown":
            self._send_json(200, {"message": "Đang lưu tiến độ và đóng ứng dụng."})
        else:
            self._send_json(404, {"error": "Not found"})


class TestWebQualityPlaywrightE2E(unittest.TestCase):
    """End-to-end browser verification of Quality v0.3 UI using Playwright."""

    @classmethod
    def setUpClass(cls):
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.bind(("127.0.0.1", 0))
        cls.port = sock.getsockname()[1]
        sock.close()

        cls.server = HTTPServer(("127.0.0.1", cls.port), MockQualityBackendHandler)
        cls.server.state_store = {
            "csrf_token": "csrf-quality-secret-123",
            "active_job": {
                "id": "job_active_running",
                "mode": "sample",
                "state": "running",
                "stage": "collecting",
                "processed": 10,
                "discovered": 20,
                "success": 10,
                "duplicates": 0,
                "failed": 0,
                "clicks": 1,
                "request_count": 10,
                "limit": 48,
                "started_at": "2026-10-14T15:00:00Z",
                "updated_at": "2026-10-14T15:05:00Z",
                "message": "Đang thu thập chi tiết quán...",
                "logs": [],
                "quality_summary": {
                    "price_status_counts": {"ok": 8, "unknown_zero": 1, "invalid_range": 1, "partial_zero": 0, "missing": 0, "nonfinite": 0},
                    "issue_counts_by_severity": {"error": 1, "warning": 1, "info": 0},
                    "eligibility": {
                        "search_eligible": {"num": 10, "den": 10, "rate": 1.0},
                        "location_eligible": {"num": 10, "den": 10, "rate": 1.0},
                        "price_filter_eligible": {"num": 8, "den": 10, "rate": 0.8},
                        "budget_eligible": {"num": 0, "den": 10, "rate": 0.0},
                        "hours_eligible": {"num": 0, "den": 10, "rate": 0.0},
                    },
                },
            },
            "history_jobs": [
                {
                    "id": "job_v3_quality_200",
                    "mode": "sample",
                    "state": "completed",
                    "processed": 200,
                    "limit": 200,
                    "discovered": 200,
                    "started_at": "2026-10-14T12:00:00Z",
                },
                {
                    "id": "job_v1_legacy_old",
                    "mode": "sample",
                    "state": "completed",
                    "processed": 50,
                    "limit": 50,
                    "discovered": 50,
                    "started_at": "2026-10-14T09:00:00Z",
                },
            ],
            "jobs_snapshots": {
                "job_active_running": {
                    "id": "job_active_running",
                    "mode": "sample",
                    "state": "running",
                    "quality_summary": {
                        "price_status_counts": {"ok": 8, "unknown_zero": 1, "invalid_range": 1, "partial_zero": 0, "missing": 0, "nonfinite": 0},
                        "issue_counts_by_severity": {"error": 1, "warning": 1, "info": 0},
                        "eligibility": {
                            "search_eligible": {"num": 10, "den": 10, "rate": 1.0},
                            "location_eligible": {"num": 10, "den": 10, "rate": 1.0},
                            "price_filter_eligible": {"num": 8, "den": 10, "rate": 0.8},
                            "budget_eligible": {"num": 0, "den": 10, "rate": 0.0},
                            "hours_eligible": {"num": 0, "den": 10, "rate": 0.0},
                        },
                    },
                },
                "job_v3_quality_200": {
                    "id": "job_v3_quality_200",
                    "mode": "sample",
                    "state": "completed",
                    "quality_summary": {
                        "price_status_counts": {
                            "ok": 194,
                            "unknown_zero": 5,
                            "invalid_range": 1,
                            "partial_zero": 0,
                            "missing": 0,
                            "nonfinite": 0,
                        },
                        "issue_counts_by_severity": {
                            "error": 1,
                            "warning": 5,
                            "info": 0,
                        },
                        "eligibility": {
                            "search_eligible": {"num": 200, "den": 200, "rate": 1.0},
                            "location_eligible": {"num": 200, "den": 200, "rate": 1.0},
                            "price_filter_eligible": {"num": 194, "den": 200, "rate": 0.97},
                            "budget_eligible": {"num": 0, "den": 200, "rate": 0.0},
                            "hours_eligible": {"num": 0, "den": 200, "rate": 0.0},
                        },
                    },
                },
                "job_v1_legacy_old": {
                    "id": "job_v1_legacy_old",
                    "mode": "sample",
                    "state": "completed",
                    "report": {"discovered": 50, "processed": 50},
                },
            },
            "previews": {
                "job_v3_quality_200": {
                    "normalized": [
                        # 1. Valid positive ordered record (50k - 70k, 2 shifts)
                        {
                            "foody_id": 101,
                            "name": "Phở Gia Truyền Bát Đàn",
                            "address": "49 Bát Đàn, Quận Hoàn Kiếm",
                            "district": "Quận Hoàn Kiếm",
                            "price_status": "ok",
                            "price_min_vnd_norm": 50000,
                            "price_max_vnd_norm": 70000,
                            "price_min_raw": 50000.0,
                            "price_max_raw": 70000.0,
                            "hours_status": "day_mapping_unknown",
                            "opening_hours_raw": [
                                {"open": "06:00", "close": "14:00", "day_of_week_raw": 3},
                                {"open": "17:00", "close": "22:00", "day_of_week_raw": 3},
                            ],
                            "source_url": "https://www.foody.vn/ha-noi/pho-bat-dan",
                        },
                        # 2. Invalid0 record (0 - 0)
                        {
                            "foody_id": 1252693,
                            "name": "Cơm Tấm Minh Nhật - Tây Sơn",
                            "address": "Tây Sơn, Đống Đa",
                            "district": "Đống Đa",
                            "price_status": "unknown_zero",
                            "price_min_vnd_norm": None,
                            "price_max_vnd_norm": None,
                            "price_min_raw": 0.0,
                            "price_max_raw": 0.0,
                            "hours_status": "day_mapping_unknown",
                            "opening_hours_raw": [{"open": "09:00", "close": "21:00", "day_of_week_raw": 3}],
                            "source_url": "https://www.foody.vn/ha-noi/com-tam-minh-nhat",
                        },
                        # 3. Reversed record (350k - 60k)
                        {
                            "foody_id": 68957,
                            "name": "Bánh Mì - Phố Huế",
                            "address": "Phố Huế, Hai Bà Trưng",
                            "district": "Hai Bà Trưng",
                            "price_status": "invalid_range",
                            "price_min_vnd_norm": None,
                            "price_max_vnd_norm": None,
                            "price_min_raw": 350000.0,
                            "price_max_raw": 60000.0,
                            "hours_status": "day_mapping_unknown",
                            "opening_hours_raw": [{"open": "06:30", "close": "22:00", "day_of_week_raw": 3}],
                            "source_url": "https://www.foody.vn/ha-noi/banh-mi-pho-hue",
                        },
                        # 4. Null-safe & XSS protection check
                        {
                            "foody_id": 999,
                            "name": "<b id='xss-inject'>Quán Bún Chả</b>",
                            "address": None,
                            "district": None,
                            "price_status": "missing",
                            "price_min_vnd_norm": None,
                            "price_max_vnd_norm": None,
                            "hours_status": "missing",
                            "opening_hours_raw": None,
                            "source_url": None,
                        },
                    ],
                    None: [  # raw fallback layer
                        {
                            "name": "Phở Gia Truyền Bát Đàn (Raw)",
                            "price_min_vnd": 50000.0,
                            "price_max_vnd": 70000.0,
                            "opening_hours_raw": [{"open": "06:00", "close": "20:30"}],
                        }
                    ],
                },
                "job_v1_legacy_old": {
                    # No normalized layer: []
                    "normalized": [],
                    None: [  # raw layer
                        {
                            "name": "Bún Ốc Cổ Truyền",
                            "address": "Khương Thượng",
                            "price_min_vnd": 30000.0,
                            "price_max_vnd": 50000.0,
                            "opening_hours_raw": [{"open": "07:00", "close": "21:00"}],
                            "source_url": "https://www.foody.vn/ha-noi/bun-oc",
                        },
                    ],
                },
            },
        }

        cls.server_thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.server_thread.start()
        time.sleep(0.3)

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()

    def test_playwright_quality_flow_and_e2e(self):
        """Playwright E2E testing:

        1. Zero console errors and zero CSP violations.
        2. Quality panel displays price ok/unknown0/reversed and eligibility.
        3. Reversed price and 0 price are NEVER usable in preview.
        4. Valid price displays formatted VND range.
        5. Multi-shift hours preserve all shifts and include day mapping unknown note.
        6. All 6 new v0.3 download links configured correctly.
        7. History selection displays selected job quality, NOT active job.
        8. Old job fallback displays 'Chưa kiểm tra chất lượng (phiên cũ)'.
        9. Reclassify saved job via POST /api/quality works properly.
        """
        from playwright.sync_api import sync_playwright

        with sync_playwright() as p:
            browser = p.chromium.launch(channel="msedge", headless=True)
            page = browser.new_page()

            console_errors = []
            page.on("console", lambda msg: console_errors.append(msg.text) if msg.type == "error" else None)
            page.on("pageerror", lambda err: console_errors.append(str(err)))

            page.goto(f"http://127.0.0.1:{self.port}/index.html")
            page.wait_for_selector("#quality-section", timeout=5000)

            # 1. Verify zero initial console / CSP errors
            self.assertEqual(console_errors, [], f"Console errors found: {console_errors}")

            # 2. Select v0.3 job from history table to test quality panel
            history_rows = page.locator("#history-tbody tr")
            self.assertGreaterEqual(history_rows.count(), 2)

            # Click "👁 Xem dữ liệu" on job_v3_quality_200 (first history row)
            history_rows.nth(0).locator("button:has-text('Xem dữ liệu')").click()
            page.wait_for_selector("#quality-viewing-job:has-text('job_v3_quality_200')", timeout=5000)

            # 3. Verify Quality Panel Metrics for 200-venue job
            self.assertEqual(page.inner_text("#stat-price-ok"), "194")
            self.assertEqual(page.inner_text("#stat-price-zero"), "5")
            self.assertEqual(page.inner_text("#stat-price-reversed"), "1")

            self.assertEqual(page.inner_text("#stat-issues-error"), "1")
            self.assertEqual(page.inner_text("#stat-issues-warning"), "5")

            self.assertIn("200 / 200", page.inner_text("#stat-elig-search"))
            self.assertIn("200 / 200", page.inner_text("#stat-elig-location"))
            self.assertIn("194 / 200", page.inner_text("#stat-elig-price-filter"))
            self.assertIn("0", page.inner_text("#stat-elig-budget"))
            self.assertIn("0", page.inner_text("#stat-elig-hours"))

            # Verify truthful Vietnamese notes in panel
            self.assertIn("Khoảng giá toàn quán, không phải ngân sách món ăn", page.inner_text("#quality-section"))
            self.assertIn("không kết luận đóng cửa", page.inner_text("#quality-section"))

            # 4. Verify Preview Table: Reversed & 0 prices NEVER usable
            page.wait_for_selector("#preview-tbody tr:not(.empty-row)", timeout=5000)
            rows = page.locator("#preview-tbody tr")
            self.assertEqual(rows.count(), 4)

            # Row 1: Valid price (50k - 70k)
            row1_price = rows.nth(0).locator("td").nth(3).inner_text()
            self.assertEqual(row1_price, "50.000 ₫ – 70.000 ₫")

            # Row 1: Opening hours - 2 shifts preserved with day mapping unknown note
            row1_hours = rows.nth(0).locator("td").nth(4).inner_text()
            self.assertIn("06:00 - 14:00, 17:00 - 22:00", row1_hours)
            self.assertIn("Chưa rõ quy ước thứ", row1_hours)

            # Row 2: Invalid0 (0-0) -> NEVER usable, not free
            row2_price = rows.nth(1).locator("td").nth(3).inner_text()
            self.assertEqual(row2_price, "Chưa có giá tham khảo")
            self.assertNotIn("0 ₫ – 0 ₫", row2_price)
            self.assertNotIn("Miễn phí", row2_price)

            # Row 3: Reversed (350k > 60k) -> NEVER usable, not swapped
            row3_price = rows.nth(2).locator("td").nth(3).inner_text()
            self.assertEqual(row3_price, "Giá đảo chiều (không sử dụng)")
            self.assertNotIn("350.000 ₫ – 60.000 ₫", row3_price)
            self.assertNotIn("60.000 ₫ – 350.000 ₫", row3_price)

            # Row 4: XSS check -> tag rendered safely as textContent
            row4_name = rows.nth(3).locator("td").nth(1).inner_text()
            self.assertIn("<b id='xss-inject'>", row4_name)
            # Ensure no injected element in DOM
            self.assertEqual(page.locator("#xss-inject").count(), 0)

            # 5. Verify All 6 New v0.3 Download Links + Legacy Links
            self.assertIn("/api/download?job_id=job_v3_quality_200&format=normalized_csv", page.locator("#btn-download-norm-csv").get_attribute("href"))
            self.assertIn("/api/download?job_id=job_v3_quality_200&format=normalized", page.locator("#btn-download-norm-json").get_attribute("href"))
            self.assertIn("/api/download?job_id=job_v3_quality_200&format=issues_csv", page.locator("#btn-download-issues-csv").get_attribute("href"))
            self.assertIn("/api/download?job_id=job_v3_quality_200&format=issues", page.locator("#btn-download-issues-json").get_attribute("href"))
            self.assertIn("/api/download?job_id=job_v3_quality_200&format=quality", page.locator("#btn-download-quality").get_attribute("href"))
            self.assertIn("/api/download?job_id=job_v3_quality_200&format=raw", page.locator("#btn-download-raw").get_attribute("href"))

            self.assertIn("/api/download?job_id=job_v3_quality_200&format=csv", page.locator("#btn-download-csv").get_attribute("href"))
            self.assertIn("/api/download?job_id=job_v3_quality_200&format=json", page.locator("#btn-download-json").get_attribute("href"))
            self.assertIn("/api/download?job_id=job_v3_quality_200&format=report", page.locator("#btn-download-report").get_attribute("href"))

            # 6. Verify "Selected history quality must match selected job, not active job"
            # Background polling happens every 1.5s with active_job = "job_active_running" (8 ok, 1 reversed)
            # Quality panel must still show job_v3_quality_200 (194 ok, 1 reversed)
            time.sleep(2.0)
            self.assertEqual(page.inner_text("#quality-viewing-job"), "job_v3_quality_200")
            self.assertEqual(page.inner_text("#stat-price-ok"), "194")
            self.assertNotEqual(page.inner_text("#stat-price-ok"), "8")

            # 7. Old Job Fallback: Select job_v1_legacy_old
            history_rows.nth(1).locator("button:has-text('Xem dữ liệu')").click()
            page.wait_for_selector("#quality-viewing-job:has-text('job_v1_legacy_old')", timeout=5000)

            # Quality panel displays fallback alert
            fallback_box = page.locator("#quality-legacy-alert")
            self.assertTrue(fallback_box.is_visible())
            self.assertIn("Chưa kiểm tra chất lượng (phiên cũ)", page.inner_text("#quality-fallback-title"))

            # Preview layer badge indicates fallback
            layer_badge_text = page.inner_text("#badge-preview-layer")
            self.assertIn("Chưa kiểm tra chất lượng (phiên cũ)", layer_badge_text)

            # Preview table renders legacy record
            legacy_rows = page.locator("#preview-tbody tr")
            self.assertIn("Bún Ốc Cổ Truyền", legacy_rows.nth(0).inner_text())

            # 8. Test Reclassify Saved Job button (POST /api/quality)
            btn_reclassify = page.locator("#btn-reclassify-quality")
            self.assertTrue(btn_reclassify.is_visible())
            btn_reclassify.click()

            # Wait for success notification
            page.wait_for_selector(".banner-success", timeout=5000)
            self.assertIn("Kiểm định chất lượng thành công", page.inner_text("#system-banner-text"))
            self.assertEqual(self.server.state_store.get("quality_reclassify_called_for"), "job_v1_legacy_old")

            # Fallback alert should now be hidden and quality panel populated
            page.wait_for_selector("#quality-legacy-alert", state="hidden", timeout=5000)
            self.assertEqual(page.inner_text("#stat-price-ok"), "10")

            # Confirm zero console errors across entire run
            self.assertEqual(console_errors, [])

            browser.close()


class TestWebQualityWithCoordinatorApp(unittest.TestCase):
    """Integration test verifying quality assets served by real make_server."""

    def test_app_server_serves_quality_ui_with_zero_csp_violations(self):
        """Start real make_server, load Web UI in Playwright, verify zero console errors / CSP violations."""
        from foody_tool.app import make_server
        from foody_tool.jobs import JobManager
        from playwright.sync_api import sync_playwright

        temp_dir = tempfile.TemporaryDirectory()
        try:
            manager = JobManager(Path(temp_dir.name))
            server = make_server(manager, port=0, web_root=WEB_DIR)
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            port = server.server_port

            errors = []
            with sync_playwright() as p:
                browser = p.chromium.launch(channel="msedge", headless=True)
                page = browser.new_page()
                page.on("console", lambda msg: errors.append(msg.text) if msg.type == "error" else None)
                page.on("pageerror", lambda err: errors.append(str(err)))

                page.goto(f"http://127.0.0.1:{port}/")
                page.wait_for_selector("#quality-section", timeout=5000)
                self.assertIn("FoodTour Hà Nội", page.title())

                self.assertEqual(errors, [], f"Console errors or CSP violations found: {errors}")
                browser.close()

            server.shutdown()
            server.server_close()
        finally:
            temp_dir.cleanup()


if __name__ == "__main__":
    unittest.main()
