"""Foody v0.3 quality metrics, classification, issue detection, and export."""
import csv
import hashlib
import json
import math
import os
import re
from datetime import datetime, timezone

from .exporter import FIELDS

QUALITY_SCHEMA_VERSION = "3.0"
PARSER_VERSION = "0.3.0"
PRICE_STATUSES = ("ok", "missing", "nonfinite", "unknown_zero", "partial_zero", "invalid_range")
HOURS_STATUSES = ("missing", "malformed", "day_mapping_unknown")
GEO_STATUSES = ("ok", "missing", "nonfinite", "out_of_range", "outside_hanoi_bbox")

SOURCE_KEYS = {
    "foody_id": "RestaurantID",
    "name": "Name",
    "address": "Address",
    "district": "District",
    "city": "City",
    "lat": "Latitude",
    "lon": "Longtitude",
    "price_min_vnd": "PriceMin",
    "price_max_vnd": "PriceMax",
    "opening_hours_raw": "OpeningTime",
}
FLAG_KEYS = ("IsActive", "IsInactive", "IsDelete", "RestaurantStatus", "IsVerifiedMap")

NORMALIZED_FIELDS = [
    "foody_id", "name", "source_url", "address", "district", "city",
    "price_min_raw", "price_max_raw", "price_status", "price_min_vnd_norm", "price_max_vnd_norm",
    "price_semantics", "price_verified",
    "opening_hours_raw", "hours_status", "hours_intervals_count", "hours_day_codes_raw",
    "hours_crosses_midnight_raw", "hours_schedule_norm",
    "source_flags", "source_flags_semantics", "operating_status", "operating_status_evidence",
    "lat", "lon", "geo_status",
    "parser_version", "raw_content_hash", "fetched_at", "source_updated_at",
    "verified_at", "verification_method", "quality_schema_version", "run_id",
    "search_eligible", "location_eligible", "price_filter_eligible",
    "budget_eligible", "hours_eligible", "tour_eligible",
]

ISSUE_FIELDS = [
    "issue_id", "foody_id", "name", "csv_line", "severity", "issue_code",
    "field", "raw_min", "raw_max", "detail", "source_url", "run_id",
]

_FORMULA_RE = re.compile(r"^'*[=+@\t\r-]")
_CLOCK_RE = re.compile(r"^(\d{2}):(\d{2})$")
_INIT_RE = re.compile(r"\bvar\s+initData\s*=\s*")


def sanitize_strict_json(val):
    """Recursively replace non-finite floats with string tokens 'NaN', 'Infinity', '-Infinity'."""
    if isinstance(val, float):
        if math.isnan(val):
            return "NaN"
        if math.isinf(val):
            return "-Infinity" if val < 0 else "Infinity"
        return val
    if isinstance(val, dict):
        return {k: sanitize_strict_json(v) for k, v in val.items()}
    if isinstance(val, (list, tuple)):
        return [sanitize_strict_json(v) for v in val]
    return val


def dumps_strict_json(obj, indent=2):
    sanitized = sanitize_strict_json(obj)
    return json.dumps(sanitized, ensure_ascii=False, indent=indent, allow_nan=False) + "\n"


def _atomic_write(path, text):
    tmp = f"{path}.tmp"
    with open(tmp, "w", encoding="utf-8", newline="") as f:
        f.write(text)
    os.replace(tmp, path)


def _safe_float_token(v):
    if isinstance(v, float):
        if math.isnan(v):
            return "NaN"
        if math.isinf(v):
            return "-Infinity" if v < 0 else "Infinity"
    return v


# ---------------------------------------------------------------------------
# Classifiers
# ---------------------------------------------------------------------------

def _is_invalid_num(v):
    if v is None:
        return False
    if isinstance(v, bool):
        return True
    if not isinstance(v, (int, float)):
        return True
    if isinstance(v, float):
        if math.isnan(v) or math.isinf(v):
            return True
        if not v.is_integer():
            return True
    if v < 0:
        return True
    return False


def classify_price(lo, hi, warnings=()):
    warn_list = [warnings] if isinstance(warnings, str) else list(warnings or [])
    has_dropped_warning = any(
        isinstance(w, str) and ("invalid PriceMin" in w or "invalid PriceMax" in w)
        for w in warn_list
    )

    if has_dropped_warning or _is_invalid_num(lo) or _is_invalid_num(hi):
        return {"status": "nonfinite", "min_norm": None, "max_norm": None}

    if lo is None or hi is None:
        return {"status": "missing", "min_norm": None, "max_norm": None}

    if lo == 0 and hi == 0:
        return {"status": "unknown_zero", "min_norm": None, "max_norm": None}

    if (lo == 0 and hi > 0) or (hi == 0 and lo > 0):
        return {"status": "partial_zero", "min_norm": None, "max_norm": None}

    if lo > 0 and hi > 0 and lo > hi:
        return {"status": "invalid_range", "min_norm": None, "max_norm": None}

    if 0 < lo <= hi:
        return {"status": "ok", "min_norm": int(lo), "max_norm": int(hi)}

    return {"status": "nonfinite", "min_norm": None, "max_norm": None}


def _is_valid_clock(t):
    if not isinstance(t, str):
        return False
    m = _CLOCK_RE.match(t)
    if not m:
        return False
    h, minute = int(m.group(1)), int(m.group(2))
    return 0 <= h <= 23 and 0 <= minute <= 59


