"""Visible-browser LoadMore discovery for the public Foody Hanoi listing.

Only the normal rendered page is used: one navigation to the fixed listing URL
and real clicks on the visible "Xem them dia diem" button. No internal API
calls, login, stealth, proxying or challenge bypass. Playwright is imported
lazily so the rest of the package works without it.

Source structure (cache/hanoi_odau.html): section[ng-controller=PlaceController],
li.ldc-item[ng-repeat="item in Items"], .btn-load-more[ng-if="IsLoadMore()"]
(raw HTML has style display:none until Angular), a[ng-class="{loading:IsLoading}"].

Session interface (what `factory` must return; see PlaywrightSession):
    goto(url, timeout_ms) -> int | None   navigation HTTP status
    card_html() -> str                    outerHTML of rendered li.ldc-item cards only
                                          (static banners are NOT cards)
    listing_state() -> dict               read-only {ready, loading, has_more, card_count}
                                          has_more: True / False / None (unknown)
    load_more_visible() -> bool           LoadMore button present and visible
    click_load_more() -> bool             real click; False if it could not be done
    challenge_visible() -> bool           visible captcha/challenge/block page
    drain_responses() -> list[dict]       {url, status, resource_type} since last call
    close() -> None
factory signature: factory(out_dir, channel, headless, timeout_ms) -> session
"""
import json
import math
import os
import time
from urllib.parse import urlsplit

from .discovery import extract_restaurant_urls

SOURCE_URL = "https://www.foody.vn/ha-noi/o-dau"
MIN_INTERVAL = 2.0
LOAD_MORE_SELECTOR = 'a[ng-click="LoadMore()"]'
LOAD_MORE_TEXT = "Xem thêm địa điểm"
BLOCK_STATUSES = (403, 429)
RELEVANT_TYPES = ("document", "xhr", "fetch")
END_CONFIRMATIONS = 3      # consecutive polls: ready, idle, has_more False, no growth
POLL_SECONDS = 0.5
MAX_EVENTS = 1000
OUTPUT_NAME = "browser_discovery.json"

# Read-only: inspects DOM and the public Angular scope flags; no requests.
_STATE_JS = """() => {
  const sec = document.querySelector('[ng-controller="PlaceController"]');
  const cards = Array.from(document.querySelectorAll('li.ldc-item .ldc-item-h-name a[href]'))
    .filter(e => !(e.getAttribute('href') || '').includes('{{'));
  let scope = null;
  try { if (window.angular && sec) scope = window.angular.element(sec).scope(); } catch (e) {}
  let hasMore = null, loading = false, source = 'dom';
  if (scope && typeof scope.IsLoadMore === 'function') {
    hasMore = !!scope.IsLoadMore();
    loading = !!scope.IsLoading;
    source = 'scope';
  } else {
    const wrap = document.querySelector('.btn-load-more');
    if (wrap && getComputedStyle(wrap).display !== 'none') hasMore = true;
    loading = !!document.querySelector('.btn-load-more a.loading');
  }
  const hydrated = !!(sec && window.angular && sec.classList.contains('ng-scope'));
  return {ready: hydrated && cards.length > 0, loading: loading, has_more: hasMore,
          card_count: cards.length, source: source};
}"""


class _Halt(Exception):
    """Internal: stop requested via should_stop."""


def _is_foody(url):
    try:
        host = (urlsplit(url).hostname or "").lower()
    except Exception:
        return False
    return host == "foody.vn" or host.endswith(".foody.vn")


