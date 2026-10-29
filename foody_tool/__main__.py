"""CLI: python -X utf8 -m foody_tool collect --urls-file urls.txt --out-dir out"""
import argparse
import json
import os
import sys

from . import collector as C
from . import exporter


def _collect(args):
    urls = C.load_url_file(args.urls_file)
    if args.max_urls > C.MAX_URLS:
        print(f"--max-urls capped at {C.MAX_URLS}", file=sys.stderr)
    col = C.Collector(args.out_dir, min_interval=args.min_interval, timeout=args.timeout,
                      max_retries=args.max_retries)
    requested, stopped = col.run(urls, max_urls=args.max_urls, refresh=args.refresh,
                                 retry_failed=args.retry_failed)
    report = exporter.export_all(args.out_dir, col.progress, col.records(requested),
                                 requested, stopped)
    print(json.dumps({"requested": report["requested_urls"],
                      "unique_restaurants_exported": report["records_exported"],
                      "outcomes": report["outcomes"], "partial": report["partial"],
                      "network_requests": col.request_count,
                      "stopped_reason": stopped}, ensure_ascii=False))
    return 3 if stopped else (2 if report["partial"] else 0)


def _quality(args):
    input_path = args.input or args.input_pos
    if not input_path:
        print("error: --input or input directory/file required", file=sys.stderr)
        return 1
    out_dir = args.out_dir or (input_path if os.path.isdir(input_path) else os.path.dirname(input_path) or ".")
    from .quality import import_and_classify
    qrep = import_and_classify(input_path, out_dir=out_dir)
    print(json.dumps({
        "quality_schema_version": qrep.get("quality_schema_version"),
        "run_id": qrep.get("run_id"),
        "unique_venues_exported": qrep["funnel"]["unique_venues_exported"],
        "price_status_counts": qrep.get("price_status_counts"),
        "issue_counts_by_severity": qrep.get("issue_counts_by_severity"),
        "import": qrep.get("import"),
        "partial": qrep.get("partial"),
    }, ensure_ascii=False))
    return 0


def _enrich(args):
    from .enrich_cache import enrich_job
    report = enrich_job(args.job_dir, network=args.fetch_missing)
    print(json.dumps({
        "job_dir": report["job_dir"],
        "pages_total": report["pages_total"],
        "pages_parsed": report["pages_parsed"],
        "network_requests": report["network_requests"],
        "needs_fetch_count": len(report["needs_fetch"]),
    }, ensure_ascii=False))
    return 0 if report["pages_failed"] == 0 else 1


def main(argv=None):
    args_list = list(sys.argv[1:] if argv is None else argv)
    if args_list and args_list[0] == "serve":
        from .app import main as serve
        return serve(args_list[1:])
    ap = argparse.ArgumentParser(prog="foody_tool")
    sub = ap.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("collect", help="collect restaurant pages listed in a URL file")
    c.add_argument("--urls-file", required=True)
    c.add_argument("--out-dir", required=True)
    c.add_argument("--max-urls", type=int, default=C.MAX_URLS)
    c.add_argument("--min-interval", type=float, default=C.MIN_INTERVAL)
    c.add_argument("--timeout", type=float, default=20.0)
    c.add_argument("--max-retries", type=int, default=2)
    c.add_argument("--refresh", action="store_true", help="ignore cache and re-fetch")
    c.add_argument("--retry-failed", action="store_true", help="retry URLs with final failures")
    c.set_defaults(func=_collect)

    q = sub.add_parser("quality", help="run quality checks and classify existing CSV/JSON data")
    q.add_argument("input_pos", nargs="?", default=None, help="input file or directory (optional positional)")
    q.add_argument("--input", default=None, help="input CSV, JSON, or directory containing export files")
    q.add_argument("--out-dir", default=None, help="directory to write quality output files to")
    q.set_defaults(func=_quality)

    e = sub.add_parser("enrich", help="enrich restaurant data from cached HTML")
    e.add_argument("--job-dir", required=True, help="job directory containing urls.json and cache/")
    e.add_argument("--fetch-missing", action="store_true", help="fetch missing cache pages over network")
    e.set_defaults(func=_enrich)

    args = ap.parse_args(args_list)
    try:
        return args.func(args)
    except (OSError, ValueError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
