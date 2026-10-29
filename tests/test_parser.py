import json
import unittest
from pathlib import Path

from foody_tool.parser import ParseError, parse_restaurant

ROOT = Path(__file__).resolve().parent.parent
FIX = ROOT / "tests" / "fixtures"
import unittest as _ut
if not (ROOT / "reference" / "sample5.json").exists():
    raise _ut.SkipTest("needs local reference/sample5.json (scraped sample, not part of the public repo)")
SAMPLE = json.loads((ROOT / "reference" / "sample5.json").read_text(encoding="utf-8"))
TS = "2026-10-14T00:00:00+00:00"


def page(obj, h1="X"):
    return f"<html><h1>{h1}</h1><script>var initData = {json.dumps(obj)};</script></html>"


def base(**kw):
    d = {"RestaurantID": 1, "Name": "Quán A", "Latitude": 21.0, "Longtitude": 105.8,
         "Address": "1 Phố", "District": "Q", "City": "Hà Nội", "PriceMin": 10000,
         "PriceMax": 20000,
         "OpeningTime": [{"DayOfWeek": 3, "CustomDate": None,
                          "TimeOpen": {"Hours": 6, "Minutes": 30},
                          "TimeClose": {"Hours": 14, "Minutes": 0}}]}
    d.update(kw)
    return d


class SampleFixtures(unittest.TestCase):
    def test_sample5_values(self):
        for s in SAMPLE:
            f = FIX / f"{s['key']}.html"
            if not f.exists():
                self.skipTest(f"local fixture {f.name} missing (gitignored)")
            r = parse_restaurant(f.read_text(encoding="utf-8"), s["source_url"], TS)
            for k in ("foody_id", "name", "address", "district", "city", "lat", "lon",
                      "opening_hours_raw", "price_min_vnd", "price_max_vnd"):
                self.assertEqual(r[k], s[k], (s["key"], k))
            self.assertEqual(r["source_flags"], s["flags"])
            self.assertEqual(r["h1_names"], s["h1_names"])
            self.assertTrue(r["field_freshness_unknown"])
            self.assertEqual(r["parse_warnings"], [])
        self.assertEqual(len({s["foody_id"] for s in SAMPLE}), 5)


class Synthetic(unittest.TestCase):
    def test_basic(self):
        r = parse_restaurant(page(base()), "u", TS)
        self.assertEqual(r["opening_hours_raw"][0]["open"], "06:30")
        self.assertEqual(r["source_url"], "u")
        self.assertEqual(r["fetched_at"], TS)

    def test_missing_optional_fields_are_null(self):
        r = parse_restaurant(page({"RestaurantID": 5, "Name": "N"}), "u", TS)
        for k in ("lat", "lon", "address", "district", "city", "price_min_vnd", "price_max_vnd"):
            self.assertIsNone(r[k])
        self.assertEqual(r["opening_hours_raw"], [])

    def test_no_initdata(self):
        with self.assertRaises(ParseError):
            parse_restaurant("<html>captcha</html>", "u", TS)

    def test_truncated_json(self):
        with self.assertRaises(ParseError):
            parse_restaurant('<script>var initData = {"RestaurantID": 1, "Name": "A', "u", TS)

    def test_bad_id_or_name(self):
        for bad in (base(RestaurantID="12"), base(RestaurantID=True), base(RestaurantID=0),
                    base(Name=""), base(Name=None)):
            with self.assertRaises(ParseError):
                parse_restaurant(page(bad), "u", TS)

    def test_invalid_coordinates_dropped_with_warning(self):
        for kw in ({"Latitude": 91}, {"Longtitude": -181}, {"Latitude": "21.0"}):
            r = parse_restaurant(page(base(**kw)), "u", TS)
            self.assertIsNone(r["lat"])
            self.assertIsNone(r["lon"])
            self.assertTrue(r["parse_warnings"])

    def test_invalid_times_not_guessed(self):
        o = [{"DayOfWeek": 9, "TimeOpen": {"Hours": 25, "Minutes": 0},
              "TimeClose": {"Hours": 10, "Minutes": 61}},
             {"DayOfWeek": 2, "TimeOpen": {"Hours": "7", "Minutes": 0}}, "junk"]
        r = parse_restaurant(page(base(OpeningTime=o)), "u", TS)
        self.assertEqual([h["open"] for h in r["opening_hours_raw"]], [None, None])
        self.assertEqual([h["close"] for h in r["opening_hours_raw"]], [None, None])
        self.assertEqual(r["opening_hours_raw"][0]["day_of_week_raw"], 9)  # unknown codes kept raw
        self.assertEqual(len(r["parse_warnings"]), 4)

    def test_bad_prices(self):
        r = parse_restaurant(page(base(PriceMin=-5, PriceMax="x")), "u", TS)
        self.assertIsNone(r["price_min_vnd"])
        self.assertIsNone(r["price_max_vnd"])

    def test_opening_time_not_list(self):
        r = parse_restaurant(page(base(OpeningTime={"a": 1})), "u", TS)
        self.assertEqual(r["opening_hours_raw"], [])
        self.assertTrue(r["parse_warnings"])

    def test_minutes_missing_not_defaulted_to_zero(self):
        o = [{"DayOfWeek": 3, "TimeOpen": {"Hours": 6}, "TimeClose": {"Hours": 14, "Minutes": 0}}]
        r = parse_restaurant(page(base(OpeningTime=o)), "u", TS)
        self.assertIsNone(r["opening_hours_raw"][0]["open"])
        self.assertEqual(r["opening_hours_raw"][0]["close"], "14:00")
        self.assertTrue(r["parse_warnings"])


if __name__ == "__main__":
    unittest.main()
