"""Tests for Foody v0.3 quality metrics, classification, issue detection, and strict JSON."""
import csv
import json
import math
import os
import tempfile
import unittest
from pathlib import Path

from foody_tool.exporter import FIELDS, export_all, read_csv_records
from foody_tool.quality import (
    HOURS_STATUSES,
    PRICE_STATUSES,
    GEO_STATUSES,
    QUALITY_SCHEMA_VERSION,
    PARSER_VERSION,
    build_quality_report,
    classify_geo,
    classify_hours,
    classify_price,
    detect_issues,
    dumps_strict_json,
    export_quality,
    import_and_classify,
    normalize_record,
    sanitize_strict_json,
)

FIXTURE_CSV = Path("tests/fixtures/audit200.csv")
ORACLE_CSV = Path("tests/fixtures/price_issues_200.csv")


def _raise_on_constant(constant):
    raise ValueError(f"Constant {constant} is not allowed in strict JSON")


def load_strict_json(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f, parse_constant=_raise_on_constant)


class TestClassifiers(unittest.TestCase):
    def test_classify_price(self):
        # Section 10 Test 7
        self.assertEqual(classify_price(None, None)["status"], "missing")
        self.assertEqual(classify_price(None, 5000)["status"], "missing")
        self.assertEqual(classify_price(0, 0)["status"], "unknown_zero")
        self.assertEqual(classify_price(0, 5000)["status"], "partial_zero")
        self.assertEqual(classify_price(5000, 0)["status"], "partial_zero")

        ok_res = classify_price(60000, 350000)
        self.assertEqual(ok_res["status"], "ok")
        self.assertEqual(ok_res["min_norm"], 60000)
        self.assertEqual(ok_res["max_norm"], 350000)

        inv_res = classify_price(350000, 60000)
        self.assertEqual(inv_res["status"], "invalid_range")
        self.assertIsNone(inv_res["min_norm"])
        self.assertIsNone(inv_res["max_norm"])

        equal_res = classify_price(5000, 5000)
        self.assertEqual(equal_res["status"], "ok")
        self.assertEqual(equal_res["min_norm"], 5000)
        self.assertEqual(equal_res["max_norm"], 5000)

        # Non-finite and invalid types
        self.assertEqual(classify_price(float("nan"), 5000)["status"], "nonfinite")
        self.assertEqual(classify_price(float("inf"), 5000)["status"], "nonfinite")
        self.assertEqual(classify_price(-1, 5000)["status"], "nonfinite")
        self.assertEqual(classify_price(True, 5000)["status"], "nonfinite")
        self.assertEqual(classify_price("5000", 5000)["status"], "nonfinite")
        self.assertEqual(classify_price(5000, "5000")["status"], "nonfinite")

        # Fractional prices must NOT silently round to int (must be nonfinite)
        self.assertEqual(classify_price(1000.4, 2000.6)["status"], "nonfinite")
        self.assertEqual(classify_price(1000.0, 2000.0)["status"], "ok")

        # Huge int safety (must not raise OverflowError in float/nan conversions)
        huge = 10**400
        self.assertEqual(classify_price(huge, 50000)["status"], "invalid_range")
        self.assertEqual(classify_price(50000, huge)["status"], "ok")

        # Parser warnings trigger nonfinite
        warn_res = classify_price(None, None, warnings=["invalid PriceMin 'abc' dropped"])
        self.assertEqual(warn_res["status"], "nonfinite")

    def test_classify_hours(self):
        # Section 10 Test 8
        self.assertEqual(classify_hours([])["status"], "missing")
        self.assertEqual(classify_hours(None)["status"], "missing")

        # Parser warnings override empty/None to malformed (spec 3.2)
        self.assertEqual(classify_hours([], warnings=["invalid OpeningTime"])["status"], "malformed")
        self.assertEqual(classify_hours(None, warnings=["corrupt hours json"])["status"], "malformed")

        mal = classify_hours([{"open": "08:00", "close": None}])
        self.assertEqual(mal["status"], "malformed")

        # Clock range validation
        self.assertEqual(classify_hours([{"open": "99:99", "close": "23:59"}])["status"], "malformed")
        self.assertEqual(classify_hours([{"open": "12:60", "close": "13:00"}])["status"], "malformed")
        self.assertEqual(classify_hours([{"open": "24:00", "close": "00:00"}])["status"], "malformed")

        # Two shifts preserved
        two = [
            {"day_of_week_raw": 3, "open": "07:00", "close": "13:00"},
            {"day_of_week_raw": 3, "open": "17:00", "close": "22:00"},
        ]
        two_res = classify_hours(two)
        self.assertEqual(two_res["status"], "day_mapping_unknown")
        self.assertEqual(two_res["intervals_count"], 2)
        self.assertFalse(two_res["crosses_midnight_raw"])

        # Overnight
        overnight = [{"day_of_week_raw": 3, "open": "20:00", "close": "02:00"}]
        ov_res = classify_hours(overnight)
        self.assertEqual(ov_res["status"], "day_mapping_unknown")
        self.assertTrue(ov_res["crosses_midnight_raw"])
        self.assertIsNone(ov_res["schedule_norm"])

        # Mixed types without TypeError (Section 13.5 & 13.7)
        mixed = [{"day_of_week_raw": 3}, {"day_of_week_raw": "3"}, {"day_of_week_raw": None}, "x", 7]
        mixed_res = classify_hours(mixed)
        self.assertEqual(mixed_res["intervals_count"], 5)
        self.assertEqual(mixed_res["status"], "malformed")
        # Ordered by (type name, canonical JSON)
        self.assertEqual(mixed_res["day_codes_raw"], [None, 3, "3"])

    def test_classify_geo(self):
        # Section 10 Test 9
        self.assertEqual(classify_geo(None, None), "missing")
        self.assertEqual(classify_geo(21.0, None), "missing")
        self.assertEqual(classify_geo(float("nan"), 105.8), "nonfinite")
        self.assertEqual(classify_geo(True, 105.8), "nonfinite")
        self.assertEqual(classify_geo(95.0, 105.8), "out_of_range")
        self.assertEqual(classify_geo(21.0, 200.0), "out_of_range")
        # Huge int safety
        huge = 10**400
        self.assertEqual(classify_geo(huge, 105.8), "out_of_range")
        self.assertEqual(classify_geo(21.0, huge), "out_of_range")
        # Outside Hanoi bbox: lat 20.5-21.5, lon 105.3-106.1
        self.assertEqual(classify_geo(10.8, 106.7), "outside_hanoi_bbox")
        self.assertEqual(classify_geo(21.0, 105.8), "ok")


