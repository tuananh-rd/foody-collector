"""Synthetic end-to-end checks of the city runner, not measurements of Foody."""
import json
import tempfile
import threading
import time
import unittest
from unittest.mock import patch
from pathlib import Path

from foody_tool.collector import Collector
from foody_tool.exporter import read_csv_records
from foody_tool.jobs import JobManager, validate_config


def urls(n):
    return [f"https://www.foody.vn/ha-noi/test-venue-{i}" for i in range(1, n + 1)]


def collector_factory(calls, *, block=None, entering=None, release=None):
    def fetch(url, timeout):
        rid = int(url.rsplit("-", 1)[1])
        calls.append(rid)
        if entering and rid == 2 and not entering.is_set():
            entering.set()
            if not release.wait(3):
                raise RuntimeError("test control timeout")
        if rid == block:
            return 403, {}, b"blocked"
        record = {"RestaurantID": rid, "Name": f"Quán thử {rid}", "Address": "Địa chỉ mẫu",
                  "City": "Hà Nội", "Latitude": 21.03, "Longtitude": 105.85,
                  "PriceMin": 20000, "PriceMax": 40000,
                  "OpeningTime": [{"DayOfWeek": 3, "TimeOpen": {"Hours": 8, "Minutes": 0},
                                   "TimeClose": {"Hours": 20, "Minutes": 0}}]}
        html = "var initData = " + json.dumps(record)
        return 200, {"content-type": "text/html; charset=utf-8"}, html.encode()

    def factory(directory, **kwargs):
        return Collector(directory, fetcher=fetch, min_interval=0, backoff=0)
    return factory


def discovery_factory(n=65, reason="exhausted"):
    class FakeDiscovery:
        def __init__(self, directory, **kwargs):
            self.directory = directory

        def run(self, on_batch, should_stop, checkpoint, max_urls):
            found = urls(n)
            if max_urls is not None:
                found = found[:max_urls]
            clicks = 0
            for start in range(0, len(found), 12):
                checkpoint()
                if should_stop():
                    return {"reason": "stopped", "coverage_verified": False, "clicks": clicks}
                clicks = start // 12
                on_batch(found[start:start + 12], {"clicks": clicks, "discovered": start + 12})
            ending = "limit" if max_urls is not None and n >= max_urls else reason
            return {"reason": ending, "coverage_verified": ending == "exhausted", "clicks": clicks,
                    "urls": found, "source_url": "https://www.foody.vn/ha-noi/o-dau", "error": None}
    return FakeDiscovery


def wait_until(test, predicate, timeout=3):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(0.01)
    test.fail("Expected checkpoint was not reached")