def classify_hours(hours_raw, warnings=()):
    warn_list = [warnings] if isinstance(warnings, str) else list(warnings or [])
    has_hours_warning = any(
        isinstance(w, str) and any(kw in w.lower() for kw in (
            "openingtime", "opening_hours", "hours", "incomplete time", "invalid time",
            "timeopen", "timeclose", "clock"
        ))
        for w in warn_list
    )

    intervals_count = len(hours_raw) if isinstance(hours_raw, list) else 0

    unique_codes = {}
    if isinstance(hours_raw, list):
        for item in hours_raw:
            if isinstance(item, dict) and "day_of_week_raw" in item:
                val = item["day_of_week_raw"]
                try:
                    cj = json.dumps(val, sort_keys=True, ensure_ascii=False, allow_nan=False)
                except (ValueError, TypeError):
                    cj = str(val)
                key = (type(val).__name__, cj)
                if key not in unique_codes:
                    unique_codes[key] = val
    day_codes_raw = [unique_codes[k] for k in sorted(unique_codes.keys())]

    # Malformed warning overrides empty list/None per review
    if has_hours_warning:
        return {
            "status": "malformed",
            "intervals_count": intervals_count,
            "day_codes_raw": day_codes_raw,
            "crosses_midnight_raw": False,
            "schedule_norm": None,
        }

    if hours_raw is None or (isinstance(hours_raw, list) and len(hours_raw) == 0):
        return {
            "status": "missing",
            "intervals_count": 0,
            "day_codes_raw": [],
            "crosses_midnight_raw": False,
            "schedule_norm": None,
        }

    if not isinstance(hours_raw, list):
        return {
            "status": "malformed",
            "intervals_count": 0,
            "day_codes_raw": [],
            "crosses_midnight_raw": False,
            "schedule_norm": None,
        }

    malformed = False
    crosses_midnight = False

    for item in hours_raw:
        if not isinstance(item, dict):
            malformed = True
            continue
        open_t = item.get("open")
        close_t = item.get("close")
        if not open_t or not close_t:
            malformed = True
        elif not _is_valid_clock(open_t) or not _is_valid_clock(close_t):
            malformed = True
        else:
            if open_t > close_t:
                crosses_midnight = True

    status = "malformed" if malformed else "day_mapping_unknown"
    return {
        "status": status,
        "intervals_count": intervals_count,
        "day_codes_raw": day_codes_raw,
        "crosses_midnight_raw": crosses_midnight,
        "schedule_norm": None,
    }


def classify_geo(lat, lon, warnings=()):
    warn_list = [warnings] if isinstance(warnings, str) else list(warnings or [])
    has_geo_warning = any(
        isinstance(w, str) and ("invalid latitude" in w or "invalid longitude" in w or "only one of latitude/longitude" in w)
        for w in warn_list
    )
    if has_geo_warning:
        return "nonfinite"

    def _is_bad_num(v):
        if v is None:
            return False
        if isinstance(v, bool) or not isinstance(v, (int, float)):
            return True
        if isinstance(v, float) and (math.isnan(v) or math.isinf(v)):
            return True
        return False

    if _is_bad_num(lat) or _is_bad_num(lon):
        return "nonfinite"

    if lat is not None and not (-90 <= lat <= 90):
        return "out_of_range"
    if lon is not None and not (-180 <= lon <= 180):
        return "out_of_range"

    if lat is None or lon is None:
        return "missing"

    if 20.5 <= lat <= 21.5 and 105.3 <= lon <= 106.1:
        return "ok"
    return "outside_hanoi_bbox"


# ---------------------------------------------------------------------------
# Field presence and provenance
# ---------------------------------------------------------------------------

def field_presence(html):
    fields = {
        "price_min_vnd": {"source_key": "PriceMin", "present": None},
        "price_max_vnd": {"source_key": "PriceMax", "present": None},
        "opening_hours_raw": {"source_key": "OpeningTime", "present": None},
        "lat": {"source_key": "Latitude", "present": None},
        "lon": {"source_key": "Longtitude", "present": None},
        "source_flags": {"source_key": ",".join(FLAG_KEYS), "present": None},
    }
    if not isinstance(html, str):
        return fields
    match = _INIT_RE.search(html)
    if not match:
        return fields
    try:
        source, _ = json.JSONDecoder().raw_decode(html[match.end():])
        if isinstance(source, dict):
            for field, key in (
                ("price_min_vnd", "PriceMin"),
                ("price_max_vnd", "PriceMax"),
                ("opening_hours_raw", "OpeningTime"),
                ("lat", "Latitude"),
                ("lon", "Longtitude"),
            ):
                fields[field] = {"source_key": key, "present": key in source}
            fields["source_flags"] = {
                "source_key": ",".join(FLAG_KEYS),
                "present": any(k in source for k in FLAG_KEYS),
            }
    except ValueError:
        pass
    return fields


def build_provenance(record, entry=None, *, run_id, parser_version=PARSER_VERSION, html=None, is_import=False):
    # The quality implementation version does not establish the old extractor's version.
    entry = {} if is_import else (entry or {})
    p_version = entry.get("parser_version") or record.get("parser_version")
    source_url = record.get("source_url") or entry.get("source_url")
    final_url = entry.get("final_url")
    fetched_at = entry.get("fetched_at") or record.get("fetched_at")
    parsed_at = entry.get("parsed_at")

    raw_content_hash = entry.get("raw_content_hash")
    text_snapshot_hash = entry.get("text_snapshot_hash")
    if text_snapshot_hash is None and isinstance(html, str):
        text_snapshot_hash = "sha256:" + hashlib.sha256(html.encode("utf-8")).hexdigest()
    hash_basis = entry.get("hash_basis")
    if not hash_basis:
        if raw_content_hash:
            hash_basis = "http_body_bytes"
        elif text_snapshot_hash:
            hash_basis = "text_snapshot"
        else:
            hash_basis = None

    fields = entry.get("field_presence")
    if not fields:
        if html is not None:
            fields = field_presence(html)
        else:
            fields = field_presence(None)

    prov = {
        "parser_version": p_version,
        "quality_schema_version": QUALITY_SCHEMA_VERSION,
        "run_id": run_id,
        "source_url": source_url,
        "final_url": final_url,
        "fetched_at": fetched_at,
        "parsed_at": parsed_at,
        "raw_content_hash": raw_content_hash,
        "text_snapshot_hash": text_snapshot_hash,
        "hash_basis": hash_basis,
        "http_status": entry.get("http_status"),
        "source_updated_at": None,
        "verified_at": None,
        "verification_method": None,
        "fields": fields,
        "raw_fidelity": "parser_filtered",
    }
    if "source_keys" in entry:
        prov["source_keys"] = entry["source_keys"]
    return prov


