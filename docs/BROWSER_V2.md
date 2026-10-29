# Browser discovery v2 (`foody_tool/browser.py`)

`BrowserDiscovery(out_dir, *, interval=3.0, browser_channel='auto', headless=False, max_clicks=10000, timeout_ms=30000, stalled_attempts=3, factory=None).run(on_batch, should_stop, checkpoint, max_urls=None)`

## Behaviour
- Playwright imported lazily (`PlaywrightSession`); optional extra `pip install .[browser]`.
- Ephemeral clean context (no user profile). `auto` = installed Edge (`msedge`), else bundled Chromium. Headed by default.
- Fixed source `https://www.foody.vn/ha-noi/o-dau`; one navigation, then real clicks on `a[ng-click="LoadMore()"]` ("Xem thêm địa điểm"). No internal API calls, no login/stealth/bypass.
- `interval` clamped to >= 2 s between navigation/click starts. Waits are sliced (0.25 s) and call `checkpoint()` and `should_stop()` each slice; checkpoint raising = cancel -> `stopped`.
- URLs via `extract_restaurant_urls`, stable unique; `on_batch(new_urls, {clicks, discovered, source_url, observed_at})` after initial render and each growth. `max_urls` trims and ends with `limit`; `None` = all.
- Result: `urls, clicks, reason, error, coverage_verified, source_url, events`; also written to `out_dir/browser_discovery.json`.

## Reasons
| reason | meaning | coverage_verified |
|---|---|---|
| exhausted | LoadMore button absent for 2 consecutive polls (0.5 s apart) with no growth, after >=1 venue rendered | **true** (only this) |
| limit | `max_urls` reached | false |
| stopped | `should_stop` / checkpoint cancel | false |
| blocked | Foody document/xhr/fetch response 403/429, navigation 403/429, or visible challenge text | false |
| stalled | click(s) produced no growth `stalled_attempts` times while button still visible; or no venues and no button | false |
| timeout | navigation timeout or no venue rendered within `timeout_ms` | false |
| safety_limit | `max_clicks` reached | false |
| error | browser missing/closed/any exception (browser cleaned up in `finally`) | false |

Third-party failures and non-document/xhr/fetch resources (images etc.) are ignored. Navigation status and click counts are actual observations; subrequests are not counted.

## Factory (offline tests)
`factory(out_dir, channel, headless, timeout_ms)` returns a session with `goto, html, load_more_visible, click_load_more, challenge_visible, drain_responses, close`. Tests may override `d._clock` / `d._sleep` for instant runs.

## Tests
`.venv/Scripts/python.exe -m unittest tests.test_browser` — 18 tests: >50 URLs with duplicates, exhaustion, limit, stall, safety limit, XHR 429, nav 403, challenge, timeouts, stop, checkpoint cancel, interval >=2 s, factory failure, closed browser, sink error, single page, lazy import. All offline.

## Limitations
- Not exercised against live Foody or a real Playwright browser (coordinator live test pending); selector and end-of-list behaviour (button disappearing at the end) are inferred from earlier receipts (+12/click, button text), not verified at the true end.
- "exhausted" means the rendered listing showed no further LoadMore, not that every real restaurant was found. If Foody caps the listing depth server-side, that cap would be reported as exhausted.
- Challenge detection is text-marker based (captcha, "access denied", "just a moment"), best effort.

## Review fix (pre-live)
- Cards, not page links: harvest reads only rendered `li.ldc-item` (`card_html()`); static banners never count. Initial render requires `listing_state().ready` (Angular hydrated + >=1 non-placeholder card).
- `listing_state()` is read-only: Angular scope `IsLoadMore()`/`IsLoading` of `[ng-controller=PlaceController]` when accessible (`source: scope`), else DOM fallback where `has_more` is True only if the LoadMore wrapper is displayed and otherwise **unknown (None)**.
- `exhausted` needs ready + not loading + explicit `has_more is False` for 3 consecutive polls with no growth. Missing button, unknown `has_more`, loading or not-ready never give coverage; they wait up to `timeout_ms` then end as `stalled`. Consequence: if the scope is unreachable in the real page, a true end shows as `stalled` (safe), not `exhausted` — check in the live test.
- A checkpoint exception becomes `stopped` only when `should_stop()` is true; otherwise `error` with the message.
- Constructor rejects non-finite interval and non-positive/non-int max_clicks, timeout_ms, stalled_attempts. `result["evidence_error"]` reports a failed evidence save (null if saved).
- Tests: 27 offline (banner-only, deferred hydration, delayed loading, hidden button/unknown state, loading forever, checkpoint error, validation, save error).
