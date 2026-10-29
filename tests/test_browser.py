"""Offline tests for foody_tool.browser using a scripted fake page factory."""
import json
import tempfile
import unittest
from unittest.mock import patch
from pathlib import Path

from foody_tool.browser import BrowserDiscovery, PlaywrightSession, SOURCE_URL


def url(i):
    return "https://www.foody.vn/ha-noi/quan-%03d" % i


class FakePage:
    """Listing with `total` venues, `step` revealed per click.

    stall_after: stop revealing after this many venues but keep the button.
    delay: clicks needed to be polled before growth shows (delayed growth).
    block_on_click: nth click triggers an XHR 429.
    """

    def __init__(self, total=120, step=12, first=12, stall_after=None,
                 duplicates=False, nav_status=200, block_on_click=None,
                 challenge=False, hide_button_at_cap=True, nav_error=None,
                 click_error=None, hydrate_after=0, banner=False,
                 unknown_state=False, hidden_button_end=False, loading_forever=False,
                 grow_delay=0):
        self.total, self.step, self.shown = total, step, min(first, total)
        self.stall_after = stall_after
        self.duplicates = duplicates
        self.nav_status = nav_status
        self.block_on_click = block_on_click
        self.challenge = challenge
        self.nav_error, self.click_error = nav_error, click_error
        self.hydrate_after = hydrate_after   # state polls before cards render
        self.banner = banner
        self.unknown_state = unknown_state   # has_more None, button never visible
        self.hidden_button_end = hidden_button_end  # end reached, has_more unknown
        self.loading_forever = loading_forever
        self.grow_delay = grow_delay         # state polls loading after a click
        self._pending = 0
        self._polls = 0
        self.clicks = 0
        self.closed = False
        self.responses = []
        self.navs = 0
        self.click_times = []
        self.clock = None

    def goto(self, u, timeout_ms):
        self.navs += 1
        if self.nav_error:
            raise self.nav_error
        return self.nav_status

    def _hydrated(self):
        return self._polls > self.hydrate_after

    def card_html(self):
        if not self._hydrated():
            return ""
        parts = ['<li class="ldc-item"><a href="%s">v</a></li>' % url(i)
                 for i in range(self.shown)]
        if self.duplicates:
            parts += ['<li class="ldc-item"><a href="%s">dup</a></li>' % url(i)
                      for i in range(self.shown)]
            parts.append('<a href="/ha-noi/o-dau">listing</a>')
        return "".join(parts)

    def _at_end(self):
        return self.shown >= self.total and self.stall_after is None

    def listing_state(self):
        self._polls += 1
        if self._pending > 0:
            self._pending -= 1
            if self._pending == 0:
                self.shown = min(self.shown + self.step, self.total)
        if not self._hydrated():
            return {"ready": False, "loading": False, "has_more": None, "card_count": 0}
        if self.unknown_state or (self.hidden_button_end and self._at_end()):
            has_more = None
        else:
            has_more = not self._at_end()
        return {"ready": True, "loading": self.loading_forever or self._pending > 0,
                "has_more": has_more, "card_count": self.shown}

    def load_more_visible(self):
        if self.unknown_state or self._at_end():
            return False
        return True

    def click_load_more(self):
        if self.click_error:
            raise self.click_error
        self.clicks += 1
        if self.clock:
            self.click_times.append(self.clock())
        if self.block_on_click == self.clicks:
            self.responses.append({"url": "https://www.foody.vn/Ajax/LoadMore",
                                   "status": 429, "resource_type": "xhr"})
            return True
        if self.grow_delay:
            self._pending = self.grow_delay
            return True
        cap = self.stall_after if self.stall_after is not None else self.total
        self.shown = min(self.shown + self.step, self.total, cap)
        return True

    def challenge_visible(self):
        return self.challenge

    def drain_responses(self):
        out, self.responses = self.responses, []
        return out

    def close(self):
        self.closed = True