class TestAudit200Fixture(unittest.TestCase):
    def setUp(self):
        if not FIXTURE_CSV.exists() or not ORACLE_CSV.exists():
            self.skipTest("audit200.csv or price_issues_200.csv fixture absent")

    def test_audit200_exact_matches_oracle(self):
        with tempfile.TemporaryDirectory() as out_dir:
            qrep = import_and_classify(str(FIXTURE_CSV), out_dir)

            # 1. Row counts
            self.assertEqual(qrep["funnel"]["unique_venues_exported"], 200)
            self.assertEqual(qrep["import"]["rows_read"], 200)
            self.assertEqual(qrep["import"]["rows_invalid"], 0)

            # 2. Strict JSON check
            for name in ("restaurants_raw.json", "restaurants_normalized.json", "issues.json", "quality_report.json"):
                load_strict_json(os.path.join(out_dir, name))

            # 3. Exactly 6 price issues matching oracle
            with open(os.path.join(out_dir, "issues.csv"), encoding="utf-8-sig") as f:
                issues_rows = list(csv.DictReader(f))

            price_issues = [r for r in issues_rows if r["issue_code"] in ("zero_price_unverified", "invalid_price_range")]
            self.assertEqual(len(price_issues), 6)

            with open(str(ORACLE_CSV), encoding="utf-8-sig") as f:
                oracle_rows = list(csv.DictReader(f))

            cols = ["csv_line", "foody_id", "name", "issue_code", "raw_min", "raw_max", "source_url"]
            subset = [{c: r[c] for c in cols} for r in price_issues]
            self.assertEqual(subset, oracle_rows)

            # 4. Check statuses and raw preservation for the 6 issues
            norm_rows = load_strict_json(os.path.join(out_dir, "restaurants_normalized.json"))
            norm_map = {r["foody_id"]: r for r in norm_rows}

            for fid in (1252693, 1000062975, 1136050, 1229666, 1204032):
                rec = norm_map[fid]
                self.assertEqual(rec["price_status"], "unknown_zero")
                self.assertIsNone(rec["price_min_vnd_norm"])
                self.assertIsNone(rec["price_max_vnd_norm"])
                self.assertEqual(rec["price_min_raw"], 0.0)
                self.assertEqual(rec["price_max_raw"], 0.0)
                self.assertFalse(rec["price_filter_eligible"])
                self.assertTrue(rec["search_eligible"])

            rev_rec = norm_map[68957]
            self.assertEqual(rev_rec["price_status"], "invalid_range")
            self.assertIsNone(rev_rec["price_min_vnd_norm"])
            self.assertIsNone(rev_rec["price_max_vnd_norm"])
            self.assertEqual(rev_rec["price_min_raw"], 350000.0)
            self.assertEqual(rev_rec["price_max_raw"], 60000.0)
            self.assertFalse(rev_rec["price_filter_eligible"])
            self.assertTrue(rev_rec["search_eligible"])

            # 5. The other 194 venues are ok
            ok_venues = [r for r in norm_rows if r["price_status"] == "ok"]
            self.assertEqual(len(ok_venues), 194)
            for r in ok_venues:
                self.assertEqual(r["price_min_vnd_norm"], int(r["price_min_raw"]))
                self.assertEqual(r["price_max_vnd_norm"], int(r["price_max_raw"]))
                self.assertTrue(r["price_filter_eligible"])
                # budget_eligible is ALWAYS false in v3 (Correction 13.1)
                self.assertFalse(r["budget_eligible"])

            # 6. Hours and shifts
            total_shifts = sum(r["hours_intervals_count"] for r in norm_rows)
            self.assertEqual(total_shifts, 220)
            multi_shift = sum(1 for r in norm_rows if r["hours_intervals_count"] > 1)
            self.assertEqual(multi_shift, 20)

            for r in norm_rows:
                if r["hours_intervals_count"] > 0:
                    self.assertEqual(r["hours_status"], "day_mapping_unknown")
                    self.assertIsNone(r["hours_schedule_norm"])
                    self.assertEqual(r["hours_day_codes_raw"], [3])
                self.assertFalse(r["hours_eligible"])
                self.assertFalse(r["tour_eligible"])
                self.assertEqual(r["operating_status"], "unknown")


