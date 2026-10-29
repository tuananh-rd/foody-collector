"""Tests for Foody Collector local Web UI (foody_tool/web/{index.html,style.css,app.js}).

Includes both static contract/security verification and full headless browser
integration tests with an in-memory mock backend server.
"""

import json
import os
import re
import socket
import threading
import time
import unittest
from http.server import HTTPServer, SimpleHTTPRequestHandler
from urllib.parse import parse_qs, urlparse

WEB_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "foody_tool", "web")
HTML_PATH = os.path.join(WEB_DIR, "index.html")
CSS_PATH = os.path.join(WEB_DIR, "style.css")
JS_PATH = os.path.join(WEB_DIR, "app.js")


class TestWebStatic(unittest.TestCase):
    """Static analysis and contract compliance tests for HTML/CSS/JS files."""

    @classmethod
    def setUpClass(cls):
        with open(HTML_PATH, "r", encoding="utf-8") as f:
            cls.html = f.read()
        with open(CSS_PATH, "r", encoding="utf-8") as f:
            cls.css = f.read()
        with open(JS_PATH, "r", encoding="utf-8") as f:
            cls.js = f.read()

    def test_files_exist_and_non_empty(self):
        """All three Web UI files must exist and contain code."""
        self.assertTrue(os.path.exists(HTML_PATH))
        self.assertTrue(os.path.exists(CSS_PATH))
        self.assertTrue(os.path.exists(JS_PATH))
        self.assertGreater(len(self.html), 200)
        self.assertGreater(len(self.css), 200)
        self.assertGreater(len(self.js), 200)

    def test_html_document_structure(self):
        """Verify HTML5 standards, UTF-8 charset, viewport, and Vietnamese language attribute."""
        self.assertTrue(self.html.startswith("<!DOCTYPE html>"))
        self.assertIn('<html lang="vi">', self.html)
        self.assertIn('<meta charset="UTF-8">', self.html)
        self.assertIn('name="viewport"', self.html)
        self.assertIn("<title>", self.html)
        self.assertIn("Hà Nội", self.html)

    def test_no_external_cdn_or_fonts(self):
        """Contract requirement: Plain HTML/CSS/JS, no build/CDN/framework or remote fonts."""
        # Find all link tags
        links = re.findall(r'<link\s+[^>]*href=["\']([^"\']+)["\']', self.html, re.IGNORECASE)
        for link in links:
            self.assertFalse(
                link.startswith("http://") or link.startswith("https://") or link.startswith("//"),
                f"External link found: {link}",
            )
            self.assertNotIn("fonts.googleapis.com", link)
            self.assertNotIn("cdnjs", link)
            self.assertNotIn("unpkg", link)

        # Find all script tags
        scripts = re.findall(r'<script\s+[^>]*src=["\']([^"\']+)["\']', self.html, re.IGNORECASE)
        for script in scripts:
            self.assertFalse(
                script.startswith("http://") or script.startswith("https://") or script.startswith("//"),
                f"External script found: {script}",
            )

        # Check CSS for @import or url(http...)
        imports = re.findall(r'@import\s+[^;]+;', self.css, re.IGNORECASE)
        self.assertEqual(imports, [], "No remote @import allowed in CSS")
        css_urls = re.findall(r'url\(["\']?(http[s]?://[^"\'\)]+)["\']?\)', self.css, re.IGNORECASE)
        self.assertEqual(css_urls, [], "No remote url(...) allowed in CSS")

    def test_required_ui_elements_in_html(self):
        """Verify all elements required by docs/V2_CONTRACT.md exist in HTML."""
        # Scope selection
        self.assertIn('id="mode-sample"', self.html)
        self.assertIn('id="mode-all"', self.html)

        # Sample limit editable with default 48
        self.assertIn('id="input-limit"', self.html)
        self.assertIn('value="48"', self.html)

        # Pace/interval >= 2.0 with default 3.0
        self.assertIn('id="input-interval"', self.html)
        self.assertIn('min="2.0"', self.html)
        self.assertIn('value="3.0"', self.html)

        # Visible browser toggle
        self.assertIn('id="input-show-browser"', self.html)
        self.assertIn('checked', self.html)

        # Action buttons: start, pause, resume, stop, shutdown
        self.assertIn('id="btn-start"', self.html)
        self.assertIn('id="btn-pause"', self.html)
        self.assertIn('id="btn-resume"', self.html)
        self.assertIn('id="btn-stop"', self.html)
        self.assertIn('id="btn-shutdown"', self.html)
        self.assertIn("Thoát ứng dụng", self.html)

        # Browser readiness container
        self.assertIn('id="browser-indicator-dot"', self.html)
        self.assertIn('id="browser-readiness-message"', self.html)

        # Metrics elements with accurate labeling
        self.assertIn('id="metric-discovered"', self.html)
        self.assertIn('id="metric-processed"', self.html)
        self.assertIn('id="metric-success"', self.html)
        self.assertIn('id="metric-duplicates"', self.html)
        self.assertIn('id="metric-failed"', self.html)
        self.assertIn('id="metric-clicks"', self.html)
        self.assertIn('id="metric-requests"', self.html)
        self.assertIn("Lượt tải trang quán", self.html)
        self.assertNotIn("Tổng yêu cầu mạng", self.html)

        # Strict CSP compliance: no inline event attributes in HTML
        self.assertNotIn("onsubmit=", self.html)
        self.assertNotIn("onclick=", self.html)

        # Table preview and downloads
        self.assertIn('id="preview-table"', self.html)
        self.assertIn('id="btn-download-csv"', self.html)
        self.assertIn('id="btn-download-json"', self.html)
        self.assertIn('id="btn-download-report"', self.html)

        # History table and resume note
        self.assertIn('id="history-table"', self.html)
        self.assertIn("bỏ qua các địa điểm đã thu thập", self.html)

    def test_no_internal_agent_architecture_terms_in_ui(self):
        """User normal flow must not use internal terms like worker, coordinator, dispatch, etc."""
        lower_html = self.html.lower()
        forbidden_terms = [
            "term_", "task_id", "dispatch_id", "ctx_", "subagent",
            "coordinator", "worker_done", "worktree", "antigravity",
        ]
        for term in forbidden_terms:
            self.assertNotIn(term, lower_html, f"Internal term '{term}' found in user-facing HTML")

    def test_css_rules_and_accessibility(self):
        """Check CSS variables, responsive breakpoints, and key classes."""
        self.assertIn("--primary:", self.css)
        self.assertIn("--success:", self.css)
        self.assertIn("--warning:", self.css)
        self.assertIn("--danger:", self.css)
        self.assertIn(".badge-running", self.css)
        self.assertIn(".btn-discreet", self.css)
        self.assertIn(".progress-fill", self.css)
        self.assertIn(".table-responsive", self.css)
        self.assertIn("@media", self.css)

    def test_js_security_and_contract(self):
        """Check app.js for safe DOM practices, CSRF header, and contract endpoints."""
        # CSRF Token
        self.assertIn("X-CSRF-Token", self.js)
        self.assertIn("csrf_token", self.js)

        # Contract endpoints
        self.assertIn("/api/status", self.js)
        self.assertIn("/api/history", self.js)
        self.assertIn("/api/start", self.js)
        self.assertIn("/api/pause", self.js)
        self.assertIn("/api/resume", self.js)
        self.assertIn("/api/stop", self.js)
        self.assertIn("/api/shutdown", self.js)
        self.assertIn("/api/preview", self.js)
        self.assertIn("/api/download", self.js)

        # Raw price 0 / 0 handling: displays Chưa có giá tham khảo (not free)
        self.assertIn("Chưa có giá tham khảo", self.js)

        # Form submit preventDefault for strict CSP compliance
        self.assertIn("preventDefault", self.js)

        # No unsafe innerHTML with data concatenation
        # Check that innerHTML is not used to insert raw record variables
        self.assertNotIn("innerHTML = record.", self.js)
        self.assertNotIn("innerHTML = item.", self.js)
        self.assertNotIn("innerHTML = job.", self.js)
        self.assertIn("textContent", self.js)

        # Incomplete / notcomplete logic on stalled/blocked/limit
        self.assertIn("stalled", self.js)
        self.assertIn("blocked", self.js)
        self.assertIn("limit", self.js)
        self.assertIn("Chưa hoàn thành", self.js)
        self.assertIn("Hoàn thành mẫu", self.js)