def make(page, **kw):
    """Build a BrowserDiscovery with fake clock/sleep so tests run instantly."""
    tmp = tempfile.mkdtemp()
    kw.setdefault("timeout_ms", 5000)
    d = BrowserDiscovery(tmp, factory=lambda *a: page, **kw)
    now = [0.0]
    d._clock = lambda: now[0]
    d._sleep = lambda s: now.__setitem__(0, now[0] + s)
    page.clock = d._clock
    d._tmp = tmp
    return d


class Collect:
    def __init__(self):
        self.batches = []

    def __call__(self, new, meta):
        self.batches.append((list(new), dict(meta)))

    @property
    def urls(self):
        return [u for b, _ in self.batches for u in b]


class TestBrowserDiscovery(unittest.TestCase):
    def test_venue_headline_is_not_lost_due_to_taxonomy_like_name(self):
        page = FakePage(total=1, first=1)
        page.card_html = lambda: '<a href="https://www.foody.vn/ha-noi/nha-hang-co-chau">Quán mẫu</a>'
        result = make(page).run(Collect())
        self.assertEqual(result["urls"], ["https://www.foody.vn/ha-noi/nha-hang-co-chau"])
        self.assertEqual(result["reason"], "exhausted")

    def test_source_server_failure_is_not_exhausted(self):
        page = FakePage(total=12)
        page.responses.append({"url": "https://www.foody.vn/listing-data", "status": 503,
                               "resource_type": "xhr"})
        result = make(page).run(Collect())
        self.assertEqual(result["reason"], "error")
        self.assertFalse(result["coverage_verified"])
        self.assertTrue(page.closed)

    def test_bounded_evidence_keeps_end_event(self):
        page = FakePage(total=72)
        with patch("foody_tool.browser.MAX_EVENTS", 12):
            result = make(page).run(Collect())
        self.assertEqual(result["reason"], "exhausted")
        self.assertLessEqual(len(result["events"]), 12)
        self.assertIn("end_observed", [e["type"] for e in result["events"]])

    def test_exhausted_over_50_urls_unique_stable_with_duplicates(self):
        page = FakePage(total=120, duplicates=True)
        d, cb = make(page), Collect()
        r = d.run(cb)
        self.assertEqual(r["reason"], "exhausted")
        self.assertTrue(r["coverage_verified"])
        self.assertEqual(len(r["urls"]), 120)
        self.assertEqual(r["urls"], [url(i) for i in range(120)])
        self.assertEqual(cb.urls, r["urls"])
        self.assertEqual(r["clicks"], 9)  # 12 initial + 9*12
        self.assertEqual(page.clicks, 9)
        self.assertTrue(page.closed)
        self.assertEqual(r["source_url"], SOURCE_URL)
        self.assertEqual(cb.batches[-1][1]["discovered"], 120)
        self.assertIn("end_observed", [e["type"] for e in r["events"]])
        saved = json.loads((Path(d._tmp) / "browser_discovery.json").read_text("utf-8"))
        self.assertEqual(len(saved["urls"]), 120)

    def test_limit_marks_not_exhausted(self):
        page = FakePage(total=500)
        r = make(page).run(Collect(), max_urls=48)
        self.assertEqual(r["reason"], "limit")
        self.assertFalse(r["coverage_verified"])
        self.assertEqual(len(r["urls"]), 48)
        self.assertTrue(page.closed)

    def test_stalled_never_exhausted(self):
        page = FakePage(total=500, stall_after=24)
        r = make(page, stalled_attempts=3).run(Collect())
        self.assertEqual(r["reason"], "stalled")
        self.assertFalse(r["coverage_verified"])
        self.assertEqual(len(r["urls"]), 24)
        self.assertTrue(page.closed)

    def test_safety_limit(self):
        page = FakePage(total=1000)
        r = make(page, max_clicks=4).run(Collect())
        self.assertEqual(r["reason"], "safety_limit")
        self.assertFalse(r["coverage_verified"])
        self.assertEqual(r["clicks"], 4)

    def test_blocked_on_xhr_429(self):
        page = FakePage(total=500, block_on_click=2)
        r = make(page).run(Collect())
        self.assertEqual(r["reason"], "blocked")
        self.assertFalse(r["coverage_verified"])
        self.assertIn("429", r["error"])
        self.assertEqual(page.clicks, 2)  # stopped immediately, no retry
        self.assertTrue(page.closed)

    def test_third_party_failure_ignored(self):
        page = FakePage(total=30)
        page.responses.append({"url": "https://ads.example.com/x", "status": 403,
                               "resource_type": "xhr"})
        page.responses.append({"url": "https://www.foody.vn/a.png", "status": 403,
                               "resource_type": "image"})
        r = make(page).run(Collect())
        self.assertEqual(r["reason"], "exhausted")

    def test_blocked_navigation_403(self):
        page = FakePage(nav_status=403)
        r = make(page).run(Collect())
        self.assertEqual(r["reason"], "blocked")
        self.assertEqual(r["urls"], [])
        self.assertTrue(page.closed)

    def test_challenge_visible_blocks(self):
        page = FakePage(challenge=True)
        r = make(page).run(Collect())
        self.assertEqual(r["reason"], "blocked")
        self.assertFalse(r["coverage_verified"])

    def test_navigation_timeout(self):
        page = FakePage(nav_error=TimeoutError("Timeout 30000ms exceeded"))
        r = make(page).run(Collect())
        self.assertEqual(r["reason"], "timeout")
        self.assertFalse(r["coverage_verified"])
        self.assertTrue(page.closed)

    def test_no_venues_render_is_timeout_not_exhausted(self):
        page = FakePage(total=0, first=0)
        r = make(page).run(Collect())
        self.assertEqual(r["reason"], "timeout")
        self.assertFalse(r["coverage_verified"])

    def test_stop_requested(self):
        page = FakePage(total=500)
        cb = Collect()
        r = make(page).run(cb, should_stop=lambda: page.clicks >= 3)
        self.assertEqual(r["reason"], "stopped")
        self.assertFalse(r["coverage_verified"])
        self.assertLessEqual(len(r["urls"]), 12 * 4)
        self.assertTrue(page.closed)

    def test_checkpoint_pause_then_cancel(self):
        page = FakePage(total=500)
        calls = {"n": 0}

        def checkpoint():
            calls["n"] += 1
            if page.clicks >= 2:
                raise RuntimeError("cancelled")

        r = make(page).run(Collect(), checkpoint=checkpoint,
                           should_stop=lambda: page.clicks >= 2)
        self.assertEqual(r["reason"], "stopped")
        self.assertGreater(calls["n"], 5)
        self.assertTrue(page.closed)

    def test_interval_between_clicks_at_least_two_seconds(self):
        page = FakePage(total=60)
        d = make(page, interval=0.1)  # clamped to >= 2.0
        d.run(Collect())
        t = page.click_times
        self.assertGreaterEqual(len(t), 3)
        for a, b in zip(t, t[1:]):
            self.assertGreaterEqual(b - a, 2.0)

    def test_factory_failure_is_error_outcome(self):
        def boom(*a):
            raise RuntimeError("msedge not found")

        d = BrowserDiscovery(tempfile.mkdtemp(), factory=boom)
        r = d.run(Collect())
        self.assertEqual(r["reason"], "error")
        self.assertIn("msedge", r["error"])
        self.assertFalse(r["coverage_verified"])

    def test_browser_closed_mid_run_is_error_and_cleans_up(self):
        page = FakePage(total=500, click_error=RuntimeError("Target page, context or browser has been closed"))
        r = make(page).run(Collect())
        self.assertEqual(r["reason"], "error")
        self.assertIn("closed", r["error"])
        self.assertTrue(page.closed)

    def test_on_batch_error_cleans_up(self):
        page = FakePage()

        def bad(new, meta):
            raise ValueError("sink failed")

        r = make(page).run(bad)
        self.assertEqual(r["reason"], "error")
        self.assertTrue(page.closed)

    def test_static_banner_alone_is_not_render(self):
        page = FakePage(total=50, hydrate_after=10 ** 6, banner=True)
        r = make(page).run(Collect())
        self.assertEqual(r["reason"], "timeout")
        self.assertEqual(r["urls"], [])
        self.assertFalse(r["coverage_verified"])

    def test_deferred_hydration_then_exhausted(self):
        page = FakePage(total=30, hydrate_after=8)
        r = make(page).run(Collect())
        self.assertEqual(r["reason"], "exhausted")
        self.assertEqual(len(r["urls"]), 30)

    def test_delayed_growth_while_loading_not_exhausted_early(self):
        page = FakePage(total=36, grow_delay=6)
        r = make(page).run(Collect())
        self.assertEqual(r["reason"], "exhausted")
        self.assertEqual(len(r["urls"]), 36)

    def test_missing_button_unknown_state_never_exhausted(self):
        page = FakePage(total=24, hidden_button_end=True)
        r = make(page).run(Collect())
        self.assertEqual(r["reason"], "stalled")
        self.assertFalse(r["coverage_verified"])
        self.assertEqual(len(r["urls"]), 24)

    def test_unknown_state_from_start_stalls(self):
        page = FakePage(total=24, unknown_state=True)
        r = make(page).run(Collect())
        self.assertEqual(r["reason"], "stalled")
        self.assertFalse(r["coverage_verified"])

    def test_loading_forever_never_exhausted(self):
        page = FakePage(total=12, loading_forever=True)
        r = make(page).run(Collect())
        self.assertEqual(r["reason"], "stalled")
        self.assertFalse(r["coverage_verified"])

    def test_checkpoint_error_without_stop_is_error(self):
        page = FakePage(total=500)

        def checkpoint():
            if page.clicks >= 1:
                raise RuntimeError("boom")

        r = make(page).run(Collect(), checkpoint=checkpoint)
        self.assertEqual(r["reason"], "error")
        self.assertIn("boom", r["error"])
        self.assertTrue(page.closed)

    def test_pause_time_not_counted_against_deadlines(self):
        page = FakePage(total=24)
        d = make(page, timeout_ms=5000)
        state = {"done": False}

        def checkpoint():
            # one long pause (60 s of fake time) after the first batch
            if page.clicks == 1 and not state["done"]:
                state["done"] = True
                d._sleep(60)

        r = d.run(Collect(), checkpoint=checkpoint)
        self.assertEqual(r["reason"], "exhausted")

    def test_invalid_parameters_rejected(self):
        for kw in ({"interval": float("nan")}, {"interval": float("inf")},
                   {"max_clicks": 0}, {"timeout_ms": -1},
                   {"stalled_attempts": 1.5}, {"max_clicks": True}):
            with self.assertRaises(ValueError):
                BrowserDiscovery(tempfile.mkdtemp(), **kw)

    def test_evidence_save_error_reported(self):
        page = FakePage(total=12)
        d = make(page)
        d.out_dir = __file__  # a file, not a directory
        r = d.run(Collect())
        self.assertEqual(r["reason"], "exhausted")
        self.assertTrue(r["evidence_error"])

    def test_single_page_listing_exhausted(self):
        page = FakePage(total=7, first=12)
        r = make(page).run(Collect())
        self.assertEqual(r["reason"], "exhausted")
        self.assertEqual(len(r["urls"]), 7)
        self.assertEqual(r["clicks"], 0)

    def test_playwright_import_lazy(self):
        import subprocess, sys
        code = ("import sys, foody_tool.browser; "
                "sys.exit(1 if 'playwright' in sys.modules else 0)")
        root = str(Path(__file__).resolve().parent.parent)
        self.assertEqual(subprocess.call([sys.executable, "-c", code], cwd=root), 0)


if __name__ == "__main__":
    unittest.main()
