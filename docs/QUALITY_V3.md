# Quality contract v0.3 (`QUALITY_SCHEMA_VERSION = "3.0"`)

Implementation note (final acceptance): source `parser_version`/`parsed_at`/`final_url` stay NULL when not recorded; global report `parser_version` denotes the quality implementation. Counter `metric_basis` is a saved URL-state snapshot, not a new crawl; offline operations have an explicit `execution_mode`. Missing retry values stay unknown. Current cached text can supply an observed text hash/key presence, never an invented HTTP-byte hash. JSON record arrays preserve non-object item types as invalid rows; unsupported scalar JSON roots raise an explicit input error. See `reports/v3/ACCEPTANCE_VI.md` for final evidence; older design examples below are superseded where they differ.

Status: design for Antigravity to implement. Owner of this doc: Claude. Sources: `foody_tool/{parser,exporter,jobs,app}.py`, user audit `BAO_CAO_BAN_GIAO_DOI_TOOL.md`, `price_issues_200.csv`.

## 0. Hard rules
1. **v1 outputs unchanged**: `restaurants.csv`, `restaurants.json`, `report.json` keep the current 18 `FIELDS` and current report keys. The only allowed addition to `report.json` is one new key `quality`. `exporter.FIELDS`, `read_csv_records` and the `parse_restaurant` return value are NOT modified.
2. v3 is **additive files** written next to the v1 files by `export_all` (after v1 files, same atomic write helper).
3. **Never guess**: no swapping min/max, no 350000 -> 35000, no 0 -> free, no day-code -> weekday, no closed/open from flags, no 24/7, no menu/dish/category from name, no `verified_at` from `fetched_at`. Unknown stays `null` + a status.
4. Raw is preserved verbatim; normalized is derived by pure functions from raw record + provenance only (re-derivable offline from `restaurants.json`).
5. Nothing is silently dropped: a bad row yields an issue; the venue still appears in every file.
6. No architecture growth: one new module `foody_tool/quality.py` (pure, stdlib only), small hooks in `exporter.py`, `jobs.py`, `app.py`, and two extra fields in `collector.py` progress entries.

## 1. New output files (per job dir / `--out`)
| File | Content |
|---|---|
| `restaurants_raw.json` | **Raw layer**, one object per venue: all 18 v1 fields + `provenance` (section 4). No derived values. |
| `restaurants_normalized.json` / `.csv` | **Normalized layer**, one row per venue (section 3). |
| `issues.json` / `issues.csv` | One row per issue (section 5). |
| `quality_report.json` | Run summary, denominators, eligibility counts (sections 6-7). Also copied under `report.json["quality"]`. |

CSV rules identical to v1 (UTF-8 no BOM, formula neutralisation with leading `'`, JSON-encoded structured cells, empty = null). Rows keep **original input record order** (never sorted by ID). Re-export of the same input must be byte-identical except `generated_at`.

## 2. Raw vs normalized
- Raw = what the parser extracted (`price_min_vnd`, `price_max_vnd`, `opening_hours_raw`, `source_flags`, ...). `parse_restaurant` already drops non-numeric/negative/out-of-range values and records a warning; the quality layer maps those warnings to issues (section 5) so a dropped value shows as `missing`/`nonfinite`, never silently.
- Normalized = decisions: a status per field family plus a value that is `null` unless the status says usable.

## 3. Normalized row schema
`foody_id` (int), `name`, `source_url`, then:

### 3.1 Price
`price_min_raw`, `price_max_raw` (copies of raw, may be null), plus `price_status`, evaluated in this order:

| status | condition | `price_min_vnd_norm` / `price_max_vnd_norm` |
|---|---|---|
| `nonfinite` | a raw value is NaN/+-Inf/non-numeric/negative/bool, or parser warning `invalid PriceMin/PriceMax ... dropped` | null / null |
| `missing` | either raw null/absent (and not nonfinite) | null / null |
| `unknown_zero` | both raw == 0 (the `0-0` case) | null / null (never "free") |
| `partial_zero` | exactly one raw == 0, the other > 0 | null / null |
| `invalid_range` | both > 0 and min > max (**reversed**) | null / null; raw kept, NOT swapped |
| `ok` | both finite and `0 < min <= max` (**positive ordered**, min==max allowed) | copied (int VND) |

`price_semantics` = parser constant (venue range, not dish/per-person). `ok` means structurally valid, not verified; `price_verified` is always `false` in v3.

