"""Pure parser for Foody restaurant detail pages (no network, no JS execution)."""
import json
import re
from html.parser import HTMLParser

PRICE_SEMANTICS = "venue price range, not individual dish or per-person guaranteed budget"
SOURCE_LICENSE = "No open-data license established; Foody permission required for intended reuse"

_INIT_RE = re.compile(r"\bvar\s+initData\s*=\s*")


class ParseError(ValueError):
    """Page is not a usable restaurant detail page."""


class _H1Collector(HTMLParser):
    def __init__(self):
        super().__init__()
        self.depth = 0
        self.h1 = []

    def handle_starttag(self, tag, attrs):
        if tag == "h1":
            self.depth += 1

    def handle_endtag(self, tag):
        if tag == "h1":
            self.depth = max(0, self.depth - 1)

    def handle_data(self, data):
        if self.depth and data.strip():
            self.h1.append(data.strip())


def _is_num(v):
    return (isinstance(v, (int, float)) and not isinstance(v, bool)
            and v == v and abs(v) != float("inf"))


def _text(v):
    if isinstance(v, str):
        v = v.strip()
        return v or None
    return None


def _clock(t, label, warnings):
    """Return 'HH:MM' for a {Hours, Minutes} dict or None; never guesses."""
    if t is None:
        return None
    if not isinstance(t, dict):
        warnings.append(f"{label}: time is not an object")
        return None
    h, m = t.get("Hours"), t.get("Minutes")
    if h is None and m is None:
        return None
    if h is None or m is None:
        warnings.append(f"{label}: incomplete time {h!r}:{m!r}")
        return None
    ok = (isinstance(h, int) and not isinstance(h, bool) and isinstance(m, int)
          and not isinstance(m, bool) and 0 <= h <= 23 and 0 <= m <= 59)
    if not ok:
        warnings.append(f"{label}: invalid time {h!r}:{m!r}")
        return None
    return f"{h:02d}:{m:02d}"


def parse_restaurant(html: str, source_url: str, fetched_at: str) -> dict:
    """Parse one restaurant page into a record dict. Raises ParseError if unusable."""
    if not isinstance(html, str):
        raise ParseError("HTML must be text")
    m = _INIT_RE.search(html)
    if not m:
        raise ParseError("No embedded initData object; unsupported page or template changed")
    try:
        d, _ = json.JSONDecoder().raw_decode(html[m.end():])
    except ValueError as e:
        raise ParseError(f"initData is not valid JSON: {e}") from None
    if not isinstance(d, dict):
        raise ParseError("initData is not an object")
    rid = d.get("RestaurantID")
    if not isinstance(rid, int) or isinstance(rid, bool) or rid <= 0:
        raise ParseError("initData has no valid RestaurantID")
    name = _text(d.get("Name"))
    if not name:
        raise ParseError("initData has no restaurant Name")

    warnings = []
    lat, lon = d.get("Latitude"), d.get("Longtitude")  # Foody's spelling
    if lat is not None and not (_is_num(lat) and -90 <= lat <= 90):
        warnings.append(f"invalid latitude {lat!r} dropped")
        lat = None
    if lon is not None and not (_is_num(lon) and -180 <= lon <= 180):
        warnings.append(f"invalid longitude {lon!r} dropped")
        lon = None
    if (lat is None) != (lon is None):
        warnings.append("only one of latitude/longitude usable; both dropped")
        lat = lon = None

    hours = []
    raw_hours = d.get("OpeningTime")
    if raw_hours is not None and not isinstance(raw_hours, list):
        warnings.append("OpeningTime is not a list; ignored")
        raw_hours = []
    for i, h in enumerate(raw_hours or []):
        if not isinstance(h, dict):
            warnings.append(f"OpeningTime[{i}] is not an object; skipped")
            continue
        hours.append({
            "day_of_week_raw": h.get("DayOfWeek"),
            "custom_date": h.get("CustomDate"),
            "open": _clock(h.get("TimeOpen"), f"OpeningTime[{i}].TimeOpen", warnings),
            "close": _clock(h.get("TimeClose"), f"OpeningTime[{i}].TimeClose", warnings),
        })

    prices = {}
    for key, src in (("price_min_vnd", "PriceMin"), ("price_max_vnd", "PriceMax")):
        v = d.get(src)
        if v is not None and not (_is_num(v) and v >= 0):
            warnings.append(f"invalid {src} {v!r} dropped")
            v = None
        prices[key] = v
    if (prices["price_min_vnd"] is not None and prices["price_max_vnd"] is not None
            and prices["price_min_vnd"] > prices["price_max_vnd"]):
        warnings.append("PriceMin greater than PriceMax; both kept as published")

    h1 = _H1Collector()
    try:
        h1.feed(html)
    except Exception:  # malformed markup must not lose the JSON record
        pass

    return {
        "foody_id": rid,
        "name": name,
        "lat": lat,
        "lon": lon,
        "address": _text(d.get("Address")),
        "district": _text(d.get("District")),
        "city": _text(d.get("City")),
        "opening_hours_raw": hours,
        "price_min_vnd": prices["price_min_vnd"],
        "price_max_vnd": prices["price_max_vnd"],
        "source_url": source_url,
        "fetched_at": fetched_at,
        "price_semantics": PRICE_SEMANTICS,
        "source_license": SOURCE_LICENSE,
        "field_freshness_unknown": True,
        "source_flags": {
            "IsActive": d.get("IsActive"),
            "IsInactive": d.get("IsInactive"),
            "IsDelete": d.get("IsDelete"),
            "RestaurantStatus": d.get("RestaurantStatus"),
            "IsVerifiedMap": d.get("IsVerifiedMap"),
        },
        "h1_names": h1.h1,
        "parse_warnings": warnings,
    }