class PlaywrightSession:
    """Real Playwright-backed session using an ephemeral clean profile."""

    def __init__(self, out_dir, channel="auto", headless=False, timeout_ms=30000):
        try:
            from playwright.sync_api import sync_playwright
        except ImportError as exc:
            raise RuntimeError(
                "Playwright is not installed (pip install playwright)") from exc
        self._pw = None
        self._browser = None
        self._responses = []
        try:
            self._pw = sync_playwright().start()
            self._browser = self._launch(channel, headless)
            context = self._browser.new_context(locale="vi-VN")
            context.set_default_timeout(timeout_ms)
            self._page = context.new_page()
            self._page.on("response", self._on_response)
        except Exception:
            self.close()
            raise

    def _launch(self, channel, headless):
        chromium = self._pw.chromium
        if channel in ("auto", "msedge"):
            try:
                return chromium.launch(channel="msedge", headless=headless)
            except Exception:
                if channel == "msedge":
                    raise
        elif channel not in ("chromium", ""):
            return chromium.launch(channel=channel, headless=headless)
        return chromium.launch(headless=headless)

    def _on_response(self, response):
        try:
            self._responses.append({
                "url": response.url,
                "status": response.status,
                "resource_type": response.request.resource_type,
            })
        except Exception:
            pass

    def goto(self, url, timeout_ms):
        resp = self._page.goto(url, wait_until="domcontentloaded", timeout=timeout_ms)
        return resp.status if resp is not None else None

    def card_html(self):
        return self._page.evaluate(
            "() => Array.from(document.querySelectorAll('li.ldc-item .ldc-item-h-name a[href]'))"
            ".map(e => { const a=document.createElement('a');a.setAttribute('href',e.href);"
            "return a.outerHTML; }).join('\\n')")

    def listing_state(self):
        try:
            return self._page.evaluate(_STATE_JS)
        except Exception:
            return {"ready": False, "loading": False, "has_more": None, "card_count": 0}

    def _button(self):
        loc = self._page.locator(LOAD_MORE_SELECTOR)
        if loc.count() == 0:
            loc = self._page.get_by_text(LOAD_MORE_TEXT, exact=False)
        return loc.first if loc.count() else None

    def load_more_visible(self):
        btn = self._button()
        return bool(btn is not None and btn.is_visible())

    def click_load_more(self):
        btn = self._button()
        if btn is None or not btn.is_visible():
            return False
        btn.scroll_into_view_if_needed()
        btn.click()
        return True

    def challenge_visible(self):
        try:
            title = (self._page.title() or "").lower()
            body = (self._page.inner_text("body", timeout=2000) or "").lower()[:4000]
        except Exception:
            return False
        markers = ("captcha", "verify you are human", "access denied",
                   "just a moment", "xác minh bạn là người")
        return any(m in title or m in body for m in markers)

    def drain_responses(self):
        out, self._responses = self._responses, []
        return out

    def close(self):
        for obj, name in ((self._browser, "close"), (self._pw, "stop")):
            if obj is not None:
                try:
                    getattr(obj, name)()
                except Exception:
                    pass
        self._browser = None
        self._pw = None


