"""UTF-8 CSV/JSON export and completeness/failure report."""
import csv
import io
import json
import os
import re

FIELDS = [
    "foody_id", "name", "lat", "lon", "address", "district", "city",
    "opening_hours_raw", "price_min_vnd", "price_max_vnd", "source_url",
    "fetched_at", "price_semantics", "source_license", "field_freshness_unknown",
    "source_flags", "h1_names", "parse_warnings",
]
_FORMULA_RE = re.compile(r"^'*[=+@\t\r-]")
_JSON_COLS = {"opening_hours_raw", "source_flags", "h1_names", "parse_warnings",
              "field_freshness_unknown", "foody_id", "lat", "lon",
              "price_min_vnd", "price_max_vnd"}
COMPLETENESS_FIELDS = ["foody_id", "name", "lat", "lon", "address", "district", "city",
                       "opening_hours_raw", "price_min_vnd", "price_max_vnd"]


def _atomic_write(path, text):
    tmp = f"{path}.tmp"
    with open(tmp, "w", encoding="utf-8", newline="") as f:
        f.write(text)
    os.replace(tmp, path)


def export_json(records, path):
    rows = [{k: r.get(k) for k in FIELDS} for r in records]
    _atomic_write(path, json.dumps(rows, ensure_ascii=False, indent=2) + "\n")