### 3.2 Opening hours
`opening_hours_raw` (verbatim list), `hours_status`, `hours_intervals_count`, `hours_day_codes_raw` (sorted distinct `day_of_week_raw`), `hours_crosses_midnight_raw` (bool observation), `hours_schedule_norm` (**always `null` in v3**).
- `hours_status`: `missing` (null/empty list) | `malformed` (any interval lacks open or close, or an OpeningTime/time warning exists) | `day_mapping_unknown` (>=1 well-formed interval; no evidence maps day codes to weekdays — all 220 audit intervals carry code `3`). Well-formed hours are therefore always `day_mapping_unknown` in v3.
- Multi-shift preserved: `hours_intervals_count == len(opening_hours_raw)`, order untouched. Missing schedule != closed. Near-all-day interval != 24/7. Overnight (close < open) only sets `hours_crosses_midnight_raw`; no schedule is built.
- `open_now` is not produced anywhere; consumers must treat it as `unknown`.

### 3.3 Business / source flags
`source_flags` (verbatim), `source_flags_semantics = "unknown"` (constant), `operating_status = "unknown"` (constant in v3; future values `open|closed|temporarily_closed` only with `operating_status_evidence`), `operating_status_evidence = null`.
`IsActive=false`, `IsInactive=true`, `RestaurantStatus=2` must NOT map to closed. Reported once per run in `quality_report.source_flag_semantics`, not per row.

### 3.4 Location
`geo_status` in `ok | missing | nonfinite | out_of_range | outside_hanoi_bbox` (bbox lat 20.5-21.5, lon 105.3-106.1; flag only, coordinates kept). `lat`/`lon` unchanged. `ok` does not mean entrance verified.

### 3.5 Provenance columns (also in raw)
`parser_version`, `raw_content_hash`, `fetched_at`, `source_updated_at` (null unless source provides it), `verified_at` (null), `verification_method` (null), `quality_schema_version`, `run_id`.

## 4. Provenance object (`restaurants_raw.json[].provenance`)
```json
{
  "parser_version": "0.3.0",
  "quality_schema_version": "3.0",
  "run_id": "<job id or cli-YYYYMMDDTHHMMSSZ>",
  "source_url": "...", "final_url": "...",
  "fetched_at": "2026-10-14T03:12:45Z",
  "parsed_at": "2026-10-14T03:12:46Z",
  "raw_content_hash": "sha256:<hex of exact response body bytes>",
  "http_status": 200,
  "source_updated_at": null, "verified_at": null, "verification_method": null,
  "fields": {
    "price_min_vnd":     {"source_key": "PriceMin",    "present": true},
    "price_max_vnd":     {"source_key": "PriceMax",    "present": true},
    "opening_hours_raw": {"source_key": "OpeningTime", "present": true},
    "lat":               {"source_key": "Latitude",    "present": true},
    "lon":               {"source_key": "Longtitude",  "present": true},
    "source_flags":      {"source_key": "IsActive,IsInactive,IsDelete,RestaurantStatus,IsVerifiedMap", "present": true}
  }
}
```
`fetched_at` is download time, never data freshness. `present` = key existed in `initData` (separates absent vs null vs dropped-by-parser). To avoid changing `parse_restaurant`, `quality.field_presence(html)` re-reads `initData` with the parser's `_INIT_RE` + `raw_decode`; when html is unavailable, `present: null` and issue `provenance_incomplete`. The hash is `hashlib.sha256(body).hexdigest()` computed in `Collector` where `res["body"]` is parsed and stored with `parsed_at` in the progress entry via `_set(...)`. Old entries lacking it -> `raw_content_hash: null` + `provenance_incomplete`. A changed hash on re-fetch updates the entry (and increments informational `fetch_count`).

## 5. Issues
Row schema (`issues.json` list / `issues.csv`): `issue_id` (`<foody_id>:<code>[:<field>]`), `foody_id`, `name`, `csv_line` (physical line in the v1 source CSV including header; see section 13), `severity` (`error|warning|info`), `issue_code`, `field`, `raw_min`, `raw_max` (price issues only), `detail`, `source_url`, `run_id`.

| `issue_code` | severity | trigger |
|---|---|---|
| `zero_price_unverified` | warning | `price_status=unknown_zero` (matches audit fixture code) |
| `invalid_price_range` | error | `price_status=invalid_range` (matches audit fixture code) |
| `partial_zero_price` | warning | `partial_zero` |
| `price_missing` | warning | `missing` |
| `price_nonfinite` | error | `nonfinite` |
| `hours_missing` | warning | `hours_status=missing` |
| `hours_malformed` | error | `malformed` |
| `geo_missing` / `geo_nonfinite` / `geo_out_of_range` / `geo_outside_hanoi_bbox` | warning / error / error / warning | `geo_status` |
| `parse_warning` | info | each v1 `parse_warnings` string not already mapped above (verbatim in `detail`) |
| `provenance_incomplete` | warning | missing hash or field presence |
| `timestamp_invalid` | error | `fetched_at` not ISO-8601 parseable |
| `duplicate_id` | info | URL resolved to an existing canonical `foody_id` (from progress) |

