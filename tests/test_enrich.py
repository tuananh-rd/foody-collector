"""Tests for foody_tool.enrich (pure enrichment parser)."""
import os
import unittest

from foody_tool.enrich import (
    parse_enrichment,
    SCHEMA_VERSION,
    PARSER_VERSION,
    FIELD_PRESENCE_KEYS,
    KNOWN_AMENITIES,
)

SYNTHETIC_FULL_HTML = """<!DOCTYPE html>
<html>
<head><title>Test Restaurant</title></head>
<body>
<div class="microsite-point-group">
    <div itemprop="aggregateRating" itemscope itemtype="http://schema.org/AggregateRating">
        <meta itemprop="bestRating" content="10">
        <div itemprop="ratingValue" class="microsite-point-avg">8.5</div>
        <div itemprop="reviewCount" class="microsite-review-count">42</div>
    </div>
    <div class="microsite-top-points">
        <div><span class="avg-txt-highlight">8.8</span></div>
        <div class="label">Chất lượng</div>
    </div>
    <div class="microsite-top-points">
        <div><span class="avg-txt-highlight">8.2</span></div>
        <div class="label">Vị tr&#237;</div>
    </div>
    <div class="microsite-top-points">
        <div><span class="avg-txt-highlight">8.0</span></div>
        <div class="label">Phục vụ</div>
    </div>
    <div class="microsite-top-points">
        <div><span class="avg-txt-highlight">8.5</span></div>
        <div class="label">Kh&#244;ng gian</div>
    </div>
    <div class="microsite-top-points">
        <div><span class="avg-txt-highlight">7.9</span></div>
        <div class="label">Gi&#225; cả</div>
    </div>
</div>

<div class="new-detail-info-area">
    <div class="new-detail-info-label">Phong c&#225;ch ẩm thực</div>
    <div>
        <a href="/ha-noi/dia-diem-phong-cach-viet-nam" title="M&#243;n Việt">M&#243;n Việt</a>,
        <a href="/ha-noi/dia-diem-phong-cach-chau-a">M&#243;n &#193;</a>
        <span class="report-data-error">
            <a class="resinfo-report" href="javascript:void(0);"><span class="fa fa-pencil"></span></a>
        </span>
    </div>
</div>

<div class="new-detail-info-area">
    <div class="new-detail-info-label">Thể loại</div>
    <div>
        <a href="/ha-noi/nha-hang">Nh&#224; h&#224;ng</a>
        <span class="report-data-error">
            <a class="resinfo-report" href="javascript:void(0);"><span class="fa fa-pencil"></span></a>
        </span>
    </div>
</div>

<div class="new-detail-info-area">
    <div class="new-detail-info-label">Phục vụ c&#225;c m&#243;n</div>
    <div>
        <a href="/ha-noi/dia-diem-phuc-vu-thit-ga">Thịt G&#224;</a>,
        <a href="/ha-noi/dia-diem-phuc-vu-com">Cơm</a>
        <span class="report-data-error">
            <a class="resinfo-report" href="javascript:void(0);"><span class="fa fa-pencil"></span></a>
        </span>
    </div>
</div>

<div class="new-detail-info-area">
    <div class="new-detail-info-label">Th&#237;ch hợp</div>
    <div>
        <a href="/ha-noi/dia-diem-phuc-vu-buoi-trua">Buổi trưa</a>
        <span class="report-data-error">
            <a class="resinfo-report" href="javascript:void(0);"><span class="fa fa-pencil"></span></a>
        </span>
    </div>
</div>

<div class="new-detail-info-area">
    <div class="new-detail-info-label">Ph&#249; hợp với</div>
    <div>
        <a href="/ha-noi/dia-diem-phu-hop-an-gia-dinh">Ăn gia đ&#236;nh</a>
        <span class="report-data-error">
            <a class="resinfo-report" href="javascript:void(0);"><span class="fa fa-pencil"></span></a>
        </span>
    </div>
</div>

<div class="new-detail-info-area">
    <div class="new-detail-info-label">Giờ nhận kh&#225;ch cuối</div>
    <div>
        21:30
        <span class="report-data-error">
            <a class="resinfo-report" href="javascript:void(0);"><span class="fa fa-pencil"></span></a>
        </span>
    </div>
</div>

<div class="new-detail-info-area">
    <div class="new-detail-info-label">Thời gian chuẩn bị</div>
    <div>
        Khoảng 5 - 10 ph&#250;t
        <span class="report-data-error">
            <a class="resinfo-report" href="javascript:void(0);"><span class="fa fa-pencil"></span></a>
        </span>
    </div>
</div>

<div class="new-detail-info-area">
    <div class="new-detail-info-label">Sức chứa</div>
    <div>
        50 người lớn
        <span class="report-data-error">
            <a class="resinfo-report" href="javascript:void(0);"><span class="fa fa-pencil"></span></a>
        </span>
    </div>
</div>

<div class="new-detail-info-area">
    <div class="new-detail-info-label">Nghỉ lễ</div>
    <div>
        C&#225;c ng&#224;y lễ trong năm
        <span class="report-data-error">
            <a class="resinfo-report" href="javascript:void(0);"><span class="fa fa-pencil"></span></a>
        </span>
    </div>
</div>

<ul class="micro-property">
    <li>
        <img src="/style/images/catico/facilities/3/wifi.png" alt="C&#243; wifi" />
        <a href="/ha-noi/dia-diem-co-wifi">C&#243; wifi</a>
        <a class="resproperties-report" istrue="true" errorkeyname="C&#243; wifi" href="javascript:void(0);"></a>
    </li>
    <li class="none">
        <img src="/style/images/catico/facilities/2/giaohang.png" alt="C&#243; giao h&#224;ng" />
        <span style="color:#aaa;">C&#243; giao h&#224;ng</span>
        <a class="resproperties-report" istrue="false" errorkeyname="C&#243; giao h&#224;ng" href="javascript:void(0);"></a>
    </li>
</ul>

<script>
var initData = {
    "RestaurantID": 12345,
    "Wifi": {"Name": "SecretSSID", "Password": "SuperSecretPassword123"}
};
</script>
</body>
</html>
"""