class TestSynthetic200Fixture(unittest.TestCase):
    """Synthetic 200-venue fixture to guarantee CI validation even if gitignored fixtures are absent."""
    def test_synthetic_200_venues(self):
        records = []
        for i in range(1, 201):
            if i == 7:  # csv_line 8
                lo, hi = 0.0, 0.0
            elif i == 47:  # csv_line 48
                lo, hi = 0.0, 0.0
            elif i == 76:  # csv_line 77
                lo, hi = 0.0, 0.0
            elif i == 93:  # csv_line 94
                lo, hi = 350000.0, 60000.0
            elif i == 99:  # csv_line 100
                lo, hi = 0.0, 0.0
            elif i == 149:  # csv_line 150
                lo, hi = 0.0, 0.0
            else:
                lo, hi = 20000.0, 50000.0

            hours = [{"day_of_week_raw": 3, "open": "08:00", "close": "22:00"}]
            if i <= 20:
                hours.append({"day_of_week_raw": 3, "open": "17:00", "close": "21:00"})

            records.append({
                "foody_id": 1000 + i,
                "name": f"Synthetic Venue {i}",
                "lat": 21.02,
                "lon": 105.83,
                "address": f"Address {i}",
                "district": "Quận Hoàn Kiếm",
                "city": "Hà Nội",
                "opening_hours_raw": hours,
                "price_min_vnd": lo,
                "price_max_vnd": hi,
                "source_url": f"https://www.foody.vn/ha-noi/synthetic-{i}",
                "fetched_at": "2026-10-14T12:00:00+00:00",
                "price_semantics": "venue price range, not individual dish or per-person guaranteed budget",
                "source_license": "No open-data license established",
                "field_freshness_unknown": True,
                "source_flags": {"IsActive": False, "IsInactive": True, "RestaurantStatus": 2},
                "h1_names": [f"Synthetic Venue {i}"],
                "parse_warnings": ["PriceMin greater than PriceMax; both kept as published"] if lo > hi else [],
                "_csv_line": i + 1,
            })

        with tempfile.TemporaryDirectory() as out_dir:
            qrep = export_quality(out_dir, {}, records, [r["source_url"] for r in records], run_id="synth-200")
            self.assertEqual(qrep["funnel"]["unique_venues_exported"], 200)
            self.assertEqual(qrep["price_status_counts"]["ok"], 194)
            self.assertEqual(qrep["price_status_counts"]["unknown_zero"], 5)
            self.assertEqual(qrep["price_status_counts"]["invalid_range"], 1)

            norm_rows = load_strict_json(os.path.join(out_dir, "restaurants_normalized.json"))
            self.assertEqual(sum(r["hours_intervals_count"] for r in norm_rows), 220)
            self.assertTrue(all(r["budget_eligible"] is False for r in norm_rows))


