"""Unit tests for pure discovery module foody_tool.discovery."""
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from foody_tool.discovery import extract_restaurant_urls, discover_from_file

ROOT = Path(__file__).resolve().parent.parent
FIXTURES = ROOT / "tests" / "fixtures"
import unittest as _ut
if not (ROOT / "reference" / "sample5.json").exists():
    raise _ut.SkipTest("needs local reference/sample5.json (scraped sample, not part of the public repo)")
SAMPLE = json.loads((ROOT / "reference" / "sample5.json").read_text(encoding="utf-8"))


class TestExtractRestaurantUrls(unittest.TestCase):
    def test_basic_absolute_and_relative(self):
        html = """
        <html>
            <a href="https://www.foody.vn/ha-noi/pho-10-ly-quoc-su-to-hieu">Pho 10</a>
            <a href="/ha-noi/lang-thang-coffee">Lang Thang</a>
            <a href="thanh-van-banh-cuon-bun-thang">Thanh Van</a>
        </html>
        """
        urls = extract_restaurant_urls(html, "https://www.foody.vn/ha-noi/")
        self.assertEqual(urls, [
            "https://www.foody.vn/ha-noi/pho-10-ly-quoc-su-to-hieu",
            "https://www.foody.vn/ha-noi/lang-thang-coffee",
            "https://www.foody.vn/ha-noi/thanh-van-banh-cuon-bun-thang",
        ])

    def test_scheme_and_host_normalization(self):
        html = """
        <a href="http://www.foody.vn/ha-noi/pho-10-ly-quoc-su-to-hieu">HTTP link</a>
        <a href="https://WWW.FOODY.VN/HA-NOI/UPPERCASE-SLUG">Upper</a>
        """
        urls = extract_restaurant_urls(html, "https://www.foody.vn/ha-noi/")
        self.assertEqual(urls, [
            "https://www.foody.vn/ha-noi/pho-10-ly-quoc-su-to-hieu",
            "https://www.foody.vn/ha-noi/uppercase-slug",
        ])

    def test_stable_unique_deduplication(self):
        html = """
        <a href="/ha-noi/quan-a">First A</a>
        <a href="/ha-noi/quan-b">First B</a>
        <a href="/ha-noi/quan-a">Duplicate A</a>
        <a href="/ha-noi/quan-c">First C</a>
        <a href="/ha-noi/quan-b">Duplicate B</a>
        """
        urls = extract_restaurant_urls(html, "https://www.foody.vn/ha-noi/")
        self.assertEqual(urls, [
            "https://www.foody.vn/ha-noi/quan-a",
            "https://www.foody.vn/ha-noi/quan-b",
            "https://www.foody.vn/ha-noi/quan-c",
        ])

    def test_external_domain_exclusions(self):
        html = """
        <a href="https://shopeefood.vn/ha-noi/pho-10">ShopeeFood</a>
        <a href="https://facebook.com/foodyvn">Facebook</a>
        <a href="https://google.com">Google</a>
        <a href="https://m.foody.vn/ha-noi/pho-10">Mobile Foody subdomain</a>
        """
        urls = extract_restaurant_urls(html, "https://www.foody.vn/ha-noi/")
        self.assertEqual(urls, [])

    def test_non_hanoi_city_exclusions(self):
        html = """
        <a href="https://www.foody.vn/ho-chi-minh/quan-an-ngon">Saigon</a>
        <a href="https://www.foody.vn/da-nang/banh-trang-thit-heo">Da Nang</a>
        <a href="https://www.foody.vn/">Home</a>
        """
        urls = extract_restaurant_urls(html, "https://www.foody.vn/ha-noi/")
        self.assertEqual(urls, [])

    def test_subpath_exclusions_menu_review_photo(self):
        html = """
        <a href="/ha-noi/pho-10/thuc-don">Menu</a>
        <a href="/ha-noi/pho-10/binh-luan">Reviews</a>
        <a href="/ha-noi/pho-10/album-anh">Photos</a>
        <a href="/ha-noi/pho-10/video">Video</a>
        <a href="/ha-noi/pho-10/ban-do">Map</a>
        <a href="/ha-noi/food/bai-viet">Blog article</a>
        """
        urls = extract_restaurant_urls(html, "https://www.foody.vn/ha-noi/")
        self.assertEqual(urls, [])

    def test_system_and_listing_slug_exclusions(self):
        html = """
        <a href="/ha-noi/o-dau">O dau</a>
        <a href="/ha-noi/an-gi">An gi</a>
        <a href="/ha-noi/thuc-don">Thuc don</a>
        <a href="/ha-noi/binh-luan">Binh luan</a>
        <a href="/ha-noi/bo-suu-tap">Bo suu tap</a>
        <a href="/ha-noi/dia-diem">Dia diem</a>
        <a href="/ha-noi/coupon">Coupon</a>
        <a href="/ha-noi/khuyen-mai">Khuyen mai</a>
        <a href="/ha-noi/top-thanh-vien">Top thanh vien</a>
        <a href="/ha-noi/dang-nhap">Login</a>
        <a href="/ha-noi/dang-ky">Register</a>
        """
        urls = extract_restaurant_urls(html, "https://www.foody.vn/ha-noi/")
        self.assertEqual(urls, [])

    def test_taxonomy_and_category_prefix_exclusions(self):
        html = """
        <a href="/ha-noi/khu-vuc-quan-hoan-kiem">Hoan Kiem district</a>
        <a href="/ha-noi/khu-vuc-pho-co">Old quarter</a>
        <a href="/ha-noi/dia-diem-phuc-vu-vao-buoi-sang">Breakfast category</a>
        <a href="/ha-noi/quan-an-phuc-vu-mon-nuoc">Noodle soup category</a>
        <a href="/ha-noi/cafe-phu-hop-hen-ho">Dating cafe category</a>
        <a href="/ha-noi/quan-an-co-wifi">Wifi filter</a>
        <a href="/ha-noi/bo-suu-tap-hinh-anh">Image collection</a>
        <a href="/ha-noi/danh-sach-quan-ngon">List</a>
        <a href="/ha-noi/top-quan-cafe">Top cafe</a>
        """
        urls = extract_restaurant_urls(html, "https://www.foody.vn/ha-noi/")
        self.assertEqual(urls, [])

    def test_angular_placeholder_exclusions(self):
        html = """
        <a ng-href="{{item.Url}}" href="{{item.Url}}">Template link</a>
        <a href="/ha-noi/{{item.Slug}}">Template slug</a>
        <a href="/ha-noi/{{item.Id}}">Template id</a>
        """
        urls = extract_restaurant_urls(html, "https://www.foody.vn/ha-noi/")
        self.assertEqual(urls, [])

    def test_query_and_fragment_handling(self):
        html = """
        <a href="/ha-noi/quan-chuan?utm_source=foody&page=1">With query</a>
        <a href="/ha-noi/quan-chuan#tab-reviews">With fragment</a>
        """
        urls = extract_restaurant_urls(html, "https://www.foody.vn/ha-noi/")
        self.assertEqual(urls, [
            "https://www.foody.vn/ha-noi/quan-chuan"
        ])

    def test_malformed_input_graceful_handling(self):
        self.assertEqual(extract_restaurant_urls(None, "https://www.foody.vn/ha-noi/"), [])
        self.assertEqual(extract_restaurant_urls(12345, "https://www.foody.vn/ha-noi/"), [])
        self.assertEqual(extract_restaurant_urls("<broken << html href=", "https://www.foody.vn/ha-noi/"), [])
        self.assertEqual(extract_restaurant_urls("", ""), [])

    def test_malformed_port_url_handling(self):
        html = """
        <a href="https://www.foody.vn:badport/ha-noi/venue-bad-port">Bad port string</a>
        <a href="https://www.foody.vn:99999999999999999999/ha-noi/venue-overflow">Overflow port</a>
        <a href="https://www.foody.vn:-1/ha-noi/venue-negative">Negative port</a>
        <a href="https://www.foody.vn:8080/ha-noi/venue-nonstandard">Port 8080</a>
        <a href="https://www.foody.vn:443/ha-noi/venue-explicit-443">Explicit port 443</a>
        <a href="/ha-noi/venue-normal">Normal</a>
        """
        urls = extract_restaurant_urls(html, "https://www.foody.vn/ha-noi/")
        self.assertEqual(urls, [
            "https://www.foody.vn/ha-noi/venue-explicit-443",
            "https://www.foody.vn/ha-noi/venue-normal",
        ])

    def test_sample5_fixtures_self_link_extraction(self):
        for s in SAMPLE:
            fixture_file = FIXTURES / f"{s['key']}.html"
            if not fixture_file.exists():
                continue
            html = fixture_file.read_text(encoding="utf-8")
            urls = extract_restaurant_urls(html, s["source_url"])
            self.assertIn(s["source_url"], urls, f"Expected {s['source_url']} in extracted URLs for {s['key']}")

    def test_discover_from_file(self):
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", suffix=".html", delete=False) as f:
            f.write('<a href="/ha-noi/test-venue-123">Test</a>')
            temp_path = f.name
        try:
            urls = discover_from_file(temp_path)
            self.assertEqual(urls, ["https://www.foody.vn/ha-noi/test-venue-123"])
        finally:
            Path(temp_path).unlink(missing_ok=True)


if __name__ == "__main__":
    unittest.main()