class BrowserDiscovery:
    def __init__(self, out_dir, *, interval=3.0, browser_channel="auto",
                 headless=False, max_clicks=10000, timeout_ms=30000,
                 stalled_attempts=3, factory=None):
        try:
            interval = float(interval)
        except (TypeError, ValueError):
            raise ValueError("interval must be a finite number")
        if not math.isfinite(interval):
            raise ValueError("interval must be a finite number")
        for name, val in (("max_clicks", max_clicks), ("timeout_ms", timeout_ms),
                          ("stalled_attempts", stalled_attempts)):
            if isinstance(val, bool) or not isinstance(val, int) or val <= 0:
                raise ValueError("%s must be a positive integer" % name)
        self.out_dir = out_dir
        self.interval = max(interval, MIN_INTERVAL)
        self.browser_channel = browser_channel
        self.headless = bool(headless)
        self.max_clicks = max_clicks
        self.timeout_ms = timeout_ms
        self.stalled_attempts = stalled_attempts
        self.factory = factory or PlaywrightSession
        self.source_url = SOURCE_URL
        # Overridable in offline tests.
        self._sleep = time.sleep
        self._clock = time.monotonic
        self._paused = 0.0   # time spent blocked in checkpoint (pause), excluded from deadlines

    # -- helpers -----------------------------------------------------------
    def _now(self):
        return self._clock() - self._paused

    def _wait(self, seconds, should_stop, checkpoint):
        end = self._now() + seconds
        while True:
            self._point(should_stop, checkpoint)
            rem = end - self._now()
            if rem <= 0:
                return
            self._sleep(min(0.25, rem))

    def _point(self, should_stop, checkpoint):
        t0 = self._clock()
        try:
            checkpoint()
            self._paused += max(0.0, self._clock() - t0)
        except Exception:
            # Only a requested stop turns a checkpoint exception into "stopped";
            # anything else is a real error and propagates with its message.
            if should_stop():
                raise _Halt()
            raise
        if should_stop():
            raise _Halt()

    def run(self, on_batch, should_stop=lambda: False, checkpoint=lambda: None,
            max_urls=None):
        urls, events = [], []
        st = {"clicks": 0, "reason": None, "error": None, "coverage": False}
        started = self._now()

        def event(kind, **data):
            data.update(type=kind, t=round(self._now() - started, 2))
            events.append(data)
            if len(events) > MAX_EVENTS:
                del events[0]

        session = None
        try:
            try:
                session = self.factory(self.out_dir, self.browser_channel,
                                       self.headless, self.timeout_ms)
            except Exception as exc:
                st.update(reason="error", error="browser unavailable: %s" % exc)
                event("browser_unavailable", error=str(exc))
            if session is not None:
                self._discover(session, urls, st, event, on_batch,
                               should_stop, checkpoint, max_urls)
        except _Halt:
            st["reason"] = "stopped"
            event("stopped", discovered=len(urls))
        except Exception as exc:
            st.update(reason="error", error="%s: %s" % (type(exc).__name__, exc))
            event("error", error=st["error"])
        finally:
            if session is not None:
                try:
                    session.close()
                    event("browser_closed")
                except Exception as exc:
                    event("close_failed", error=str(exc))
        result = {
            "urls": list(urls),
            "clicks": st["clicks"],
            "reason": st["reason"] or "error",
            "error": st["error"],
            "coverage_verified": bool(st["coverage"] and st["reason"] == "exhausted"),
            "source_url": self.source_url,
            "events": events,
            "event_time_basis": "active elapsed seconds, excluding checkpoint pause time",
        }
        result["evidence_error"] = self._save(result)
        return result

    def _blocked_reason(self, session):
        for r in session.drain_responses():
            relevant = _is_foody(r.get("url", "")) and r.get("resource_type") in RELEVANT_TYPES
            if relevant and (r.get("status") == 408 or (r.get("status") or 0) >= 500):
                raise RuntimeError("source HTTP %s on %s %s" % (
                    r["status"], r["resource_type"], urlsplit(r["url"]).path))
            if (r.get("status") in BLOCK_STATUSES and _is_foody(r.get("url", ""))
                    and r.get("resource_type") in RELEVANT_TYPES):
                return "HTTP %s on %s %s" % (r["status"], r["resource_type"],
                                             urlsplit(r["url"]).path)
        if session.challenge_visible():
            return "visible challenge page"
        return None

    def _discover(self, session, urls, res, event, on_batch, should_stop,
                  checkpoint, max_urls):
        seen = set()
        last_action = [None]
        timeout_s = self.timeout_ms / 1000.0

        def pace():
            if last_action[0] is not None:
                due = last_action[0] + self.interval - self._now()
                if due > 0:
                    self._wait(due, should_stop, checkpoint)
            self._point(should_stop, checkpoint)
            last_action[0] = self._now()

        def block(why):
            res.update(reason="blocked", error=why)
            event("blocked", detail=why, discovered=len(urls))

        def harvest():
            """Newly rendered card URLs (stable order), capped by max_urls."""
            fresh = []
            # These are only venue-card headline links; a venue name may resemble a taxonomy prefix.
            for u in extract_restaurant_urls(session.card_html(), self.source_url, exclude_taxonomy=False):
                if u not in seen:
                    seen.add(u)
                    fresh.append(u)
            if max_urls is not None:
                fresh = fresh[:max(0, max_urls - len(urls))]
            return fresh

        def emit(fresh):
            urls.extend(fresh)
            event("growth", new=len(fresh), discovered=len(urls), clicks=res["clicks"])
            on_batch(list(fresh), {
                "clicks": res["clicks"],
                "discovered": len(urls),
                "source_url": self.source_url,
                "observed_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            })

        def limit_hit():
            return max_urls is not None and len(urls) >= max_urls

        def listing():
            s = session.listing_state() or {}
            return {"ready": bool(s.get("ready")), "loading": bool(s.get("loading")),
                    "has_more": s.get("has_more"),
                    "card_count": int(s.get("card_count") or 0)}

        # initial navigation
        pace()
        try:
            status = session.goto(self.source_url, self.timeout_ms)
        except Exception as exc:
            if "timeout" in type(exc).__name__.lower() or "timeout" in str(exc).lower():
                res.update(reason="timeout", error="navigation timeout")
                event("nav_timeout")
                return
            raise
        event("navigated", status=status)
        if status in BLOCK_STATUSES:
            return block("navigation HTTP %s" % status)
        if status is not None and status >= 400:
            res.update(reason="error", error="navigation HTTP %s" % status)
            return

        # initial render: wait for real dynamic cards, never static banners alone
        deadline = self._now() + timeout_s
        while True:
            why = self._blocked_reason(session)
            if why:
                return block(why)
            ls = listing()
            fresh = harvest() if ls["ready"] else []
            if fresh:
                break
            if self._now() >= deadline:
                res.update(reason="timeout",
                           error="no dynamic venue cards rendered in time "
                                 "(ready=%s cards=%d)" % (ls["ready"], ls["card_count"]))
                event("render_timeout", **ls)
                return
            self._wait(POLL_SECONDS, should_stop, checkpoint)
        emit(fresh)
        if limit_hit():
            res["reason"] = "limit"
            return

        stalls = 0          # clicks without growth
        end_seen = 0        # consecutive confirmations of an explicit end
        waiting_since = None

        def settle(why):
            """Bounded wait for an unsettled state. True if the bound expired."""
            nonlocal waiting_since
            now = self._now()
            if waiting_since is None:
                waiting_since = now
            if now - waiting_since > timeout_s:
                res.update(reason="stalled",
                           error="listing state never settled: " + why)
                event("settle_timeout", detail=why, discovered=len(urls))
                return True
            self._wait(POLL_SECONDS, should_stop, checkpoint)
            return False

        while True:
            self._point(should_stop, checkpoint)
            why = self._blocked_reason(session)
            if why:
                return block(why)
            if res["clicks"] >= self.max_clicks:
                res["reason"] = "safety_limit"
                event("safety_limit", clicks=res["clicks"])
                return
            fresh = harvest()
            if fresh or len(seen) > len(urls):
                stalls = end_seen = 0
                waiting_since = None
                if fresh:
                    emit(fresh)
                if limit_hit():
                    res["reason"] = "limit"
                    return
                continue
            ls = listing()
            if not ls["ready"]:
                end_seen = 0
                if settle("listing not ready"):
                    return
                continue
            if ls["loading"]:
                end_seen = 0
                if settle("still loading"):
                    return
                continue
            if ls["has_more"] is False:
                end_seen += 1
                if end_seen >= END_CONFIRMATIONS:
                    res.update(reason="exhausted", coverage=True)
                    event("end_observed", discovered=len(urls), has_more=False,
                          confirmations=end_seen, clicks=res["clicks"])
                    return
                self._wait(POLL_SECONDS, should_stop, checkpoint)
                continue
            end_seen = 0
            if ls["has_more"] is None or not session.load_more_visible():
                if settle("has_more=%s button_visible=%s" % (
                        ls["has_more"], session.load_more_visible())):
                    return
                continue
            waiting_since = None
            if stalls >= self.stalled_attempts:
                res.update(reason="stalled",
                           error="no growth after %d clicks with LoadMore available" % stalls)
                event("no_growth", attempts=stalls, discovered=len(urls))
                return
            pace()
            try:
                clicked = session.click_load_more()
            except Exception as exc:
                if "timeout" in type(exc).__name__.lower():
                    clicked = False
                else:
                    raise
            stalls += 1
            if clicked:
                res["clicks"] += 1
                event("click", n=res["clicks"])
            why = self._blocked_reason(session)
            if why:
                return block(why)

    def _save(self, result):
        """Write evidence; return None on success or an honest error string."""
        try:
            os.makedirs(self.out_dir, exist_ok=True)
            with open(os.path.join(self.out_dir, OUTPUT_NAME), "w", encoding="utf-8") as f:
                json.dump(result, f, ensure_ascii=False, indent=1)
            return None
        except Exception as exc:
            return "%s: %s" % (type(exc).__name__, exc)