class TestStrictJSONAndSanitization(unittest.TestCase):
    def test_strict_json_replaces_nan_inf(self):
        data = {
            "name": "Test",
            "nan_val": float("nan"),
            "inf_val": float("inf"),
            "neg_inf_val": float("-inf"),
            "nested": [float("nan"), 123],
        }
        json_str = dumps_strict_json(data)
        loaded = json.loads(json_str, parse_constant=_raise_on_constant)
        self.assertEqual(loaded["nan_val"], "NaN")
        self.assertEqual(loaded["inf_val"], "Infinity")
        self.assertEqual(loaded["neg_inf_val"], "-Infinity")
        self.assertEqual(loaded["nested"], ["NaN", 123])


class TestMetricsFunnel(unittest.TestCase):
    def test_scripted_funnel_counts(self):
        # Section 10 Test 11:
        # Scripted run: 3 ok, 1 parse_error, 1 blocked, 1 duplicate_id, 1 transient_failed, cap-stop with 2 pending
        # Total requested: 9
        progress = {
            "u1": {"status": "ok", "http_status": 200},
            "u2": {"status": "ok", "http_status": 200},
            "u3": {"status": "ok", "http_status": 200},
            "u4": {"status": "parse_error", "http_status": 200},
            "u5": {"status": "blocked", "http_status": 429},
            "u6": {"status": "duplicate_id", "duplicate_of": "u1", "http_status": 200},
            "u7": {"status": "transient_failed", "http_status": 500},
            "u8": {"status": "pending"},
            "u9": {"status": "pending"},
        }
        requested = ["u1", "u2", "u3", "u4", "u5", "u6", "u7", "u8", "u9"]
        raw_rows = [{"foody_id": 1}, {"foody_id": 2}, {"foody_id": 3}]
        norm_rows = [{"foody_id": 1, "price_status": "ok", "hours_status": "day_mapping_unknown", "geo_status": "ok", "search_eligible": True, "location_eligible": True, "price_filter_eligible": True, "budget_eligible": False, "hours_eligible": False, "tour_eligible": False},
                     {"foody_id": 2, "price_status": "ok", "hours_status": "day_mapping_unknown", "geo_status": "ok", "search_eligible": True, "location_eligible": True, "price_filter_eligible": True, "budget_eligible": False, "hours_eligible": False, "tour_eligible": False},
                     {"foody_id": 3, "price_status": "ok", "hours_status": "day_mapping_unknown", "geo_status": "ok", "search_eligible": True, "location_eligible": True, "price_filter_eligible": True, "budget_eligible": False, "hours_eligible": False, "tour_eligible": False}]
        
        rep = build_quality_report(progress, requested, raw_rows, norm_rows, [], run_id="funnel-test", stopped_reason="limit reached")
        
        funnel = rep["funnel"]
        self.assertEqual(funnel["requested_urls"], 9)
        self.assertEqual(funnel["attempted"], 7)
        self.assertEqual(funnel["fetched_ok_http200"], 5)  # u1, u2, u3, u4, u6
        self.assertEqual(funnel["fetch_failed"], 1)         # u7
        self.assertEqual(funnel["blocked"], 1)              # u5
        self.assertEqual(funnel["parse_ok"], 3)             # u1, u2, u3
        self.assertEqual(funnel["parse_error"], 1)          # u4
        self.assertEqual(funnel["duplicate_id"], 1)         # u6
        self.assertEqual(funnel["pending_not_attempted"], 2)
        self.assertEqual(funnel["unique_venues_exported"], 3)
        self.assertTrue(rep["partial"])

        # Rates & explicit denominators
        rates = rep["rates"]
        self.assertEqual(rates["fetch_success"]["num"], 5)
        self.assertEqual(rates["fetch_success"]["den"], 7)
        self.assertEqual(rates["fetch_success"]["den_label"], "attempted")

        self.assertEqual(rates["parse_success"]["num"], 3)
        self.assertEqual(rates["parse_success"]["den"], 5)
        self.assertEqual(rates["parse_success"]["den_label"], "fetched_ok_http200")

        self.assertEqual(rates["extraction_success"]["num"], 3)
        self.assertEqual(rates["extraction_success"]["den"], 8)  # 9 - 1
        self.assertEqual(rates["extraction_success"]["den_label"], "requested_urls - duplicate_id")


