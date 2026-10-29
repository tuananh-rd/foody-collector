import csv
import json
import os
import tempfile
import unittest

from foody_tool.exporter import FIELDS, build_report, export_all, read_csv_records
from foody_tool.parser import parse_restaurant

TS = "2026-10-14T00:00:00+00:00"


def rec(i, **kw):
    d = {"RestaurantID": i, "Name": f"Quán, \"{i}\"\nxuống dòng", "Latitude": 21.5,
         "Longtitude": 105.25, "Address": None if i % 2 else "Số 1, Phố", "District": "Quận",
         "City": "Hà Nội", "PriceMin": 15000.0, "PriceMax": 28000,
         "IsActive": False, "RestaurantStatus": 2,
         "OpeningTime": [{"DayOfWeek": 3, "TimeOpen": {"Hours": 6, "Minutes": 30},
                          "TimeClose": {"Hours": 14, "Minutes": 0}}]}
    d.update(kw)
    return parse_restaurant(f"<script>var initData = {json.dumps(d)};</script>", f"u{i}", TS)


class Export(unittest.TestCase):
    def test_csv_json_equivalence_and_utf8(self):
        recs = [rec(1), rec(2), rec(3, Latitude=None, Longtitude=None, OpeningTime=[])]
        with tempfile.TemporaryDirectory() as d:
            export_all(d, {}, recs, [])
            with open(os.path.join(d, "restaurants.csv"), "rb") as fh:
                raw = fh.read()
            self.assertFalse(raw.startswith(b"\xef\xbb\xbf"))
            raw.decode("utf-8")
            self.assertIn("Hà Nội".encode(), raw)
            with open(os.path.join(d, "restaurants.json"), encoding="utf-8") as fh:
                js = json.load(fh)
            cs = read_csv_records(os.path.join(d, "restaurants.csv"))
            self.assertEqual(cs, js)
            self.assertEqual(list(js[0]), FIELDS)
            self.assertEqual(js[0]["name"], recs[0]["name"])
            self.assertIsNone(js[2]["lat"])
            self.assertEqual(js[0]["source_flags"]["IsActive"], False)

    def test_csv_header_and_row_count(self):
        with tempfile.TemporaryDirectory() as d:
            export_all(d, {}, [rec(1), rec(2)], [])
            with open(os.path.join(d, "restaurants.csv"), encoding="utf-8", newline="") as fh:
                rows = list(csv.reader(fh))
            self.assertEqual(rows[0], FIELDS)
            self.assertEqual(len(rows), 3)

    def test_report_completeness_and_failures(self):
        progress = {"a": {"status": "ok"}, "b": {"status": "blocked", "http_status": 429, "error": "HTTP 429"},
                    "c": {"status": "duplicate_id", "duplicate_of": "a"}}
        r = build_report(progress, [rec(1, Latitude=None, Longtitude=None), rec(2)],
                         ["a", "b", "c", "d"], "blocked at b")
        self.assertEqual(r["outcomes"], {"ok": 1, "blocked": 1, "duplicate_id": 1, "pending": 1})
        self.assertEqual(r["completeness"]["lat"], {"present": 1, "total": 2, "rate": 0.5})
        self.assertEqual({f["url"] for f in r["failures"]}, {"b", "c"})
        self.assertEqual(r["stopped_reason"], "blocked at b")

    def test_usable_positive_price_range_distinct_from_presence(self):
        recs = [rec(1), rec(2, PriceMin=0, PriceMax=0), rec(3, PriceMin=50000, PriceMax=10000),
                rec(4, PriceMin=None, PriceMax=20000), rec(5, PriceMin=0, PriceMax=30000)]
        r = build_report({}, recs, [])
        self.assertEqual(r["completeness"]["price_min_vnd"]["present"], 4)  # raw 0 counts as present
        u = r["usable_positive_price_range"]
        self.assertEqual((u["usable"], u["total"], u["rate"]), (1, 5, 0.2))
        self.assertEqual(u["raw_zero_price_records"], 2)
        self.assertEqual(recs[1]["price_min_vnd"], 0)  # raw value retained

    def test_empty_report(self):
        r = build_report({}, [], [])
        self.assertIsNone(r["completeness"]["name"]["rate"])

    def test_hours_completeness_needs_open_and_close(self):
        null_iv = rec(1, OpeningTime=[{"DayOfWeek": 3, "TimeOpen": {"Hours": 99, "Minutes": 0},
                                        "TimeClose": None}])
        half = rec(2, OpeningTime=[{"DayOfWeek": 3, "TimeOpen": {"Hours": 8, "Minutes": 0}}])
        r = build_report({}, [null_iv, half, rec(3)], [])
        self.assertEqual(len(null_iv["opening_hours_raw"]), 1)  # raw list retained
        self.assertEqual(r["completeness"]["opening_hours_raw"]["present"], 1)

    def test_csv_formula_injection_neutralised_json_canonical(self):
        names = ["=HYPERLINK(\"http://x\")", "+1", "-2+3", "@SUM(A1)", "'=x", "\tTab", "Safe"]
        recs = [rec(i, Name=n, Address=n) for i, n in enumerate(names, 1)]
        with tempfile.TemporaryDirectory() as d:
            export_all(d, {}, recs, [])
            with open(os.path.join(d, "restaurants.csv"), encoding="utf-8", newline="") as fh:
                rows = list(csv.DictReader(fh))
            for row, n in zip(rows, names):
                self.assertFalse(row["name"][0] in "=+-@\t\r", row["name"])
            with open(os.path.join(d, "restaurants.json"), encoding="utf-8") as fh:
                js = json.load(fh)
            self.assertEqual([r["name"] for r in js], [n.strip() for n in names])  # parser trims
            self.assertEqual(read_csv_records(os.path.join(d, "restaurants.csv")), js)


if __name__ == "__main__":
    unittest.main()