# ---------------------------------------------------------------------------
# Record normalization
# ---------------------------------------------------------------------------

def normalize_record(record, provenance=None):
    provenance = provenance or {}
    raw_id = record.get("foody_id")
    # Exact positive int and not bool; no string or float int-casting
    if isinstance(raw_id, int) and not isinstance(raw_id, bool) and raw_id > 0:
        foody_id = raw_id
    else:
        foody_id = None

    raw_name = record.get("name")
    name = str(raw_name).strip() if (isinstance(raw_name, str) and raw_name.strip()) else (
        raw_name if raw_name is not None else None
    )
    source_url = record.get("source_url")
    warnings = record.get("parse_warnings") or ()

    lo = record.get("price_min_vnd")
    hi = record.get("price_max_vnd")
    price_info = classify_price(lo, hi, warnings)

    hours_raw = record.get("opening_hours_raw")
    hours_info = classify_hours(hours_raw, warnings)

    lat = record.get("lat")
    lon = record.get("lon")
    geo_status = classify_geo(lat, lon, warnings)

    norm_lat = lat if (isinstance(lat, (int, float)) and not isinstance(lat, bool) and (not isinstance(lat, float) or math.isfinite(lat))) else None
    norm_lon = lon if (isinstance(lon, (int, float)) and not isinstance(lon, bool) and (not isinstance(lon, float) or math.isfinite(lon))) else None

    # Search eligible requires valid positive int foody_id and non-empty name
    search_eligible = bool(foody_id is not None and name and isinstance(name, str) and name.strip())
    location_eligible = (geo_status == "ok")
    price_filter_eligible = (price_info["status"] == "ok")
    budget_eligible = False
    hours_eligible = False
    tour_eligible = False

    sf = record.get("source_flags")
    source_flags = dict(sf) if isinstance(sf, dict) else (sf if sf is not None else {})

    return {
        "foody_id": foody_id,
        "name": name,
        "source_url": source_url,
        "address": record.get("address"),
        "district": record.get("district"),
        "city": record.get("city"),
        "price_min_raw": _safe_float_token(lo),
        "price_max_raw": _safe_float_token(hi),
        "price_status": price_info["status"],
        "price_min_vnd_norm": price_info["min_norm"],
        "price_max_vnd_norm": price_info["max_norm"],
        "price_semantics": record.get("price_semantics") or "venue price range, not individual dish or per-person guaranteed budget",
        "price_verified": False,
        "opening_hours_raw": hours_raw,
        "hours_status": hours_info["status"],
        "hours_intervals_count": hours_info["intervals_count"],
        "hours_day_codes_raw": hours_info["day_codes_raw"],
        "hours_crosses_midnight_raw": hours_info["crosses_midnight_raw"],
        "hours_schedule_norm": None,
        "source_flags": source_flags,
        "source_flags_semantics": "unknown",
        "operating_status": "unknown",
        "operating_status_evidence": None,
        "lat": _safe_float_token(norm_lat),
        "lon": _safe_float_token(norm_lon),
        "geo_status": geo_status,
        "parser_version": provenance.get("parser_version"),
        "raw_content_hash": provenance.get("raw_content_hash"),
        "fetched_at": provenance.get("fetched_at"),
        "source_updated_at": provenance.get("source_updated_at"),
        "verified_at": provenance.get("verified_at"),
        "verification_method": provenance.get("verification_method"),
        "quality_schema_version": provenance.get("quality_schema_version"),
        "run_id": provenance.get("run_id"),
        "search_eligible": search_eligible,
        "location_eligible": location_eligible,
        "price_filter_eligible": price_filter_eligible,
        "budget_eligible": budget_eligible,
        "hours_eligible": hours_eligible,
        "tour_eligible": tour_eligible,
    }


# ---------------------------------------------------------------------------
# Issue detection
# ---------------------------------------------------------------------------

