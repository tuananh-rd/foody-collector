"""Tests for Vietnamese v0.4 Enriched UI and API (foody_tool/web/*, app.py, jobs.py).

Compliant with docs/V4_CONTRACT.md:
- Enriched data view shows fields from restaurants_enriched.json when present
- Table columns & filters: cuisine, venue type, dish group, suitable meal, audience,
  rating >= N (with review-count minimum), amenity yes filter (only status yes;
  tri-state labeled distinctly with tooltips), prep time, capacity, source link
- Honest Vietnamese copy: dish groups are categories not itemized menu; price is venue range;
  ratings are platform signals not verified quality; gray amenity is platform-asserted unconfirmed;
  hours are not a verified weekly schedule
- API: POST /api/enrich (CSRF + Host/Origin checks, saved job only, rejects running jobs,
  zero network requests, returns enrichment report), GET download of restaurants_enriched.csv/json
- Legacy 18-column behavior unchanged
- Old-job fallback: degrades gracefully, shows no enrichment columns, no errors
"""

import csv
import json
import os
import re
import socket
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.request
from http.server import HTTPServer, SimpleHTTPRequestHandler
from pathlib import Path

from foody_tool.app import make_server
from foody_tool.jobs import JobManager

WEB_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "foody_tool", "web")
HTML_PATH = os.path.join(WEB_DIR, "index.html")
CSS_PATH = os.path.join(WEB_DIR, "style.css")
JS_PATH = os.path.join(WEB_DIR, "app.js")


class TestWebEnrichStatic(unittest.TestCase):
    """Static analysis and contract compliance tests for HTML/CSS/JS files."""

    @classmethod
    def setUpClass(cls):
        with open(HTML_PATH, "r", encoding="utf-8") as f:
            cls.html = f.read()
        with open(CSS_PATH, "r", encoding="utf-8") as f:
            cls.css = f.read()
        with open(JS_PATH, "r", encoding="utf-8") as f:
            cls.js = f.read()

    def test_enrichment_dom_elements_exist_in_html(self):
        """Verify layer switcher, download buttons, disclaimer, filters, and table header exist."""
        # Layer controls
        self.assertIn('id="layer-enriched"', self.html)
        self.assertIn('id="layer-normalized"', self.html)
        self.assertIn('id="layer-raw"', self.html)
        self.assertIn('id="badge-preview-layer"', self.html)

        # Download buttons
        self.assertIn('id="btn-download-enriched-csv"', self.html)
        self.assertIn('id="btn-download-enriched-json"', self.html)
        self.assertIn('id="btn-download-enrichment-report"', self.html)
        self.assertIn('id="btn-enrich-job"', self.html)

        # Disclaimer
        self.assertIn('id="enrichment-disclaimer"', self.html)

        # Filter toolbar and inputs
        self.assertIn('id="preview-filter-toolbar"', self.html)
        self.assertIn('id="filter-cuisine"', self.html)
        self.assertIn('id="filter-venue-type"', self.html)
        self.assertIn('id="filter-dish-group"', self.html)
        self.assertIn('id="filter-suitable-meal"', self.html)
        self.assertIn('id="filter-audience"', self.html)
        self.assertIn('id="filter-min-rating"', self.html)
        self.assertIn('id="filter-min-reviews"', self.html)
        self.assertIn('id="filter-amenity"', self.html)
        self.assertIn('id="filter-prep-time"', self.html)
        self.assertIn('id="filter-capacity"', self.html)
        self.assertIn('id="btn-reset-filters"', self.html)

        # Dynamic table thead
        self.assertIn('id="preview-thead"', self.html)
        self.assertIn('id="preview-thead-row"', self.html)

    def test_honest_copy_strings_present(self):
        """Verify truthful Vietnamese copy required by v0.4 contract is present."""
        # 1. Dish groups are categories, not an itemized menu
        self.assertTrue(
            "Nhóm món là phân loại danh mục tổng quát, không phải thực đơn chi tiết" in self.html or
            "không phải thực đơn chi tiết" in self.html
        )
        self.assertIn("không phải thực đơn chi tiết", self.js)

        # 2. Price is a venue range
        self.assertTrue(
            "Khoảng giá toàn quán" in self.html or
            "khoảng giá toàn quán" in self.html
        )
        self.assertIn("Khoảng giá toàn quán", self.js)

        # 3. Ratings are platform signals not verified quality or current business status
        self.assertTrue(
            "Tín hiệu từ nền tảng Foody" in self.html or
            "tín hiệu tổng hợp từ người dùng trên nền tảng Foody" in self.html
        )
        self.assertIn("Tín hiệu từ nền tảng Foody, không phải chứng nhận chất lượng đã kiểm định", self.js)

        # 4. Gray amenity = platform marks not offered/unconfirmed, not independently verified
        self.assertTrue(
            "platform-asserted" in self.html or
            "chưa được kiểm định độc lập" in self.html or
            "chưa kiểm định độc lập" in self.html
        )
        self.assertIn("platform-asserted", self.js)
        self.assertIn("chưa kiểm định độc lập", self.js)

        # 5. Hours are not a verified weekly schedule
        self.assertTrue(
            "không phải lịch hoạt động hàng tuần đã xác minh" in self.html or
            "chưa rõ quy ước thứ" in self.html
        )
        self.assertIn("không phải lịch tuần đã xác minh", self.js)

    def test_csp_and_no_inline_handlers(self):
        """Strict CSP compliance: no inline handlers or external CDNs."""
        for pattern in (r'onclick\s*=', r'onsubmit\s*=', r'onload\s*=', r'onerror\s*='):
            self.assertEqual(re.findall(pattern, self.html, re.IGNORECASE), [], f"Found inline handler: {pattern}")
        self.assertNotIn("cdnjs", self.html)
        self.assertNotIn("googleapis", self.html)
        self.assertNotIn("unpkg", self.html)

    def test_amenity_semantics_ui_contract(self):
        """Regression test for Task C UI requirements:
        1. Header uses 'Tiện ích (Có / Chưa xác nhận)' without implying not available.
        2. Amenity filter only offers yes.
        3. Gray amenities show as 'chưa xác nhận' with proper tooltip.
        4. amenities_no export column is always empty."""
        from foody_tool.exporter import record_to_enriched_row

        # 1. Header has 'Tiện ích (Có / Chưa xác nhận)'
        self.assertIn("Tiện ích (Có / Chưa xác nhận)", self.js)
        self.assertNotIn("Tiện ích (Có / Không / Chưa rõ)", self.js)

        # 2. Amenity filter only offers yes
        self.assertIn("Tiện ích có sẵn (chỉ lọc Có)", self.html)

        # 3. JS tooltip explains platform did not mark it as offered, not verification of absence
        self.assertIn("không phải xác minh là không có", self.js)
        self.assertIn("not verification that it is absent", self.js)
        self.assertIn("chưa xác nhận", self.js)

        # 4. record_to_enriched_row always emits amenities_no as empty string
        mock_rec = {
            "name": "Test",
            "enrichment": {
                "amenities": [
                    {"key": "wifi", "label": "Có wifi", "status": "yes"},
                    {"key": "giaohang", "label": "Có giao hàng", "status": "no"},
                    {"key": "maylanh", "label": "Có máy lạnh", "status": "unknown"},
                ]
            }
        }
        row = record_to_enriched_row(mock_rec)
        self.assertEqual(row["amenities_no"], "")
        self.assertEqual(row["amenities_yes"], "Có wifi")
        self.assertIn("Có máy lạnh", row["amenities_unknown"])