`hours_day_mapping_unknown` is **not** a per-row issue (would add 200 noise rows); it is a run-level count only. The audit oracle `price_issues_200.csv` columns (`csv_line,foody_id,name,issue_code,raw_min,raw_max,source_url`) are a subset of `issues.csv`, so a direct diff is possible.

## 6. Run metrics and denominators (`quality_report.json`)
```json
{
  "quality_schema_version": "3.0", "parser_version": "0.3.0", "run_id": "...",
  "generated_at": "...", "stopped_reason": null, "partial": false,
  "funnel": {
    "discovered_urls": 0, "requested_urls": 0, "attempted": 0,
    "fetched_ok_http200": 0, "fetch_failed": 0, "blocked": 0,
    "parse_ok": 0, "parse_error": 0, "duplicate_id": 0, "retried_urls": 0,
    "pending_not_attempted": 0, "unique_venues_exported": 0
  },
  "rates": {
    "fetch_success":      {"num": 0, "den": 0, "rate": null, "den_label": "attempted"},
    "parse_success":      {"num": 0, "den": 0, "rate": null, "den_label": "fetched_ok_http200"},
    "extraction_success": {"num": 0, "den": 0, "rate": null, "den_label": "requested_urls - duplicate_id"}
  },
  "price_status_counts": {"ok":0,"unknown_zero":0,"partial_zero":0,"invalid_range":0,"missing":0,"nonfinite":0},
  "hours_status_counts": {"missing":0,"malformed":0,"day_mapping_unknown":0},
  "geo_status_counts": {},
  "issue_counts_by_code": {}, "issue_counts_by_severity": {},
  "source_flag_semantics": {"IsActive": {}, "IsInactive": {}, "RestaurantStatus": {}, "interpretation": "unknown"},
  "eligibility": {},
  "notes": ["HTTP 200 is not extraction success"]
}
```
Rules: fetch failures, blocked and duplicate_id are never counted as parse failures; `rate=null` when `den==0`; `pending_not_attempted` plus `stopped_reason` expose cap/stop (e.g. limit 200); venue-level quality rates use `unique_venues_exported` and say so in `den_label`.

## 7. Eligibility (per venue in normalized row; counted in report)
Derived booleans; none imply verification:
- `search_eligible`: `foody_id` present and `name` non-empty (a price error does not remove it).
- `location_eligible`: `geo_status == "ok"`.
- `price_filter_eligible`: `price_status == "ok"`. `budget_eligible`: **always `false` in v3** (venue range is not a dish/portion price; true only with dish/portion price evidence, absent here).
- `hours_eligible`: **false for all in v3** (no day mapping evidence).
- `tour_eligible`: all four above; therefore 0 in v3 and reported honestly.
Report: `eligibility = {name: {"num","den","rate","den_label":"unique_venues_exported"}}`.

## 8. Function / API names (module `foody_tool/quality.py`)
```python
QUALITY_SCHEMA_VERSION = "3.0"
PRICE_STATUSES = ("ok", "missing", "nonfinite", "unknown_zero", "partial_zero", "invalid_range")
HOURS_STATUSES = ("missing", "malformed", "day_mapping_unknown")
GEO_STATUSES   = ("ok", "missing", "nonfinite", "out_of_range", "outside_hanoi_bbox")

def classify_price(lo, hi, warnings=()) -> dict    # {"status","min_norm","max_norm"}
def classify_hours(hours_raw, warnings=()) -> dict # {"status","intervals_count","day_codes_raw","crosses_midnight_raw","schedule_norm": None}
def classify_geo(lat, lon, warnings=()) -> str
def field_presence(html) -> dict                   # section 4 "fields" map; present=None if html is None
def build_provenance(record, entry, *, run_id, parser_version, html=None) -> dict  # entry = Collector.progress[url]
def normalize_record(record, provenance) -> dict   # section 3 row incl. eligibility
def detect_issues(record, normalized, *, csv_line, run_id) -> list
def build_quality_report(progress, requested, raw_rows, normalized_rows, issues, *, run_id, stopped_reason=None) -> dict
def export_quality(out_dir, progress, records, requested, *, run_id, stopped_reason=None, html_for=None) -> dict
```
Hooks:
- `exporter.export_all(..., run_id=None, quality=True)`: after v1 files call `export_quality(...)`; v1 return value gains only `["quality"]`. `html_for(url)` reads the collector's existing cache file when present.
- `jobs.CrawlJob._export` passes `run_id=self.id`; CLI `collect` passes a generated run id.
- Non-finite: use `math.isfinite`; Python `json` accepts `NaN`/`Infinity` tokens, so `quality` must check explicitly (parser `_is_num` stays as is).

