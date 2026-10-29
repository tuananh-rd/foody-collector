"""Pure detail-page server-rendered enrichment parser.

Implements foody-enrichment/1 schema using stdlib html.parser/regex only (no network).
Strictly adheres to docs/V4_CONTRACT.md:
- Pure parse_enrichment(html, *, parsed_from="cached_html") -> dict
- Tri-state amenities (yes with platform_true, gray unconfirmed unknown with platform_gray_unconfirmed, absent unknown with absent; status no is never emitted)
- 13 field_presence keys (present / absent / ambiguous)
- Exact-pattern prep time and capacity parsing
- Never accesses or stores initData.Wifi or credentials
"""
import html
from html.parser import HTMLParser
import re
import unicodedata

SCHEMA_VERSION = "foody-enrichment/1"
PARSER_VERSION = "0.4.0"

KNOWN_AMENITIES = {
    "banngoaitroi": "Có bàn ngoài trời",
    "chieubongda": "Có chiếu bóng đá",
    "chodauxehoi": "Có chỗ đậu ôtô",
    "datbantruoc": "Nên đặt trước",
    "giaohang": "Có giao hàng",
    "giuxemienphi": "Giữ xe máy miễn phí",
    "hotrohoithao": "Có hỗ trợ hội thảo",
    "hutthuoc": "Có khu vực hút thuốc",
    "karaoke": "Có karaoke",
    "losuoi": "Có lò sưởi",
    "maylanh": "Có máy lạnh & điều hòa",
    "muamangve": "Cho mua về",
    "nguoikhuyettat": "Có hỗ trợ người khuyết tật",
    "nhacsong": "Có nhạc sống",
    "phongrieng": "Có phòng riêng",
    "thethanhvien": "Có thẻ thành viên",
    "tipnhanvien": "Tip cho nhân viên",
    "trabangthe": "Trả bằng thẻ",
    "vuichoitreem": "Có chỗ chơi cho trẻ em",
    "wifi": "Có wifi",
    "xuathoadon": "Có xuất hóa đơn đỏ",
}

LABEL_TO_AMENITY_KEY = {v.strip().lower(): k for k, v in KNOWN_AMENITIES.items()}

CRITERIA_LABEL_MAP = {
    "Chất lượng": "quality",
    "Vị trí": "location",
    "Phục vụ": "service",
    "Không gian": "space",
    "Giá cả": "price",
}

FIELD_PRESENCE_KEYS = [
    "cuisine_styles",
    "venue_types",
    "dish_groups",
    "suitable_meals",
    "audiences",
    "last_guest_time",
    "prep_time",
    "capacity",
    "holiday",
    "rating",
    "review_count",
    "criteria",
    "amenities",
]

PREP_EXACT_RE = re.compile(r"^Khoảng\s+(\d+)\s*-\s*(\d+)\s+phút$", re.IGNORECASE)
PREP_SINGLE_RE = re.compile(r"^(\d+)\s+phút$", re.IGNORECASE)
CAPACITY_RE = re.compile(r"^(\d+)\s+người(?:\s+.*)?$", re.IGNORECASE)


def _slugify(text):
    if not text:
        return "unknown"
    normalized = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode("ascii")
    slug = re.sub(r"[^a-zA-Z0-9]+", "_", normalized).strip("_").lower()
    return slug or "unknown"


def _extract_links(raw_html):
    if not raw_html:
        return []
    res = []
    for m in re.finditer(r'<a\b([^>]*)>(.*?)</a>', raw_html, re.DOTALL | re.IGNORECASE):
        attrs = m.group(1)
        inner_html = m.group(2)
        m_href = re.search(r'href=["\']([^"\']*)["\']', attrs, re.IGNORECASE)
        href = m_href.group(1).strip() if m_href else None
        if href and href.startswith("javascript:"):
            continue
        text = html.unescape(re.sub(r"<[^>]+>", "", inner_html))
        text = text.replace("\u00a0", " ")
        text = re.sub(r"\s+", " ", text).strip()
        if text:
            res.append({"text": text, "href": href if href else None})
    return res


def _extract_text(raw_html):
    if not raw_html:
        return ""
    text = html.unescape(re.sub(r"<[^>]+>", " ", raw_html)).strip()
    return re.sub(r"\s+", " ", text)