# --- Mock HTTP Server for End-to-End Browser Testing ---

class MockFoodyBackendHandler(SimpleHTTPRequestHandler):
    """Mock HTTP handler implementing docs/V2_CONTRACT.md API for WebUI testing."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=WEB_DIR, **kwargs)

    def log_message(self, format, *args):
        # Silence standard server logging during test runs
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

        if path == "/api/status":
            server_state = getattr(self.server, "state_store", {})
            self._send_json(200, {
                "active_job": server_state.get("active_job"),
                "browser_ready": server_state.get("browser_ready", True),
                "browser_message": server_state.get("browser_message", "Microsoft Edge đã sẵn sàng"),
                "csrf_token": server_state.get("csrf_token", "csrf-token-abc-123"),
            })
        elif path == "/api/history":
            server_state = getattr(self.server, "state_store", {})
            self._send_json(200, {
                "jobs": server_state.get("history_jobs", [])
            })
        elif path == "/api/preview":
            job_id = qs.get("job_id", [None])[0]
            server_state = getattr(self.server, "state_store", {})
            records = server_state.get("preview_records", [])
            self._send_json(200, {
                "records": records,
                "total": len(records),
            })
        elif path == "/api/download":
            job_id = qs.get("job_id", [""])[0]
            fmt = qs.get("format", ["csv"])[0]
            content = f"id,name\n1,Test Quán ({fmt})"
            data = content.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/octet-stream")
            self.send_header("Content-Disposition", f'attachment; filename="data_{job_id}.{fmt}"')
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
        else:
            # Serve static files (index.html, style.css, app.js)
            super().do_GET()

    def do_POST(self):
        parsed = urlparse(self.path)
        path = parsed.path
        server_state = getattr(self.server, "state_store", {})

        # Verify CSRF Token
        csrf_received = self.headers.get("X-CSRF-Token")
        expected_csrf = server_state.get("csrf_token", "csrf-token-abc-123")
        if csrf_received != expected_csrf:
            self._send_json(403, {"error": "Invalid CSRF token"})
            return

        content_length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(content_length).decode("utf-8") if content_length > 0 else "{}"
        try:
            req_data = json.loads(body)
        except Exception:
            req_data = {}

        if path == "/api/start":
            mode = req_data.get("mode", "sample")
            limit = req_data.get("limit", 48)
            interval = req_data.get("interval", 3)
            show_browser = req_data.get("show_browser", True)

            job = {
                "id": "job_mock_001",
                "mode": mode,
                "state": "running",
                "stage": "discovering",
                "discovered": 12,
                "processed": 4,
                "success": 4,
                "duplicates": 0,
                "failed": 0,
                "clicks": 1,
                "request_count": 5,
                "limit": limit if mode == "sample" else None,
                "interval": interval,
                "started_at": "2026-10-14T14:30:00Z",
                "updated_at": "2026-10-14T14:31:00Z",
                "termination_reason": None,
                "coverage_verified": False,
                "message": "Đang tìm kiếm liên kết quán...",
                "logs": [
                    {"time": "14:30:00", "message": "Bắt đầu khởi động trình duyệt..."},
                    {"time": "14:30:10", "message": "Tải trang Foody Hà Nội thành công."},
                    {"time": "14:30:20", "message": "Phát hiện 12 địa điểm đầu tiên."},
                ],
            }
            server_state["active_job"] = job
            server_state["last_start_req"] = req_data
            self._send_json(200, {"job_id": job["id"], "job": job})

        elif path == "/api/pause":
            job = server_state.get("active_job", {})
            if job:
                job["state"] = "paused"
                job["message"] = "Tiến trình đang tạm dừng."
            self._send_json(200, {"job": job})

        elif path == "/api/resume":
            job = server_state.get("active_job", {})
            if job:
                job["state"] = "running"
                job["message"] = "Tiếp tục thu thập dữ liệu..."
            self._send_json(200, {"job": job})

        elif path == "/api/stop":
            job = server_state.get("active_job", {})
            if job:
                job["state"] = "stopped"
                job["termination_reason"] = "stopped"
                job["message"] = "Người dùng đã dừng tiến trình."
            self._send_json(200, {"job": job})

        elif path == "/api/shutdown":
            server_state["shutdown_called"] = True
            server_state["last_shutdown_body"] = req_data
            server_state["last_shutdown_csrf"] = csrf_received
            self._send_json(200, {"message": "Đang lưu tiến độ và đóng ứng dụng."})
        else:
            self._send_json(404, {"error": "Not found"})


class TestWebBrowserE2E(unittest.TestCase):
    """End-to-End Headless Browser tests for WebUI using Playwright and local mock server."""

    @classmethod
    def setUpClass(cls):
        # Find free port
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.bind(("127.0.0.1", 0))
        cls.port = sock.getsockname()[1]
        sock.close()

        # Start Mock HTTP Server
        cls.server = HTTPServer(("127.0.0.1", cls.port), MockFoodyBackendHandler)
        cls.server.state_store = {
            "csrf_token": "csrf-test-token-777",
            "browser_ready": True,
            "browser_message": "Microsoft Edge tự động sẵn sàng",
            "active_job": None,
            "history_jobs": [
                {
                    "id": "job_past_100",
                    "mode": "sample",
                    "state": "completed",
                    "processed": 48,
                    "limit": 48,
                    "discovered": 48,
                    "started_at": "2026-10-14T10:00:00Z",
                },
                {
                    "id": "job_past_101",
                    "mode": "all",
                    "state": "stopped",
                    "processed": 36,
                    "limit": None,
                    "discovered": 50,
                    "started_at": "2026-10-14T11:00:00Z",
                },
            ],
            "preview_records": [
                {
                    "name": "Phở Gia Truyền Bát Đàn",
                    "address": "49 Bát Đàn, Quận Hoàn Kiếm",
                    "district": "Quận Hoàn Kiếm",
                    "price_min_vnd": 50000.0,
                    "price_max_vnd": 70000.0,
                    "opening_hours_raw": [{"open": "06:00", "close": "20:30"}],
                    "source_url": "https://www.foody.vn/ha-noi/pho-gia-truyen-bat-dan",
                },
                {
                    "name": "<script>window.__xss_fired=true;</script>Quán Test XSS",
                    "address": None,
                    "district": None,
                    "price_min_vnd": None,
                    "price_max_vnd": None,
                    "opening_hours_raw": None,
                    "source_url": "https://www.foody.vn/ha-noi/quan-test",
                },
                {
                    "name": "Bún Ốc Bà Lương",
                    "address": "195 Khương Thượng, Quận Đống Đa",
                    "district": "Quận Đống Đa",
                    "price_min_vnd": 0.0,
                    "price_max_vnd": 0.0,
                    "opening_hours_raw": [{"open": "07:00", "close": "21:00"}],
                    "source_url": "https://www.foody.vn/ha-noi/bun-oc-ba-luong",
                },
            ],
        }

        cls.server_thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.server_thread.start()
        time.sleep(0.3)

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()

    def test_full_web_ui_flow_in_browser(self):
        """Test full user interaction flow in headless browser:

        1. Page loads cleanly and displays Vietnamese branding.
        2. Browser readiness message rendered from /api/status.
        3. Starting a job sends POST /api/start with X-CSRF-Token and updates buttons.
        4. Metrics and progress update live.
        5. Data preview renders safely (XSS tags sanitized, nulls handled gracefully).
        6. Pause, Resume, Stop controls function properly.
        7. Termination reasons and incomplete status displayed accurately.
        8. History list displays past runs and provides resume actions.
        """
        from playwright.sync_api import sync_playwright

        with sync_playwright() as p:
            # Launch Edge headless
            browser = p.chromium.launch(channel="msedge", headless=True)
            page = browser.new_page()

            page.goto(f"http://127.0.0.1:{self.port}/index.html")

            # 1. Verify Branding & Header
            title = page.title()
            self.assertIn("FoodTour Hà Nội", title)
            h1 = page.inner_text(".brand-title")
            self.assertIn("FoodTour Hà Nội", h1)

            # 2. Browser Readiness
            page.wait_for_selector("#browser-indicator-dot.dot-ready", timeout=5000)
            readiness_text = page.inner_text("#browser-readiness-message")
            self.assertIn("Microsoft Edge tự động sẵn sàng", readiness_text)

            # 3. Check Initial Button States
            btn_start = page.locator("#btn-start")
            btn_pause = page.locator("#btn-pause")
            btn_resume = page.locator("#btn-resume")
            btn_stop = page.locator("#btn-stop")

            self.assertTrue(btn_start.is_enabled())
            self.assertTrue(btn_pause.is_disabled())
            self.assertTrue(btn_resume.is_disabled())
            self.assertTrue(btn_stop.is_disabled())

            # 4. Test Mode Selection (Switching to 'all' disables limit input)
            input_limit = page.locator("#input-limit")
            self.assertTrue(input_limit.is_enabled())

            page.locator("label:has(#mode-all)").click()
            self.assertTrue(input_limit.is_disabled())

            # Switch back to 'sample'
            page.locator("label:has(#mode-sample)").click()
            self.assertTrue(input_limit.is_enabled())

            # 5. Click "Bắt đầu" (Start)
            btn_start.click()
            page.wait_for_selector("#badge-job-state.badge-running", timeout=5000)

            # Verify POST payload received by server
            last_req = self.server.state_store.get("last_start_req", {})
            self.assertEqual(last_req.get("mode"), "sample")
            self.assertEqual(last_req.get("limit"), 48)
            self.assertEqual(last_req.get("interval"), 3.0)
            self.assertTrue(last_req.get("show_browser"))

            # Verify Button States during running
            self.assertTrue(btn_start.is_disabled())
            self.assertTrue(btn_pause.is_enabled())
            self.assertTrue(btn_resume.is_disabled())
            self.assertTrue(btn_stop.is_enabled())

            # Verify Metrics Display
            page.wait_for_function("document.getElementById('metric-processed').textContent !== '0'")
            self.assertEqual(page.inner_text("#metric-processed"), "4")
            self.assertEqual(page.inner_text("#metric-discovered"), "12")
            self.assertEqual(page.inner_text("#metric-success"), "4")
            self.assertIn("4 / 48 (8%)", page.inner_text("#progress-counter-text"))

            # Verify Accurate Label for requests metric
            metric_requests_label = page.inner_text(".metric-card:has(#metric-requests) .metric-label")
            self.assertEqual(metric_requests_label, "Lượt tải trang quán")

            # 6. Verify Data Preview & XSS Safety
            page.wait_for_selector("#preview-tbody tr:not(.empty-row)", timeout=5000)
            rows = page.locator("#preview-tbody tr")
            self.assertEqual(rows.count(), 3)

            # First row: normal restaurant
            first_row_text = rows.nth(0).inner_text()
            self.assertIn("Phở Gia Truyền Bát Đàn", first_row_text)
            self.assertIn("49 Bát Đàn, Quận Hoàn Kiếm", first_row_text)
            self.assertIn("50.000 ₫ – 70.000 ₫", first_row_text)
            self.assertIn("06:00 - 20:30", first_row_text)

            # Second row: XSS tag in name and nulls
            second_row_name = rows.nth(1).locator("td").nth(1).inner_text()
            self.assertIn("<script>", second_row_name)
            # Verify script NEVER executed
            xss_fired = page.evaluate("() => window.__xss_fired")
            self.assertIsNone(xss_fired, "XSS was executed! textContent must be used.")

            # Second row null-safe labels
            second_row_addr = rows.nth(1).locator("td").nth(2).inner_text()
            second_row_price = rows.nth(1).locator("td").nth(3).inner_text()
            second_row_hours = rows.nth(1).locator("td").nth(4).inner_text()
            self.assertIn("Chưa có thông tin", second_row_addr)
            self.assertIn("Không khả dụng", second_row_price)
            self.assertIn("Chưa có thông tin", second_row_hours)

            # Third row: raw 0 / 0 price displayed as Chưa có giá tham khảo (not free)
            third_row_name = rows.nth(2).locator("td").nth(1).inner_text()
            third_row_price = rows.nth(2).locator("td").nth(3).inner_text()
            self.assertIn("Bún Ốc Bà Lương", third_row_name)
            self.assertEqual(third_row_price, "Chưa có giá tham khảo")

            # 7. Test Pause
            btn_pause.click()
            page.wait_for_selector("#badge-job-state.badge-paused", timeout=5000)
            self.assertTrue(btn_pause.is_disabled())
            self.assertTrue(btn_resume.is_enabled())
            self.assertTrue(btn_stop.is_enabled())

            # 8. Test Resume
            btn_resume.click()
            page.wait_for_selector("#badge-job-state.badge-running", timeout=5000)
            self.assertTrue(btn_pause.is_enabled())
            self.assertTrue(btn_resume.is_disabled())

            # 9. Test Stop
            btn_stop.click()
            page.wait_for_selector("#badge-job-state.badge-stopped", timeout=5000)
            self.assertTrue(btn_start.is_enabled())
            self.assertTrue(btn_pause.is_disabled())
            self.assertTrue(btn_stop.is_disabled())

            # Check Termination Notice Box & Incomplete Badge
            notice = page.locator("#termination-notice")
            self.assertTrue(notice.is_visible())
            self.assertIn("Người dùng đã dừng phiên", page.inner_text("#termination-title"))
            self.assertTrue(page.locator("#badge-incomplete").is_visible())

            # 10. Verify Download Links
            csv_href = page.locator("#btn-download-csv").get_attribute("href")
            json_href = page.locator("#btn-download-json").get_attribute("href")
            report_href = page.locator("#btn-download-report").get_attribute("href")
            self.assertIn("/api/download?job_id=job_mock_001&format=csv", csv_href)
            self.assertIn("/api/download?job_id=job_mock_001&format=json", json_href)
            self.assertIn("/api/download?job_id=job_mock_001&format=report", report_href)

            # 11. Verify History Table & Sample Complete Labeling
            history_rows = page.locator("#history-tbody tr")
            self.assertEqual(history_rows.count(), 2)
            self.assertIn("job_past_100", history_rows.nth(0).inner_text())
            self.assertIn("Hoàn thành mẫu", history_rows.nth(0).inner_text())
            self.assertIn("job_past_101", history_rows.nth(1).inner_text())

            # 12. Test Form Submit (strict CSP: preventDefault, no reload)
            page.evaluate("() => document.getElementById('collector-form').dispatchEvent(new Event('submit', { cancelable: true }))")
            self.assertIn("FoodTour Hà Nội", page.title())

            # 13. Test Discreet Exit Button (POST /api/shutdown)
            btn_shutdown = page.locator("#btn-shutdown")
            self.assertTrue(btn_shutdown.is_visible())
            btn_shutdown.click()
            page.wait_for_selector(".banner-info", timeout=5000)
            banner_text = page.inner_text("#system-banner-text")
            self.assertIn("Đang lưu tiến độ và đóng ứng dụng.", banner_text)
            self.assertTrue(self.server.state_store.get("shutdown_called"))
            self.assertEqual(self.server.state_store.get("last_shutdown_body"), {})
            self.assertEqual(self.server.state_store.get("last_shutdown_csrf"), self.server.state_store["csrf_token"])
            self.assertTrue(btn_start.is_disabled())
            self.assertTrue(btn_shutdown.is_disabled())

            browser.close()


class TestWebWithCoordinatorApp(unittest.TestCase):
    """Integration test verifying web assets directly served by foody_tool.app.make_server."""

    def test_app_server_serves_web_assets_with_zero_csp_violations(self):
        """Start real make_server, load Web UI in Playwright, verify zero console errors / CSP violations."""
        import tempfile
        from pathlib import Path
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
                page.wait_for_selector("#browser-indicator-dot.dot-ready", timeout=5000)
                self.assertIn("FoodTour Hà Nội", page.title())

                # Verify no CSP errors or console exceptions were raised
                self.assertEqual(errors, [], f"Console errors or CSP violations found: {errors}")
                browser.close()

            server.shutdown()
            server.server_close()
        finally:
            temp_dir.cleanup()


if __name__ == "__main__":
    unittest.main()
