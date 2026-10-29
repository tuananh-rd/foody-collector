# FoodTour Foody collector: approved implementation contract

Build a small Python CLI for private limited feasibility testing of publicly accessible Foody restaurant pages. No menu, UGC, images, auth, captcha bypass, proxy rotation, or all-city crawl. Foody permission for intended reuse has NOT been obtained; do not publish data or imply open licensing. Full raw HTML fixtures are local-only and gitignored.

Shared interfaces (do not change without coordinator agreement):
- `foody_tool.parser.parse_restaurant(html: str, source_url: str, fetched_at: str) -> dict`.
- `foody_tool.discovery.extract_restaurant_urls(html: str, base_url: str) -> list[str]`: pure discovery, stable unique absolute HTTPS www.foody.vn/ha-noi/<venue> URLs. Exclude listing, editorial, menu, auth URLs. Discovery is untrusted; collector validates restaurant identity.
- Network discovery may additionally expose a separate CLI; collection core does not depend on it before review.
- Record fields: foody_id, name, lat, lon, address, district, city, opening_hours_raw (list of raw day/time values; never infer a week or map unknown DayOfWeek), price_min_vnd, price_max_vnd, source_url, fetched_at (UTC ISO8601), price_semantics, source_license, field_freshness_unknown. Missing values null/blank, no inferred facts. Preserve source status flags separately without claiming open/closed.

Defaults: one sequential request at a time, minimum 2 seconds between network request starts, maximum 50 restaurant URLs per invocation, timeout, bounded transient retries, stop on 403/429/captcha, validate target host/path and redirects. Cache HTML privately; persistent progress and per-URL outcome; ID dedup; UTF-8 CSV and JSON; completeness and failure report. No unnecessary infrastructure/UI/database service.

Ownership:
- Claude: foody_tool/{__init__,__main__,parser,collector,exporter}.py, pyproject.toml, tests/test_parser.py, tests/test_collector.py, tests/test_exporter.py, README.md. May add narrowly scoped helper files in core; never discovery.py or Antigravity reports/tests.
- Antigravity: foody_tool/discovery.py, tests/test_discovery.py, docs/DISCOVERY.md, reports/discovery/*, inputs/*, reports/verification/*, tests/test_independent.py. Read core code, don't edit it. Initial independent validation may wait for core availability; send findings rather than patching core.
- Coordinator: this contract, integration and task docs. Only coordinator commits shared workspace after checks; workers don't commit/reset/rebase or spawn other workers.

Evidence: use reference/sample5.json and 5 local HTML fixtures for regression. HTTP200 is not extraction success; flags in sample have unknown meaning. Existing prototype var initData JSON is starting point, validate malformed/time/coordinate cases without executing JS. Offline simulated network tests should cover interruption/resume, ID duplication, blocked response, transient retries, redirect target and CSV/JSON equivalence.

Live testing: overall target 30-50 detail URLs only if publicly accessible real URL discovery supports it; no slug guessing or ID brute force. Antigravity discovery research max 10 sequential public listing page requests and no detail-page downloads during initial research. Claude initially ONLY old 5 URLs live if needed; coordinator assigns the larger live batch after inspecting URL evidence. Report actual counts and observed gaps without fabricated data. Browser rendering may be assessed using documented Orca browser commands; do not claim pagination proven from placeholders.