def detect_issues(record, normalized, *, csv_line, run_id):
    issues = []
    foody_id = normalized.get("foody_id")
    fid_str = str(foody_id) if foody_id is not None else f"row{csv_line}"
    name = normalized.get("name")
    source_url = normalized.get("source_url")

    p_status = normalized.get("price_status")
    lo_raw = normalized.get("price_min_raw")
    hi_raw = normalized.get("price_max_raw")

    if p_status == "unknown_zero":
        issues.append({
            "issue_id": f"{fid_str}:zero_price_unverified:L{csv_line}",
            "foody_id": foody_id,
            "name": name,
            "csv_line": csv_line,
            "severity": "warning",
            "issue_code": "zero_price_unverified",
            "field": "price",
            "raw_min": lo_raw,
            "raw_max": hi_raw,
            "detail": "both prices are zero; unverified",
            "source_url": source_url,
            "run_id": run_id,
        })
    elif p_status == "invalid_range":
        issues.append({
            "issue_id": f"{fid_str}:invalid_price_range:L{csv_line}",
            "foody_id": foody_id,
            "name": name,
            "csv_line": csv_line,
            "severity": "error",
            "issue_code": "invalid_price_range",
            "field": "price",
            "raw_min": lo_raw,
            "raw_max": hi_raw,
            "detail": "PriceMin greater than PriceMax",
            "source_url": source_url,
            "run_id": run_id,
        })
    elif p_status == "partial_zero":
        issues.append({
            "issue_id": f"{fid_str}:partial_zero_price:L{csv_line}",
            "foody_id": foody_id,
            "name": name,
            "csv_line": csv_line,
            "severity": "warning",
            "issue_code": "partial_zero_price",
            "field": "price",
            "raw_min": lo_raw,
            "raw_max": hi_raw,
            "detail": "one price is zero",
            "source_url": source_url,
            "run_id": run_id,
        })
    elif p_status == "missing":
        issues.append({
            "issue_id": f"{fid_str}:price_missing:L{csv_line}",
            "foody_id": foody_id,
            "name": name,
            "csv_line": csv_line,
            "severity": "warning",
            "issue_code": "price_missing",
            "field": "price",
            "raw_min": lo_raw,
            "raw_max": hi_raw,
            "detail": "price is missing",
            "source_url": source_url,
            "run_id": run_id,
        })
    elif p_status == "nonfinite":
        issues.append({
            "issue_id": f"{fid_str}:price_nonfinite:L{csv_line}",
            "foody_id": foody_id,
            "name": name,
            "csv_line": csv_line,
            "severity": "error",
            "issue_code": "price_nonfinite",
            "field": "price",
            "raw_min": lo_raw,
            "raw_max": hi_raw,
            "detail": "price is non-finite or invalid",
            "source_url": source_url,
            "run_id": run_id,
        })

    h_status = normalized.get("hours_status")
    if h_status == "missing":
        issues.append({
            "issue_id": f"{fid_str}:hours_missing:L{csv_line}",
            "foody_id": foody_id,
            "name": name,
            "csv_line": csv_line,
            "severity": "warning",
            "issue_code": "hours_missing",
            "field": "opening_hours_raw",
            "raw_min": None,
            "raw_max": None,
            "detail": "opening hours missing",
            "source_url": source_url,
            "run_id": run_id,
        })
    elif h_status == "malformed":
        issues.append({
            "issue_id": f"{fid_str}:hours_malformed:L{csv_line}",
            "foody_id": foody_id,
            "name": name,
            "csv_line": csv_line,
            "severity": "error",
            "issue_code": "hours_malformed",
            "field": "opening_hours_raw",
            "raw_min": None,
            "raw_max": None,
            "detail": "opening hours malformed",
            "source_url": source_url,
            "run_id": run_id,
        })

    g_status = normalized.get("geo_status")
    if g_status == "missing":
        issues.append({
            "issue_id": f"{fid_str}:geo_missing:L{csv_line}",
            "foody_id": foody_id,
            "name": name,
            "csv_line": csv_line,
            "severity": "warning",
            "issue_code": "geo_missing",
            "field": "lat,lon",
            "raw_min": None,
            "raw_max": None,
            "detail": "coordinates missing",
            "source_url": source_url,
            "run_id": run_id,
        })
    elif g_status == "nonfinite":
        issues.append({
            "issue_id": f"{fid_str}:geo_nonfinite:L{csv_line}",
            "foody_id": foody_id,
            "name": name,
            "csv_line": csv_line,
            "severity": "error",
            "issue_code": "geo_nonfinite",
            "field": "lat,lon",
            "raw_min": None,
            "raw_max": None,
            "detail": "coordinates nonfinite",
            "source_url": source_url,
            "run_id": run_id,
        })
    elif g_status == "out_of_range":
        issues.append({
            "issue_id": f"{fid_str}:geo_out_of_range:L{csv_line}",
            "foody_id": foody_id,
            "name": name,
            "csv_line": csv_line,
            "severity": "error",
            "issue_code": "geo_out_of_range",
            "field": "lat,lon",
            "raw_min": None,
            "raw_max": None,
            "detail": "coordinates out of valid range [-90,90]/[-180,180]",
            "source_url": source_url,
            "run_id": run_id,
        })
    elif g_status == "outside_hanoi_bbox":
        issues.append({
            "issue_id": f"{fid_str}:geo_outside_hanoi_bbox:L{csv_line}",
            "foody_id": foody_id,
            "name": name,
            "csv_line": csv_line,
            "severity": "warning",
            "issue_code": "geo_outside_hanoi_bbox",
            "field": "lat,lon",
            "raw_min": None,
            "raw_max": None,
            "detail": "coordinates outside Hanoi bounding box",
            "source_url": source_url,
            "run_id": run_id,
        })

    pw = record.get("parse_warnings")
    warn_list = [pw] if isinstance(pw, str) else (list(pw) if isinstance(pw, (list, tuple)) else [])
    for w in warn_list:
        w_str = str(w)
        is_mapped = (
            "PriceMin greater than PriceMax" in w_str
            or "invalid PriceMin" in w_str
            or "invalid PriceMax" in w_str
            or "invalid latitude" in w_str
            or "invalid longitude" in w_str
            or "only one of latitude/longitude" in w_str
            or "OpeningTime" in w_str
            or "incomplete time" in w_str
            or "invalid time" in w_str
        )
        if not is_mapped:
            issues.append({
                "issue_id": f"{fid_str}:parse_warning:L{csv_line}",
                "foody_id": foody_id,
                "name": name,
                "csv_line": csv_line,
                "severity": "info",
                "issue_code": "parse_warning",
                "field": None,
                "raw_min": None,
                "raw_max": None,
                "detail": w_str,
                "source_url": source_url,
                "run_id": run_id,
            })

    prov = record.get("provenance") or {}
    has_body_hash = bool(normalized.get("raw_content_hash"))
    prov_fields = prov.get("fields") or {}
    fields_incomplete = (not prov_fields) or any(v.get("present") is None for v in prov_fields.values())
    if (not has_body_hash) or fields_incomplete:
        issues.append({
            "issue_id": f"{fid_str}:provenance_incomplete:L{csv_line}",
            "foody_id": foody_id,
            "name": name,
            "csv_line": csv_line,
            "severity": "warning",
            "issue_code": "provenance_incomplete",
            "field": "provenance",
            "raw_min": None,
            "raw_max": None,
            "detail": "raw_content_hash or field presence incomplete",
            "source_url": source_url,
            "run_id": run_id,
        })

    fa = normalized.get("fetched_at")
    if fa is None:
        issues.append({
            "issue_id": f"{fid_str}:timestamp_invalid:L{csv_line}",
            "foody_id": foody_id,
            "name": name,
            "csv_line": csv_line,
            "severity": "error",
            "issue_code": "timestamp_invalid",
            "field": "fetched_at",
            "raw_min": None,
            "raw_max": None,
            "detail": "fetched_at is missing",
            "source_url": source_url,
            "run_id": run_id,
        })
    elif not isinstance(fa, str):
        issues.append({
            "issue_id": f"{fid_str}:timestamp_invalid:L{csv_line}",
            "foody_id": foody_id,
            "name": name,
            "csv_line": csv_line,
            "severity": "error",
            "issue_code": "timestamp_invalid",
            "field": "fetched_at",
            "raw_min": None,
            "raw_max": None,
            "detail": f"fetched_at {fa!r} is not text",
            "source_url": source_url,
            "run_id": run_id,
        })
    else:
        try:
            datetime.fromisoformat(fa.replace("Z", "+00:00"))
        except (ValueError, TypeError):
            issues.append({
                "issue_id": f"{fid_str}:timestamp_invalid:L{csv_line}",
                "foody_id": foody_id,
                "name": name,
                "csv_line": csv_line,
                "severity": "error",
                "issue_code": "timestamp_invalid",
                "field": "fetched_at",
                "raw_min": None,
                "raw_max": None,
                "detail": f"fetched_at {fa!r} is not valid ISO-8601",
                "source_url": source_url,
                "run_id": run_id,
            })

    return issues


