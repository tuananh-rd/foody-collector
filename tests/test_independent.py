"""Independent validation tests evaluating sample5 evidence and core collector contracts."""
import json
import os
import tempfile
import unittest
from pathlib import Path

from foody_tool.parser import parse_restaurant, ParseError
from foody_tool.collector import normalize_restaurant_url, UrlError, Collector, load_url_file
from foody_tool.exporter import export_json, export_csv, read_csv_records, build_report

ROOT = Path(__file__).resolve().parent.parent
import unittest as _ut
if not (ROOT / "reference" / "sample5.json").exists():
    raise _ut.SkipTest("needs local reference/sample5.json (scraped sample, not part of the public repo)")
SAMPLE_PATH = ROOT / "reference" / "sample5.json"
FIXTURES_DIR = ROOT / "tests" / "fixtures"
CANDIDATES_PATH = ROOT / "inputs" / "candidates_49.txt"
TS = "2026-10-14T12:00:00+00:00"


class TestSample5Evidence(unittest.TestCase):
    """Independent inspection of the 5 reference sample records and fixtures."""

    @classmethod
    def setUpClass(cls):
        cls.sample = json.loads(SAMPLE_PATH.read_text(encoding="utf-8"))

    def test_sample_count_and_uniqueness(self):
        self.assertEqual(len(self.sample), 5)
        ids = [s["foody_id"] for s in self.sample]
        self.assertEqual(len(set(ids)), 5, "Sample records must have distinct Foody IDs")

    def test_hanoi_bounding_coordinates(self):
        # Hanoi coordinates roughly: 20.8 to 21.3 N, 105.7 to 106.0 E
        for s in self.sample:
            lat, lon = s["lat"], s["lon"]
            self.assertIsNotNone(lat)
            self.assertIsNotNone(lon)
            self.assertTrue(20.8 <= lat <= 21.3, f"{s['key']} lat {lat} out of Hanoi bounds")
            self.assertTrue(105.6 <= lon <= 106.1, f"{s['key']} lon {lon} out of Hanoi bounds")

    def test_opening_hours_phenomenon(self):
        # BAO_CAO_FOODY note: all 5 records only exhibit DayOfWeek=3
        for s in self.sample:
            days = s.get("opening_days_present", [])
            self.assertEqual(days, [3], f"{s['key']} has unexpected opening days: {days}")

    def test_internal_flags_phenomenon(self):
        # BAO_CAO_FOODY note: all 5 records have IsActive=False, IsInactive=True, RestaurantStatus=2
        for s in self.sample:
            flags = s["flags"]
            self.assertFalse(flags.get("IsActive"))
            self.assertTrue(flags.get("IsInactive"))
            self.assertEqual(flags.get("RestaurantStatus"), 2)


class TestCoreParserEvaluation(unittest.TestCase):
    """Independent evaluation of foody_tool.parser against reference fixtures."""

    @classmethod
    def setUpClass(cls):
        cls.sample = json.loads(SAMPLE_PATH.read_text(encoding="utf-8"))

    def test_parse_reference_fixtures(self):
        for s in self.sample:
            fix_path = FIXTURES_DIR / f"{s['key']}.html"
            if not fix_path.exists():
                self.skipTest(f"Fixture {fix_path.name} not present")
            html = fix_path.read_text(encoding="utf-8")
            rec = parse_restaurant(html, s["source_url"], TS)
            self.assertEqual(rec["foody_id"], s["foody_id"])
            self.assertEqual(rec["name"], s["name"])
            self.assertEqual(rec["lat"], s["lat"])
            self.assertEqual(rec["lon"], s["lon"])
            self.assertEqual(rec["source_flags"], s["flags"])
            self.assertEqual(rec["parse_warnings"], [])

    def test_parse_error_on_non_venue_pages(self):
        # Non-restaurant HTML must raise ParseError, not crash
        with self.assertRaises(ParseError):
            parse_restaurant("<html><title>Not found</title><body>Error</body></html>", "https://url", TS)
        with self.assertRaises(ParseError):
            parse_restaurant("<script>var initData = null;</script>", "https://url", TS)


class TestCandidateUrlConformity(unittest.TestCase):
    """Verify that all 49 discovered candidate URLs conform to core collector's normalize_restaurant_url."""

    def test_candidates_normalize_without_error(self):
        if not CANDIDATES_PATH.exists():
            self.skipTest("candidates_49.txt not yet generated")
        urls = load_url_file(str(CANDIDATES_PATH))
        self.assertEqual(len(urls), 49, "Expected exactly 49 candidate URLs")
        for u in urls:
            try:
                norm = normalize_restaurant_url(u)
                self.assertEqual(norm, u, f"Normalized URL {norm} did not match input {u}")
            except UrlError as e:
                self.fail(f"Candidate URL {u} failed normalize_restaurant_url: {e}")

    def test_coordinator_urls48_normalize_without_error(self):
        urls48_path = ROOT / "reports" / "coordinator" / "urls48.txt"
        if not urls48_path.exists():
            self.skipTest("urls48.txt not present")
        urls = load_url_file(str(urls48_path))
        self.assertEqual(len(urls), 48, "Expected exactly 48 coordinator URLs")
        for u in urls:
            try:
                norm = normalize_restaurant_url(u)
                self.assertEqual(norm, u, f"Normalized URL {norm} did not match input {u}")
            except UrlError as e:
                self.fail(f"Coordinator URL {u} failed normalize_restaurant_url: {e}")


class TestCoreExporterRoundtrip(unittest.TestCase):
    """Verify that exporter CSV and JSON formats are equivalent and roundtrip cleanly."""

    def test_csv_json_roundtrip(self):
        records = []
        for s in json.loads(SAMPLE_PATH.read_text(encoding="utf-8")):
            fix_path = FIXTURES_DIR / f"{s['key']}.html"
            if fix_path.exists():
                rec = parse_restaurant(fix_path.read_text(encoding="utf-8"), s["source_url"], TS)
                records.append(rec)

        with tempfile.TemporaryDirectory() as tmpdir:
            json_path = os.path.join(tmpdir, "out.json")
            csv_path = os.path.join(tmpdir, "out.csv")
            export_json(records, json_path)
            export_csv(records, csv_path)

            read_back = read_csv_records(csv_path)
            self.assertEqual(len(read_back), len(records))
            for orig, loaded in zip(records, read_back):
                self.assertEqual(orig["foody_id"], loaded["foody_id"])
                self.assertEqual(orig["name"], loaded["name"])
                self.assertEqual(orig["lat"], loaded["lat"])
                self.assertEqual(orig["lon"], loaded["lon"])
                self.assertEqual(orig["opening_hours_raw"], loaded["opening_hours_raw"])
                self.assertEqual(orig["source_flags"], loaded["source_flags"])


class TestCollectorContracts(unittest.TestCase):
    """Verify safety boundaries: min_interval enforcement and rate-limiting."""

    def test_minimum_interval_enforcement(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            # Setting min_interval < 2.0 with default_fetcher must raise ValueError
            with self.assertRaises(ValueError):
                Collector(tmpdir, min_interval=1.0)


if __name__ == "__main__":
    unittest.main()
