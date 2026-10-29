"""Tests for foody_tool.enrich_cache and CLI enrich subcommand."""
import csv
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from foody_tool.enrich_cache import enrich_job, cache_file_for_url
from foody_tool.exporter import ENRICHED_FIELDS
from foody_tool.enrich import FIELD_PRESENCE_KEYS, KNOWN_AMENITIES

SYNTHETIC_PAGE = """<!DOCTYPE html>
<html>
<body>
<div class="microsite-point-group">
    <div itemprop="aggregateRating" itemscope itemtype="http://schema.org/AggregateRating">
        <meta itemprop="bestRating" content="10">
        <div itemprop="ratingValue" class="microsite-point-avg">7.5</div>
        <div itemprop="reviewCount" class="microsite-review-count">10</div>
    </div>
    <div class="microsite-top-points">
        <div><span class="avg-txt-highlight">7.0</span></div>
        <div class="label">Chất lượng</div>
    </div>
    <div class="microsite-top-points">
        <div><span class="avg-txt-highlight">8.0</span></div>
        <div class="label">Vị trí</div>
    </div>
    <div class="microsite-top-points">
        <div><span class="avg-txt-highlight">7.5</span></div>
        <div class="label">Phục vụ</div>
    </div>
    <div class="microsite-top-points">
        <div><span class="avg-txt-highlight">7.0</span></div>
        <div class="label">Không gian</div>
    </div>
    <div class="microsite-top-points">
        <div><span class="avg-txt-highlight">8.0</span></div>
        <div class="label">Giá cả</div>
    </div>
</div>
<div class="new-detail-info-area">
    <div class="new-detail-info-label">Phong cách ẩm thực</div>
    <div><a href="/ha-noi/dia-diem-phong-cach-viet-nam">Món Việt</a></div>
</div>
<div class="new-detail-info-area">
    <div class="new-detail-info-label">Thể loại</div>
    <div><a href="/ha-noi/quan-an">Quán ăn</a></div>
</div>
<div class="new-detail-info-area">
    <div class="new-detail-info-label">Phục vụ các món</div>
    <div><a href="/ha-noi/dia-diem-phuc-vu-bun">Bún</a></div>
</div>
<div class="new-detail-info-area">
    <div class="new-detail-info-label">Thích hợp</div>
    <div><a href="/ha-noi/dia-diem-phuc-vu-buoi-sang">Buổi sáng</a></div>
</div>
<div class="new-detail-info-area">
    <div class="new-detail-info-label">Phù hợp với</div>
    <div><a href="/ha-noi/dia-diem-phu-hop-an-gia-dinh">Ăn gia đình</a></div>
</div>
<div class="new-detail-info-area">
    <div class="new-detail-info-label">Thời gian chuẩn bị</div>
    <div>Khoảng 5 - 10 phút</div>
</div>
<div class="new-detail-info-area">
    <div class="new-detail-info-label">Sức chứa</div>
    <div>30 người lớn</div>
</div>
<div class="new-detail-info-area">
    <div class="new-detail-info-label">Nghỉ lễ</div>
    <div>Không nghỉ lễ</div>
</div>
<div class="new-detail-info-area">
    <div class="new-detail-info-label">Giờ nhận khách cuối</div>
    <div>21:00</div>
</div>
<ul class="micro-property">
    <li>
        <img src="/style/images/catico/facilities/3/wifi.png" alt="Có wifi" />
        <a href="/ha-noi/dia-diem-co-wifi">Có wifi</a>
        <a class="resproperties-report" istrue="true" errorkeyname="Có wifi" href="javascript:void(0);"></a>
    </li>
</ul>
</body>
</html>
"""