# ---------------------------------------------------------------------------
# Report generation
# ---------------------------------------------------------------------------

def build_quality_report(progress, requested, raw_rows, normalized_rows, issues, *, run_id, stopped_reason=None, is_import=False):
    progress = progress or {}
    requested = list(requested or [])

    if is_import or (not progress and not requested):
        # Offline import: zero measured network
        funnel = {
            "discovered_urls": 0,
            "requested_urls": 0,
            "attempted": 0,
            "fetched_ok_http200": 0,
            "fetch_failed": 0,
            "blocked": 0,
            "parse_ok": 0,
            "parse_error": 0,
            "duplicate_id": 0,
            "retried_urls": 0,
            "pending_not_attempted": 0,
            "unique_venues_exported": len(normalized_rows),
        }
        rates = {
            "fetch_success": {"num": 0, "den": 0, "rate": None, "den_label": "attempted"},
            "parse_success": {"num": 0, "den": 0, "rate": None, "den_label": "fetched_ok_http200"},
            "extraction_success": {"num": 0, "den": 0, "rate": None, "den_label": "requested_urls - duplicate_id"},
        }
    else:
        outcomes = {}
        for u in requested:
            st = progress.get(u, {}).get("status", "pending")
            outcomes[st] = outcomes.get(st, 0) + 1

        discovered_urls = len(requested)
        requested_urls = len(requested)

        attempted = sum(
            1 for u in requested
            if progress.get(u, {}).get("status", "pending") not in ("pending", "invalid_url")
        )

        fetched_ok_http200 = sum(
            1 for u in requested
            if progress.get(u, {}).get("status", "pending") in ("ok", "parse_error", "duplicate_id")
            or progress.get(u, {}).get("http_status") == 200
        )

        fetch_failed = sum(
            1 for u in requested
            if progress.get(u, {}).get("status") in ("transient_failed", "http_error", "unsafe_redirect")
        )

        blocked = sum(1 for u in requested if progress.get(u, {}).get("status") == "blocked")
        parse_ok = sum(1 for u in requested if progress.get(u, {}).get("status", "pending") == "ok")
        parse_error = sum(1 for u in requested if progress.get(u, {}).get("status") == "parse_error")
        duplicate_id = sum(1 for u in requested if progress.get(u, {}).get("status") == "duplicate_id")

        retry_values = [progress.get(u, {}).get("retry_count") for u in requested
                        if progress.get(u, {}).get("status", "pending") not in ("pending", "invalid_url")]
        known_retries = [v for v in retry_values if type(v) is int and v >= 0]
        retry_unknown_urls = len(retry_values) - len(known_retries)
        retried_urls_known = sum(v > 0 for v in known_retries)
        retried_urls = None if retry_unknown_urls else retried_urls_known

        pending_not_attempted = sum(
            1 for u in requested
            if progress.get(u, {}).get("status", "pending") == "pending"
        )
        from_cache = sum(1 for u in requested if progress.get(u, {}).get("from_cache"))
        unique_venues_exported = len(normalized_rows)

        funnel = {
            "discovered_urls": discovered_urls,
            "requested_urls": requested_urls,
            "attempted": attempted,
            "from_cache": from_cache,
            "fetched_ok_http200": fetched_ok_http200,
            "fetch_failed": fetch_failed,
            "blocked": blocked,
            "parse_ok": parse_ok,
            "parse_error": parse_error,
            "duplicate_id": duplicate_id,
            "retried_urls": retried_urls,
            "retried_urls_known": retried_urls_known,
            "retry_known_urls": len(known_retries),
            "retry_unknown_urls": retry_unknown_urls,
            "pending_not_attempted": pending_not_attempted,
            "unique_venues_exported": unique_venues_exported,
        }

        def _rate(num, den, label):
            if den == 0:
                return {"num": num, "den": den, "rate": None, "den_label": label}
            return {"num": num, "den": den, "rate": round(num / den, 4), "den_label": label}

        rates = {
            "fetch_success": _rate(fetched_ok_http200, attempted, "attempted"),
            "parse_success": _rate(parse_ok, fetched_ok_http200, "fetched_ok_http200"),
            "extraction_success": _rate(unique_venues_exported, requested_urls - duplicate_id, "requested_urls - duplicate_id"),
        }

    price_status_counts = {k: 0 for k in PRICE_STATUSES}
    for r in normalized_rows:
        st = r.get("price_status")
        if st in price_status_counts:
            price_status_counts[st] += 1

    hours_status_counts = {k: 0 for k in HOURS_STATUSES}
    for r in normalized_rows:
        st = r.get("hours_status")
        if st in hours_status_counts:
            hours_status_counts[st] += 1

    geo_status_counts = {k: 0 for k in GEO_STATUSES}
    for r in normalized_rows:
        st = r.get("geo_status")
        if st in geo_status_counts:
            geo_status_counts[st] += 1

    issue_counts_by_code = {}
    issue_counts_by_severity = {"error": 0, "warning": 0, "info": 0}
    for iss in issues:
        c = iss.get("issue_code")
        s = iss.get("severity")
        issue_counts_by_code[c] = issue_counts_by_code.get(c, 0) + 1
        if s in issue_counts_by_severity:
            issue_counts_by_severity[s] += 1

    flags_counts = {"IsActive": {}, "IsInactive": {}, "RestaurantStatus": {}, "interpretation": "unknown"}
    for r in raw_rows:
        sf = r.get("source_flags")
        if isinstance(sf, dict):
            for fk in ("IsActive", "IsInactive", "RestaurantStatus"):
                val = str(sf.get(fk))
                flags_counts[fk][val] = flags_counts[fk].get(val, 0) + 1

    den_e = len(normalized_rows)
    def _elig_rate(num):
        if den_e == 0:
            return {"num": num, "den": 0, "rate": None, "den_label": "unique_venues_exported"}
        return {"num": num, "den": den_e, "rate": round(num / den_e, 4), "den_label": "unique_venues_exported"}

    eligibility = {
        "search_eligible": _elig_rate(sum(1 for r in normalized_rows if r.get("search_eligible"))),
        "location_eligible": _elig_rate(sum(1 for r in normalized_rows if r.get("location_eligible"))),
        "price_filter_eligible": _elig_rate(sum(1 for r in normalized_rows if r.get("price_filter_eligible"))),
        "budget_eligible": _elig_rate(0),
        "hours_eligible": _elig_rate(0),
        "tour_eligible": _elig_rate(0),
    }

    if is_import:
        partial = False
    else:
        outcomes_map = {u: progress.get(u, {}).get("status", "pending") for u in requested}
        partial = bool(stopped_reason) or funnel.get("pending_not_attempted", 0) > 0 or any(
            s not in ("ok", "duplicate_id") for s in outcomes_map.values()
        )

    now_str = datetime.now(timezone.utc).isoformat()
    return {
        "quality_schema_version": QUALITY_SCHEMA_VERSION,
        "parser_version": PARSER_VERSION,
        "run_id": run_id,
        "generated_at": now_str,
        "execution_mode": "offline_import" if is_import or (not progress and not requested) else "crawl_snapshot",
        "metric_basis": "Saved URL status snapshot, including historical fetches and cached parsing; not current-operation network requests.",
        "stopped_reason": stopped_reason,
        "partial": partial,
        "funnel": funnel,
        "rates": rates,
        "price_status_counts": price_status_counts,
        "hours_status_counts": hours_status_counts,
        "geo_status_counts": geo_status_counts,
        "issue_counts_by_code": issue_counts_by_code,
        "issue_counts_by_severity": issue_counts_by_severity,
        "source_flag_semantics": flags_counts,
        "eligibility": eligibility,
        "notes": ["HTTP 200 is not extraction success"],
    }