HTTP (`app.py`, same CSRF/host rules; GET only, whitelisted names, no paths):
- `GET /api/download?job_id=<id>&format=quality|issues|issues_csv|normalized|normalized_csv|raw` (existing `csv|json|report` unchanged; unknown -> 400).
- `GET /api/jobs/<id>` snapshot gains optional `quality_summary` (`price_status_counts`, `issue_counts_by_severity`, `eligibility`), additive and absent for old jobs.
- `GET /api/preview` unchanged; optional `&layer=normalized`.

## 9. Backward compatibility
- Old job dirs (no quality files): `download format=quality` -> 404 `{"error":"not_available"}`. Optional CLI `python -m foody_tool quality <dir>` may re-derive from `restaurants.json` with hash/presence null -> `provenance_incomplete`.
- v1 `read_csv_records` round-trip unaffected; quality files are never read by v1 code.
- Bump `__version__` and `pyproject.toml` to `0.3.0`.

## 10. Validation criteria (`tests/test_quality.py`)
Fixture = the 200-venue CSV (`restaurants (1).csv`, load via `read_csv_records`) with `price_issues_200.csv` as oracle. Fixture redistribution permission is unknown: tests must `skip` if the files are absent; also build a synthetic 200-row fixture reproducing the six cases so CI is not skip-only.
1. **Six issues**: exactly 6 price-code issues: 5 x `zero_price_unverified` (ids 1252693, 1000062975, 1136050, 1229666, 1204032; csv_line 8, 48, 77, 100, 150) and 1 x `invalid_price_range` (id 68957, csv_line 94, raw 350000/60000). `(csv_line, foody_id, issue_code, raw_min, raw_max)` equals the oracle exactly; no other price-code issue.
2. For those 6: statuses `unknown_zero` x5 / `invalid_range` x1; norm prices null; raw unchanged (350000/60000 not swapped, 0/0 kept); `price_filter_eligible=false`; `search_eligible=true`.
3. The other 194: `price_status=ok`, norm == raw.
4. v1 `restaurants.csv`/`restaurants.json` byte-identical to pre-change output on the same input (golden hash); `len(FIELDS)==18`.
5. raw rows = normalized rows = 200, unique `foody_id` 200; import -> export keeps ids and raw hour lists; sum of `hours_intervals_count` == 220 (20 multi-shift venues keep all shifts).
6. Hours: every venue with intervals has `hours_status=day_mapping_unknown`, `hours_schedule_norm is null`, `hours_eligible=false`, no `open_now`; day code `3` kept; `operating_status=="unknown"` for all including the 196 with `IsInactive=true`.
7. `classify_price`: (None,None)->missing; (None,5000)->missing; (0,0)->unknown_zero; (0,5000)->partial_zero; (60000,350000)->ok; (350000,60000)->invalid_range; (5000,5000)->ok; (nan,5)/(inf,5)/(-1,5)/(True,5)/("5000",5000)->nonfinite; norm null whenever not ok.
8. Hours: `[]`->missing; interval without close->malformed; two shifts->count 2 with order kept; open>close->crosses_midnight_raw true and status still day_mapping_unknown; `00:00-23:59`->no 24/7 field.
9. Geo: None->missing; NaN->nonfinite; lat 95->out_of_range; (10.8,106.7)->outside_hanoi_bbox with coordinates preserved.
10. Provenance: `raw_content_hash` equals sha256 of the body bytes given to a fake fetcher; `parser_version=="0.3.0"`; `source_updated_at`/`verified_at` null; resumed run keeps hash; html missing -> `provenance_incomplete`.
11. Metrics: scripted run 3 ok, 1 parse_error, 1 blocked, 1 duplicate_id, 1 transient_failed, cap-stop with 2 pending -> funnel numbers and denominators exactly per section 6; `rate=null` when den 0; `partial=true`; parse failures exclude fetch failures.
12. Idempotence: exporting twice gives identical files (ignoring `generated_at`); no duplicate rows/issues.
13. CSV safety: names starting `=`/`-`/`+`/`@` neutralised in all new CSVs; Vietnamese UTF-8 preserved.
14. API: new `format` values return correct bodies/content-types; unknown -> 400; old formats unchanged; no path traversal.

