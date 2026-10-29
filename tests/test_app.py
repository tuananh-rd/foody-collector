"""HTTP integration on loopback with a synthetic source; never calls Foody."""
import json
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from pathlib import Path

from foody_tool.app import make_server
from foody_tool.jobs import JobManager
try:
    from tests.test_jobs import collector_factory, discovery_factory
except ImportError:
    from test_jobs import collector_factory, discovery_factory


class LocalAPI(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        folder = Path(self.temp.name)
        assets = folder / "web"
        assets.mkdir()
        (assets / "index.html").write_text("<html>FoodTour thử nghiệm</html>", encoding="utf8")
        self.manager = JobManager(folder / "jobs", discovery_factory=discovery_factory(4),
                                  collector_factory=collector_factory([]))
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
            options["data"] = json.dumps(body).encode()
            options["headers"] = {"Content-Type": "application/json", **options["headers"]}
        req = urllib.request.Request(self.base + path, **options)
        try:
            response = urllib.request.urlopen(req, timeout=3)
        except urllib.error.HTTPError as exc:
            response = exc
        with response:
            raw = response.read()
            data = json.loads(raw) if response.headers.get_content_type() == "application/json" else raw
            return response.status, data

    def test_start_preview_download_and_history(self):
        code, data = self.request("/api/start", {"mode": "all"}, {"X-CSRF-Token": self.token})
        self.assertEqual(code, 200)
        job_id = data["job_id"]
        self.manager.get(job_id).thread.join(3)
        code, preview = self.request(f"/api/preview?job_id={job_id}")
        self.assertEqual((code, preview["total"]), (200, 4))
        code, rows = self.request(f"/api/download?job_id={job_id}&format=json")
        self.assertEqual((code, len(rows)), (200, 4))
        code, csv = self.request(f"/api/download?job_id={job_id}&format=csv")
        self.assertEqual(code, 200)
        self.assertIn(b"foody_id,name", csv)
        code, hist = self.request("/api/history")
        self.assertEqual(hist["jobs"][0]["id"], job_id)
        self.assertEqual(hist["jobs"][0]["state"], "completed")

    def test_mutation_checks_csrf_origin_and_host(self):
        self.assertEqual(self.request("/api/start", {"mode": "all"})[0], 403)
        self.assertEqual(self.request("/api/start", {"mode": "all"},
             {"X-CSRF-Token": self.token, "Origin": "https://external.example"})[0], 403)
        self.assertEqual(self.request("/api/status", headers={"Host": "external.example"})[0], 403)

    def test_bad_parameters_and_path_do_not_read_files(self):
        self.assertEqual(self.request("/api/start", {"interval": 0}, {"X-CSRF-Token": self.token})[0], 400)
        self.assertEqual(self.request("/api/jobs/../../outside")[0], 404)
        self.assertEqual(self.request("/../../pyproject.toml")[0], 404)
        self.assertEqual(self.request("/")[0], 200)

    def test_shutdown_requires_token_and_stops_server(self):
        self.assertEqual(self.request("/api/shutdown", {})[0], 403)
        self.assertEqual(self.request("/api/shutdown", {}, {"X-CSRF-Token": self.token})[0], 200)
        self.thread.join(2)
        self.assertFalse(self.thread.is_alive())


if __name__ == "__main__":
    unittest.main()