class Jobs(unittest.TestCase):
    def test_all_mode_is_not_capped_at_50_and_csv_json_match(self):
        with tempfile.TemporaryDirectory() as folder:
            calls = []
            manager = JobManager(folder, discovery_factory=discovery_factory(),
                                 collector_factory=collector_factory(calls))
            job = manager.start({"mode": "all", "interval": 2})
            job.thread.join(5)
            data = job.snapshot()
            self.assertEqual(data["state"], "completed")
            self.assertEqual(data["success"], 65)
            self.assertTrue(data["coverage_verified"])
            self.assertEqual(calls, list(range(1, 66)))
            records = json.loads(job.read_artifact("restaurants.json"))
            self.assertEqual(len(records), 65)
            self.assertEqual(records, read_csv_records(job.directory / "restaurants.csv"))

    def test_sample_limit_is_not_city_coverage(self):
        with tempfile.TemporaryDirectory() as folder:
            calls = []
            manager = JobManager(folder, discovery_factory=discovery_factory(),
                                 collector_factory=collector_factory(calls))
            job = manager.start({"mode": "sample", "limit": 4})
            job.thread.join(3)
            self.assertEqual(job.snapshot()["state"], "completed")
            self.assertEqual(job.snapshot()["success"], 4)
            self.assertFalse(job.snapshot()["coverage_verified"])
            self.assertEqual(calls, [1, 2, 3, 4])

    def test_stalled_is_partial_even_if_known_urls_all_collected(self):
        with tempfile.TemporaryDirectory() as folder:
            manager = JobManager(folder, discovery_factory=discovery_factory(4, "stalled"),
                                 collector_factory=collector_factory([]))
            job = manager.start({"mode": "all"})
            job.thread.join(3)
            self.assertEqual(job.snapshot()["state"], "partial")
            report = json.loads(job.read_artifact("report.json"))
            self.assertTrue(report["partial"])
            self.assertEqual(report["discovery"]["reason"], "stalled")
            self.assertFalse(job.snapshot()["coverage_verified"])

    def test_pause_stop_restart_resume_no_refetch_of_success(self):
        with tempfile.TemporaryDirectory() as folder:
            calls, entering, release = [], threading.Event(), threading.Event()
            factory = collector_factory(calls, entering=entering, release=release)
            manager = JobManager(folder, discovery_factory=discovery_factory(), collector_factory=factory)
            job = manager.start({"mode": "all"})
            self.assertTrue(entering.wait(2))
            job.pause()
            release.set()
            wait_until(self, lambda: job.snapshot()["success"] == 2 and
                       len(json.loads(job.read_artifact("restaurants.json"))) == 2)
            self.assertEqual(job.snapshot()["state"], "paused")
            self.assertEqual(len(json.loads(job.read_artifact("restaurants.json"))), 2)
            with self.assertRaises(ValueError):
                manager.start({"mode": "sample"})
            job.stop()
            job.thread.join(3)
            self.assertEqual(job.snapshot()["state"], "stopped")
            restarted = JobManager(folder, discovery_factory=discovery_factory(), collector_factory=factory)
            recovered = restarted.resume(job.data["id"])
            recovered.thread.join(5)
            self.assertEqual(recovered.snapshot()["success"], 65)
            self.assertEqual(recovered.snapshot()["request_count"], 65)
            self.assertEqual(len(calls), len(set(calls)), "successful URLs must not be fetched twice")

    def test_block_stops_pipeline_before_remaining_urls(self):
        with tempfile.TemporaryDirectory() as folder:
            calls = []
            manager = JobManager(folder, discovery_factory=discovery_factory(),
                                 collector_factory=collector_factory(calls, block=2))
            job = manager.start({"mode": "all"})
            job.thread.join(3)
            self.assertEqual(calls, [1, 2])
            self.assertEqual(job.snapshot()["state"], "blocked")
            self.assertEqual(job.snapshot()["success"], 1)
            self.assertTrue(json.loads(job.read_artifact("report.json"))["partial"])

    def test_recovered_running_job_requires_explicit_resume(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder) / ("a" * 32)
            root.mkdir()
            (root / "job.json").write_text(json.dumps({"id": root.name, "mode": "all", "interval": 3,
                 "show_browser": True, "state": "running", "started_at": "2026-01-01", "logs": []}), encoding="utf8")
            manager = JobManager(folder)
            self.assertEqual(manager.status()["state"], "paused")
            self.assertIsNone(manager.get(root.name).thread)

    def test_invalid_configs_and_ids(self):
        for config in ({"mode": "bad"}, {"limit": 0}, {"limit": True}, {"interval": 1},
                       {"interval": float("nan")}, {"show_browser": "yes"}):
            with self.subTest(config=config), self.assertRaises(ValueError):
                validate_config(config)
        with tempfile.TemporaryDirectory() as folder:
            manager = JobManager(folder)
            with self.assertRaises(KeyError):
                manager.get("../outside")

    def test_resume_rechecks_cached_challenge_page(self):
        with tempfile.TemporaryDirectory() as folder:
            calls, blocked = [], [True]
            original_factory = collector_factory(calls)
            def factory(directory, **kwargs):
                collector = original_factory(directory, **kwargs)
                fetch = collector.fetcher
                def controlled(url, timeout):
                    response = fetch(url, timeout)
                    if blocked[0] and url.endswith("-2"):
                        return 200, {"content-type": "text/html"}, b"<html>captcha challenge</html>"
                    return response
                collector.fetcher = controlled
                return collector
            manager = JobManager(folder, discovery_factory=discovery_factory(4), collector_factory=factory)
            job = manager.start({"mode": "all"})
            job.thread.join(3)
            self.assertEqual(job.snapshot()["state"], "blocked")
            blocked[0] = False
            manager.resume(job.data["id"])
            job.thread.join(3)
            self.assertEqual(job.snapshot()["state"], "completed")
            self.assertEqual(calls, [1, 2, 2, 3, 4])
            self.assertEqual(job.snapshot()["success"], 4)

    def test_storage_failure_does_not_leave_ui_reporting_running(self):
        with tempfile.TemporaryDirectory() as folder:
            entering, release = threading.Event(), threading.Event()
            manager = JobManager(folder, discovery_factory=discovery_factory(),
                                 collector_factory=collector_factory([], entering=entering, release=release))
            job = manager.start({"mode": "all"})
            self.assertTrue(entering.wait(2))
            with patch("foody_tool.jobs.atomic_json", side_effect=OSError("test disk full")):
                release.set()
                job.thread.join(3)
                self.assertFalse(job.thread.is_alive())
                self.assertEqual(job.snapshot()["state"], "error")
                self.assertFalse(job.snapshot()["coverage_verified"])


if __name__ == "__main__":
    unittest.main()