## 11. Non-goals (v3)
Menu/dish/category, dish prices, delivery vs dine-in, weekday mapping, operating-status inference, entrance/routing verification, fuzzy duplicate merge, source-permission workflow (see `docs/SOURCE_REGISTER_V3.md` owned elsewhere), pilot selection. Reserved but not populated: `hours_schedule_norm`, `operating_status_evidence`, `source_updated_at`, `verified_at`.

## 12. Addendum (coordinator follow-up)
- **Hash kinds are distinct**: `raw_content_hash` = sha256 of HTTP response body **bytes** (Collector). `text_snapshot_hash` = sha256 of the UTF-8 text actually parsed/exported (e.g. the cached HTML text or the canonical `restaurants_raw.json` row JSON); never reuse one name for the other. When only a cache/text snapshot exists, set `raw_content_hash: null`, `text_snapshot_hash` set, and `hash_basis: "text_snapshot"`.
- **No full-raw-preservation claim**: the legacy parser drops malformed values (invalid lat/lon, negative/non-numeric prices, non-object OpeningTime items) before export. Raw layer is "raw as parsed", flagged by `raw_fidelity: "parser_filtered"`; dropped values appear only in the verbatim `parse_warning` issue. Exact original values are recoverable only from the cached HTML (`raw_content_hash` matches it).
- **Invalid JSON/imports**: when importing an existing CSV/JSON (`quality <dir>` or `read_csv_records`), any cell that fails JSON decoding or row with wrong column count/missing `foody_id` yields issue `import_row_invalid` (error, `detail` = line + decoder message, raw cell text kept in `detail` truncated to 500 chars) and the row is still emitted in raw/normalized with the affected fields null and statuses `missing`/`malformed`. Row count in = row count out; report `import.rows_read`, `import.rows_invalid`.
- **Output naming**: normalized files may be named `restaurants_normalized_v2.{json,csv}` if the coordinator prefers; contents per section 3 unchanged.

## 13. Corrections (supersede any conflicting text above)
1. **budget_eligible** is `false` for every venue in v3, even with `price_status=ok`. `tour_eligible` stays false. `price_filter_eligible` is the only price-based true flag.
2. **Order and csv_line**: raw/normalized/issues preserve original input record order. `csv_line` = physical line in the v1 source CSV that was read (header = 1), captured from the reader (`csv.reader.line_num` at the start of each record, so multi-line quoted cells stay correct), not from sort order or `foody_id`. For a live run it is the line in the `restaurants.csv` the same export writes (same order). The oracle lines 8, 48, 77, 94, 100, 150 must match when the 200 fixture is imported in file order.
3. **Bytes vs text hash**: `raw_content_hash` is computed from HTTP bytes on fresh fetch. A cache never invents this hash. It may retain a previously measured byte hash only when its text matches the saved `text_snapshot_hash`; old or changed caches have null byte hash and a measured text hash. Tests cover fresh, matching-cache and changed-cache cases.
4. **Field presence and source key values** are **progress metadata outside the v1 record**: the Collector reads whitelisted `initData` fields into `field_presence` and `source_keys` on fresh or cached HTML parsing. Non-finite raw values use explicit string tokens. Old entries without these observations give unknown presence. `parse_restaurant` and the v1 record stay unchanged. Raw import preserves original CSV cell text or JSON object per row in `import_original` next to decoded fields.
5. **No crashes on mixed types**: classifiers accept any JSON value. `hours_day_codes_raw` = distinct values de-duplicated by canonical JSON and ordered by `(type name, canonical JSON)` so ints, strings, null, bool and lists mix without `TypeError`. Non-dict intervals count as `malformed` and are kept verbatim; open/close of any non-conforming type -> `malformed`, never an exception. Any per-row exception in quality code is caught: issue `quality_internal_error` (error; class + message), row still written with statuses `missing`/`malformed`; rows are never dropped and export never aborts.
6. **Strict JSON**: every new JSON file is written with `json.dumps(..., allow_nan=False)` after a sanitiser. Normalized numeric fields are finite numbers or null only (no NaN/Inf). In raw / `import_original` / issue `raw_min`,`raw_max`, non-finite floats become the string tokens `"NaN"`/`"Infinity"`/`"-Infinity"` together with the row's `nonfinite` status. Test: every new JSON file loads with `parse_constant` raising.
7. **Added validation cases**: order preserved with shuffled IDs; csv_line from a file with a multi-line quoted cell; hours with `[{"day_of_week_raw":3},{"day_of_week_raw":"3"},{"day_of_week_raw":null},"x",7]` raises nothing; NaN/Inf price row yields strict-JSON-valid outputs; `budget_eligible` false for all 194 `ok` venues.
