"""API integration tests for Foody v0.3 quality downloads, normalized preview, and quality_summary."""
import json
import os
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from pathlib import Path

from foody_tool.app import make_server
from foody_tool.jobs import JobManager, atomic_json
from tests.test_jobs import collector_factory, discovery_factory


class QualityAPITests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        folder = Path(self.temp.name)
        assets = folder / "web"
        assets.mkdir()
        (assets / "index.html").write_text("<html>FoodTour test</html>", encoding="utf8")
        
        # Seed two sample jobs: one with v3 quality files, one legacy (without quality files)
        self.jobs_dir = folder / "jobs"
        self.jobs_dir.mkdir()
        
        self.manager = JobManager(self.jobs_dir, discovery_factory=discovery_factory(4),
                                  collector_factory=collector_factory([]))
        self.server = make_server(self.manager, port=0, web_root=assets)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.base = f"http://127.0.0.1:{self.server.server_port}"
        _, status, _ = self.request("/api/status")
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
            options["data"] = json.dumps(body).encode()
            options["headers"] = {"Content-Type": "application/json", **options["headers"]}
        req = urllib.request.Request(self.base + path, **options)
        try:
            response = urllib.request.urlopen(req, timeout=5)
        except urllib.error.HTTPError as exc:
            response = exc
        with response:
            raw = response.read()
            data = json.loads(raw) if response.headers.get_content_type() == "application/json" else raw
            return response.status, data, response.headers

    def test_quality_downloads_and_normalized_preview(self):
        # 1. Start a job and wait for completion
        code, data, _ = self.request("/api/start", {"mode": "all"}, {"X-CSRF-Token": self.token})
        self.assertEqual(code, 200)
        job_id = data["job_id"]
        job = self.manager.get(job_id)
        job.thread.join(5)

        # 2. Check preview default vs normalized
        code, prev_default, _ = self.request(f"/api/preview?job_id={job_id}")
        self.assertEqual(code, 200)
        self.assertEqual(prev_default["total"], 4)
        self.assertIn("foody_id", prev_default["records"][0])

        code, prev_norm, _ = self.request(f"/api/preview?job_id={job_id}&layer=normalized")
        self.assertEqual(code, 200)
        self.assertEqual(prev_norm["total"], 4)
        self.assertIn("price_status", prev_norm["records"][0])
        self.assertIn("geo_status", prev_norm["records"][0])

        # 3. Test all whitelisted download formats
        formats_to_test = [
            ("quality", "application/json", "quality_report.json"),
            ("issues", "application/json", "issues.json"),
            ("issues_csv", "text/csv", "issues.csv"),
            ("normalized", "application/json", "restaurants_normalized.json"),
            ("normalized_csv", "text/csv", "restaurants_normalized.csv"),
            ("raw", "application/json", "restaurants_raw.json"),
            ("csv", "text/csv", "restaurants.csv"),
            ("json", "application/json", "restaurants.json"),
            ("report", "application/json", "report.json"),
        ]
        for fmt, expected_mime, expected_filename in formats_to_test:
            code, body, headers = self.request(f"/api/download?job_id={job_id}&format={fmt}")
            self.assertEqual(code, 200, f"Format {fmt} failed with {code}")
            content_type = headers.get("Content-Type", "")
            self.assertIn(expected_mime, content_type)
            disp = headers.get("Content-Disposition", "")
            self.assertIn(expected_filename, disp)

        # 4. Unknown format yields 400
        code, err, _ = self.request(f"/api/download?job_id={job_id}&format=unsupported_format")
        self.assertEqual(code, 400)

        # 5. Path traversal attempt yields 400
        code, _, _ = self.request(f"/api/download?job_id={job_id}&format=../../pyproject.toml")
        self.assertEqual(code, 400)

        # 6. Check quality_summary in GET /api/jobs/<job_id>
        code, job_resp, _ = self.request(f"/api/jobs/{job_id}")
        self.assertEqual(code, 200)
        snap = job_resp["job"]
        self.assertIn("quality_summary", snap)
        qs = snap["quality_summary"]
        self.assertIn("price_status_counts", qs)
        self.assertIn("issue_counts_by_severity", qs)
        self.assertIn("eligibility", qs)

    def test_legacy_job_dir_quality_download_returns_not_available(self):
        # Create an artificial legacy job directory without quality files
        legacy_id = "0123456789abcdef0123456789abcdef"
        leg_dir = self.jobs_dir / legacy_id
        leg_dir.mkdir()
        leg_job = {
            "id": legacy_id,
            "mode": "sample",
            "limit": 5,
            "interval": 2.0,
            "show_browser": False,
            "state": "completed",
            "stage": "finished",
        }
        atomic_json(leg_dir / "job.json", leg_job)
        atomic_json(leg_dir / "restaurants.json", [{"foody_id": 1, "name": "Legacy Venue"}])
        atomic_json(leg_dir / "report.json", {"requested_urls": 1})

        # Reload manager to pick up legacy job
        self.manager.jobs[legacy_id] = self.manager.get(legacy_id) if legacy_id in self.manager.jobs else None
        # Use JobManager to initialize job
        from foody_tool.jobs import CrawlJob
        self.manager.jobs[legacy_id] = CrawlJob(leg_dir, saved=leg_job)

        # Legacy files still download fine
        code, _, _ = self.request(f"/api/download?job_id={legacy_id}&format=json")
        self.assertEqual(code, 200)

        # Quality format download on legacy job returns 404 {"error": "not_available"}
        code, err, _ = self.request(f"/api/download?job_id={legacy_id}&format=quality")
        self.assertEqual(code, 404)
        self.assertEqual(err, {"error": "not_available"})

        # Snapshot of legacy job does not contain quality_summary
        code, job_resp, _ = self.request(f"/api/jobs/{legacy_id}")
        self.assertEqual(code, 200)
        self.assertNotIn("quality_summary", job_resp["job"])

    def test_post_quality_csrf_and_validation(self):
        # 1. Missing CSRF returns 403
        code, err, _ = self.request("/api/quality", {"job_id": "bad"})
        self.assertEqual(code, 403)

        # 2. Invalid CSRF returns 403
        code, err, _ = self.request("/api/quality", {"job_id": "bad"}, {"X-CSRF-Token": "wrong-token"})
        self.assertEqual(code, 403)

        # 3. Missing job_id returns 400
        code, err, _ = self.request("/api/quality", {}, {"X-CSRF-Token": self.token})
        self.assertEqual(code, 400)
        self.assertIn("Thiếu mã phiên", err.get("error", ""))

        # 4. Unknown job_id returns 404
        code, err, _ = self.request("/api/quality", {"job_id": "0123456789abcdef0123456789abcdef"},
                                    {"X-CSRF-Token": self.token})
        self.assertEqual(code, 404)

    def test_post_quality_rejects_running_job(self):
        # Start a job
        code, data, _ = self.request("/api/start", {"mode": "all"}, {"X-CSRF-Token": self.token})
        self.assertEqual(code, 200)
        job_id = data["job_id"]
        job = self.manager.get(job_id)

        # If job is running, POST /api/quality should reject with 400
        if job.thread and job.thread.is_alive():
            code, err, _ = self.request("/api/quality", {"job_id": job_id}, {"X-CSRF-Token": self.token})
            self.assertEqual(code, 400)
            self.assertIn("đang chạy", err.get("error", ""))

        job.thread.join(5)

    def test_post_quality_reclassifies_completed_or_legacy_job(self):
        legacy_id = "11112222333344445555666677778888"
        leg_dir = self.jobs_dir / legacy_id
        leg_dir.mkdir()
        leg_job = {
            "id": legacy_id,
            "mode": "sample",
            "limit": 5,
            "interval": 2.0,
            "show_browser": False,
            "state": "completed",
            "stage": "finished",
        }
        atomic_json(leg_dir / "job.json", leg_job)
        atomic_json(leg_dir / "restaurants.json", [
            {
                "foody_id": 100,
                "name": "Pho 10",
                "lat": 21.03,
                "lon": 105.85,
                "address": "10 Ly Quoc Su",
                "district": "Hoan Kiem",
                "city": "Ha Noi",
                "opening_hours_raw": [{"open": "06:00", "close": "22:00"}],
                "price_min_vnd": 50000,
                "price_max_vnd": 110000,
                "source_url": "https://www.foody.vn/ha-noi/pho-10",
                "fetched_at": "2026-10-14T00:00:00Z",
                "price_semantics": "venue",
                "source_license": "none",
                "field_freshness_unknown": True,
                "source_flags": {},
                "h1_names": [],
                "parse_warnings": [],
            }
        ])
        atomic_json(leg_dir / "report.json", {"requested_urls": 1, "records_exported": 1})

        from foody_tool.jobs import CrawlJob
        self.manager.jobs[legacy_id] = CrawlJob(leg_dir, saved=leg_job)

        # Before POST /api/quality: quality download gives 404 not_available
        code, err, _ = self.request(f"/api/download?job_id={legacy_id}&format=quality")
        self.assertEqual(code, 404)
        self.assertEqual(err, {"error": "not_available"})

        # Trigger POST /api/quality
        code, resp, _ = self.request("/api/quality", {"job_id": legacy_id}, {"X-CSRF-Token": self.token})
        self.assertEqual(code, 200)
        self.assertIn("job", resp)
        snap = resp["job"]
        self.assertIn("quality_summary", snap)
        qs = snap["quality_summary"]
        self.assertEqual(qs["price_status_counts"]["ok"], 1)
        self.assertEqual(qs["eligibility"]["search_eligible"]["rate"], 1.0)

        # Artifacts now exist and can be downloaded
        code, qrep, _ = self.request(f"/api/download?job_id={legacy_id}&format=quality")
        self.assertEqual(code, 200)
        self.assertEqual(qrep["rates"]["fetch_success"]["rate"], None)  # offline reclassification: zero network claims
        self.assertEqual(qrep["funnel"]["attempted"], 0)

        code, norm_data, _ = self.request(f"/api/download?job_id={legacy_id}&format=normalized")
        self.assertEqual(code, 200)
        self.assertEqual(len(norm_data), 1)
        self.assertEqual(norm_data[0]["foody_id"], 100)
        self.assertEqual(norm_data[0]["price_status"], "ok")


if __name__ == "__main__":
    unittest.main()