class TestTolerantImport(unittest.TestCase):
    def test_corrupt_csv_cell_preserves_row_and_logs_issue(self):
        csv_text = (
            "foody_id,name,lat,lon,address,district,city,opening_hours_raw,price_min_vnd,price_max_vnd,source_url,fetched_at,price_semantics,source_license,field_freshness_unknown,source_flags,h1_names,parse_warnings\n"
            "1001,Quán Hỏng,21.0,105.8,Đường A,Quận B,Hà Nội,NOT_A_JSON,15000,30000,https://www.foody.vn/ha-noi/quan-hong,2026-10-14T00:00:00Z,venue,none,true,{},[],[]\n"
        )
        with tempfile.TemporaryDirectory() as tmp:
            bad_csv = Path(tmp) / "bad.csv"
            bad_csv.write_text(csv_text, encoding="utf-8")
            out_dir = Path(tmp) / "out"
            qrep = import_and_classify(str(bad_csv), str(out_dir))
            
            self.assertEqual(qrep["import"]["rows_read"], 1)
            self.assertEqual(qrep["import"]["rows_invalid"], 1)
            self.assertEqual(qrep["funnel"]["unique_venues_exported"], 1)

            issues = load_strict_json(out_dir / "issues.json")
            invalid_issue = [i for i in issues if i["issue_code"] == "import_row_invalid"]
            self.assertEqual(len(invalid_issue), 1)
            self.assertIn("NOT_A_JSON", invalid_issue[0]["detail"])

            raw_rows = load_strict_json(out_dir / "restaurants_raw.json")
            self.assertIn("import_original", raw_rows[0])
            self.assertEqual(raw_rows[0]["import_original"]["opening_hours_raw"], "NOT_A_JSON")


class TestCSVFormulaSafety(unittest.TestCase):
    def test_formulas_neutralized(self):
        records = [{
            "foody_id": 9999,
            "name": "=1+2",
            "lat": 21.0,
            "lon": 105.8,
            "address": "@SUM(A1)",
            "district": "-District",
            "city": "+Hà Nội",
            "opening_hours_raw": [],
            "price_min_vnd": 10000,
            "price_max_vnd": 20000,
            "source_url": "https://www.foody.vn/ha-noi/safe",
            "fetched_at": "2026-10-14T00:00:00Z",
            "price_semantics": "venue",
            "source_license": "none",
            "field_freshness_unknown": True,
            "source_flags": {},
            "h1_names": [],
            "parse_warnings": [],
        }]
        with tempfile.TemporaryDirectory() as tmp:
            export_quality(tmp, {}, records, [r["source_url"] for r in records], run_id="safe-test")
            with open(Path(tmp) / "restaurants_normalized.csv", encoding="utf-8") as f:
                content = f.read()
            self.assertIn("'=1+2", content)
            self.assertIn("'@SUM(A1)", content)
            self.assertIn("'-District", content)
            self.assertIn("'+Hà Nội", content)