class TestEnrichCache(unittest.TestCase):
    def test_enrich_job_offline_with_missing_cache(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            job_dir = Path(tmpdir)
            cache_dir = job_dir / "cache"
            cache_dir.mkdir()

            url1 = "https://www.foody.vn/ha-noi/quan-an-ngon-1"
            url2 = "https://www.foody.vn/ha-noi/quan-an-ngon-2"
            urls = [url1, url2]

            (job_dir / "urls.json").write_text(json.dumps(urls), encoding="utf-8")

            # Write cache file for url1 only
            c1_path = cache_file_for_url(str(cache_dir), url1)
            Path(c1_path).write_text(SYNTHETIC_PAGE, encoding="utf-8")

            # Legacy files
            legacy_restaurants = [
                {"foody_id": 101, "name": "Quán Ngon 1", "source_url": url1},
                {"foody_id": 102, "name": "Quán Ngon 2", "source_url": url2},
            ]
            rest_json = job_dir / "restaurants.json"
            rest_json.write_text(json.dumps(legacy_restaurants), encoding="utf-8")
            original_rest_content = rest_json.read_bytes()

            # Run enrich_job (offline by default)
            rep = enrich_job(str(job_dir), network=False)

            # Check network calls
            self.assertEqual(rep["network_requests"], 0)
            self.assertEqual(rep["pages_total"], 2)
            self.assertEqual(rep["pages_with_cache"], 1)
            self.assertEqual(rep["pages_parsed"], 1)
            self.assertEqual(rep["pages_failed"], 0)
            self.assertEqual(rep["needs_fetch"], [url2])

            # Check schema
            self.assertEqual(rep["schema"], "foody-enrichment-report/1")

            # Check field presence counts
            fpc = rep["field_presence_counts"]
            self.assertEqual(set(fpc.keys()), set(FIELD_PRESENCE_KEYS))
            for f in FIELD_PRESENCE_KEYS:
                # 1 page parsed -> sum of present, absent, ambiguous must equal 1
                total = fpc[f]["present"] + fpc[f]["absent"] + fpc[f]["ambiguous"]
                self.assertEqual(total, 1, f"Mismatch for field {f}")

            # Check amenity status counts
            asc = rep["amenity_status_counts"]
            self.assertEqual(set(asc.keys()), set(KNOWN_AMENITIES.keys()))
            for k in KNOWN_AMENITIES:
                total = asc[k]["yes"] + asc[k]["no"] + asc[k]["unknown"]
                self.assertEqual(total, 1, f"Mismatch for amenity {k}")
                self.assertEqual(asc[k]["no"], 0, f"Amenity {k} has non-zero 'no' count")
            self.assertEqual(asc["wifi"]["yes"], 1)

            # Check files created
            enriched_csv = job_dir / "restaurants_enriched.csv"
            enriched_json = job_dir / "restaurants_enriched.json"
            rep_json = job_dir / "enrichment_report.json"
            self.assertTrue(enriched_csv.is_file())
            self.assertTrue(enriched_json.is_file())
            self.assertTrue(rep_json.is_file())

            # Check CSV columns
            with open(enriched_csv, encoding="utf-8", newline="") as f:
                reader = csv.reader(f)
                header = next(reader)
                self.assertEqual(header, ENRICHED_FIELDS)
                rows = list(reader)
                self.assertEqual(len(rows), 1)
                row = dict(zip(header, rows[0]))
                self.assertEqual(row["foody_id"], "101")
                self.assertEqual(row["name"], "Quán Ngon 1")
                self.assertEqual(row["cuisine_styles"], "Món Việt")
                self.assertEqual(row["venue_types"], "Quán ăn")
                self.assertEqual(row["dish_groups"], "Bún")
                self.assertEqual(row["prep_time_min"], "5")
                self.assertEqual(row["prep_time_max"], "10")
                self.assertEqual(row["capacity_value"], "30")
                self.assertEqual(row["amenities_yes"], "Có wifi")
                self.assertEqual(row["amenities_no"], "")

            # Check JSON
            with open(enriched_json, encoding="utf-8") as f:
                ej = json.load(f)
                self.assertEqual(len(ej), 1)
                self.assertEqual(ej[0]["foody_id"], 101)
                self.assertEqual(ej[0]["rating_value"], 7.5)

            # Check legacy restaurants.json byte-identical
            self.assertEqual(rest_json.read_bytes(), original_rest_content)

    def test_cli_enrich_subcommand(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            job_dir = Path(tmpdir)
            cache_dir = job_dir / "cache"
            cache_dir.mkdir()

            url = "https://www.foody.vn/ha-noi/quan-an-ngon-1"
            (job_dir / "urls.json").write_text(json.dumps([url]), encoding="utf-8")
            c_path = cache_file_for_url(str(cache_dir), url)
            Path(c_path).write_text(SYNTHETIC_PAGE, encoding="utf-8")

            # Invoke via CLI subprocess
            cmd = [
                sys.executable,
                "-X",
                "utf8",
                "-m",
                "foody_tool",
                "enrich",
                "--job-dir",
                str(job_dir),
            ]
            res = subprocess.run(cmd, capture_output=True, text=True, check=True)
            output = json.loads(res.stdout.strip())
            self.assertEqual(output["pages_total"], 1)
            self.assertEqual(output["pages_parsed"], 1)
            self.assertEqual(output["network_requests"], 0)
            self.assertEqual(output["needs_fetch_count"], 0)

    def test_legacy_files_byte_identical_hash_check(self):
        import hashlib
        import shutil

        with tempfile.TemporaryDirectory() as tmpdir:
            job_dir = Path(tmpdir)
            cache_dir = job_dir / "cache"
            cache_dir.mkdir()

            url = "https://www.foody.vn/ha-noi/quan-an-ngon-1"
            (job_dir / "urls.json").write_text(json.dumps([url]), encoding="utf-8")
            c_path = cache_file_for_url(str(cache_dir), url)
            Path(c_path).write_text(SYNTHETIC_PAGE, encoding="utf-8")

            # Create synthetic legacy files
            legacy_files = {
                "restaurants.json": json.dumps([{"foody_id": 101, "name": "Quán Ngon 1", "source_url": url}], indent=2) + "\n",
                "restaurants.csv": "foody_id,name,source_url\n101,Quán Ngon 1," + url + "\n",
                "restaurants_raw.json": json.dumps([{"raw_id": 101}], indent=2) + "\n",
                "restaurants_normalized.json": json.dumps([{"norm_id": 101}], indent=2) + "\n",
                "restaurants_normalized.csv": "norm_id\n101\n",
                "quality_report.json": json.dumps({"quality_status": "ok"}, indent=2) + "\n",
                "report.json": json.dumps({"report_status": "complete"}, indent=2) + "\n",
            }
            for fname, content in legacy_files.items():
                (job_dir / fname).write_text(content, encoding="utf-8")

            # Hash all legacy files before enrich
            before_hashes = {}
            for fname in legacy_files:
                before_hashes[fname] = hashlib.sha256((job_dir / fname).read_bytes()).hexdigest()

            # Run enrich_job
            enrich_job(str(job_dir), network=False)

            # Hash all legacy files after enrich and verify byte-identical
            for fname in legacy_files:
                after_hash = hashlib.sha256((job_dir / fname).read_bytes()).hexdigest()
                self.assertEqual(
                    before_hashes[fname],
                    after_hash,
                    f"Legacy file {fname} was modified by enrich_job!",
                )

        # Check real job directory if available
        real_job = Path(os.environ.get("FOODY_REAL_JOB", "")) if os.environ.get("FOODY_REAL_JOB") else Path("__no_real_job__")
        if real_job.is_dir():
            with tempfile.TemporaryDirectory() as tmpdir:
                copy_job = Path(tmpdir) / "job_copy"
                shutil.copytree(real_job, copy_job)

                checked_files = [
                    "restaurants.csv",
                    "restaurants.json",
                    "restaurants_raw.json",
                    "restaurants_normalized.csv",
                    "restaurants_normalized.json",
                    "quality_report.json",
                    "report.json",
                ]
                real_before_hashes = {}
                for cf in checked_files:
                    p = copy_job / cf
                    if p.is_file():
                        real_before_hashes[cf] = hashlib.sha256(p.read_bytes()).hexdigest()

                enrich_job(str(copy_job), network=False)

                for cf, expected_hash in real_before_hashes.items():
                    actual_hash = hashlib.sha256((copy_job / cf).read_bytes()).hexdigest()
                    self.assertEqual(
                        expected_hash,
                        actual_hash,
                        f"Real job legacy file {cf} changed after enrich_job!",
                    )

    def test_fetch_missing_network_interval_and_block_stop(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            job_dir = Path(tmpdir)
            cache_dir = job_dir / "cache"
            cache_dir.mkdir()

            u1 = "https://www.foody.vn/ha-noi/test-1"
            u2 = "https://www.foody.vn/ha-noi/test-2"
            u3 = "https://www.foody.vn/ha-noi/test-3"
            urls = [u1, u2, u3]
            (job_dir / "urls.json").write_text(json.dumps(urls), encoding="utf-8")

            # Mock Collector that enforces interval and returns blocked on u2
            class MockCollector:
                def __init__(self, out_dir, min_interval=2.0):
                    assert min_interval >= 2.0, "min_interval must be >= 2.0"
                    self.out_dir = out_dir
                    self.min_interval = min_interval
                    self.request_count = 0

                def process(self, url):
                    self.request_count += 1
                    if url == u1:
                        c_path = cache_file_for_url(str(cache_dir), url)
                        Path(c_path).write_text(SYNTHETIC_PAGE, encoding="utf-8")
                        return "ok"
                    elif url == u2:
                        return "blocked"
                    return "ok"

            rep = enrich_job(str(job_dir), network=True, collector_factory=MockCollector)
            self.assertEqual(rep["network_requests"], 2)
            # u1 succeeded, u2 blocked, u3 never attempted because u2 blocked
            self.assertEqual(rep["pages_parsed"], 1)
            self.assertEqual(rep["needs_fetch"], [u2, u3])

    def test_gray_amenity_enrich_cache_counts_and_empty_amenities_no(self):
        """Regression test for Task C: cache enrichment correctly tallies gray amenities
        under 'unknown' with 'no' staying 0, and exports amenities_no as empty string."""
        html_with_gray = """<!DOCTYPE html>
        <html><body>
        <div class="new-detail-info-area">
            <div class="new-detail-info-label">Thể loại</div><div><a href="/ha-noi/quan-an">Quán ăn</a></div>
        </div>
        <ul class="micro-property">
            <li>
                <img src="/style/images/catico/facilities/3/wifi.png" alt="Có wifi" />
                <a class="resproperties-report" istrue="true" errorkeyname="Có wifi" href="javascript:void(0);"></a>
            </li>
            <li class="none">
                <img src="/style/images/catico/facilities/2/giaohang.png" alt="Có giao hàng" />
                <span style="color:#aaa;">Có giao hàng</span>
                <a class="resproperties-report" istrue="false" errorkeyname="Có giao hàng" href="javascript:void(0);"></a>
            </li>
        </ul>
        </body></html>
        """
        with tempfile.TemporaryDirectory() as tmpdir:
            job_dir = Path(tmpdir)
            cache_dir = job_dir / "cache"
            cache_dir.mkdir()

            url = "https://www.foody.vn/ha-noi/quan-gray-amenity"
            (job_dir / "urls.json").write_text(json.dumps([url]), encoding="utf-8")
            c_path = cache_file_for_url(str(cache_dir), url)
            Path(c_path).write_text(html_with_gray, encoding="utf-8")

            rep = enrich_job(str(job_dir), network=False)
            asc = rep["amenity_status_counts"]

            # wifi is yes, no is 0
            self.assertEqual(asc["wifi"]["yes"], 1)
            self.assertEqual(asc["wifi"]["no"], 0)
            self.assertEqual(asc["wifi"]["unknown"], 0)

            # giaohang is gray unconfirmed -> unknown is 1, no is 0!
            self.assertEqual(asc["giaohang"]["yes"], 0)
            self.assertEqual(asc["giaohang"]["no"], 0)
            self.assertEqual(asc["giaohang"]["unknown"], 1)

            # absent amenity (e.g. maylanh) -> unknown is 1, no is 0
            self.assertEqual(asc["maylanh"]["yes"], 0)
            self.assertEqual(asc["maylanh"]["no"], 0)
            self.assertEqual(asc["maylanh"]["unknown"], 1)

            # verify ALL amenities have no == 0
            for k in KNOWN_AMENITIES:
                self.assertEqual(asc[k]["no"], 0, f"Amenity {k} has non-zero 'no' count")

            # verify restaurants_enriched.csv has empty amenities_no
            with open(job_dir / "restaurants_enriched.csv", encoding="utf-8", newline="") as f:
                reader = csv.DictReader(f)
                row = next(reader)
                self.assertEqual(row["amenities_yes"], "Có wifi")
                self.assertEqual(row["amenities_no"], "")
                self.assertIn("Có giao hàng", row["amenities_unknown"])

            # verify restaurants_enriched.json has empty amenities_no
            with open(job_dir / "restaurants_enriched.json", encoding="utf-8") as f:
                ej = json.load(f)
                self.assertEqual(ej[0]["amenities_no"], "")
                self.assertIn("Có giao hàng", ej[0]["amenities_unknown"])

    def test_price_edge_cases_merged(self):
        """Verify price classification in merged enriched record:
        - missing price: price_status='missing', norm null, raw null
        - zero-zero price: price_status='unknown_zero', norm null, raw kept (zero is not free)
        - reversed range: price_status='invalid_range', norm null, raw kept (not swapped)
        - nonfinite: price_status='nonfinite', norm null
        """
        cases = [
            # 1. missing price
            {
                "url": "https://www.foody.vn/ha-noi/missing-price",
                "initData": {"RestaurantID": 501, "Name": "Missing Price"},
                "expected": {
                    "price_status": "missing",
                    "price_min_raw": None,
                    "price_max_raw": None,
                    "price_min_vnd_norm": None,
                    "price_max_vnd_norm": None,
                }
            },
            # 2. zero-zero price
            {
                "url": "https://www.foody.vn/ha-noi/zero-zero-price",
                "initData": {"RestaurantID": 502, "Name": "Zero Zero Price", "PriceMin": 0, "PriceMax": 0},
                "expected": {
                    "price_status": "unknown_zero",
                    "price_min_raw": 0,
                    "price_max_raw": 0,
                    "price_min_vnd_norm": None,
                    "price_max_vnd_norm": None,
                }
            },
            # 3. reversed range (min > max, not swapped!)
            {
                "url": "https://www.foody.vn/ha-noi/reversed-range",
                "initData": {"RestaurantID": 503, "Name": "Reversed Range", "PriceMin": 60000, "PriceMax": 30000},
                "expected": {
                    "price_status": "invalid_range",
                    "price_min_raw": 60000,
                    "price_max_raw": 30000,
                    "price_min_vnd_norm": None,
                    "price_max_vnd_norm": None,
                }
            },
            # 4. nonfinite
            {
                "url": "https://www.foody.vn/ha-noi/nonfinite-price",
                "initData": {"RestaurantID": 504, "Name": "Nonfinite Price", "PriceMin": "invalid_number", "PriceMax": 50000},
                "expected": {
                    "price_status": "nonfinite",
                    "price_min_raw": None,
                    "price_max_raw": 50000,
                    "price_min_vnd_norm": None,
                    "price_max_vnd_norm": None,
                }
            },
        ]
        with tempfile.TemporaryDirectory() as tmpdir:
            job_dir = Path(tmpdir)
            cache_dir = job_dir / "cache"
            cache_dir.mkdir()
            urls = [c["url"] for c in cases]
            (job_dir / "urls.json").write_text(json.dumps(urls), encoding="utf-8")
            for c in cases:
                c_path = cache_file_for_url(str(cache_dir), c["url"])
                html = f"<html><body><script>var initData = {json.dumps(c['initData'])};</script>{SYNTHETIC_PAGE}</body></html>"
                Path(c_path).write_text(html, encoding="utf-8")

            enrich_job(str(job_dir), network=False)

            with open(job_dir / "restaurants_enriched.json", encoding="utf-8") as f:
                records = json.load(f)
            self.assertEqual(len(records), len(cases))
            for c, rec in zip(cases, records):
                for k, v in c["expected"].items():
                    self.assertEqual(rec.get(k), v, f"Mismatch for {c['url']} on {k}")

    def test_hours_edge_cases_merged(self):
        """Verify hours classification in merged enriched record:
        - absent hours: hours_status='missing', hours_displayed is None, count 0
        - malformed hours: invalid clock format -> hours_status='malformed'
        - multiple intervals: e.g. 2 shifts -> hours_displayed has |, count 2, status day_mapping_unknown
        """
        cases = [
            # 1. absent hours
            {
                "url": "https://www.foody.vn/ha-noi/absent-hours",
                "initData": {"RestaurantID": 601, "Name": "Absent Hours", "OpeningTime": []},
                "expected": {
                    "hours_status": "missing",
                    "hours_displayed": None,
                    "hours_intervals_count": 0,
                }
            },
            # 2. malformed hours
            {
                "url": "https://www.foody.vn/ha-noi/malformed-hours",
                "initData": {"RestaurantID": 602, "Name": "Malformed Hours", "OpeningTime": [{"TimeOpen": {"Hours": 25, "Minutes": 99}, "TimeClose": {"Hours": 26, "Minutes": 0}}]},
                "expected": {
                    "hours_status": "malformed",
                }
            },
            # 3. multiple intervals
            {
                "url": "https://www.foody.vn/ha-noi/multiple-intervals",
                "initData": {
                    "RestaurantID": 603,
                    "Name": "Multiple Intervals",
                    "OpeningTime": [
                        {"DayOfWeek": 2, "TimeOpen": {"Hours": 9, "Minutes": 0}, "TimeClose": {"Hours": 13, "Minutes": 0}},
                        {"DayOfWeek": 2, "TimeOpen": {"Hours": 17, "Minutes": 0}, "TimeClose": {"Hours": 22, "Minutes": 0}},
                    ]
                },
                "expected": {
                    "hours_status": "day_mapping_unknown",
                    "hours_displayed": "09:00 - 13:00 | 17:00 - 22:00",
                    "hours_intervals_count": 2,
                    "hours_day_codes_raw": [2],
                }
            },
        ]
        with tempfile.TemporaryDirectory() as tmpdir:
            job_dir = Path(tmpdir)
            cache_dir = job_dir / "cache"
            cache_dir.mkdir()
            urls = [c["url"] for c in cases]
            (job_dir / "urls.json").write_text(json.dumps(urls), encoding="utf-8")
            for c in cases:
                c_path = cache_file_for_url(str(cache_dir), c["url"])
                html = f"<html><body><script>var initData = {json.dumps(c['initData'])};</script>{SYNTHETIC_PAGE}</body></html>"
                Path(c_path).write_text(html, encoding="utf-8")

            enrich_job(str(job_dir), network=False)

            with open(job_dir / "restaurants_enriched.json", encoding="utf-8") as f:
                records = json.load(f)
            self.assertEqual(len(records), len(cases))
            for c, rec in zip(cases, records):
                for k, v in c["expected"].items():
                    self.assertEqual(rec.get(k), v, f"Mismatch for {c['url']} on {k}")

    def test_historical_job_without_enrichment_then_enrich(self):
        """Historical job without any enriched files: enrich_job creates merged files
        with all 43 columns, correct schema marker and columns list, without altering legacy files.
        """
        import hashlib
        with tempfile.TemporaryDirectory() as tmpdir:
            job_dir = Path(tmpdir)
            cache_dir = job_dir / "cache"
            cache_dir.mkdir()

            url = "https://www.foody.vn/ha-noi/historical-restaurant"
            (job_dir / "urls.json").write_text(json.dumps([url]), encoding="utf-8")
            init_data = {
                "RestaurantID": 701,
                "Name": "Historical Restaurant",
                "Address": "123 Phố Cổ",
                "District": "Quận Hoàn Kiếm",
                "City": "Hà Nội",
                "PriceMin": 30000,
                "PriceMax": 70000,
                "OpeningTime": [{"TimeOpen": {"Hours": 8, "Minutes": 0}, "TimeClose": {"Hours": 22, "Minutes": 0}}]
            }
            c_path = cache_file_for_url(str(cache_dir), url)
            Path(c_path).write_text(f"<html><body><script>var initData = {json.dumps(init_data)};</script>{SYNTHETIC_PAGE}</body></html>", encoding="utf-8")

            legacy_json = json.dumps([{"foody_id": 701, "name": "Historical Restaurant", "source_url": url}], indent=2) + "\n"
            legacy_csv = f"foody_id,name,source_url\n701,Historical Restaurant,{url}\n"
            (job_dir / "restaurants.json").write_text(legacy_json, encoding="utf-8")
            (job_dir / "restaurants.csv").write_text(legacy_csv, encoding="utf-8")

            h_json_before = hashlib.sha256((job_dir / "restaurants.json").read_bytes()).hexdigest()
            h_csv_before = hashlib.sha256((job_dir / "restaurants.csv").read_bytes()).hexdigest()

            # Ensure enriched files do not exist initially
            self.assertFalse((job_dir / "restaurants_enriched.csv").exists())
            self.assertFalse((job_dir / "restaurants_enriched.json").exists())
            self.assertFalse((job_dir / "enrichment_report.json").exists())

            rep = enrich_job(str(job_dir), network=False)

            # Files created
            self.assertTrue((job_dir / "restaurants_enriched.csv").exists())
            self.assertTrue((job_dir / "restaurants_enriched.json").exists())
            self.assertTrue((job_dir / "enrichment_report.json").exists())

            # Schema marker and columns list in enrichment_report.json
            with open(job_dir / "enrichment_report.json", encoding="utf-8") as f:
                report_data = json.load(f)
            self.assertEqual(report_data.get("schema_version"), "foody-enriched-export/2")
            self.assertEqual(report_data.get("columns"), list(ENRICHED_FIELDS))

            # Legacy hash invariance
            self.assertEqual(hashlib.sha256((job_dir / "restaurants.json").read_bytes()).hexdigest(), h_json_before)
            self.assertEqual(hashlib.sha256((job_dir / "restaurants.csv").read_bytes()).hexdigest(), h_csv_before)

    def test_re_enrich_of_old_format_enriched_files_atomic_and_idempotent(self):
        """Re-running enrich on a job that already has old 25-column enriched files
        overwrites them atomically with 43 columns, and repeating enrich is idempotent.
        """
        import hashlib
        with tempfile.TemporaryDirectory() as tmpdir:
            job_dir = Path(tmpdir)
            cache_dir = job_dir / "cache"
            cache_dir.mkdir()

            url = "https://www.foody.vn/ha-noi/re-enrich-restaurant"
            (job_dir / "urls.json").write_text(json.dumps([url]), encoding="utf-8")
            init_data = {
                "RestaurantID": 801,
                "Name": "Re-enrich Restaurant",
                "Address": "456 Phố Huế",
                "District": "Quận Hai Bà Trưng",
                "City": "Hà Nội",
                "PriceMin": 40000,
                "PriceMax": 80000,
                "OpeningTime": [{"TimeOpen": {"Hours": 7, "Minutes": 0}, "TimeClose": {"Hours": 21, "Minutes": 0}}]
            }
            c_path = cache_file_for_url(str(cache_dir), url)
            Path(c_path).write_text(f"<html><body><script>var initData = {json.dumps(init_data)};</script>{SYNTHETIC_PAGE}</body></html>", encoding="utf-8")

            # Seed with old 25-column enriched files
            old_25_cols = list(ENRICHED_FIELDS)[:25]
            (job_dir / "restaurants_enriched.csv").write_text(",".join(old_25_cols) + "\n801,Re-enrich Restaurant\n", encoding="utf-8")
            (job_dir / "restaurants_enriched.json").write_text(json.dumps([{"foody_id": 801, "name": "Re-enrich Restaurant"}]), encoding="utf-8")
            (job_dir / "enrichment_report.json").write_text(json.dumps({"schema": "foody-enrichment-report/1"}), encoding="utf-8")

            # First run: overwrites old 25-column files
            rep1 = enrich_job(str(job_dir), network=False)
            with open(job_dir / "restaurants_enriched.csv", encoding="utf-8", newline="") as f:
                reader = csv.reader(f)
                header1 = next(reader)
            self.assertEqual(len(header1), 43)
            self.assertEqual(header1, list(ENRICHED_FIELDS))

            h_csv1 = hashlib.sha256((job_dir / "restaurants_enriched.csv").read_bytes()).hexdigest()
            h_json1 = hashlib.sha256((job_dir / "restaurants_enriched.json").read_bytes()).hexdigest()

            # Second run: idempotent
            rep2 = enrich_job(str(job_dir), network=False)
            h_csv2 = hashlib.sha256((job_dir / "restaurants_enriched.csv").read_bytes()).hexdigest()
            h_json2 = hashlib.sha256((job_dir / "restaurants_enriched.json").read_bytes()).hexdigest()

            self.assertEqual(h_csv1, h_csv2)
            self.assertEqual(h_json1, h_json2)

    def test_live_path_record_merge(self):
        """Live collection path: record_to_enriched_row accurately merges a record
        carrying normalized/legacy fields plus enrichment dict.
        """
        from foody_tool.exporter import record_to_enriched_row
        from foody_tool.enrich import parse_enrichment

        rec = {
            "foody_id": 901,
            "name": "Live Path Restaurant",
            "address": "789 Phố Bà Triệu",
            "district": "Quận Hai Bà Trưng",
            "city": "Hà Nội",
            "lat": 21.0123,
            "lon": 105.8456,
            "geo_status": "ok",
            "price_min_raw": 25000,
            "price_max_raw": 50000,
            "price_status": "ok",
            "price_min_vnd_norm": 25000,
            "price_max_vnd_norm": 50000,
            "price_semantics": "venue price range, not individual dish or per-person guaranteed budget",
            "opening_hours_raw": [{"day_of_week_raw": 1, "open": "08:00", "close": "20:00"}],
            "hours_displayed": "08:00 - 20:00",
            "hours_status": "day_mapping_unknown",
            "hours_intervals_count": 1,
            "hours_day_codes_raw": [1],
            "fetched_at": "2026-10-15T02:00:00Z",
            "source_url": "https://www.foody.vn/ha-noi/live-path-restaurant",
            "enrichment": parse_enrichment(SYNTHETIC_PAGE),
        }

        row = record_to_enriched_row(rec)
        self.assertEqual(list(row.keys()), list(ENRICHED_FIELDS))
        self.assertEqual(len(row), 43)
        self.assertEqual(row["foody_id"], 901)
        self.assertEqual(row["address"], "789 Phố Bà Triệu")
        self.assertEqual(row["district"], "Quận Hai Bà Trưng")
        self.assertEqual(row["city"], "Hà Nội")
        self.assertEqual(row["lat"], 21.0123)
        self.assertEqual(row["lon"], 105.8456)
        self.assertEqual(row["geo_status"], "ok")
        self.assertEqual(row["price_status"], "ok")
        self.assertEqual(row["price_min_vnd_norm"], 25000)
        self.assertEqual(row["hours_displayed"], "08:00 - 20:00")
        self.assertEqual(row["cuisine_styles"], "Món Việt")
        self.assertEqual(row["venue_types"], "Quán ăn")

    def test_csv_and_json_column_equality(self):
        """CSV and JSON exports must have matching 43 columns in the exact same order as ENRICHED_FIELDS.
        In JSON, opening_hours_raw and hours_day_codes_raw are lists; in CSV they are JSON strings.
        Spreadsheet formula neutralization is verified.
        """
        from foody_tool.exporter import export_enriched_csv, export_enriched_json

        with tempfile.TemporaryDirectory() as tmpdir:
            csv_path = Path(tmpdir) / "test_enriched.csv"
            json_path = Path(tmpdir) / "test_enriched.json"

            sample_record = {
                "foody_id": 999,
                "name": "=HYPERLINK(\"malicious.com\")",
                "cuisine_styles": "Món Việt",
                "venue_types": "Quán ăn",
                "dish_groups": "Bún",
                "suitable_meals": "Buổi sáng",
                "audiences": "Gia đình",
                "prep_time_raw": "Khoảng 5 - 10 phút",
                "prep_time_min": 5,
                "prep_time_max": 10,
                "capacity_raw": "30 người",
                "capacity_value": 30,
                "holiday_raw": "Không nghỉ lễ",
                "rating_value": 7.5,
                "rating_scale_max": 10,
                "review_count": 10,
                "rating_quality": 7.0,
                "rating_location": 8.0,
                "rating_service": 7.5,
                "rating_space": 7.0,
                "rating_price": 8.0,
                "amenities_yes": "Có wifi",
                "amenities_no": "",
                "amenities_unknown": "",
                "source_url": "https://www.foody.vn/ha-noi/test-equality",
                "address": "123 Tràng Tiền",
                "district": "Quận Hoàn Kiếm",
                "city": "Hà Nội",
                "lat": 21.02,
                "lon": 105.85,
                "geo_status": "ok",
                "price_min_raw": 30000,
                "price_max_raw": 50000,
                "price_status": "ok",
                "price_min_vnd_norm": 30000,
                "price_max_vnd_norm": 50000,
                "price_semantics": "venue price range, not individual dish or per-person guaranteed budget",
                "opening_hours_raw": [{"day_of_week_raw": 2, "open": "08:00", "close": "22:00"}],
                "hours_displayed": "08:00 - 22:00",
                "hours_status": "day_mapping_unknown",
                "hours_intervals_count": 1,
                "hours_day_codes_raw": [2],
                "fetched_at": "2026-10-15T00:00:00Z",
            }

            export_enriched_csv([sample_record], str(csv_path))
            export_enriched_json([sample_record], str(json_path))

            # CSV verification
            with open(csv_path, encoding="utf-8", newline="") as f:
                reader = csv.reader(f)
                csv_header = next(reader)
                csv_row = next(reader)

            self.assertEqual(csv_header, list(ENRICHED_FIELDS))
            self.assertEqual(len(csv_header), 43)

            # Formula neutralization in CSV
            name_idx = csv_header.index("name")
            self.assertTrue(csv_row[name_idx].startswith("'"), "Formula was not neutralized!")

            # JSON columns in CSV are strings
            oh_idx = csv_header.index("opening_hours_raw")
            hd_idx = csv_header.index("hours_day_codes_raw")
            self.assertIsInstance(json.loads(csv_row[oh_idx]), list)
            self.assertIsInstance(json.loads(csv_row[hd_idx]), list)

            # JSON verification
            with open(json_path, encoding="utf-8") as f:
                json_data = json.load(f)

            json_rec = json_data[0]
            self.assertEqual(list(json_rec.keys()), list(ENRICHED_FIELDS))
            self.assertEqual(len(json_rec), 43)
            self.assertIsInstance(json_rec["opening_hours_raw"], list)
            self.assertIsInstance(json_rec["hours_day_codes_raw"], list)


if __name__ == "__main__":
    unittest.main()

