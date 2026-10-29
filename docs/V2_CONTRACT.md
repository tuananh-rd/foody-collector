# Approved v2: automatic listing discovery and local UI

User requested automatic browser opening, LoadMore pagination for the full public Hanoi source listing, and a usable GUI. This supersedes v1 limits that forbade browser discovery and city mode. Use the existing core parser/collector/exporter and preserve raw/basic-field semantics. No login, stealth, proxy rotation, captcha/rate-limit bypass, menu/UGC/images, publication, or arbitrary source hosts. No permission has been obtained for Foody reuse; keep outputs local. No extra permission checkbox or approval workflow: user already approved development. No whole-city live scrape in worker testing; coordinator assigns small live test after code review.

Architecture: Python local web application using stdlib HTTP server, one background job, plain HTML/CSS/JS Vietnamese UI, plus optional Playwright browser dependency. Existing collect CLI stays compatible and capped50; city runner streams all discovered URLs through Collector.process without that old batch cap. Edge available here; Playwright can use clean temporary msedge profile or installed Chromium (no user browser profile). Visible browser default, no stealth. The GUI handles starting/pausing/resuming/stopping, progress, preview and CSV/JSON downloads. No external service/database/accounts needed.

Ownership:
- Claude: foody_tool/browser.py, tests/test_browser.py, docs/BROWSER_V2.md, pyproject.toml optional browser extra/version. Do not edit jobs.py/app.py/frontend/core unless coordinator agrees.
- Antigravity: foody_tool/web/index.html, style.css, app.js, tests/test_web.py (only static or browser UI tests through agreed API), reports/ui_v2.md. Do not edit backend/core/browser/pyproject.
- Coordinator: foody_tool/jobs.py, app.py, __main__.py wiring, backend tests, Start-Foody.cmd launcher, install/setup docs, integration, real small live test, packaging/commits. Workers do not commit, reset or spawn workers.

Browser interface fixed:
`BrowserDiscovery(out_dir, *, interval=3.0, browser_channel='auto', headless=False, max_clicks=10000, timeout_ms=30000, stalled_attempts=3, factory=None)`.
`run(on_batch, should_stop=lambda:False, checkpoint=lambda:None, max_urls=None) -> dict`.
`on_batch(new_urls: list[str], metadata: dict)` after initial render and each observed growth; metadata contains clicks, discovered count, source_url, observed_at. Emit URLs in stable unique order, using existing extract_restaurant_urls. checkpoint blocks when paused, raises on cancelled if coordinator desires; should_stop exits gracefully. Each iteration should call both and wait cooperatively. Default source fixed https://www.foody.vn/ha-noi/o-dau; interval>=2s between navigation/click starts. Browser cleanup in finally on every exit. Playwright imported lazily so old core tests work without it. No direct requests to undocumented/internal API, only normal visible page navigation/button click.

Result: urls, clicks, reason (exhausted, limit, stopped, blocked, stalled, timeout, error, safety_limit), error or null, coverage_verified boolean, source_url, events list. Coverage true ONLY when genuine end-of-list observed on rendered venue listing, never on no growth/timeouts/cap/captcha/403/429 or missing unrendered page. Report exact observed end evidence, not all real-world restaurants. Bound no-growth retries and max_clicks; sample max_urls limits via URL count while all uses None. Capture minimal counts/URL event evidence, not full raw DOM/UGC in tracked reports. Distinguish actual navigation status, browser actions, unmeasured subrequests. Detection of Foody document/XHR/fetch403/429 should stop; skip irrelevant third-party asset failures. Browser missing/closed/window errors must become useful outcome, not unhandled thread error. Scripted page factory for meaningful offline tests: growth duplicates, exhaustion, delayed growth, stalled vs exhausted, limit, blocked, stop, cleanup.

GUI HTTP contract (coordinator backend):
- GET /api/status -> {active_job: <snapshot|null>, browser_ready: bool, browser_message: str, csrf_token: str}
- GET /api/history -> {jobs: [snapshots]}
- POST /api/start JSON {mode:'sample'|'all', limit:48, interval:3, show_browser:true} -> {job_id, job:snapshot}; all ignores limit.
- POST /api/pause|resume|stop JSON {job_id} -> {job:snapshot}.
- GET /api/jobs/<id> -> {job:snapshot}.
- GET /api/preview?job_id=<id> -> {records:[basic records], total:<unique records count>}; default limit20, optionaloffset.
- GET /api/download?job_id=<id>&format=csv|json|report -> file download.
- GET /api/status provides csrf_token; all POST send X-CSRF-Token. Listen127.0.0.1 only, verify host and Origin on mutations, no arbitrary file paths.
- Job snapshot keys: id, mode, state, stage, discovered, processed, success, duplicates, failed, clicks, request_count, limit, interval, started_at, updated_at, termination_reason, coverage_verified, message (Vietnamese), logs (last30 entries {time,message}), report (optional/null). States queued,running,paused,stopped,blocked,completed,partial,error; stages discovering,collecting,finished. No fake percent in all mode without total; show counts. Sample limit is bound, not 100% city coverage. Download current checkpoint on pause/stop. Resume persisted job skips already-done URL/IDs, may rewalk listing from beginning to rediscover URLs; describe this accurately.

UI: Vietnamese, simple polished local dashboard. Header FoodTour data collector, source Hanoi Foody, sample/all choice, sample quantity, pace>=2, showbrowser toggle, start/pause/resume/stop; live metrics and readable stop reason, progress count, preview table (name/address/price/rawhours with nullshown as unavailable), CSV/JSON/report downloads and history resume. Use textContent for external data, no unsafe innerHTML. Poll status lightly (1-2s) and keep controls consistent with job state. No technical implementation details in normal flow. Footer modest data freshness/price/hours notes without blocking use. No builds/external fonts/dependency frameworks.