class TestWebEnrichAPI(unittest.TestCase):
    """Direct HTTP API integration tests for /api/enrich and download endpoints."""

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        folder = Path(self.temp.name)
        assets = folder / "web"
        assets.mkdir()
        (assets / "index.html").write_text("<html>FoodTour Test</html>", encoding="utf-8")
        self.manager = JobManager(folder / "jobs")
        self.server = make_server(self.manager, port=0, web_root=assets)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.base = f"http://127.0.0.1:{self.server.server_port}"
        _, status = self.request("/api/status")
        self.token = status["csrf_token"]

    def tearDown(self):
        self.manager.shutdown()
        self.server.shutdown()
        self.thread.join(2)
        self.server.server_close()
        self.temp.cleanup()

    def request(self, path, body=None, headers=None):
        options = {"headers": headers or {}}
        if body is not None:
            options["data"] = json.dumps(body).encode("utf-8")
            options["headers"] = {"Content-Type": "application/json", **options["headers"]}
        req = urllib.request.Request(self.base + path, **options)
        try:
            response = urllib.request.urlopen(req, timeout=5)
        except urllib.error.HTTPError as exc:
            response = exc
        with response:
            raw = response.read()
            data = json.loads(raw) if response.headers.get_content_type() == "application/json" else raw
            return response.status, data

    def test_post_enrich_csrf_and_security(self):
        """POST /api/enrich requires valid CSRF and rejects bad origin/host."""
        # 1. Missing CSRF
        code, _ = self.request("/api/enrich", {"job_id": "nonexistent"})
        self.assertEqual(code, 403)

        # 2. Invalid CSRF
        code, _ = self.request("/api/enrich", {"job_id": "nonexistent"}, {"X-CSRF-Token": "bad-token"})
        self.assertEqual(code, 403)

        # 3. Bad Origin
        code, _ = self.request("/api/enrich", {"job_id": "nonexistent"},
                               {"X-CSRF-Token": self.token, "Origin": "https://evil.attacker.com"})
        self.assertEqual(code, 403)

    def test_post_enrich_rejects_running_job(self):
        """POST /api/enrich rejects running jobs with 400 Bad Request."""
        job = self.manager.start({"mode": "sample", "limit": 50})
        try:
            code, data = self.request("/api/enrich", {"job_id": job.data["id"]}, {"X-CSRF-Token": self.token})
            self.assertEqual(code, 400)
            self.assertIn("error", data)
            self.assertIn("Không thể làm giàu dữ liệu khi phiên đang chạy hoặc tạm dừng", data["error"])
        finally:
            job.stop()

    def test_post_enrich_success_and_downloads_on_saved_job(self):
        """POST /api/enrich enriches a saved job, writes files, and enables downloads."""
        # Create a synthetic stopped job with cached HTML
        job_id = "a" * 32
        job_dir = Path(self.temp.name) / "jobs" / job_id
        job_dir.mkdir(parents=True, exist_ok=True)
        cache_dir = job_dir / "cache"
        cache_dir.mkdir(exist_ok=True)

        url = "https://www.foody.vn/ha-noi/pho-gia-truyen-bat-dan"
        import hashlib
        cache_file = cache_dir / (hashlib.sha256(url.encode()).hexdigest()[:20] + ".html")
        sample_html = (
            '<html><head><title>Phở Bát Đàn</title></head><body>'
            '<script>var initData = {"RestaurantID": 101, "Name": "Phở Bát Đàn", "PriceMin": 50000, "PriceMax": 70000};</script>'
            '<div class="new-detail-info-area"><div class="new-detail-info-label">Phong cách ẩm thực</div><div><a href="/ha-noi/mon-viet">Món Việt</a></div></div>'
            '<div class="new-detail-info-area"><div class="new-detail-info-label">Thể loại</div><div><a href="/ha-noi/quan-an">Quán ăn</a></div></div>'
            '<div class="new-detail-info-area"><div class="new-detail-info-label">Phục vụ các món</div><div><a href="/ha-noi/pho-bo">Phở bò</a></div></div>'
            '<div class="new-detail-info-area"><div class="new-detail-info-label">Thích hợp</div><div><a href="/ha-noi/bua-sang">Bữa sáng</a></div></div>'
            '<div class="new-detail-info-area"><div class="new-detail-info-label">Phù hợp với</div><div><a href="/ha-noi/moi-lua-tuoi">Mọi lứa tuổi</a></div></div>'
            '<div class="new-detail-info-area"><div class="new-detail-info-label">Thời gian chuẩn bị</div><div><span>Khoảng 5 - 10 phút</span></div></div>'
            '<div class="new-detail-info-area"><div class="new-detail-info-label">Sức chứa</div><div><span>50 người lớn</span></div></div>'
            '<span itemprop="ratingValue">8.8</span><span itemprop="reviewCount">42</span>'
            '<ul class="micro-property"><li><a class="resproperties-report" istrue="true"><span errorkeyname="Wifi">Wifi</span></a></li></ul>'
            '</body></html>'
        )
        cache_file.write_text(sample_html, encoding="utf-8")
        (job_dir / "urls.json").write_text(json.dumps([url]), encoding="utf-8")
        (job_dir / "restaurants.json").write_text(json.dumps([{
            "foody_id": 101, "name": "Phở Bát Đàn", "source_url": url,
            "price_min_vnd": 50000, "price_max_vnd": 70000
        }]), encoding="utf-8")
        (job_dir / "job.json").write_text(json.dumps({
            "id": job_id, "mode": "sample", "state": "completed",
            "started_at": "2026-10-15T00:00:00Z", "processed": 1
        }), encoding="utf-8")

        # Reload manager so it discovers the saved job
        self.manager = JobManager(Path(self.temp.name) / "jobs")
        self.server.manager = self.manager

        # 1. Call POST /api/enrich
        code, res = self.request("/api/enrich", {"job_id": job_id}, {"X-CSRF-Token": self.token})
        self.assertEqual(code, 200)
        self.assertIn("pages_parsed", res)
        self.assertEqual(res["pages_parsed"], 1)
        self.assertEqual(res["network_requests"], 0)

        # 2. Verify enriched files exist on disk
        self.assertTrue((job_dir / "restaurants_enriched.json").is_file())
        self.assertTrue((job_dir / "restaurants_enriched.csv").is_file())
        self.assertTrue((job_dir / "enrichment_report.json").is_file())

        # 3. Test GET download enriched JSON
        code, data_json = self.request(f"/api/download?job_id={job_id}&format=enriched")
        self.assertEqual(code, 200)
        self.assertEqual(len(data_json), 1)
        self.assertEqual(data_json[0]["name"], "Phở Bát Đàn")
        self.assertEqual(data_json[0]["cuisine_styles"], "Món Việt")
        self.assertEqual(data_json[0]["prep_time_raw"], "Khoảng 5 - 10 phút")
        self.assertEqual(data_json[0]["amenities_yes"], "Wifi")
        self.assertEqual(data_json[0]["amenities_no"], "")

        # 4. Test GET download enriched CSV
        code, data_csv = self.request(f"/api/download?job_id={job_id}&format=enriched_csv")
        self.assertEqual(code, 200)
        self.assertIn(b"cuisine_styles", data_csv)
        self.assertIn(b"M\xc3\xb3n Vi\xe1\xbb\x87t", data_csv)

        # 5. Test GET download enrichment report
        code, rep_json = self.request(f"/api/download?job_id={job_id}&format=enrichment_report")
        self.assertEqual(code, 200)
        self.assertEqual(rep_json["pages_parsed"], 1)

        # 6. Test GET preview with layer=enriched
        code, preview = self.request(f"/api/preview?job_id={job_id}&layer=enriched")
        self.assertEqual(code, 200)
        self.assertEqual(preview["total"], 1)
        self.assertEqual(preview["records"][0]["dish_groups"], "Phở bò")

        # 7. Test legacy download unchanged
        code, leg_json = self.request(f"/api/download?job_id={job_id}&format=json")
        self.assertEqual(code, 200)
        self.assertEqual(leg_json[0]["foody_id"], 101)

    def test_old_job_fallback_and_graceful_degradation(self):
        """Old jobs without enrichment files return 404 for enriched downloads and empty preview."""
        job_id = "b" * 32
        job_dir = Path(self.temp.name) / "jobs" / job_id
        job_dir.mkdir(parents=True, exist_ok=True)
        (job_dir / "restaurants.json").write_text(json.dumps([{"foody_id": 999, "name": "Old Venue"}]), encoding="utf-8")
        (job_dir / "job.json").write_text(json.dumps({
            "id": job_id, "mode": "sample", "state": "completed",
            "started_at": "2026-10-15T00:00:00Z", "processed": 1
        }), encoding="utf-8")

        self.manager = JobManager(Path(self.temp.name) / "jobs")
        self.server.manager = self.manager

        # Download enriched fails with not_available
        code, res = self.request(f"/api/download?job_id={job_id}&format=enriched")
        self.assertEqual(code, 404)
        self.assertEqual(res, {"error": "not_available"})

        # Preview layer=enriched returns empty records without raising error
        code, preview = self.request(f"/api/preview?job_id={job_id}&layer=enriched")
        self.assertEqual(code, 200)
        self.assertEqual(preview["records"], [])
        self.assertEqual(preview["total"], 0)


