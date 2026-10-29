"""Regressions found by independent saved-job integration checks."""
import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from foody_tool.exporter import export_csv, export_json
from foody_tool.jobs import CrawlJob
from foody_tool.quality import build_provenance, build_quality_report, import_and_classify, normalize_record


def record(rid=1):
    return dict(foody_id=rid, name="Quán thử", source_url=f"https://www.foody.vn/ha-noi/test-{rid}",
                lat=21.03, lon=105.85, price_min_vnd=10000, price_max_vnd=20000,
                opening_hours_raw=[dict(day_of_week_raw=3, open="06:00", close="22:00")],
                source_flags={}, parse_warnings=[], fetched_at="2026-10-14T00:00:00Z")


class FinalIntegration(unittest.TestCase):
    def test_saved_job_missing_report_and_cached_evidence(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / ("e" * 32)
            job = CrawlJob(path, config={"mode":"sample", "limit":1, "interval":2})
            job.update(state="completed", termination_reason="limit")
            row = record()
            export_csv([row], path / "restaurants.csv")
            export_json([row], path / "restaurants.json")
            originals = {name:(path/name).read_bytes() for name in ("restaurants.csv","restaurants.json")}
            cache = path / "cache"
            cache.mkdir()
            html = '<script>var initData = {"RestaurantID":1,"Name":"Quán thử","PriceMin":10000,"PriceMax":20000,"OpeningTime":[]};</script>'
            (cache / (hashlib.sha256(row["source_url"].encode()).hexdigest()[:20] + ".html")).write_text(html, encoding="utf-8")
            result = job.reclassify_quality()
            self.assertEqual(result, job.snapshot()["report"]["quality"])
            self.assertEqual(result, json.loads((path / "quality_report.json").read_text(encoding="utf-8")))
            self.assertEqual(result["execution_mode"], "offline_reclassification")
            self.assertEqual(result["detail_requests_this_operation"], 0)
            for name, data in originals.items():
                self.assertEqual(data, (path/name).read_bytes())
            evidence = json.loads((path / "restaurants_raw.json").read_text(encoding="utf-8"))[0]["provenance"]
            self.assertEqual(evidence["text_snapshot_hash"], "sha256:" + hashlib.sha256(html.encode()).hexdigest())
            self.assertTrue(evidence["fields"]["price_min_vnd"]["present"])
            self.assertEqual(evidence["hash_basis"], "text_snapshot")
            for name in ("raw_content_hash", "parsed_at", "final_url", "parser_version", "http_status"):
                self.assertIsNone(evidence[name], name)

    def test_corrupt_old_report_is_explicit_and_preserved(self):
        with tempfile.TemporaryDirectory() as folder:
            job = CrawlJob(Path(folder)/("f"*32), config={"mode":"sample", "limit":1})
            job.update(state="completed")
            export_json([record()], job.directory/"restaurants.json")
            report = job.directory/"report.json"
            report.write_text("{broken", encoding="utf-8")
            with self.assertRaises(ValueError):
                job.reclassify_quality()
            self.assertEqual(report.read_text(), "{broken")
            self.assertFalse((job.directory/"quality_report.json").exists())

    def test_retry_unknown_and_unrelated_progress_not_in_denominator(self):
        rows = [record(1), record(2)]
        urls = [r["source_url"] for r in rows]
        progress = {urls[0]:dict(status="ok",retry_count=2,from_cache=True),
                    urls[1]:dict(status="ok",retry_count=None),
                    "unrelated":dict(status="ok",retry_count=0)}
        report = build_quality_report(progress, urls, rows,
                                      [normalize_record(r,{}) for r in rows], [], run_id="test")
        self.assertEqual(report["funnel"]["discovered_urls"], 2)
        self.assertIsNone(report["funnel"]["retried_urls"])
        self.assertEqual(report["funnel"]["retried_urls_known"], 1)
        self.assertEqual(report["funnel"]["retry_unknown_urls"], 1)
        self.assertEqual(report["execution_mode"], "crawl_snapshot")

    def test_known_source_parse_facts_are_retained(self):
        evidence = build_provenance(record(), dict(parser_version="0.2.0", parsed_at="observed",
                                                   final_url="observed-url",http_status=200), run_id="test")
        self.assertEqual(evidence["parser_version"], "0.2.0")
        self.assertEqual(evidence["parsed_at"], "observed")
        self.assertEqual(evidence["final_url"], "observed-url")

    def test_json_types_and_reserved_import_metadata(self):
        with tempfile.TemporaryDirectory() as folder:
            source = Path(folder)/"input.json"
            source.write_text("true", encoding="utf-8")
            with self.assertRaises(ValueError):
                import_and_classify(source, Path(folder)/"bad")
            item = record()
            item.update(_csv_line=999, import_original="untrusted")
            source.write_text(json.dumps([True,item]), encoding="utf-8")
            destination = Path(folder)/"good"
            report = import_and_classify(source,destination,run_id="test")
            self.assertEqual(report["import"]["rows_read"], 2)
            self.assertEqual(report["import"]["rows_invalid"], 1)
            raw = json.loads((destination/"restaurants_raw.json").read_text(encoding="utf-8"))
            self.assertIs(raw[0]["import_original"], True)
            self.assertEqual(raw[1]["import_original"], item)
            issues = json.loads((destination/"issues.json").read_text(encoding="utf-8"))
            self.assertTrue(all(i["csv_line"] in (2,3) for i in issues))


if __name__ == "__main__":
    unittest.main()