REAL_CACHE_DIR = os.environ.get("FOODY_REAL_JOB_CACHE", "")  # optional local job cache; tests skip when unset


class TestEnrich(unittest.TestCase):
    def test_full_synthetic_enrichment(self):
        res = parse_enrichment(SYNTHETIC_FULL_HTML, parsed_from="cached_html")
        self.assertEqual(res["schema"], SCHEMA_VERSION)
        self.assertEqual(res["parsed_from"], "cached_html")

        # Links
        self.assertEqual(
            res["cuisine_styles"],
            [
                {"text": "Món Việt", "href": "/ha-noi/dia-diem-phong-cach-viet-nam"},
                {"text": "Món Á", "href": "/ha-noi/dia-diem-phong-cach-chau-a"},
            ],
        )
        self.assertEqual(res["venue_types"], [{"text": "Nhà hàng", "href": "/ha-noi/nha-hang"}])
        self.assertEqual(
            res["dish_groups"],
            [
                {"text": "Thịt Gà", "href": "/ha-noi/dia-diem-phuc-vu-thit-ga"},
                {"text": "Cơm", "href": "/ha-noi/dia-diem-phuc-vu-com"},
            ],
        )
        self.assertEqual(res["suitable_meals"], [{"text": "Buổi trưa", "href": "/ha-noi/dia-diem-phuc-vu-buoi-trua"}])
        self.assertEqual(res["audiences"], [{"text": "Ăn gia đình", "href": "/ha-noi/dia-diem-phu-hop-an-gia-dinh"}])

        # Times and capacities
        self.assertEqual(res["last_guest_time_raw"], "21:30")
        self.assertEqual(res["prep_time_raw"], "Khoảng 5 - 10 phút")
        self.assertEqual(res["prep_time_min"], 5)
        self.assertEqual(res["prep_time_max"], 10)
        self.assertEqual(res["capacity_raw"], "50 người lớn")
        self.assertEqual(res["capacity_value"], 50)
        self.assertEqual(res["holiday_raw"], "Các ngày lễ trong năm")

        # Ratings
        rating = res["rating"]
        self.assertEqual(rating["value"], 8.5)
        self.assertEqual(rating["scale_max"], 10)
        self.assertEqual(rating["review_count"], 42)
        self.assertEqual(
            rating["criteria"],
            {
                "quality": 8.8,
                "location": 8.2,
                "service": 8.0,
                "space": 8.5,
                "price": 7.9,
            },
        )

        # Amenities tri-state
        amenities = {a["key"]: a for a in res["amenities"]}
        self.assertEqual(amenities["wifi"]["status"], "yes")
        self.assertEqual(amenities["wifi"]["status_basis"], "platform_true")
        self.assertEqual(amenities["giaohang"]["status"], "unknown")
        self.assertEqual(amenities["giaohang"]["status_basis"], "platform_gray_unconfirmed")

        # Absent amenity
        self.assertEqual(amenities["maylanh"]["status"], "unknown")
        self.assertEqual(amenities["maylanh"]["status_basis"], "absent")

        # Status 'no' is never emitted
        self.assertTrue(all(a["status"] != "no" for a in res["amenities"]))

        # Field presence
        fp = res["field_presence"]
        self.assertEqual(set(fp.keys()), set(FIELD_PRESENCE_KEYS))
        for k in FIELD_PRESENCE_KEYS:
            self.assertEqual(fp[k], "present")

    def test_never_stores_initdata_wifi(self):
        res = parse_enrichment(SYNTHETIC_FULL_HTML)
        dumped = str(res)
        self.assertNotIn("SecretSSID", dumped)
        self.assertNotIn("SuperSecretPassword123", dumped)

    def test_prep_time_patterns(self):
        # Range
        h1 = '<div class="new-detail-info-area"><div class="new-detail-info-label">Thời gian chuẩn bị</div><div>Khoảng 15 - 30 phút</div></div>'
        r1 = parse_enrichment(h1)
        self.assertEqual(r1["prep_time_min"], 15)
        self.assertEqual(r1["prep_time_max"], 30)
        self.assertEqual(r1["field_presence"]["prep_time"], "present")

        # Single
        h2 = '<div class="new-detail-info-area"><div class="new-detail-info-label">Thời gian chuẩn bị</div><div>20 phút</div></div>'
        r2 = parse_enrichment(h2)
        self.assertEqual(r2["prep_time_min"], 20)
        self.assertEqual(r2["prep_time_max"], 20)
        self.assertEqual(r2["field_presence"]["prep_time"], "present")

        # Unmatched pattern
        h3 = '<div class="new-detail-info-area"><div class="new-detail-info-label">Thời gian chuẩn bị</div><div>Nhanh chóng</div></div>'
        r3 = parse_enrichment(h3)
        self.assertEqual(r3["prep_time_raw"], "Nhanh chóng")
        self.assertIsNone(r3["prep_time_min"])
        self.assertIsNone(r3["prep_time_max"])
        self.assertEqual(r3["field_presence"]["prep_time"], "ambiguous")

    def test_capacity_patterns(self):
        h1 = '<div class="new-detail-info-area"><div class="new-detail-info-label">Sức chứa</div><div>100 người lớn (Có chỗ cho trẻ em)</div></div>'
        r1 = parse_enrichment(h1)
        self.assertEqual(r1["capacity_value"], 100)
        self.assertEqual(r1["capacity_raw"], "100 người lớn (Có chỗ cho trẻ em)")
        self.assertEqual(r1["field_presence"]["capacity"], "present")

        h2 = '<div class="new-detail-info-area"><div class="new-detail-info-label">Sức chứa</div><div>Không xác định</div></div>'
        r2 = parse_enrichment(h2)
        self.assertIsNone(r2["capacity_value"])
        self.assertEqual(r2["capacity_raw"], "Không xác định")
        self.assertEqual(r2["field_presence"]["capacity"], "ambiguous")

    def test_empty_and_absent_markup(self):
        res = parse_enrichment("")
        self.assertEqual(res["schema"], SCHEMA_VERSION)
        for k in FIELD_PRESENCE_KEYS:
            self.assertEqual(res["field_presence"][k], "absent")

    def test_partial_criteria_ambiguous(self):
        html_crit = """
        <div class="microsite-top-points">
            <div><span class="avg-txt-highlight">7.0</span></div>
            <div class="label">Vị trí</div>
        </div>
        <div class="microsite-top-points">
            <div><span class="avg-txt-highlight"></span></div>
            <div class="label">Chất lượng</div>
        </div>
        """
        res = parse_enrichment(html_crit)
        self.assertEqual(res["field_presence"]["criteria"], "ambiguous")
        self.assertEqual(res["rating"]["criteria"]["location"], 7.0)
        self.assertIsNone(res["rating"]["criteria"]["quality"])

    def test_real_cached_page_private_fixture(self):
        if not os.path.isdir(REAL_CACHE_DIR):
            self.skipTest("Real cache directory not present on this machine")
        files = [os.path.join(REAL_CACHE_DIR, f) for f in os.listdir(REAL_CACHE_DIR) if f.endswith(".html")]
        if not files:
            self.skipTest("No cached html files found in real cache dir")
        with open(files[0], encoding="utf-8") as f:
            content = f.read()
        res = parse_enrichment(content, parsed_from="cached_html")
        self.assertEqual(res["schema"], SCHEMA_VERSION)
        self.assertIn("field_presence", res)
        self.assertEqual(len(res["field_presence"]), 13)

    def test_category_lists_anchor_without_href_and_whitespace_normalization(self):
        html_markup = """
        <div class="new-detail-info-area">
            <div class="new-detail-info-label">Phong cách ẩm thực</div>
            <div>
                <a>Món&nbsp;&nbsp;Gia&nbsp;Truyền</a>,
                <a href="/ha-noi/phong-cach-a">Món Á</a>
            </div>
        </div>
        <div class="new-detail-info-area">
            <div class="new-detail-info-label">Thể loại</div>
            <div>
                <a>   Quán   Vỉa   Hè   </a>
            </div>
        </div>
        <div class="new-detail-info-area">
            <div class="new-detail-info-label">Phục vụ các món</div>
            <div>
                <a>Bánh Đa Cua</a>,
                <a>Đậu&nbsp;hũ</a>,
                <a href="/ha-noi/dia-diem-phuc-vu-bun">Bún</a>
                <span class="report-data-error">
                    <a class="resinfo-report" href="javascript:void(0);"><span class="fa fa-pencil"></span></a>
                </span>
            </div>
        </div>
        <div class="new-detail-info-area">
            <div class="new-detail-info-label">Thích hợp</div>
            <div>
                <a>Họp&nbsp;&nbsp;Bạn&nbsp;&nbsp;Bè</a>
            </div>
        </div>
        <div class="new-detail-info-area">
            <div class="new-detail-info-label">Phù hợp với</div>
            <div>
                <a>Khách&nbsp;Du&nbsp;Lịch</a>
            </div>
        </div>
        """
        res = parse_enrichment(html_markup)
        self.assertEqual(
            res["cuisine_styles"],
            [
                {"text": "Món Gia Truyền", "href": None},
                {"text": "Món Á", "href": "/ha-noi/phong-cach-a"},
            ],
        )
        self.assertEqual(res["venue_types"], [{"text": "Quán Vỉa Hè", "href": None}])
        self.assertEqual(
            res["dish_groups"],
            [
                {"text": "Bánh Đa Cua", "href": None},
                {"text": "Đậu hũ", "href": None},
                {"text": "Bún", "href": "/ha-noi/dia-diem-phuc-vu-bun"},
            ],
        )
        self.assertEqual(res["suitable_meals"], [{"text": "Họp Bạn Bè", "href": None}])
        self.assertEqual(res["audiences"], [{"text": "Khách Du Lịch", "href": None}])

    def test_gray_amenity_unknown_and_no_never_emitted(self):
        """Regression test for Task C: gray amenities are status unknown with basis platform_gray_unconfirmed,
        absent is unknown with basis absent, istrue true is yes with basis platform_true, and status no is NEVER emitted."""
        html_markup = """
        <ul class="micro-property">
            <li>
                <img src="/style/images/catico/facilities/3/wifi.png" alt="Có wifi" />
                <a href="/ha-noi/dia-diem-co-wifi">Có wifi</a>
                <a class="resproperties-report" istrue="true" errorkeyname="Có wifi" href="javascript:void(0);"></a>
            </li>
            <li class="none">
                <img src="/style/images/catico/facilities/2/giaohang.png" alt="Có giao hàng" />
                <span style="color:#aaa;">Có giao hàng</span>
                <a class="resproperties-report" istrue="false" errorkeyname="Có giao hàng" href="javascript:void(0);"></a>
            </li>
            <li class="none">
                <img src="/style/images/catico/facilities/2/chodauxehoi.png" alt="Có chỗ đậu ôtô" />
                <span style="color:#aaa;">Có chỗ đậu ôtô</span>
                <a class="resproperties-report" istrue="false" errorkeyname="Có chỗ đậu ôtô" href="javascript:void(0);"></a>
            </li>
        </ul>
        """
        res = parse_enrichment(html_markup)
        amenities = {a["key"]: a for a in res["amenities"]}

        # 1. istrue="true" -> yes / platform_true
        self.assertEqual(amenities["wifi"]["status"], "yes")
        self.assertEqual(amenities["wifi"]["status_basis"], "platform_true")

        # 2. gray (istrue="false") -> unknown / platform_gray_unconfirmed
        self.assertEqual(amenities["giaohang"]["status"], "unknown")
        self.assertEqual(amenities["giaohang"]["status_basis"], "platform_gray_unconfirmed")
        self.assertEqual(amenities["chodauxehoi"]["status"], "unknown")
        self.assertEqual(amenities["chodauxehoi"]["status_basis"], "platform_gray_unconfirmed")

        # 3. absent -> unknown / absent
        self.assertEqual(amenities["maylanh"]["status"], "unknown")
        self.assertEqual(amenities["maylanh"]["status_basis"], "absent")

        # 4. status "no" is NEVER emitted across all amenities
        all_statuses = [a["status"] for a in res["amenities"]]
        self.assertNotIn("no", all_statuses)
        self.assertTrue(all(s in ("yes", "unknown") for s in all_statuses))


if __name__ == "__main__":
    unittest.main()