class _CriteriaParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.in_top_points = False
        self.in_highlight = False
        self.in_label = False
        self.current_val = []
        self.current_label = []
        self.results = []
        self.depth = 0

    def handle_starttag(self, tag, attrs):
        classes = dict(attrs).get("class", "").split()
        if tag == "div" and "microsite-top-points" in classes:
            self.in_top_points = True
            self.depth = 1
            self.current_val = []
            self.current_label = []
            return
        if self.in_top_points:
            if tag == "div":
                self.depth += 1
                if "label" in classes:
                    self.in_label = True
            elif tag == "span" and "avg-txt-highlight" in classes:
                self.in_highlight = True

    def handle_endtag(self, tag):
        if self.in_top_points:
            if tag == "span" and self.in_highlight:
                self.in_highlight = False
            elif tag == "div":
                if self.in_label:
                    self.in_label = False
                self.depth -= 1
                if self.depth == 0:
                    self.in_top_points = False
                    val = "".join(self.current_val).strip()
                    lbl = "".join(self.current_label).strip()
                    self.results.append((lbl, val))

    def handle_data(self, data):
        if self.in_top_points:
            if self.in_highlight:
                self.current_val.append(data)
            elif self.in_label:
                self.current_label.append(data)


def parse_enrichment(html_text, *, parsed_from="cached_html"):
    """Pure parse of detail page HTML into foody-enrichment/1 schema."""
    warnings = []
    if not isinstance(html_text, str) or not html_text.strip():
        return {
            "schema": SCHEMA_VERSION,
            "parsed_from": parsed_from,
            "cuisine_styles": [],
            "venue_types": [],
            "dish_groups": [],
            "suitable_meals": [],
            "audiences": [],
            "last_guest_time_raw": None,
            "prep_time_raw": None,
            "prep_time_min": None,
            "prep_time_max": None,
            "capacity_raw": None,
            "capacity_value": None,
            "holiday_raw": None,
            "rating": {
                "value": None,
                "scale_max": None,
                "review_count": None,
                "criteria": {k: None for k in CRITERIA_LABEL_MAP.values()},
            },
            "amenities": [
                {"key": k, "label": v, "status": "unknown", "status_basis": "absent"}
                for k, v in KNOWN_AMENITIES.items()
            ],
            "field_presence": {k: "absent" for k in FIELD_PRESENCE_KEYS},
            "warnings": ["empty or invalid html content"],
        }

    has_info = "new-detail-info-area" in html_text
    has_micro = "micro-property" in html_text
    has_points = "microsite-top-points" in html_text
    has_rating = "ratingValue" in html_text

    if not (has_info or has_micro or has_points or has_rating):
        return {
            "schema": SCHEMA_VERSION,
            "parsed_from": parsed_from,
            "cuisine_styles": [],
            "venue_types": [],
            "dish_groups": [],
            "suitable_meals": [],
            "audiences": [],
            "last_guest_time_raw": None,
            "prep_time_raw": None,
            "prep_time_min": None,
            "prep_time_max": None,
            "capacity_raw": None,
            "capacity_value": None,
            "holiday_raw": None,
            "rating": {
                "value": None,
                "scale_max": None,
                "review_count": None,
                "criteria": {k: None for k in CRITERIA_LABEL_MAP.values()},
            },
            "amenities": [
                {"key": k, "label": v, "status": "unknown", "status_basis": "absent"}
                for k, v in KNOWN_AMENITIES.items()
            ],
            "field_presence": {k: "absent" for k in FIELD_PRESENCE_KEYS},
            "warnings": [],
        }

    # 1. Info rows in div.new-detail-info-area
    info_rows = {}
    if "new-detail-info-area" in html_text:
        areas = re.findall(
            r'<div[^>]*class="[^"]*new-detail-info-area[^"]*"[^>]*>(.*?)</div>\s*</div>',
            html_text,
            re.DOTALL,
        )
        for area in areas:
            m_label = re.search(
                r'<div[^>]*class="[^"]*new-detail-info-label[^"]*"[^>]*>(.*?)</div>',
                area,
                re.DOTALL,
            )
            if m_label:
                raw_label = html.unescape(re.sub(r"<[^>]+>", "", m_label.group(1))).strip()
                val_part = area[m_label.end():]
                val_clean = re.sub(
                    r'<span[^>]*class="[^"]*report-data-error[^"]*"[^>]*>.*?</span>',
                    "",
                    val_part,
                    flags=re.DOTALL,
                )
                info_rows[raw_label] = val_clean

    # Category link lists
    has_cuisine_label = "Phong cách ẩm thực" in info_rows
    cuisine_styles = _extract_links(info_rows.get("Phong cách ẩm thực"))

    has_venue_label = "Thể loại" in info_rows
    venue_types = _extract_links(info_rows.get("Thể loại"))

    has_dish_label = "Phục vụ các món" in info_rows
    dish_groups = _extract_links(info_rows.get("Phục vụ các món"))

    has_suitable_label = "Thích hợp" in info_rows
    suitable_meals = _extract_links(info_rows.get("Thích hợp"))

    has_audiences_label = "Phù hợp với" in info_rows
    audiences = _extract_links(info_rows.get("Phù hợp với"))

    # last_guest_time
    has_last_guest_label = "Giờ nhận khách cuối" in info_rows
    last_guest_text = _extract_text(info_rows.get("Giờ nhận khách cuối"))
    last_guest_time_raw = last_guest_text if last_guest_text else None

    # prep_time
    has_prep_label = "Thời gian chuẩn bị" in info_rows
    prep_text = _extract_text(info_rows.get("Thời gian chuẩn bị"))
    prep_time_raw = prep_text if prep_text else None
    prep_time_min = None
    prep_time_max = None
    if prep_time_raw:
        m_exact = PREP_EXACT_RE.match(prep_time_raw)
        if m_exact:
            prep_time_min = int(m_exact.group(1))
            prep_time_max = int(m_exact.group(2))
        else:
            m_single = PREP_SINGLE_RE.match(prep_time_raw)
            if m_single:
                prep_time_min = int(m_single.group(1))
                prep_time_max = int(m_single.group(1))

    # capacity
    has_cap_label = "Sức chứa" in info_rows
    cap_text = _extract_text(info_rows.get("Sức chứa"))
    capacity_raw = cap_text if cap_text else None
    capacity_value = None
    if capacity_raw:
        m_cap = CAPACITY_RE.match(capacity_raw)
        if m_cap:
            capacity_value = int(m_cap.group(1))

    # holiday
    has_holiday_label = "Nghỉ lễ" in info_rows
    holiday_text = _extract_text(info_rows.get("Nghỉ lễ"))
    holiday_raw = holiday_text if holiday_text else None

    # 2. Rating & Review count & Criteria
    rating_val = None
    m_rate = re.search(r'itemprop=["\']ratingValue["\'][^>]*>([^<]+)<', html_text)
    if m_rate:
        try:
            rating_val = float(m_rate.group(1).strip())
        except ValueError:
            warnings.append(f"Unparseable ratingValue: {m_rate.group(1)!r}")

    rating_scale_max = None
    m_scale = re.search(r'itemprop=["\']bestRating["\'][^>]*content=["\'](\d+)["\']', html_text)
    if m_scale:
        try:
            rating_scale_max = int(m_scale.group(1).strip())
        except ValueError:
            pass

    review_count = None
    m_rev = re.search(r'itemprop=["\']reviewCount["\'][^>]*>([^<]+)<', html_text)
    if m_rev:
        try:
            review_count = int(m_rev.group(1).strip())
        except ValueError:
            warnings.append(f"Unparseable reviewCount: {m_rev.group(1)!r}")

    # Criteria
    criteria = {k: None for k in CRITERIA_LABEL_MAP.values()}
    has_criteria_markup = "microsite-top-points" in html_text
    criteria_parsed_count = 0
    if has_criteria_markup:
        cp = _CriteriaParser()
        cp.feed(html_text)
        for lbl, val in cp.results:
            key = CRITERIA_LABEL_MAP.get(lbl)
            if key:
                if val:
                    try:
                        criteria[key] = float(val)
                        criteria_parsed_count += 1
                    except ValueError:
                        warnings.append(f"Unparseable criteria {key}: {val!r}")

    # 3. Amenities
    has_amenities_markup = "micro-property" in html_text
    found_amenities = {}
    if has_amenities_markup:
        m_ul = re.search(r'<ul[^>]*class="[^"]*micro-property[^"]*"[^>]*>(.*?)</ul>', html_text, re.DOTALL)
        if m_ul:
            lis = re.findall(r'<li[^>]*>(.*?)</li>', m_ul.group(1), re.DOTALL)
            for li in lis:
                m_img = re.search(r'src="[^"]*/([^"/]+)\.png"', li)
                img_key = m_img.group(1) if m_img else None
                m_a = re.search(r'<a[^>]*class="[^"]*resproperties-report[^"]*"([^>]*)>', li)
                attrs = m_a.group(1) if m_a else ""
                m_istrue = re.search(r'istrue="([^"]*)"', attrs)
                m_err = re.search(r'errorkeyname="([^"]*)"', attrs)
                err_label = html.unescape(m_err.group(1)).strip() if m_err else None
                if not err_label:
                    m_span = re.search(r'<span[^>]*>(.*?)</span>', li, re.DOTALL)
                    if m_span:
                        err_label = html.unescape(re.sub(r"<[^>]+>", "", m_span.group(1))).strip()

                key = img_key or (LABEL_TO_AMENITY_KEY.get(err_label.lower()) if err_label else None) or (_slugify(err_label) if err_label else None)
                if not key:
                    continue

                label = err_label or KNOWN_AMENITIES.get(key, key)
                istrue_val = m_istrue.group(1).lower() if m_istrue else None
                if istrue_val == "true":
                    status = "yes"
                    status_basis = "platform_true"
                else:
                    status = "unknown"
                    status_basis = "platform_gray_unconfirmed"

                found_amenities[key] = {
                    "key": key,
                    "label": label,
                    "status": status,
                    "status_basis": status_basis,
                }

    amenities = []
    all_keys = list(KNOWN_AMENITIES.keys())
    for k in found_amenities:
        if k not in all_keys:
            all_keys.append(k)
    for k in all_keys:
        if k in found_amenities:
            amenities.append(found_amenities[k])
        else:
            amenities.append({
                "key": k,
                "label": KNOWN_AMENITIES.get(k, k),
                "status": "unknown",
                "status_basis": "absent",
            })

    # 4. Field presence
    field_presence = {}

    if has_cuisine_label:
        field_presence["cuisine_styles"] = "present" if cuisine_styles else "ambiguous"
    else:
        field_presence["cuisine_styles"] = "absent"

    if has_venue_label:
        field_presence["venue_types"] = "present" if venue_types else "ambiguous"
    else:
        field_presence["venue_types"] = "absent"

    if has_dish_label:
        field_presence["dish_groups"] = "present" if dish_groups else "ambiguous"
    else:
        field_presence["dish_groups"] = "absent"

    if has_suitable_label:
        field_presence["suitable_meals"] = "present" if suitable_meals else "ambiguous"
    else:
        field_presence["suitable_meals"] = "absent"

    if has_audiences_label:
        field_presence["audiences"] = "present" if audiences else "ambiguous"
    else:
        field_presence["audiences"] = "absent"

    if has_last_guest_label:
        field_presence["last_guest_time"] = "present" if last_guest_time_raw else "ambiguous"
    else:
        field_presence["last_guest_time"] = "absent"

    if has_prep_label:
        if prep_time_min is not None:
            field_presence["prep_time"] = "present"
        elif prep_time_raw:
            field_presence["prep_time"] = "ambiguous"
        else:
            field_presence["prep_time"] = "ambiguous"
    else:
        field_presence["prep_time"] = "absent"

    if has_cap_label:
        if capacity_value is not None:
            field_presence["capacity"] = "present"
        elif capacity_raw:
            field_presence["capacity"] = "ambiguous"
        else:
            field_presence["capacity"] = "ambiguous"
    else:
        field_presence["capacity"] = "absent"

    if has_holiday_label:
        field_presence["holiday"] = "present" if holiday_raw else "ambiguous"
    else:
        field_presence["holiday"] = "absent"

    if m_rate:
        field_presence["rating"] = "present" if rating_val is not None else "ambiguous"
    else:
        field_presence["rating"] = "absent"

    if m_rev:
        field_presence["review_count"] = "present" if review_count is not None else "ambiguous"
    else:
        field_presence["review_count"] = "absent"

    if has_criteria_markup:
        field_presence["criteria"] = "present" if criteria_parsed_count == 5 else "ambiguous"
    else:
        field_presence["criteria"] = "absent"

    if has_amenities_markup:
        field_presence["amenities"] = "present" if found_amenities else "ambiguous"
    else:
        field_presence["amenities"] = "absent"

    return {
        "schema": SCHEMA_VERSION,
        "parsed_from": parsed_from,
        "cuisine_styles": cuisine_styles,
        "venue_types": venue_types,
        "dish_groups": dish_groups,
        "suitable_meals": suitable_meals,
        "audiences": audiences,
        "last_guest_time_raw": last_guest_time_raw,
        "prep_time_raw": prep_time_raw,
        "prep_time_min": prep_time_min,
        "prep_time_max": prep_time_max,
        "capacity_raw": capacity_raw,
        "capacity_value": capacity_value,
        "holiday_raw": holiday_raw,
        "rating": {
            "value": rating_val,
            "scale_max": rating_scale_max,
            "review_count": review_count,
            "criteria": criteria,
        },
        "amenities": amenities,
        "field_presence": field_presence,
        "warnings": warnings,
    }