class MockWebEnrichBackendHandler(SimpleHTTPRequestHandler):
    """Synthetic backend serving mock endpoints for Playwright E2E browser tests."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=WEB_DIR, **kwargs)

    def log_message(self, fmt, *args):
        pass

    def _send_json(self, status, payload):
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Security-Policy",
                         "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; base-uri 'self'")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        from urllib.parse import parse_qs, urlparse
        parsed = urlparse(self.path)
        path = parsed.path
        query = parse_qs(parsed.query)
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
                "active_job": None,
                "browser_ready": True,
                "browser_message": "Sẵn sàng",
                "csrf_token": server_state.get("csrf_token", "test-token-123")
            })
        elif path == "/api/history":
            self._send_json(200, {"jobs": server_state.get("history_jobs", [])})
        elif path.startswith("/api/jobs/"):
            job_id = path[len("/api/jobs/"):]
            jobs_map = server_state.get("jobs_snapshots", {})
            if job_id in jobs_map:
                self._send_json(200, {"job": jobs_map[job_id]})
            else:
                self._send_json(404, {"error": "Job not found"})
        elif path == "/api/preview":
            job_id = query.get("job_id", [None])[0]
            layer = query.get("layer", [None])[0]
            previews = server_state.get("previews", {}).get(job_id, {})
            records = previews.get(layer, [])
            self._send_json(200, {"records": records, "total": len(records), "layer": layer or "legacy"})
        elif path == "/api/download":
            fmt = query.get("format", [""])[0]
            if fmt in {"enriched", "enriched_json"}:
                self._send_json(200, [{"foody_id": 1, "name": "Enriched Download"}])
            elif fmt in {"csv", "json", "report"}:
                self._send_json(200, [{"foody_id": 1, "name": "Legacy Download"}])
            else:
                self._send_json(200, {"status": "ok"})
        else:
            super().do_GET()

    def do_POST(self):
        from urllib.parse import urlparse
        path = urlparse(self.path).path
        server_state = getattr(self.server, "state_store", {})
        if path == "/api/enrich":
            self._send_json(200, {
                "schema": "foody-enrichment-report/1",
                "pages_parsed": 4,
                "network_requests": 0,
                "report": {"pages_parsed": 4}
            })
        elif path == "/api/shutdown":
            self._send_json(200, {"message": "Đang đóng"})
        else:
            self._send_json(404, {"error": "Not found"})


class TestWebEnrichPlaywrightE2E(unittest.TestCase):
    """Browser verification using Playwright: filters, old-job fallback, honest copy."""

    @classmethod
    def setUpClass(cls):
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.bind(("127.0.0.1", 0))
        cls.port = sock.getsockname()[1]
        sock.close()

        cls.server = HTTPServer(("127.0.0.1", cls.port), MockWebEnrichBackendHandler)
        cls.server.state_store = {
            "csrf_token": "token-enrich-test-xyz",
            "history_jobs": [
                {
                    "id": "job_v4_enriched",
                    "mode": "sample",
                    "state": "completed",
                    "processed": 4,
                    "started_at": "2026-10-15T02:00:00Z",
                    "has_enrichment": True,
                },
                {
                    "id": "job_v1_old_legacy",
                    "mode": "sample",
                    "state": "completed",
                    "processed": 2,
                    "started_at": "2026-10-14T01:00:00Z",
                    "has_enrichment": False,
                },
            ],
            "jobs_snapshots": {
                "job_v4_enriched": {
                    "id": "job_v4_enriched",
                    "mode": "sample",
                    "state": "completed",
                    "has_enrichment": True,
                    "quality_summary": {"price_status_counts": {"ok": 4}},
                },
                "job_v1_old_legacy": {
                    "id": "job_v1_old_legacy",
                    "mode": "sample",
                    "state": "completed",
                    "has_enrichment": False,
                },
            },
            "previews": {
                "job_v4_enriched": {
                    "enriched": [
                        {
                            "foody_id": 101,
                            "name": "Bún Chả Hương Liên",
                            "cuisine_styles": "Món Việt | Châu Á",
                            "venue_types": "Quán ăn",
                            "dish_groups": "Bún & Phở",
                            "suitable_meals": "Bữa trưa | Bữa tối",
                            "audiences": "Gia đình | Khách du lịch",
                            "rating_value": 8.5,
                            "rating_scale_max": 10,
                            "review_count": 50,
                            "amenities_yes": "Wifi | Máy lạnh",
                            "amenities_no": "",
                            "amenities_unknown": "Chỗ để ô tô | Giao hàng",
                            "prep_time_raw": "Khoảng 10 - 15 phút",
                            "prep_time_min": 10,
                            "prep_time_max": 15,
                            "capacity_raw": "80 người",
                            "capacity_value": 80,
                            "price_min_raw": 40000,
                            "price_max_raw": 60000,
                            "price_status": "ok",
                            "price_min_vnd_norm": 40000,
                            "price_max_vnd_norm": 60000,
                            "price_semantics": "venue price range, not individual dish or per-person guaranteed budget",
                            "opening_hours_raw": [{"day_of_week_raw": 3, "open": "08:00", "close": "20:30"}],
                            "hours_displayed": "08:00 - 20:30",
                            "hours_status": "day_mapping_unknown",
                            "hours_intervals_count": 1,
                            "hours_day_codes_raw": [3],
                            "address": "24 Lê Văn Hưu",
                            "district": "Quận Hai Bà Trưng",
                            "city": "Hà Nội",
                            "lat": 21.018,
                            "lon": 105.853,
                            "geo_status": "ok",
                            "fetched_at": "2026-10-15T02:00:00Z",
                            "source_url": "https://www.foody.vn/ha-noi/bun-cha-huong-lien",
                        },
                        {
                            "foody_id": 102,
                            "name": "Pizza 4P's - Tràng Tiền",
                            "cuisine_styles": "Món Ý | Châu Âu",
                            "venue_types": "Nhà hàng",
                            "dish_groups": "Pizza & Mỳ Ý",
                            "suitable_meals": "Bữa tối",
                            "audiences": "Cặp đôi | Gia đình",
                            "rating_value": 9.2,
                            "rating_scale_max": 10,
                            "review_count": 120,
                            "amenities_yes": "Wifi | Chỗ để ô tô | Máy lạnh",
                            "amenities_no": "",
                            "amenities_unknown": "Hút thuốc",
                            "prep_time_raw": "Khoảng 15 - 30 phút",
                            "prep_time_min": 15,
                            "prep_time_max": 30,
                            "capacity_raw": "150 người",
                            "capacity_value": 150,
                            "price_min_raw": 150000,
                            "price_max_raw": 350000,
                            "price_status": "ok",
                            "price_min_vnd_norm": 150000,
                            "price_max_vnd_norm": 350000,
                            "price_semantics": "venue price range, not individual dish or per-person guaranteed budget",
                            "opening_hours_raw": [{"day_of_week_raw": 3, "open": "10:00", "close": "22:00"}],
                            "hours_displayed": "10:00 - 22:00",
                            "hours_status": "day_mapping_unknown",
                            "hours_intervals_count": 1,
                            "hours_day_codes_raw": [3],
                            "address": "Tràng Tiền",
                            "district": "Quận Hoàn Kiếm",
                            "city": "Hà Nội",
                            "lat": 21.025,
                            "lon": 105.856,
                            "geo_status": "ok",
                            "fetched_at": "2026-10-15T02:00:00Z",
                            "source_url": "https://www.foody.vn/ha-noi/pizza-4ps-trang-tien",
                        },
                        {
                            "foody_id": 103,
                            "name": "Trà Chanh Chợ Gạo",
                            "cuisine_styles": "Giải khát",
                            "venue_types": "Quán vỉa hè",
                            "dish_groups": "Trà & Đồ ăn vặt",
                            "suitable_meals": "Ăn vặt",
                            "audiences": "Nhóm bạn | Học sinh sinh viên",
                            "rating_value": 7.0,
                            "rating_scale_max": 10,
                            "review_count": 5,
                            "amenities_yes": "Wifi",
                            "amenities_no": "",
                            "amenities_unknown": "Máy lạnh | Chỗ để ô tô",
                            "prep_time_raw": "Khoảng 5 phút",
                            "prep_time_min": 5,
                            "prep_time_max": 5,
                            "capacity_raw": "30 người",
                            "capacity_value": 30,
                            "price_min_raw": 15000,
                            "price_max_raw": 30000,
                            "price_status": "ok",
                            "price_min_vnd_norm": 15000,
                            "price_max_vnd_norm": 30000,
                            "price_semantics": "venue price range, not individual dish or per-person guaranteed budget",
                            "opening_hours_raw": [{"day_of_week_raw": 3, "open": "07:00", "close": "23:00"}],
                            "hours_displayed": "07:00 - 23:00",
                            "hours_status": "day_mapping_unknown",
                            "hours_intervals_count": 1,
                            "hours_day_codes_raw": [3],
                            "address": "Chợ Gạo",
                            "district": "Quận Hoàn Kiếm",
                            "city": "Hà Nội",
                            "lat": 21.034,
                            "lon": 105.852,
                            "geo_status": "ok",
                            "fetched_at": "2026-10-15T02:00:00Z",
                            "source_url": "https://www.foody.vn/ha-noi/tra-chanh-cho-gao",
                        },
                        {
                            "foody_id": 104,
                            "name": "Quán Cũ Chưa Đánh Giá",
                            "cuisine_styles": "Món Việt",
                            "venue_types": "Quán bình dân",
                            "dish_groups": "Cơm bình dân",
                            "suitable_meals": "Bữa trưa",
                            "audiences": "Dân văn phòng",
                            "rating_value": None,
                            "rating_scale_max": 10,
                            "review_count": None,
                            "amenities_yes": "",
                            "amenities_no": "",
                            "amenities_unknown": "Wifi",
                            "prep_time_raw": None,
                            "prep_time_min": None,
                            "prep_time_max": None,
                            "capacity_raw": None,
                            "capacity_value": None,
                            "price_min_raw": 30000,
                            "price_max_raw": 40000,
                            "price_status": "ok",
                            "price_min_vnd_norm": 30000,
                            "price_max_vnd_norm": 40000,
                            "price_semantics": "venue price range, not individual dish or per-person guaranteed budget",
                            "opening_hours_raw": [{"day_of_week_raw": 3, "open": "06:00", "close": "14:00"}],
                            "hours_displayed": "06:00 - 14:00",
                            "hours_status": "day_mapping_unknown",
                            "hours_intervals_count": 1,
                            "hours_day_codes_raw": [3],
                            "address": "Phố Huế",
                            "district": "Quận Hai Bà Trưng",
                            "city": "Hà Nội",
                            "lat": 21.015,
                            "lon": 105.852,
                            "geo_status": "ok",
                            "fetched_at": "2026-10-15T02:00:00Z",
                            "source_url": "https://www.foody.vn/ha-noi/com-binh-dan",
                        },
                    ],
                    "normalized": [
                        {
                            "foody_id": 101,
                            "name": "Bún Chả Hương Liên",
                            "address": "24 Lê Văn Hưu",
                            "price_status": "ok",
                            "price_min_vnd_norm": 40000,
                            "price_max_vnd_norm": 60000,
                            "source_url": "https://www.foody.vn/ha-noi/bun-cha-huong-lien",
                        }
                    ],
                },
                "job_v1_old_legacy": {
                    "normalized": [],
                    None: [
                        {
                            "foody_id": 201,
                            "name": "Quán Cổ Truyền (v1)",
                            "address": "Hà Nội",
                            "price_min_vnd": 30000,
                            "price_max_vnd": 50000,
                            "source_url": "https://www.foody.vn/ha-noi/quan-co-truyen",
                        }
                    ],
                },
            },
        }

        cls.server_thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.server_thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server_thread.join(timeout=2)
        cls.server.server_close()

    def test_playwright_filters_and_fallback(self):
        """End-to-end browser test for enriched table rendering, filters, and fallback."""
        try:
            from playwright.sync_api import sync_playwright
        except ImportError:
            self.skipTest("playwright not installed")

        with sync_playwright() as p:
            browser = p.chromium.launch(channel="msedge", headless=True)
            page = browser.new_page()

            console_errors = []
            page.on("console", lambda msg: console_errors.append(msg.text) if msg.type == "error" else None)
            page.on("pageerror", lambda err: console_errors.append(str(err)))

            page.goto(f"http://127.0.0.1:{self.port}/index.html")
            page.wait_for_selector("#history-tbody tr", timeout=5000)

            # 1. Zero initial console errors
            self.assertEqual(console_errors, [], f"Console errors: {console_errors}")

            # 2. Select job_v4_enriched from history
            history_rows = page.locator("#history-tbody tr")
            self.assertGreaterEqual(history_rows.count(), 2)
            history_rows.nth(0).locator("button:has-text('Xem dữ liệu')").click()

            page.wait_for_selector("#preview-tbody tr:not(.empty-row)", timeout=5000)

            # Verify enriched disclaimer is visible with truthful Vietnamese copy
            self.assertTrue(page.is_visible("#enrichment-disclaimer"))
            disclaimer_text = page.inner_text("#enrichment-disclaimer")
            self.assertIn("Nhóm món là phân loại danh mục tổng quát", disclaimer_text)
            self.assertIn("không phải thực đơn chi tiết", disclaimer_text)
            self.assertIn("Khoảng giá toàn quán là mức tham khảo", disclaimer_text)
            self.assertIn("tín hiệu tổng hợp từ người dùng trên nền tảng Foody", disclaimer_text)
            self.assertIn("chưa được kiểm định độc lập", disclaimer_text)

            # Verify filter toolbar is visible
            self.assertTrue(page.is_visible("#preview-filter-toolbar"))

            # Verify enriched 16 columns rendered
            headers = page.locator("#preview-thead th")
            self.assertEqual(headers.count(), 16)
            self.assertEqual(headers.nth(1).inner_text(), "Tên quán")
            self.assertEqual(headers.nth(2).inner_text(), "Điểm đánh giá")
            self.assertEqual(headers.nth(3).inner_text(), "Phong cách ẩm thực")
            self.assertEqual(headers.nth(4).inner_text(), "Thể loại")
            self.assertEqual(headers.nth(5).inner_text(), "Nhóm món")
            self.assertEqual(headers.nth(8).inner_text(), "Tiện ích (Có / Chưa xác nhận)")
            self.assertEqual(headers.nth(11).inner_text(), "Địa chỉ")
            self.assertEqual(headers.nth(12).inner_text(), "Quận")
            self.assertEqual(headers.nth(13).inner_text(), "Khoảng giá quán")
            self.assertEqual(headers.nth(14).inner_text(), "Giờ mở cửa")
            self.assertEqual(headers.nth(15).inner_text(), "Nguồn")

            # All 4 rows initially displayed
            rows = page.locator("#preview-tbody tr")
            self.assertEqual(rows.count(), 4)

            # 3. Test Filter by Cuisine: 'Món Ý'
            page.fill("#filter-cuisine", "Món Ý")
            self.assertEqual(page.locator("#preview-tbody tr").count(), 1)
            self.assertIn("Pizza 4P's", page.locator("#preview-tbody tr").nth(0).inner_text())

            # Reset filter
            page.click("#btn-reset-filters")
            self.assertEqual(page.locator("#preview-tbody tr").count(), 4)

            # 4. Test Filter by Venue Type: 'Quán vỉa hè'
            page.fill("#filter-venue-type", "Quán vỉa hè")
            self.assertEqual(page.locator("#preview-tbody tr").count(), 1)
            self.assertIn("Trà Chanh Chợ Gạo", page.locator("#preview-tbody tr").nth(0).inner_text())
            page.click("#btn-reset-filters")

            # 5. Test Filter by Dish Group: 'Bún'
            page.fill("#filter-dish-group", "Bún")
            self.assertEqual(page.locator("#preview-tbody tr").count(), 1)
            self.assertIn("Bún Chả Hương Liên", page.locator("#preview-tbody tr").nth(0).inner_text())
            page.click("#btn-reset-filters")

            # 6. Test Filter by Suitable Meal: 'Bữa tối'
            page.fill("#filter-suitable-meal", "Bữa tối")
            self.assertEqual(page.locator("#preview-tbody tr").count(), 2)
            page.click("#btn-reset-filters")

            # 7. Test Filter by Audience: 'Cặp đôi'
            page.fill("#filter-audience", "Cặp đôi")
            self.assertEqual(page.locator("#preview-tbody tr").count(), 1)
            self.assertIn("Pizza 4P's", page.locator("#preview-tbody tr").nth(0).inner_text())
            page.click("#btn-reset-filters")

            # 8. Test Rating >= N with Review Count Minimum
            # Rating >= 8.0 with min reviews 10 -> Bún Chả (8.5, 50 rev) and Pizza 4P's (9.2, 120 rev)
            page.fill("#filter-min-rating", "8.0")
            page.fill("#filter-min-reviews", "10")
            self.assertEqual(page.locator("#preview-tbody tr").count(), 2)

            # Rating >= 9.0 -> only Pizza 4P's
            page.fill("#filter-min-rating", "9.0")
            self.assertEqual(page.locator("#preview-tbody tr").count(), 1)
            self.assertIn("Pizza 4P's", page.locator("#preview-tbody tr").nth(0).inner_text())
            page.click("#btn-reset-filters")

            # 9. Test Amenity Filter (ONLY status YES matches!)
            # Filter 'Chỗ để ô tô':
            # Pizza 4P's has it in amenities_yes -> matches!
            # Bún Chả has it in amenities_unknown -> must NOT match!
            # Trà Chanh has it in amenities_unknown -> must NOT match!
            page.fill("#filter-amenity", "Chỗ để ô tô")
            self.assertEqual(page.locator("#preview-tbody tr").count(), 1)
            self.assertIn("Pizza 4P's", page.locator("#preview-tbody tr").nth(0).inner_text())
            page.click("#btn-reset-filters")

            # 10. Test Prep Time Filter: '5 phút'
            page.fill("#filter-prep-time", "5 phút")
            self.assertEqual(page.locator("#preview-tbody tr").count(), 1)
            self.assertIn("Trà Chanh Chợ Gạo", page.locator("#preview-tbody tr").nth(0).inner_text())
            page.click("#btn-reset-filters")

            # 11. Test Capacity Filter: >= 100
            page.fill("#filter-capacity", "100")
            self.assertEqual(page.locator("#preview-tbody tr").count(), 1)
            self.assertIn("Pizza 4P's", page.locator("#preview-tbody tr").nth(0).inner_text())
            page.click("#btn-reset-filters")

            # 12. Verify Amenity Badges and Tooltips (No badge implying not available)
            first_row = page.locator("#preview-tbody tr").nth(0)
            yes_badge = first_row.locator(".amenity-yes").nth(0)
            self.assertIn("✓ Wifi", yes_badge.inner_text())
            self.assertIn("Nền tảng ghi nhận có (chưa kiểm định độc lập)", yes_badge.get_attribute("title"))

            # No badge with .amenity-no or implying not available
            self.assertEqual(page.locator(".amenity-no").count(), 0)

            # Gray unconfirmed badge shows as 'chưa xác nhận' with proper tooltip
            unk_badge = first_row.locator(".amenity-unknown").nth(0)
            self.assertIn("Chỗ để ô tô", unk_badge.inner_text())
            self.assertIn("chưa xác nhận", unk_badge.inner_text())
            unk_title = unk_badge.get_attribute("title")
            self.assertTrue(
                "không phải xác minh là không có" in unk_title or
                "not verification that it is absent" in unk_title
            )

            # Verify source link on row
            link = first_row.locator("a:has-text('Mở Foody ↗')")
            self.assertEqual(link.get_attribute("href"), "https://www.foody.vn/ha-noi/bun-cha-huong-lien")

            # 13. Test Old Job Fallback (job_v1_old_legacy)
            # Click "Xem dữ liệu" on job_v1_old_legacy (second history row)
            page.locator("#history-tbody tr").nth(1).locator("button:has-text('Xem dữ liệu')").click()
            page.wait_for_selector("text=Quán Cổ Truyền (v1)", timeout=5000)

            # Must degrade gracefully:
            # - No enrichment columns (exactly 6 legacy columns)
            # - Filter toolbar hidden
            # - Disclaimer hidden
            self.assertFalse(page.is_visible("#preview-filter-toolbar"))
            self.assertFalse(page.is_visible("#enrichment-disclaimer"))
            legacy_headers = page.locator("#preview-thead th")
            self.assertEqual(legacy_headers.count(), 6)
            self.assertEqual(legacy_headers.nth(1).inner_text(), "Tên quán")
            self.assertEqual(legacy_headers.nth(2).inner_text(), "Địa chỉ")
            self.assertEqual(legacy_headers.nth(3).inner_text(), "Khoảng giá tham khảo")

            # Zero console or page errors throughout the whole run
            self.assertEqual(console_errors, [], f"Console errors observed: {console_errors}")

            browser.close()


class TestWebEnrichDownloadsRegressionPlaywright(unittest.TestCase):
    """Playwright E2E regression tests for Task D UI bug fix:
    Verifies that:
    1. A completed job with restaurants_enriched.json present loads, retains enabled
       enriched download buttons across multiple periodic status polls (>= 2 polls),
       and downloads enriched CSV and JSON matching record counts with correct headers.
    2. An old legacy job without enrichment keeps enriched buttons disabled, while legacy
       downloads are enabled and functional.
    """

    def _launch_browser(self, playwright):
        try:
            return playwright.chromium.launch(channel="msedge", headless=True)
        except Exception:
            return playwright.chromium.launch(headless=True)

    def _create_synthetic_job(self, jobs_root, job_id, *, enriched=True, count=3, started_at="2026-10-15T01:00:00Z"):
        job_dir = Path(jobs_root) / job_id
        job_dir.mkdir(parents=True, exist_ok=True)

        job_meta = {
            "id": job_id,
            "mode": "sample",
            "state": "completed",
            "stage": "done",
            "limit": 48,
            "discovered": count,
            "processed": count,
            "success": count,
            "duplicates": 0,
            "failed": 0,
            "clicks": 0,
            "request_count": 0,
            "started_at": started_at,
            "updated_at": "2026-10-15T01:05:00Z",
            "message": "Hoàn thành mẫu thử nghiệm.",
            "logs": [],
        }
        (job_dir / "job.json").write_text(json.dumps(job_meta), encoding="utf-8")

        legacy_records = [
            {
                "foody_id": 1000 + i,
                "name": f"Quán Cơm {i}",
                "address": f"{i} Phố Huế, Hà Nội",
                "price_min_vnd": 30000,
                "price_max_vnd": 60000,
                "source_url": f"https://www.foody.vn/ha-noi/quan-com-{i}",
            }
            for i in range(1, count + 1)
        ]
        (job_dir / "restaurants.json").write_text(json.dumps(legacy_records), encoding="utf-8")

        legacy_csv_lines = ["foody_id,name,address,price_min_vnd,price_max_vnd,source_url"]
        for r in legacy_records:
            legacy_csv_lines.append(f"{r['foody_id']},{r['name']},{r['address']},{r['price_min_vnd']},{r['price_max_vnd']},{r['source_url']}")
        (job_dir / "restaurants.csv").write_text("\n".join(legacy_csv_lines) + "\n", encoding="utf-8")

        if enriched:
            enriched_records = [
                {
                    "foody_id": 1000 + i,
                    "name": f"Quán Cơm {i}",
                    "address": f"{i} Phố Huế, Hà Nội",
                    "district": "Quận Hai Bà Trưng",
                    "city": "Hà Nội",
                    "lat": 21.01,
                    "lon": 105.85,
                    "geo_status": "ok",
                    "price_min_vnd": 30000,
                    "price_max_vnd": 60000,
                    "price_min_raw": 30000,
                    "price_max_raw": 60000,
                    "price_status": "ok",
                    "price_min_vnd_norm": 30000,
                    "price_max_vnd_norm": 60000,
                    "price_semantics": "venue price range, not individual dish or per-person guaranteed budget",
                    "opening_hours_raw": [{"day_of_week_raw": 3, "open": "09:00", "close": "21:00"}],
                    "hours_displayed": "09:00 - 21:00",
                    "hours_status": "day_mapping_unknown",
                    "hours_intervals_count": 1,
                    "hours_day_codes_raw": [3],
                    "fetched_at": "2026-10-15T01:00:00Z",
                    "source_url": f"https://www.foody.vn/ha-noi/quan-com-{i}",
                    "cuisine_styles": "Món Việt",
                    "venue_types": "Quán ăn",
                    "dish_groups": "Cơm bình dân",
                    "suitable_meals": "Bữa trưa",
                    "audiences": "Dân văn phòng",
                    "rating_value": 8.0 + (0.2 * i),
                    "rating_scale_max": 10,
                    "review_count": 30 + (5 * i),
                    "amenities_yes": "Wifi | Máy lạnh",
                    "amenities_no": "",
                    "amenities_unknown": "",
                    "prep_time_raw": "Khoảng 10 phút",
                    "prep_time_min": 10,
                    "prep_time_max": 10,
                    "capacity_raw": "40 người",
                    "capacity_value": 40,
                }
                for i in range(1, count + 1)
            ]
            from foody_tool.exporter import export_enriched_csv, export_enriched_json, ENRICHED_FIELDS
            export_enriched_json(enriched_records, str(job_dir / "restaurants_enriched.json"))
            export_enriched_csv(enriched_records, str(job_dir / "restaurants_enriched.csv"))
            (job_dir / "enrichment_report.json").write_text(
                json.dumps({
                    "schema": "foody-enrichment-report/1",
                    "schema_version": "foody-enriched-export/2",
                    "columns": list(ENRICHED_FIELDS),
                    "pages_total": count,
                    "pages_parsed": count,
                    "pages_failed": 0
                }),
                encoding="utf-8"
            )

        return job_dir

    def test_completed_enriched_job_downloads_persist_after_status_polls(self):
        """Completed job with restaurants_enriched.json present:
        Wait for at least two status polls, assert enriched CSV/JSON buttons stay enabled,
        assert enriched preview shows price text and hours text,
        and trigger real browser downloads asserting row count, headers, and matching price/hours values.
        """
        try:
            from playwright.sync_api import sync_playwright
        except ImportError:
            self.skipTest("playwright not installed")

        temp_dir = tempfile.TemporaryDirectory()
        try:
            jobs_root = Path(temp_dir.name) / "jobs"
            job_id = "e" * 32
            record_count = 3
            self._create_synthetic_job(jobs_root, job_id, enriched=True, count=record_count)

            manager = JobManager(jobs_root)
            server = make_server(manager, port=0, web_root=WEB_DIR)
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            port = server.server_port

            with sync_playwright() as p:
                browser = self._launch_browser(p)
                page = browser.new_page()

                poll_count = 0
                def count_polls(res):
                    nonlocal poll_count
                    if "/api/status" in res.url:
                        poll_count += 1
                page.on("response", count_polls)

                page.goto(f"http://127.0.0.1:{port}/index.html")
                page.wait_for_selector("#preview-tbody tr:not(.empty-row)", timeout=5000)

                # Wait for at least two status polls (pollIntervalMs is 1500ms)
                start_wait = time.time()
                while poll_count < 2 and time.time() - start_wait < 6.0:
                    page.wait_for_timeout(500)
                self.assertGreaterEqual(poll_count, 2, f"Expected at least 2 status polls, got {poll_count}")

                # Assert preview table displays price text and hours text via getRecordPriceInfo / getRecordHoursInfo
                layer_enriched_radio = page.locator("#layer-enriched")
                if not layer_enriched_radio.is_checked():
                    layer_enriched_radio.click()
                    page.wait_for_selector("#preview-tbody tr:not(.empty-row)", timeout=5000)

                first_row = page.locator("#preview-tbody tr").nth(0)
                # Columns: STT (0), Tên (1), Điểm (2), Phong cách (3), Thể loại (4), Nhóm món (5),
                # Bữa ăn (6), Phù hợp (7), Tiện ích (8), TG (9), Sức chứa (10), Địa chỉ (11), Quận (12),
                # Khoảng giá (13), Giờ mở cửa (14), Nguồn (15)
                row_price = first_row.locator("td").nth(13).inner_text()
                row_hours = first_row.locator("td").nth(14).inner_text()
                self.assertIn("30.000 ₫ – 60.000 ₫", row_price)
                self.assertIn("09:00 - 21:00", row_hours)
                self.assertIn("Chưa rõ quy ước thứ", row_hours)

                # Assert enriched CSV/JSON buttons have no aria-disabled and href contains format=enriched_csv / format=enriched
                btn_csv = page.locator("#btn-download-enriched-csv")
                btn_json = page.locator("#btn-download-enriched-json")

                self.assertIsNone(btn_csv.get_attribute("aria-disabled"))
                self.assertIn("format=enriched_csv", btn_csv.get_attribute("href") or "")
                self.assertNotIn("btn-disabled", btn_csv.get_attribute("class") or "")

                self.assertIsNone(btn_json.get_attribute("aria-disabled"))
                self.assertIn("format=enriched", btn_json.get_attribute("href") or "")
                self.assertNotIn("btn-disabled", btn_json.get_attribute("class") or "")

                # Trigger real browser download of enriched CSV
                with page.expect_download() as dl_csv_info:
                    btn_csv.click()
                dl_csv = dl_csv_info.value
                csv_path = dl_csv.path()

                with open(csv_path, "r", encoding="utf-8") as f:
                    csv_reader = csv.DictReader(f)
                    fieldnames = csv_reader.fieldnames
                    self.assertIn("cuisine_styles", fieldnames)
                    self.assertIn("rating_value", fieldnames)
                    self.assertIn("amenities_yes", fieldnames)
                    self.assertIn("price_status", fieldnames)
                    self.assertIn("price_min_vnd_norm", fieldnames)
                    self.assertIn("hours_status", fieldnames)
                    self.assertIn("hours_displayed", fieldnames)
                    self.assertIn("address", fieldnames)
                    self.assertIn("district", fieldnames)
                    csv_rows = list(csv_reader)
                    self.assertEqual(len(csv_rows), record_count)
                    for idx, r in enumerate(csv_rows, start=1):
                        self.assertEqual(r["foody_id"], str(1000 + idx))
                        self.assertEqual(r["price_min_raw"], "30000")
                        self.assertEqual(r["price_max_raw"], "60000")
                        self.assertEqual(r["price_status"], "ok")
                        self.assertEqual(r["price_min_vnd_norm"], "30000")
                        self.assertEqual(r["price_max_vnd_norm"], "60000")
                        self.assertEqual(r["hours_displayed"], "09:00 - 21:00")
                        self.assertEqual(r["hours_status"], "day_mapping_unknown")

                # Trigger real browser download of enriched JSON
                with page.expect_download() as dl_json_info:
                    btn_json.click()
                dl_json = dl_json_info.value
                json_path = dl_json.path()

                with open(json_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    self.assertEqual(len(data), record_count)
                    for idx, r in enumerate(data, start=1):
                        self.assertEqual(r["foody_id"], 1000 + idx)
                        self.assertEqual(r["price_min_raw"], 30000)
                        self.assertEqual(r["price_max_raw"], 60000)
                        self.assertEqual(r["price_status"], "ok")
                        self.assertEqual(r["price_min_vnd_norm"], 30000)
                        self.assertEqual(r["price_max_vnd_norm"], 60000)
                        self.assertEqual(r["hours_displayed"], "09:00 - 21:00")
                        self.assertEqual(r["hours_status"], "day_mapping_unknown")

                browser.close()

                browser.close()
        finally:
            manager.shutdown()
            server.shutdown()
            thread.join(timeout=2)
            server.server_close()
            temp_dir.cleanup()

    def test_old_job_without_enrichment_stays_disabled(self):
        """Old job without enrichment:
        Enriched buttons stay disabled, legacy downloads enabled and functional.
        """
        try:
            from playwright.sync_api import sync_playwright
        except ImportError:
            self.skipTest("playwright not installed")

        temp_dir = tempfile.TemporaryDirectory()
        try:
            jobs_root = Path(temp_dir.name) / "jobs"
            job_id = "f" * 32
            record_count = 2
            self._create_synthetic_job(jobs_root, job_id, enriched=False, count=record_count)

            manager = JobManager(jobs_root)
            server = make_server(manager, port=0, web_root=WEB_DIR)
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            port = server.server_port

            with sync_playwright() as p:
                browser = self._launch_browser(p)
                page = browser.new_page()

                poll_count = 0
                def count_polls(res):
                    nonlocal poll_count
                    if "/api/status" in res.url:
                        poll_count += 1
                page.on("response", count_polls)

                page.goto(f"http://127.0.0.1:{port}/index.html")
                page.wait_for_selector("#preview-tbody tr:not(.empty-row)", timeout=5000)

                # Wait for at least two status polls
                start_wait = time.time()
                while poll_count < 2 and time.time() - start_wait < 6.0:
                    page.wait_for_timeout(500)
                self.assertGreaterEqual(poll_count, 2, f"Expected at least 2 status polls, got {poll_count}")

                # Enriched buttons must stay disabled
                btn_enriched_csv = page.locator("#btn-download-enriched-csv")
                btn_enriched_json = page.locator("#btn-download-enriched-json")
                btn_enrichment_rep = page.locator("#btn-download-enrichment-report")

                self.assertEqual(btn_enriched_csv.get_attribute("aria-disabled"), "true")
                self.assertIn("btn-disabled", btn_enriched_csv.get_attribute("class") or "")

                self.assertEqual(btn_enriched_json.get_attribute("aria-disabled"), "true")
                self.assertIn("btn-disabled", btn_enriched_json.get_attribute("class") or "")

                self.assertEqual(btn_enrichment_rep.get_attribute("aria-disabled"), "true")
                self.assertIn("btn-disabled", btn_enrichment_rep.get_attribute("class") or "")

                # Legacy downloads must stay enabled
                btn_legacy_csv = page.locator("#btn-download-csv")
                btn_legacy_json = page.locator("#btn-download-json")

                self.assertIsNone(btn_legacy_csv.get_attribute("aria-disabled"))
                self.assertNotIn("btn-disabled", btn_legacy_csv.get_attribute("class") or "")
                self.assertIn("format=csv", btn_legacy_csv.get_attribute("href") or "")

                self.assertIsNone(btn_legacy_json.get_attribute("aria-disabled"))
                self.assertNotIn("btn-disabled", btn_legacy_json.get_attribute("class") or "")
                self.assertIn("format=json", btn_legacy_json.get_attribute("href") or "")

                # Trigger real browser download of legacy CSV
                with page.expect_download() as dl_info:
                    btn_legacy_csv.click()
                dl = dl_info.value
                csv_path = dl.path()

                with open(csv_path, "r", encoding="utf-8") as f:
                    csv_rows = [line for line in f if line.strip()][1:]  # skip header
                    self.assertEqual(len(csv_rows), record_count)

                # Trigger real browser download of legacy JSON
                with page.expect_download() as dl_info:
                    btn_legacy_json.click()
                dl = dl_info.value
                json_path = dl.path()

                with open(json_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    self.assertEqual(len(data), record_count)

                browser.close()
        finally:
            manager.shutdown()
            server.shutdown()
            thread.join(timeout=2)
            server.server_close()
            temp_dir.cleanup()

    def test_history_selection_and_status_poll_isolation(self):
        """Selecting between enriched and legacy jobs from history:
        Status polls of the active job cannot overwrite the state/buttons of the selected history job.
        """
        try:
            from playwright.sync_api import sync_playwright
        except ImportError:
            self.skipTest("playwright not installed")

        temp_dir = tempfile.TemporaryDirectory()
        try:
            jobs_root = Path(temp_dir.name) / "jobs"
            # Job 1: Active completed job with enrichment
            active_id = "1" * 32
            self._create_synthetic_job(jobs_root, active_id, enriched=True, count=3, started_at="2026-10-15T02:00:00Z")

            # Job 2: Older completed job without enrichment
            legacy_id = "2" * 32
            self._create_synthetic_job(jobs_root, legacy_id, enriched=False, count=2, started_at="2026-10-14T01:00:00Z")

            manager = JobManager(jobs_root)
            server = make_server(manager, port=0, web_root=WEB_DIR)
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            port = server.server_port

            with sync_playwright() as p:
                browser = self._launch_browser(p)
                page = browser.new_page()

                poll_count = 0
                def count_polls(res):
                    nonlocal poll_count
                    if "/api/status" in res.url:
                        poll_count += 1
                page.on("response", count_polls)

                page.goto(f"http://127.0.0.1:{port}/index.html")
                page.wait_for_selector("#history-tbody tr", timeout=5000)

                # Initially, active_job (active_id) is selected and enriched downloads are enabled
                btn_enriched_csv = page.locator("#btn-download-enriched-csv")
                self.assertIsNone(btn_enriched_csv.get_attribute("aria-disabled"))

                # Now click "Xem dữ liệu" on the legacy job (legacy_id) in history table
                history_rows = page.locator("#history-tbody tr")
                self.assertGreaterEqual(history_rows.count(), 2)

                legacy_row = None
                for i in range(history_rows.count()):
                    row = history_rows.nth(i)
                    if legacy_id in row.inner_text():
                        legacy_row = row
                        break
                self.assertIsNotNone(legacy_row, f"Could not find history row for {legacy_id}")
                legacy_row.locator("button:has-text('Xem dữ liệu')").click()

                # Wait for preview of legacy job to load (legacy columns, no filter toolbar)
                page.wait_for_selector("#preview-filter-toolbar", state="hidden", timeout=5000)
                self.assertFalse(page.is_visible("#preview-filter-toolbar"))

                # Reset poll count and wait for at least two status polls while legacy job is selected
                poll_count = 0
                start_wait = time.time()
                while poll_count < 2 and time.time() - start_wait < 6.0:
                    page.wait_for_timeout(500)
                self.assertGreaterEqual(poll_count, 2)

                # Verify: Even though active job is enriched, status polling has NOT overwritten legacy job!
                # Enriched buttons MUST remain disabled for the selected legacy job:
                self.assertEqual(btn_enriched_csv.get_attribute("aria-disabled"), "true")
                self.assertIn("btn-disabled", btn_enriched_csv.get_attribute("class") or "")

                # Legacy downloads remain enabled
                btn_legacy_csv = page.locator("#btn-download-csv")
                self.assertIsNone(btn_legacy_csv.get_attribute("aria-disabled"))
                self.assertIn("format=csv", btn_legacy_csv.get_attribute("href") or "")

                browser.close()
        finally:
            manager.shutdown()
            server.shutdown()
            thread.join(timeout=2)
            server.server_close()
            temp_dir.cleanup()

    def test_enrich_job_enables_buttons_without_page_reload(self):
        """After POST /api/enrich succeeds on a saved job, the enriched download buttons
        enable immediately in the UI without needing a page reload.
        """
        try:
            from playwright.sync_api import sync_playwright
        except ImportError:
            self.skipTest("playwright not installed")

        import hashlib

        temp_dir = tempfile.TemporaryDirectory()
        try:
            jobs_root = Path(temp_dir.name) / "jobs"
            job_id = "3" * 32
            job_dir = Path(jobs_root) / job_id
            job_dir.mkdir(parents=True, exist_ok=True)
            cache_dir = job_dir / "cache"
            cache_dir.mkdir(exist_ok=True)

            url = "https://www.foody.vn/ha-noi/pho-bo-nam-dinh"
            cache_file = cache_dir / (hashlib.sha256(url.encode()).hexdigest()[:20] + ".html")
            sample_html = (
                '<html><body>'
                '<script>var initData = {"RestaurantID": 202, "Name": "Phở Bò Nam Định", "PriceMin": 40000, "PriceMax": 60000};</script>'
                '<div class="new-detail-info-area"><div class="new-detail-info-label">Phong cách ẩm thực</div><div><a href="/ha-noi/mon-viet">Món Việt</a></div></div>'
                '<div class="new-detail-info-area"><div class="new-detail-info-label">Thể loại</div><div><a href="/ha-noi/quan-an">Quán ăn</a></div></div>'
                '<div class="new-detail-info-area"><div class="new-detail-info-label">Phục vụ các món</div><div><a href="/ha-noi/pho-bo">Phở bò</a></div></div>'
                '<div class="new-detail-info-area"><div class="new-detail-info-label">Thích hợp</div><div><a href="/ha-noi/bua-sang">Bữa sáng</a></div></div>'
                '<div class="new-detail-info-area"><div class="new-detail-info-label">Phù hợp với</div><div><a href="/ha-noi/moi-lua-tuoi">Mọi lứa tuổi</a></div></div>'
                '<span itemprop="ratingValue">8.6</span><span itemprop="reviewCount">28</span>'
                '<ul class="micro-property"><li><a class="resproperties-report" istrue="true"><span errorkeyname="Wifi">Wifi</span></a></li></ul>'
                '</body></html>'
            )
            cache_file.write_text(sample_html, encoding="utf-8")
            (job_dir / "urls.json").write_text(json.dumps([url]), encoding="utf-8")
            (job_dir / "restaurants.json").write_text(json.dumps([{
                "foody_id": 202, "name": "Phở Bò Nam Định", "source_url": url,
                "price_min_vnd": 40000, "price_max_vnd": 60000
            }]), encoding="utf-8")
            (job_dir / "restaurants.csv").write_text("foody_id,name,source_url,price_min_vnd,price_max_vnd\n202,Phở Bò Nam Định,url,40000,60000\n", encoding="utf-8")
            (job_dir / "job.json").write_text(json.dumps({
                "id": job_id, "mode": "sample", "state": "completed",
                "started_at": "2026-10-15T00:00:00Z", "processed": 1
            }), encoding="utf-8")

            manager = JobManager(jobs_root)
            server = make_server(manager, port=0, web_root=WEB_DIR)
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            port = server.server_port

            with sync_playwright() as p:
                browser = self._launch_browser(p)
                page = browser.new_page()

                page.goto(f"http://127.0.0.1:{port}/index.html")
                page.wait_for_selector("#preview-tbody tr:not(.empty-row)", timeout=5000)

                btn_enriched_csv = page.locator("#btn-download-enriched-csv")
                btn_enriched_json = page.locator("#btn-download-enriched-json")
                btn_enrich = page.locator("#btn-enrich-job")

                # Before enrichment: buttons are disabled
                self.assertEqual(btn_enriched_csv.get_attribute("aria-disabled"), "true")
                self.assertEqual(btn_enriched_json.get_attribute("aria-disabled"), "true")

                # Click "Làm giàu dữ liệu" button
                self.assertTrue(btn_enrich.is_enabled())
                btn_enrich.click()

                # Wait for success notification
                page.wait_for_selector(".banner-success", timeout=8000)

                # Verify enriched buttons are enabled immediately WITHOUT reloading the page
                self.assertIsNone(btn_enriched_csv.get_attribute("aria-disabled"))
                self.assertNotIn("btn-disabled", btn_enriched_csv.get_attribute("class") or "")
                self.assertIn("format=enriched_csv", btn_enriched_csv.get_attribute("href") or "")

                self.assertIsNone(btn_enriched_json.get_attribute("aria-disabled"))
                self.assertNotIn("btn-disabled", btn_enriched_json.get_attribute("class") or "")
                self.assertIn("format=enriched", btn_enriched_json.get_attribute("href") or "")

                # Trigger real download to verify the enriched file is served
                with page.expect_download() as dl_info:
                    btn_enriched_csv.click()
                dl = dl_info.value
                csv_path = dl.path()

                with open(csv_path, "r", encoding="utf-8") as f:
                    csv_header = f.readline()
                    self.assertIn("cuisine_styles", csv_header)
                    self.assertIn("rating_value", csv_header)
                    self.assertIn("amenities_yes", csv_header)

                browser.close()
        finally:
            manager.shutdown()
            server.shutdown()
            thread.join(timeout=2)
            server.server_close()
            temp_dir.cleanup()


if __name__ == "__main__":
    unittest.main()
