"""Job enrichment from local cache or conservative live fetch.

Reads urls.json and cache/*.html, produces:
- restaurants_enriched.csv
- restaurants_enriched.json
- enrichment_report.json
"""
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path

from .collector import Collector, normalize_restaurant_url, UrlError
from .enrich import (
    parse_enrichment,
    SCHEMA_VERSION,
    PARSER_VERSION,
    FIELD_PRESENCE_KEYS,
    KNOWN_AMENITIES,
)
from .exporter import (
    export_enriched_csv,
    export_enriched_json,
    record_to_enriched_row,
    ENRICHED_FIELDS,
)
from .parser import parse_restaurant

REPORT_SCHEMA_VERSION = "foody-enrichment-report/1"


def cache_file_for_url(cache_dir, url):
    """Derive deterministic cache path from restaurant URL."""
    filename = hashlib.sha256(url.encode("utf-8")).hexdigest()[:20] + ".html"
    return os.path.join(cache_dir, filename)


def enrich_job(job_dir, *, network=False, collector_factory=Collector):
    """Enrich a job directory using cached HTML pages.

    Parameters:
        job_dir: Directory containing urls.json and cache/
        network: If True, fetches missing pages via Collector (min_interval >= 2.0s).
                 Defaults to False (zero network requests).
        collector_factory: Callable returning Collector instance. Defaults to Collector.

    Returns:
        Dict representing enrichment_report.json
    """
    job_path = Path(job_dir)
    cache_dir = job_path / "cache"

    urls = []
    urls_file = job_path / "urls.json"
    if urls_file.is_file():
        try:
            raw_urls = json.loads(urls_file.read_text(encoding="utf-8"))
            if isinstance(raw_urls, list):
                urls = raw_urls
        except Exception:
            urls = []

    if not urls:
        prog_file = job_path / "progress.json"
        if prog_file.is_file():
            try:
                prog = json.loads(prog_file.read_text(encoding="utf-8"))
                if isinstance(prog, dict):
                    urls = list(prog.keys())
            except Exception:
                urls = []

    # Map existing restaurants.json if available
    legacy_map = {}
    rest_file = job_path / "restaurants.json"
    if rest_file.is_file():
        try:
            stored = json.loads(rest_file.read_text(encoding="utf-8"))
            if isinstance(stored, list):
                for r in stored:
                    if isinstance(r, dict) and r.get("source_url"):
                        legacy_map[r["source_url"]] = r
        except Exception:
            pass

    field_presence_counts = {
        f: {"present": 0, "absent": 0, "ambiguous": 0}
        for f in FIELD_PRESENCE_KEYS
    }
    amenity_status_counts = {
        k: {"yes": 0, "no": 0, "unknown": 0}
        for k in KNOWN_AMENITIES
    }

    needs_fetch = []
    pages_with_cache = 0
    pages_parsed = 0
    pages_failed = 0
    warnings_total = 0
    network_requests = 0

    enriched_records = []

    # Identify cached vs missing
    cached_map = {}
    for url in urls:
        c_path = cache_file_for_url(str(cache_dir), url)
        if os.path.isfile(c_path):
            pages_with_cache += 1
            cached_map[url] = c_path
        else:
            needs_fetch.append(url)

    # Optional network fetch if requested
    if network and needs_fetch:
        collector = collector_factory(str(job_path), min_interval=2.0)
        remaining_needs_fetch = []
        for idx, u in enumerate(needs_fetch):
            try:
                st = collector.process(u)
                if st == "blocked":
                    remaining_needs_fetch.extend(needs_fetch[idx:])
                    break
                c_path = cache_file_for_url(str(cache_dir), u)
                if os.path.isfile(c_path):
                    pages_with_cache += 1
                    cached_map[u] = c_path
                else:
                    remaining_needs_fetch.append(u)
            except Exception:
                remaining_needs_fetch.append(u)
        network_requests = collector.request_count
        needs_fetch = remaining_needs_fetch

    # Process each URL in order
    for url in urls:
        c_path = cached_map.get(url)
        if not c_path or not os.path.isfile(c_path):
            continue

        try:
            with open(c_path, "r", encoding="utf-8") as f:
                html_text = f.read()

            en = parse_enrichment(html_text, parsed_from="cached_html")
            warnings_total += len(en.get("warnings", []))

            # Legacy metadata
            leg = dict(legacy_map.get(url) or {})
            fetched_at = leg.get("fetched_at")
            if not fetched_at:
                try:
                    fetched_at = datetime.fromtimestamp(
                        os.path.getmtime(c_path), timezone.utc
                    ).isoformat()
                except Exception:
                    fetched_at = datetime.now(timezone.utc).isoformat()

            # If leg is missing basic restaurant fields, parse them from cached HTML
            if not leg or not leg.get("foody_id") or not leg.get("name") or not leg.get("address") or leg.get("price_min_vnd") is None:
                try:
                    parsed_legacy = parse_restaurant(html_text, url, fetched_at)
                    if leg:
                        for k, v in parsed_legacy.items():
                            leg.setdefault(k, v)
                    else:
                        leg = parsed_legacy
                except Exception:
                    pass

            rec = dict(leg)
            rec["source_url"] = url
            rec["enrichment"] = en
            if not rec.get("fetched_at"):
                rec["fetched_at"] = fetched_at

            enriched_records.append(rec)
            pages_parsed += 1

            for fld, val in en.get("field_presence", {}).items():
                if fld in field_presence_counts and val in field_presence_counts[fld]:
                    field_presence_counts[fld][val] += 1

            for a in en.get("amenities", []):
                k = a.get("key")
                st = a.get("status")
                if k in amenity_status_counts and st in amenity_status_counts[k]:
                    amenity_status_counts[k][st] += 1

        except Exception:
            pages_failed += 1

    # Export enriched files
    enriched_csv_path = str(job_path / "restaurants_enriched.csv")
    enriched_json_path = str(job_path / "restaurants_enriched.json")
    export_enriched_csv(enriched_records, enriched_csv_path)
    export_enriched_json(enriched_records, enriched_json_path)

    report = {
        "schema": REPORT_SCHEMA_VERSION,
        "schema_version": "foody-enriched-export/2",
        "columns": list(ENRICHED_FIELDS),
        "job_dir": str(Path(job_dir).resolve()),
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "pages_total": len(urls),
        "pages_with_cache": pages_with_cache,
        "pages_parsed": pages_parsed,
        "pages_failed": pages_failed,
        "needs_fetch": needs_fetch,
        "network_requests": network_requests,
        "field_presence_counts": field_presence_counts,
        "amenity_status_counts": amenity_status_counts,
        "warnings_total": warnings_total,
        "parser_version": PARSER_VERSION,
    }

    report_path = job_path / "enrichment_report.json"
    temp_report = report_path.with_suffix(".json.tmp")
    temp_report.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(temp_report, report_path)

    return report