class TestReviewGapsAndP1Fixes(unittest.TestCase):
    def test_export_all_guards_against_quality_exception_and_handles_nondict_flags(self):
        records = [{
            "foody_id": 1,
            "name": "Pho A",
            "lat": 21.02,
            "lon": 105.84,
            "address": "Address A",
            "district": "Ba Dinh",
            "city": "Ha Noi",
            "opening_hours_raw": [{"open": "07:00", "close": "21:00"}],
            "price_min_vnd": 30000,
            "price_max_vnd": 60000,
            "source_url": "https://www.foody.vn/ha-noi/pho-a",
            "fetched_at": "2026-10-14T00:00:00Z",
            "price_semantics": "venue",
            "source_license": "none",
            "field_freshness_unknown": True,
            "source_flags": ["list_flag_not_dict"],
            "h1_names": [],
            "parse_warnings": "single_string_warning",
        }]
        with tempfile.TemporaryDirectory() as tmp:
            report = export_all(tmp, {}, records, ["https://www.foody.vn/ha-noi/pho-a"], run_id="r1")
            # report.json must always exist even with unexpected data types
            self.assertTrue((Path(tmp) / "report.json").is_file())
            self.assertTrue((Path(tmp) / "restaurants.csv").is_file())
            self.assertIn("quality", report)

            # Check that string parse_warnings does not iterate per character into 21 issues
            issues = load_strict_json(Path(tmp) / "issues.json")
            pw_issues = [i for i in issues if i["issue_code"] == "parse_warning"]
            self.assertEqual(len(pw_issues), 1)
            self.assertEqual(pw_issues[0]["detail"], "single_string_warning")

    def test_foody_id_validation_and_non_int_rejection(self):
        prov = {"run_id": "t", "parser_version": "0.3.0"}
        for bad_id in (True, False, "5", 5.0, -10, None, "abc"):
            norm = normalize_record({"foody_id": bad_id, "name": "Venue", "lat": 21.0, "lon": 105.8}, prov)
            self.assertIsNone(norm["foody_id"], f"bad_id {bad_id!r} was not normalized to None")
            self.assertFalse(norm["search_eligible"], f"bad_id {bad_id!r} became search_eligible")

        good_norm = normalize_record({"foody_id": 42, "name": "Venue", "lat": 21.0, "lon": 105.8}, prov)
        self.assertEqual(good_norm["foody_id"], 42)
        self.assertTrue(good_norm["search_eligible"])

    def test_import_row_invalid_included_in_quality_report(self):
        # JSON import with missing foody_id
        with tempfile.TemporaryDirectory() as tmp:
            bad_json = Path(tmp) / "bad.json"
            bad_json.write_text(json.dumps([{"name": "No ID Venue"}]), encoding="utf-8")
            out_dir = Path(tmp) / "out"
            qrep = import_and_classify(str(bad_json), str(out_dir))

            # Must be reflected in quality report issue counts
            self.assertEqual(qrep["issue_counts_by_code"].get("import_row_invalid"), 1)
            self.assertGreaterEqual(qrep["issue_counts_by_severity"].get("error", 0), 1)
            self.assertEqual(qrep["funnel"]["attempted"], 0)

            # Order: import issues must be included in issues.json
            issues = load_strict_json(out_dir / "issues.json")
            self.assertTrue(any(i["issue_code"] == "import_row_invalid" for i in issues))

    def test_import_csv_extra_cells_preserved(self):
        header = list(FIELDS)
        row_vals = ["123", "Name", "21.0", "105.8", "Addr", "Dist", "Hanoi", "[]", "10000", "20000",
                    "https://www.foody.vn/ha-noi/test", "2026-10-14T00:00:00Z", "venue", "none", "true",
                    "{}", "[]", "[]", "extra_cell_1", "extra_cell_2"]
        with tempfile.TemporaryDirectory() as tmp:
            csv_path = Path(tmp) / "extra.csv"
            with open(csv_path, "w", encoding="utf-8", newline="") as f:
                w = csv.writer(f)
                w.writerow(header)
                w.writerow(row_vals)
            out_dir = Path(tmp) / "out"
            import_and_classify(str(csv_path), str(out_dir))
            raw_rows = load_strict_json(out_dir / "restaurants_raw.json")
            orig = raw_rows[0].get("import_original", {})
            self.assertIn("_extra_18", orig)
            self.assertEqual(orig["_extra_18"], "extra_cell_1")
            self.assertEqual(orig["_extra_19"], "extra_cell_2")

    def test_physical_csv_line_across_multiline_fields(self):
        records = [
            {
                "foody_id": 1,
                "name": "Line 1\nLine 2\nLine 3",
                "lat": 21.02,
                "lon": 105.84,
                "address": "Address 1",
                "district": "Ba Dinh",
                "city": "Ha Noi",
                "opening_hours_raw": [],
                "price_min_vnd": 30000,
                "price_max_vnd": 60000,
                "source_url": "https://www.foody.vn/ha-noi/r1",
                "fetched_at": "2026-10-14T00:00:00Z",
                "price_semantics": "venue",
                "source_license": "none",
                "field_freshness_unknown": True,
                "source_flags": {},
                "h1_names": [],
                "parse_warnings": [],
            },
            {
                "foody_id": 2,
                "name": "Venue 2",
                "lat": 21.03,
                "lon": 105.85,
                "address": "Address 2",
                "district": "Hoan Kiem",
                "city": "Ha Noi",
                "opening_hours_raw": [],
                "price_min_vnd": None,
                "price_max_vnd": None,  # triggers price_missing issue
                "source_url": "https://www.foody.vn/ha-noi/r2",
                "fetched_at": "2026-10-14T00:00:00Z",
                "price_semantics": "venue",
                "source_license": "none",
                "field_freshness_unknown": True,
                "source_flags": {},
                "h1_names": [],
                "parse_warnings": [],
            },
        ]
        with tempfile.TemporaryDirectory() as tmp:
            export_all(tmp, {}, records, [r["source_url"] for r in records], run_id="multiline-test")
            # Record 1 starts at line 2 and takes 3 physical lines (2, 3, 4).
            # Record 2 starts at physical line 5!
            issues = load_strict_json(Path(tmp) / "issues.json")
            r2_issues = [i for i in issues if i["foody_id"] == 2]
            self.assertTrue(len(r2_issues) > 0)
            for iss in r2_issues:
                self.assertEqual(iss["csv_line"], 5, f"Expected csv_line 5, got {iss['csv_line']}")
                self.assertTrue(iss["issue_id"].endswith(":L5"), f"Expected :L5 suffix, got {iss['issue_id']}")

    def test_corrupt_timestamp_does_not_corrupt_other_statuses(self):
        records = [{
            "foody_id": 10,
            "name": "Pho Ten",
            "lat": 21.02,
            "lon": 105.84,
            "address": "Address 10",
            "district": "Ba Dinh",
            "city": "Ha Noi",
            "opening_hours_raw": [{"open": "07:00", "close": "21:00"}],
            "price_min_vnd": 30000,
            "price_max_vnd": 60000,
            "source_url": "https://www.foody.vn/ha-noi/r10",
            "fetched_at": 123456,  # Corrupt non-string timestamp
            "price_semantics": "venue",
            "source_license": "none",
            "field_freshness_unknown": True,
            "source_flags": {},
            "h1_names": [],
            "parse_warnings": [],
        }]
        with tempfile.TemporaryDirectory() as tmp:
            export_quality(tmp, {}, records, ["https://www.foody.vn/ha-noi/r10"], run_id="ts-test")
            norm_rows = load_strict_json(Path(tmp) / "restaurants_normalized.json")
            self.assertEqual(norm_rows[0]["price_status"], "ok")
            self.assertEqual(norm_rows[0]["geo_status"], "ok")
            self.assertEqual(norm_rows[0]["hours_status"], "day_mapping_unknown")

    def test_offline_import_zero_network_claims(self):
        records = [{
            "foody_id": 1,
            "name": "Venue 1",
            "lat": 21.02,
            "lon": 105.84,
            "address": "Address 1",
            "district": "Ba Dinh",
            "city": "Ha Noi",
            "opening_hours_raw": [],
            "price_min_vnd": 30000,
            "price_max_vnd": 60000,
            "source_url": "https://www.foody.vn/ha-noi/v1",
            "fetched_at": "2026-10-14T00:00:00Z",
            "price_semantics": "venue",
            "source_license": "none",
            "field_freshness_unknown": True,
            "source_flags": {},
            "h1_names": [],
            "parse_warnings": [],
        }]
        with tempfile.TemporaryDirectory() as tmp:
            qrep = export_quality(tmp, {}, records, [], run_id="off-test", is_import=True)
            funnel = qrep["funnel"]
            self.assertEqual(funnel["attempted"], 0)
            self.assertEqual(funnel["fetched_ok_http200"], 0)
            self.assertEqual(funnel["parse_ok"], 0)
            self.assertIsNone(qrep["rates"]["fetch_success"]["rate"])

            raw_rows = load_strict_json(Path(tmp) / "restaurants_raw.json")
            prov = raw_rows[0]["provenance"]
            self.assertIsNone(prov["http_status"])
            self.assertIsNone(prov["hash_basis"])


if __name__ == "__main__":
    unittest.main()