# ---------------------------------------------------------------------------
# CSV Exporters
# ---------------------------------------------------------------------------

def export_normalized_csv(records, path):
    tmp = f"{path}.tmp"
    with open(tmp, "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(NORMALIZED_FIELDS)
        for r in records:
            row = []
            for k in NORMALIZED_FIELDS:
                v = r.get(k)
                if v is None:
                    row.append("")
                elif isinstance(v, bool):
                    row.append("true" if v else "false")
                elif isinstance(v, (list, dict)):
                    row.append(json.dumps(sanitize_strict_json(v), ensure_ascii=False, allow_nan=False))
                elif isinstance(v, str) and _FORMULA_RE.match(v):
                    row.append("'" + v)
                else:
                    v = _safe_float_token(v)
                    row.append(str(v))
            w.writerow(row)
    os.replace(tmp, path)


def export_issues_csv(issues, path):
    tmp = f"{path}.tmp"
    with open(tmp, "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(ISSUE_FIELDS)
        for iss in issues:
            row = []
            for k in ISSUE_FIELDS:
                v = iss.get(k)
                if v is None:
                    row.append("")
                elif isinstance(v, bool):
                    row.append("true" if v else "false")
                elif isinstance(v, (list, dict)):
                    row.append(json.dumps(sanitize_strict_json(v), ensure_ascii=False, allow_nan=False))
                elif isinstance(v, str) and _FORMULA_RE.match(v):
                    row.append("'" + v)
                else:
                    v = _safe_float_token(v)
                    row.append(str(v))
            w.writerow(row)
    os.replace(tmp, path)


# ---------------------------------------------------------------------------
# Main export hook
# ---------------------------------------------------------------------------

def export_quality(out_dir, progress, records, requested, *, run_id, stopped_reason=None, html_for=None, is_import=False):
    os.makedirs(out_dir, exist_ok=True)
    raw_rows = []
    normalized_rows = []
    all_issues = []

    seen_ids = set()

    for idx, rec in enumerate(records, start=2):
        csv_line = rec.get("_csv_line", idx)
        try:
            url = rec.get("source_url")
            entry = (progress or {}).get(url, {})
            html = html_for(url) if html_for else None
            prov = build_provenance(rec, entry, run_id=run_id, parser_version=PARSER_VERSION, html=html, is_import=is_import)

            raw_row = dict(rec)
            raw_row.pop("_csv_line", None)
            raw_row["provenance"] = prov
            raw_row["raw_fidelity"] = "parser_filtered"

            norm_row = normalize_record(raw_row, prov)
            row_issues = detect_issues(raw_row, norm_row, csv_line=csv_line, run_id=run_id)

            # Check duplicate ID within this export
            fid = norm_row.get("foody_id")
            if fid is not None:
                if fid in seen_ids:
                    row_issues.append({
                        "issue_id": f"{fid}:duplicate_id:L{csv_line}",
                        "foody_id": fid,
                        "name": norm_row.get("name"),
                        "csv_line": csv_line,
                        "severity": "info",
                        "issue_code": "duplicate_id",
                        "field": "foody_id",
                        "raw_min": None,
                        "raw_max": None,
                        "detail": f"duplicate foody_id {fid} in export",
                        "source_url": norm_row.get("source_url"),
                        "run_id": run_id,
                    })
                else:
                    seen_ids.add(fid)

            # If rec already has import issues attached, add them first for this row
            prior_issues = rec.pop("_import_issues", [])
            row_issues = prior_issues + row_issues

            raw_rows.append(raw_row)
            if entry.get("enrichment"):
                norm_row["enrichment"] = entry["enrichment"]
            elif rec.get("enrichment"):
                norm_row["enrichment"] = rec["enrichment"]

            normalized_rows.append(norm_row)
            all_issues.extend(row_issues)
        except Exception as exc:
            foody_id = rec.get("foody_id")
            fid_safe = foody_id if (isinstance(foody_id, int) and not isinstance(foody_id, bool)) else None
            name = rec.get("name")
            err_issue = {
                "issue_id": f"{fid_safe or 'row' + str(csv_line)}:quality_internal_error:L{csv_line}",
                "foody_id": fid_safe,
                "name": name,
                "csv_line": csv_line,
                "severity": "error",
                "issue_code": "quality_internal_error",
                "field": None,
                "raw_min": None,
                "raw_max": None,
                "detail": f"{exc.__class__.__name__}: {exc}",
                "source_url": rec.get("source_url"),
                "run_id": run_id,
            }
            all_issues.append(err_issue)
            raw_row = dict(rec)
            raw_row.pop("_csv_line", None)
            raw_row["provenance"] = {
                "parser_version": PARSER_VERSION,
                "quality_schema_version": QUALITY_SCHEMA_VERSION,
                "run_id": run_id,
                "source_url": rec.get("source_url"),
                "final_url": None,
                "fetched_at": rec.get("fetched_at"),
                "parsed_at": None,
                "raw_content_hash": None,
                "text_snapshot_hash": None,
                "hash_basis": None,
                "http_status": None,
                "source_updated_at": None,
                "verified_at": None,
                "verification_method": None,
                "fields": field_presence(None),
            }
            raw_row["raw_fidelity"] = "parser_filtered"
            raw_rows.append(raw_row)
            norm_fallback = {
                "foody_id": fid_safe,
                "name": name,
                "source_url": rec.get("source_url"),
                "address": rec.get("address"),
                "district": rec.get("district"),
                "city": rec.get("city"),
                "price_min_raw": _safe_float_token(rec.get("price_min_vnd")),
                "price_max_raw": _safe_float_token(rec.get("price_max_vnd")),
                "price_status": "missing",
                "price_min_vnd_norm": None,
                "price_max_vnd_norm": None,
                "price_semantics": "venue price range, not individual dish or per-person guaranteed budget",
                "price_verified": False,
                "opening_hours_raw": rec.get("opening_hours_raw"),
                "hours_status": "malformed",
                "hours_intervals_count": 0,
                "hours_day_codes_raw": [],
                "hours_crosses_midnight_raw": False,
                "hours_schedule_norm": None,
                "source_flags": rec.get("source_flags") if isinstance(rec.get("source_flags"), dict) else {},
                "source_flags_semantics": "unknown",
                "operating_status": "unknown",
                "operating_status_evidence": None,
                "lat": None,
                "lon": None,
                "geo_status": "missing",
                "parser_version": PARSER_VERSION,
                "raw_content_hash": None,
                "fetched_at": rec.get("fetched_at"),
                "source_updated_at": None,
                "verified_at": None,
                "verification_method": None,
                "quality_schema_version": QUALITY_SCHEMA_VERSION,
                "run_id": run_id,
                "search_eligible": bool(fid_safe and name),
                "location_eligible": False,
                "price_filter_eligible": False,
                "budget_eligible": False,
                "hours_eligible": False,
                "tour_eligible": False,
            }
            normalized_rows.append(norm_fallback)

    quality_rep = build_quality_report(
        progress, requested, raw_rows, normalized_rows, all_issues,
        run_id=run_id, stopped_reason=stopped_reason, is_import=is_import
    )

    _atomic_write(os.path.join(out_dir, "restaurants_raw.json"), dumps_strict_json(raw_rows))
    _atomic_write(os.path.join(out_dir, "restaurants_normalized.json"), dumps_strict_json(normalized_rows))
    export_normalized_csv(normalized_rows, os.path.join(out_dir, "restaurants_normalized.csv"))
    _atomic_write(os.path.join(out_dir, "issues.json"), dumps_strict_json(all_issues))
    export_issues_csv(all_issues, os.path.join(out_dir, "issues.csv"))
    _atomic_write(os.path.join(out_dir, "quality_report.json"), dumps_strict_json(quality_rep))

    return quality_rep


# ---------------------------------------------------------------------------
# Offline tolerant import & classification
# ---------------------------------------------------------------------------

_JSON_COLS = {
    "opening_hours_raw", "source_flags", "h1_names", "parse_warnings",
    "field_freshness_unknown", "foody_id", "lat", "lon",
    "price_min_vnd", "price_max_vnd",
}


def import_and_classify(input_path, out_dir=None, *, run_id=None):
    """Tolerantly import an existing CSV or JSON file/directory and write quality outputs."""
    input_path = str(input_path)
    if os.path.isdir(input_path):
        csv_candidate = os.path.join(input_path, "restaurants.csv")
        json_candidate = os.path.join(input_path, "restaurants.json")
        if os.path.isfile(csv_candidate):
            file_to_read = csv_candidate
        elif os.path.isfile(json_candidate):
            file_to_read = json_candidate
        else:
            raise FileNotFoundError(f"No restaurants.csv or restaurants.json found in {input_path}")
    else:
        file_to_read = input_path

    if not out_dir:
        out_dir = os.path.dirname(os.path.abspath(file_to_read))
    os.makedirs(out_dir, exist_ok=True)

    if not run_id:
        run_id = f"cli-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}"

    records = []
    rows_read = 0
    rows_invalid = 0

    if file_to_read.endswith(".csv"):
        with open(file_to_read, encoding="utf-8-sig", newline="") as f:
            reader = csv.reader(f)
            try:
                header = next(reader)
            except StopIteration:
                header = []
            
            header_map = {col: i for i, col in enumerate(header)}
            
            while True:
                line_before = reader.line_num + 1
                try:
                    row = next(reader)
                except StopIteration:
                    break
                rows_read += 1
                csv_line = line_before

                rec = {"_csv_line": csv_line}
                # Preserve all raw cells including extra cells beyond header
                import_original = {}
                for i, col in enumerate(header):
                    import_original[col] = row[i] if i < len(row) else ""
                for i in range(len(header), len(row)):
                    import_original[f"_extra_{i}"] = row[i]
                import_original["_raw_cells"] = list(row)
                rec["import_original"] = import_original

                is_row_invalid = False
                invalid_detail = []

                if len(row) != len(header):
                    is_row_invalid = True
                    invalid_detail.append(f"column count mismatch: expected {len(header)}, got {len(row)}")

                for col in FIELDS:
                    idx = header_map.get(col)
                    if idx is None or idx >= len(row):
                        rec[col] = None
                        continue
                    v = row[idx]
                    if v == "":
                        rec[col] = None
                    elif col in _JSON_COLS:
                        try:
                            rec[col] = json.loads(v)
                        except Exception as exc:
                            is_row_invalid = True
                            truncated_val = str(v)[:500]
                            invalid_detail.append(f"{col} JSON decode error: {exc}; raw: {truncated_val}")
                            rec[col] = None
                    elif v.startswith("'") and _FORMULA_RE.match(v):
                        rec[col] = v[1:]
                    else:
                        rec[col] = v

                fid = rec.get("foody_id")
                if fid is None or isinstance(fid, bool) or not isinstance(fid, int) or fid <= 0:
                    is_row_invalid = True
                    invalid_detail.append(f"invalid or missing foody_id: {fid!r}")

                rec["_import_issues"] = []
                if is_row_invalid:
                    rows_invalid += 1
                    fid_safe = fid if (isinstance(fid, int) and not isinstance(fid, bool)) else None
                    rec["_import_issues"].append({
                        "issue_id": f"{fid_safe or 'row' + str(csv_line)}:import_row_invalid:L{csv_line}",
                        "foody_id": fid_safe,
                        "name": rec.get("name"),
                        "csv_line": csv_line,
                        "severity": "error",
                        "issue_code": "import_row_invalid",
                        "field": None,
                        "raw_min": _safe_float_token(rec.get("price_min_vnd")),
                        "raw_max": _safe_float_token(rec.get("price_max_vnd")),
                        "detail": f"line {csv_line}: " + "; ".join(invalid_detail),
                        "source_url": rec.get("source_url"),
                        "run_id": run_id,
                    })

                records.append(rec)
    else:
        with open(file_to_read, encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, list):
            if not isinstance(data, dict):
                raise ValueError("JSON input must be an array of records or a single record object")
            data = [data]

        for idx, item in enumerate(data, start=2):
            rows_read += 1
            csv_line = idx
            rec = {"_csv_line": csv_line}
            if isinstance(item, dict):
                rec.update(item)
                rec["import_original"] = dict(item)
                rec["_csv_line"] = csv_line
            else:
                rec["import_original"] = item

            fid = rec.get("foody_id")
            rec["_import_issues"] = []
            if fid is None or isinstance(fid, bool) or not isinstance(fid, int) or fid <= 0:
                rows_invalid += 1
                fid_safe = fid if (isinstance(fid, int) and not isinstance(fid, bool)) else None
                rec["_import_issues"].append({
                    "issue_id": f"{fid_safe or 'row' + str(csv_line)}:import_row_invalid:L{csv_line}",
                    "foody_id": fid_safe,
                    "name": rec.get("name"),
                    "csv_line": csv_line,
                    "severity": "error",
                    "issue_code": "import_row_invalid",
                    "field": None,
                    "raw_min": _safe_float_token(rec.get("price_min_vnd")),
                    "raw_max": _safe_float_token(rec.get("price_max_vnd")),
                    "detail": f"line {csv_line}: invalid or missing foody_id: {fid!r}",
                    "source_url": rec.get("source_url"),
                    "run_id": run_id,
                })
            records.append(rec)

    # Now export quality with is_import=True
    quality_rep = export_quality(
        out_dir, progress={}, records=records, requested=[],
        run_id=run_id, is_import=True
    )

    quality_rep["import"] = {
        "rows_read": rows_read,
        "rows_invalid": rows_invalid,
    }
    _atomic_write(os.path.join(out_dir, "quality_report.json"), dumps_strict_json(quality_rep))

    return quality_rep