def export_csv(records, path):
    tmp = f"{path}.tmp"
    with open(tmp, "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(FIELDS)
        current_line = 2
        for r in records:
            r["_csv_line"] = current_line
            row = []
            for k in FIELDS:
                v = r.get(k)
                if v is None:
                    row.append("")
                elif k in _JSON_COLS:
                    row.append(json.dumps(v, ensure_ascii=False))
                elif isinstance(v, str) and _FORMULA_RE.match(v):
                    row.append("'" + v)  # neutralise spreadsheet formulas; JSON stays canonical
                else:
                    row.append(v)
            sio = io.StringIO()
            sw = csv.writer(sio)
            sw.writerow(row)
            current_line += sio.getvalue().count("\n")
            w.writerow(row)
    os.replace(tmp, path)


def read_csv_records(path):
    """Decode an exported CSV back into record dicts (inverse of export_csv)."""
    out = []
    with open(path, encoding="utf-8", newline="") as f:
        for row in csv.DictReader(f):
            rec = {}
            for k in FIELDS:
                v = row[k]
                if v == "":
                    rec[k] = None
                elif k in _JSON_COLS:
                    rec[k] = json.loads(v)
                elif v.startswith("'") and _FORMULA_RE.match(v):
                    rec[k] = v[1:]
                else:
                    rec[k] = v
            out.append(rec)
    return out


def _present(v):
    return v is not None and v != "" and v != []


def _hours_usable(v):
    """At least one interval with both open and close present."""
    return isinstance(v, list) and any(
        isinstance(h, dict) and h.get("open") and h.get("close") for h in v)


def price_range_usable(r):
    """Both prices present, positive and ordered (min <= max). Raw 0/0 is NOT usable."""
    lo, hi = r.get("price_min_vnd"), r.get("price_max_vnd")
    return (isinstance(lo, (int, float)) and isinstance(hi, (int, float))
            and not isinstance(lo, bool) and not isinstance(hi, bool) and 0 < lo <= hi)


def build_report(progress, records, requested, stopped_reason=None):
    """progress: {url: entry}; records: exported records; requested: ordered URL list."""
    outcomes = {}
    for url in requested:
        status = (progress.get(url) or {}).get("status", "pending")
        outcomes[status] = outcomes.get(status, 0) + 1
    n = len(records)
    completeness = {}
    for f in COMPLETENESS_FIELDS:
        ok_fn = _hours_usable if f == "opening_hours_raw" else _present
        have = sum(1 for r in records if ok_fn(r.get(f)))
        completeness[f] = {"present": have, "total": n,
                           "rate": round(have / n, 4) if n else None}
    usable_price = sum(1 for r in records if price_range_usable(r))
    zero_price = sum(1 for r in records if r.get("price_min_vnd") == 0 or r.get("price_max_vnd") == 0)
    failures = [
        {"url": u, "status": progress[u].get("status"),
         "http_status": progress[u].get("http_status"),
         "error": progress[u].get("error"), "attempts": progress[u].get("attempts"),
         "duplicate_of": progress[u].get("duplicate_of")}
        for u in requested
        if u in progress and progress[u].get("status") != "ok"
    ]
    return {
        "requested_urls": len(requested),
        "records_exported": n,
        "unique_restaurants": n,
        "usable_records_note": "duplicate_id URLs resolve to their canonical record; each foody_id once",
        "outcomes": outcomes,
        "stopped_reason": stopped_reason,
        "partial": bool(stopped_reason) or any(
            s not in ("ok", "duplicate_id") for s in outcomes),
        "completeness": completeness,
        "usable_positive_price_range": {
            "usable": usable_price, "total": n,
            "rate": round(usable_price / n, 4) if n else None,
            "raw_zero_price_records": zero_price,
            "note": "requires both prices positive and min <= max; raw 0/0 is kept as published and "
                    "means the budget cannot be planned from this value (not inferred as free or missing)"},
        "records_with_parse_warnings": sum(1 for r in records if r.get("parse_warnings")),
        "failures": failures,
        "notes": "HTTP 200 is not extraction success; completeness counts parsed non-empty fields only. "
                 "Raw field presence (completeness) differs from usable_positive_price_range. "
                 "Opening hours are raw source values, not a week schedule. "
                 "Foody permission for reuse has not been obtained; do not publish.",
    }


def export_all(out_dir, progress, records, requested, stopped_reason=None, run_id=None, quality=True):
    os.makedirs(out_dir, exist_ok=True)
    export_json(records, os.path.join(out_dir, "restaurants.json"))
    export_csv(records, os.path.join(out_dir, "restaurants.csv"))
    report = build_report(progress, records, requested, stopped_reason)
    if quality:
        try:
            from .quality import export_quality
            from datetime import datetime, timezone
            if not run_id:
                run_id = f"cli-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}"
            q_rep = export_quality(out_dir, progress, records, requested, run_id=run_id, stopped_reason=stopped_reason)
            report["quality"] = q_rep
        except Exception as exc:
            report["quality"] = {"error": f"{type(exc).__name__}: {exc}"}
    has_enrichment = False
    for r in records:
        if r.get("enrichment"):
            has_enrichment = True
            break
        u = r.get("source_url")
        if u and progress and progress.get(u, {}).get("enrichment"):
            r["enrichment"] = progress[u]["enrichment"]
            has_enrichment = True

    if has_enrichment:
        export_enriched_json(records, os.path.join(out_dir, "restaurants_enriched.json"))
        export_enriched_csv(records, os.path.join(out_dir, "restaurants_enriched.csv"))

    _atomic_write(os.path.join(out_dir, "report.json"),
                  json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    return report


ENRICHED_FIELDS = [
    "foody_id", "name", "cuisine_styles", "venue_types", "dish_groups", "suitable_meals",
    "audiences", "prep_time_raw", "prep_time_min", "prep_time_max", "capacity_raw",
    "capacity_value", "holiday_raw", "rating_value", "rating_scale_max", "review_count",
    "rating_quality", "rating_location", "rating_service", "rating_space", "rating_price",
    "amenities_yes", "amenities_no", "amenities_unknown", "source_url",
    "address", "district", "city", "lat", "lon", "geo_status",
    "price_min_raw", "price_max_raw", "price_status", "price_min_vnd_norm", "price_max_vnd_norm",
    "price_semantics", "opening_hours_raw", "hours_displayed", "hours_status",
    "hours_intervals_count", "hours_day_codes_raw", "fetched_at",
]
ENRICHED_JSON_COLS = {"opening_hours_raw", "hours_day_codes_raw"}


def format_hours_displayed(opening_hours_raw):
    """Format raw opening hours intervals into text joined by ' | '."""
    if not opening_hours_raw or not isinstance(opening_hours_raw, list):
        return None
    intervals = []
    for h in opening_hours_raw:
        if isinstance(h, dict):
            op = h.get("open")
            cl = h.get("close")
            if op and cl:
                intervals.append(f"{op} - {cl}")
            elif op:
                intervals.append(str(op))
            elif cl:
                intervals.append(str(cl))
        elif isinstance(h, str) and h.strip():
            intervals.append(h.strip())
    return " | ".join(intervals) if intervals else None


def record_to_enriched_row(rec):
    """Normalize a record (flat or nested with enrichment) into a flat enriched row with 43 columns."""
    from .quality import normalize_record

    en = rec.get("enrichment") if isinstance(rec.get("enrichment"), dict) else rec
    rating = en.get("rating") if isinstance(en.get("rating"), dict) else {}
    criteria = rating.get("criteria") if isinstance(rating.get("criteria"), dict) else {}
    amenities = en.get("amenities") if isinstance(en.get("amenities"), list) else []

    def _extract_text_list(val, en_key):
        if isinstance(rec.get(en_key), str) and rec.get(en_key) != "":
            return rec[en_key]
        if isinstance(val, list):
            return " | ".join(x.get("text", "") for x in val if isinstance(x, dict) and x.get("text"))
        return ""

    cuisine_styles = _extract_text_list(en.get("cuisine_styles"), "cuisine_styles")
    venue_types = _extract_text_list(en.get("venue_types"), "venue_types")
    dish_groups = _extract_text_list(en.get("dish_groups"), "dish_groups")
    suitable_meals = _extract_text_list(en.get("suitable_meals"), "suitable_meals")
    audiences = _extract_text_list(en.get("audiences"), "audiences")

    if isinstance(rec.get("amenities_yes"), str) and rec.get("amenities_yes") != "":
        amenities_yes = rec["amenities_yes"]
    else:
        amenities_yes = " | ".join(a.get("label", "") for a in amenities if isinstance(a, dict) and a.get("status") == "yes" and a.get("label"))

    amenities_no = ""  # Kept for schema compatibility, always empty per V4_CONTRACT

    if isinstance(rec.get("amenities_unknown"), str) and rec.get("amenities_unknown") != "":
        amenities_unknown = rec["amenities_unknown"]
    else:
        amenities_unknown = " | ".join(a.get("label", "") for a in amenities if isinstance(a, dict) and a.get("status") == "unknown" and a.get("label"))

    rating_value = rec.get("rating_value") if rec.get("rating_value") is not None else rating.get("value")
    rating_scale_max = rec.get("rating_scale_max") if rec.get("rating_scale_max") is not None else rating.get("scale_max")
    review_count = rec.get("review_count") if rec.get("review_count") is not None else rating.get("review_count")
    rating_quality = rec.get("rating_quality") if rec.get("rating_quality") is not None else criteria.get("quality")
    rating_location = rec.get("rating_location") if rec.get("rating_location") is not None else criteria.get("location")
    rating_service = rec.get("rating_service") if rec.get("rating_service") is not None else criteria.get("service")
    rating_space = rec.get("rating_space") if rec.get("rating_space") is not None else criteria.get("space")
    rating_price = rec.get("rating_price") if rec.get("rating_price") is not None else criteria.get("price")

    prep_time_raw = en.get("prep_time_raw") if en.get("prep_time_raw") is not None else rec.get("prep_time_raw")
    prep_time_min = en.get("prep_time_min") if en.get("prep_time_min") is not None else rec.get("prep_time_min")
    prep_time_max = en.get("prep_time_max") if en.get("prep_time_max") is not None else rec.get("prep_time_max")
    capacity_raw = en.get("capacity_raw") if en.get("capacity_raw") is not None else rec.get("capacity_raw")
    capacity_value = en.get("capacity_value") if en.get("capacity_value") is not None else rec.get("capacity_value")
    holiday_raw = en.get("holiday_raw") if en.get("holiday_raw") is not None else rec.get("holiday_raw")

    # Appended normalized columns
    if "price_status" in rec and "geo_status" in rec and "hours_status" in rec:
        norm = rec
    else:
        prov = {"fetched_at": rec.get("fetched_at"), "parser_version": "0.3.0"}
        norm = normalize_record(rec, prov)

    foody_id = rec.get("foody_id") or norm.get("foody_id")
    name = rec.get("name") or norm.get("name")
    source_url = rec.get("source_url") or norm.get("source_url")

    address = norm.get("address") if norm.get("address") is not None else rec.get("address")
    district = norm.get("district") if norm.get("district") is not None else rec.get("district")
    city = norm.get("city") if norm.get("city") is not None else rec.get("city")
    lat = norm.get("lat") if norm.get("lat") is not None else rec.get("lat")
    lon = norm.get("lon") if norm.get("lon") is not None else rec.get("lon")
    geo_status = norm.get("geo_status") if norm.get("geo_status") is not None else rec.get("geo_status")

    price_min_raw = norm.get("price_min_raw") if norm.get("price_min_raw") is not None else rec.get("price_min_raw")
    price_max_raw = norm.get("price_max_raw") if norm.get("price_max_raw") is not None else rec.get("price_max_raw")
    price_status = norm.get("price_status") if norm.get("price_status") is not None else rec.get("price_status")
    price_min_vnd_norm = norm.get("price_min_vnd_norm") if norm.get("price_min_vnd_norm") is not None else rec.get("price_min_vnd_norm")
    price_max_vnd_norm = norm.get("price_max_vnd_norm") if norm.get("price_max_vnd_norm") is not None else rec.get("price_max_vnd_norm")
    price_semantics = norm.get("price_semantics") if norm.get("price_semantics") is not None else rec.get("price_semantics")

    opening_hours_raw = norm.get("opening_hours_raw") if "opening_hours_raw" in norm else rec.get("opening_hours_raw")
    hours_status = norm.get("hours_status") if norm.get("hours_status") is not None else rec.get("hours_status")
    hours_intervals_count = norm.get("hours_intervals_count") if norm.get("hours_intervals_count") is not None else rec.get("hours_intervals_count")
    hours_day_codes_raw = norm.get("hours_day_codes_raw") if norm.get("hours_day_codes_raw") is not None else rec.get("hours_day_codes_raw")

    hours_displayed = rec.get("hours_displayed")
    if not hours_displayed:
        hours_displayed = format_hours_displayed(opening_hours_raw)

    fetched_at = rec.get("fetched_at") or norm.get("fetched_at")

    return {
        "foody_id": foody_id,
        "name": name,
        "cuisine_styles": cuisine_styles,
        "venue_types": venue_types,
        "dish_groups": dish_groups,
        "suitable_meals": suitable_meals,
        "audiences": audiences,
        "prep_time_raw": prep_time_raw,
        "prep_time_min": prep_time_min,
        "prep_time_max": prep_time_max,
        "capacity_raw": capacity_raw,
        "capacity_value": capacity_value,
        "holiday_raw": holiday_raw,
        "rating_value": rating_value,
        "rating_scale_max": rating_scale_max,
        "review_count": review_count,
        "rating_quality": rating_quality,
        "rating_location": rating_location,
        "rating_service": rating_service,
        "rating_space": rating_space,
        "rating_price": rating_price,
        "amenities_yes": amenities_yes,
        "amenities_no": amenities_no,
        "amenities_unknown": amenities_unknown,
        "source_url": source_url,
        "address": address,
        "district": district,
        "city": city,
        "lat": lat,
        "lon": lon,
        "geo_status": geo_status,
        "price_min_raw": price_min_raw,
        "price_max_raw": price_max_raw,
        "price_status": price_status,
        "price_min_vnd_norm": price_min_vnd_norm,
        "price_max_vnd_norm": price_max_vnd_norm,
        "price_semantics": price_semantics,
        "opening_hours_raw": opening_hours_raw,
        "hours_displayed": hours_displayed,
        "hours_status": hours_status,
        "hours_intervals_count": hours_intervals_count,
        "hours_day_codes_raw": hours_day_codes_raw,
        "fetched_at": fetched_at,
    }


def export_enriched_json(records, path):
    rows = [record_to_enriched_row(r) for r in records]
    _atomic_write(path, json.dumps(rows, ensure_ascii=False, indent=2) + "\n")


def export_enriched_csv(records, path):
    tmp = f"{path}.tmp"
    with open(tmp, "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(ENRICHED_FIELDS)
        for r in records:
            row_dict = record_to_enriched_row(r)
            row = []
            for k in ENRICHED_FIELDS:
                v = row_dict.get(k)
                if v is None:
                    row.append("")
                elif k in ENRICHED_JSON_COLS:
                    row.append(json.dumps(v, ensure_ascii=False))
                elif isinstance(v, (list, dict)):
                    row.append(json.dumps(v, ensure_ascii=False))
                elif isinstance(v, str) and _FORMULA_RE.match(v):
                    row.append("'" + v)
                else:
                    row.append(v)
            w.writerow(row)
    os.replace(tmp, path)

