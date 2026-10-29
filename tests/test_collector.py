import json
import tempfile
import unittest
from pathlib import Path

from foody_tool import collector as C
from foody_tool.exporter import export_all

ROOT = Path(__file__).resolve().parent.parent
FIX = ROOT / "tests" / "fixtures"
import unittest as _ut
if not (ROOT / "reference" / "sample5.json").exists():
    raise _ut.SkipTest("needs local reference/sample5.json (scraped sample, not part of the public repo)")
SAMPLE = json.loads((ROOT / "reference" / "sample5.json").read_text(encoding="utf-8"))
BASE = "https://www.foody.vn/ha-noi/"


def html_for(i, name=None):
    d = {"RestaurantID": i, "Name": name or f"Quán {i}", "Latitude": 21.0 + i / 1000,
         "Longtitude": 105.8, "Address": f"{i} Phố", "District": "Q", "City": "Hà Nội",
         "PriceMin": 1000, "PriceMax": 2000, "OpeningTime": []}
    return f"<h1>{d['Name']}</h1><script>var initData = {json.dumps(d)};</script>"


class FakeNet:
    """Scripted fetcher. routes: url -> list of (status, headers, body) consumed in order
    (last one repeats); an Exception instance in the list is raised."""

    def __init__(self, routes):
        self.routes = {k: list(v) for k, v in routes.items()}
        self.calls = []

    def __call__(self, url, timeout):
        self.calls.append(url)
        seq = self.routes[url]
        item = seq.pop(0) if len(seq) > 1 else seq[0]
        if isinstance(item, BaseException):
            raise item
        s, h, b = item
        return s, {k.lower(): v for k, v in h.items()}, b.encode("utf-8") if isinstance(b, str) else b


def ok(i):
    return (200, {"Content-Type": "text/html; charset=utf-8"}, html_for(i))


class Base(unittest.TestCase):
    def setUp(self):
        self._t = tempfile.TemporaryDirectory()
        self.addCleanup(self._t.cleanup)
        self.out = self._t.name
        self.now_t = 0.0
        self.sleeps = []

    def clock(self):
        return self.now_t

    def sleep(self, s):
        self.sleeps.append(s)
        self.now_t += s

    def col(self, net, **kw):
        kw.setdefault("backoff", 1.0)
        return C.Collector(self.out, net, clock=self.clock, sleeper=self.sleep,
                           now=lambda: "2026-10-14T00:00:00+00:00", **kw)


class UrlValidation(unittest.TestCase):
    def test_valid(self):
        self.assertEqual(C.normalize_restaurant_url(BASE + "abc-1/"), BASE + "abc-1")

    def test_invalid(self):
        for u in ("http://www.foody.vn/ha-noi/a", "https://evil.com/ha-noi/a",
                  "https://www.foody.vn.evil.com/ha-noi/a", "https://www.foody.vn/ha-noi/a/thuc-don",
                  "https://www.foody.vn/ha-noi/o-dau", "https://www.foody.vn/sai-gon/a",
                  "https://www.foody.vn/ha-noi/a?x=1", "https://u:p@www.foody.vn/ha-noi/a",
                  "https://www.foody.vn:8443/ha-noi/a", "https://www.foody.vn/ha-noi/"):
            with self.assertRaises(C.UrlError, msg=u):
                C.normalize_restaurant_url(u)


class Collect(Base):
    def test_success_and_rate_limit(self):
        urls = [BASE + "a", BASE + "b", BASE + "c"]
        net = FakeNet({u: [ok(i)] for i, u in enumerate(urls, 1)})
        c = self.col(net)
        req, stopped = c.run(urls)
        self.assertIsNone(stopped)
        self.assertEqual(len(c.records(req)), 3)
        self.assertEqual(net.calls, urls)
        self.assertEqual(self.sleeps, [2.0, 2.0])  # min 2s between request starts

    def test_max_50(self):
        urls = [BASE + f"v{i}" for i in range(60)]
        net = FakeNet({u: [ok(i + 1)] for i, u in enumerate(urls)})
        req, _ = self.col(net).run(urls, max_urls=500)
        self.assertEqual(len(req), 50)
        self.assertEqual(len(net.calls), 50)

    def test_live_min_interval_floor(self):
        with self.assertRaises(ValueError):
            C.Collector(self.out, C.default_fetcher, min_interval=0.5)

    def test_transient_retry_then_success(self):
        u = BASE + "a"
        net = FakeNet({u: [(503, {}, ""), TimeoutError("t"), ok(1)]})
        c = self.col(net)
        req, _ = c.run([u])
        self.assertEqual(c.progress[u]["status"], "ok")
        self.assertEqual(c.progress[u]["attempts"], 3)
        self.assertEqual(len(net.calls), 3)

    def test_transient_retries_bounded(self):
        u = BASE + "a"
        net = FakeNet({u: [(500, {}, "")]})
        c = self.col(net, max_retries=2)
        c.run([u])
        self.assertEqual(len(net.calls), 3)
        self.assertEqual(c.progress[u]["status"], "transient_failed")

    def test_404_not_retried(self):
        u = BASE + "a"
        net = FakeNet({u: [(404, {}, "nf")]})
        c = self.col(net)
        c.run([u])
        self.assertEqual(len(net.calls), 1)
        self.assertEqual(c.progress[u]["status"], "http_error")

    def test_blocked_429_stops_run(self):
        urls = [BASE + "a", BASE + "b", BASE + "c"]
        net = FakeNet({urls[0]: [ok(1)], urls[1]: [(429, {}, "slow down")], urls[2]: [ok(3)]})
        c = self.col(net)
        req, stopped = c.run(urls)
        self.assertIn("blocked", stopped)
        self.assertEqual(net.calls, urls[:2])
        self.assertNotIn(urls[2], c.progress)
        self.assertEqual(c.progress[urls[1]]["status"], "blocked")

    def test_403_and_captcha_page_block(self):
        u = BASE + "a"
        c = self.col(FakeNet({u: [(403, {}, "no")]}))
        self.assertIn("blocked", c.run([u])[1])
        u2 = BASE + "b"
        with tempfile.TemporaryDirectory() as d:
            c2 = C.Collector(d, FakeNet({u2: [(200, {}, "<html>Please solve the CAPTCHA</html>")]}),
                             clock=self.clock, sleeper=self.sleep)
            _, stopped = c2.run([u2])
            self.assertIn("blocked", stopped)
            self.assertEqual(c2.records([u2]), [])

    def test_200_without_initdata_is_parse_error_not_success(self):
        u = BASE + "a"
        c = self.col(FakeNet({u: [(200, {}, "<html>hello</html>")]}))
        req, stopped = c.run([u])
        self.assertIsNone(stopped)
        self.assertEqual(c.progress[u]["status"], "parse_error")
        self.assertEqual(c.records(req), [])

    def test_unsafe_redirects(self):
        cases = ["https://evil.example/ha-noi/a", "http://www.foody.vn/ha-noi/a",
                 "https://www.foody.vn/ha-noi/o-dau", "https://www.foody.vn/dang-nhap?r=1",
                 "https://www.foody.vn.evil.com/ha-noi/a"]
        for loc in cases:
            with tempfile.TemporaryDirectory() as d:
                u = BASE + "a"
                net = FakeNet({u: [(302, {"Location": loc}, "")]})
                c = C.Collector(d, net, clock=self.clock, sleeper=self.sleep)
                c.run([u])
                self.assertEqual(c.progress[u]["status"], "unsafe_redirect", loc)
                self.assertEqual(net.calls, [u], "must not follow unsafe redirect")

    def test_safe_redirect_followed_and_loop_bounded(self):
        a, b = BASE + "a", BASE + "a-new"
        net = FakeNet({a: [(301, {"Location": "/ha-noi/a-new"}, "")], b: [ok(7)]})
        c = self.col(net)
        c.run([a])
        self.assertEqual(c.progress[a]["status"], "ok")
        self.assertEqual(c.progress[a]["final_url"], b)
        self.assertEqual(c.progress[a]["record"]["source_url"], a)
        loop = BASE + "loop"
        net2 = FakeNet({loop: [(302, {"Location": "/ha-noi/loop2"}, "")],
                        BASE + "loop2": [(302, {"Location": "/ha-noi/loop"}, "")]})
        with tempfile.TemporaryDirectory() as d:
            c2 = C.Collector(d, net2, clock=self.clock, sleeper=self.sleep)
            c2.run([loop])
            self.assertEqual(c2.progress[loop]["status"], "unsafe_redirect")
            self.assertLessEqual(len(net2.calls), C.MAX_REDIRECTS + 1)

    def test_invalid_input_url_never_fetched(self):
        net = FakeNet({})
        c = self.col(net)
        req, _ = c.run(["https://evil.com/ha-noi/a"])
        self.assertEqual(net.calls, [])
        self.assertEqual(c.progress["https://evil.com/ha-noi/a"]["status"], "invalid_url")

    def test_duplicate_ids(self):
        a, b, c3 = BASE + "a", BASE + "b", BASE + "c"
        net = FakeNet({a: [ok(9)], b: [ok(9)], c3: [ok(10)]})
        c = self.col(net)
        req, _ = c.run([a, b, c3])
        self.assertEqual([r["foody_id"] for r in c.records(req)], [9, 10])
        self.assertEqual(c.progress[b]["status"], "duplicate_id")
        self.assertEqual(c.progress[b]["duplicate_of"], a)

    def test_duplicate_urls_in_input_fetched_once(self):
        a = BASE + "a"
        net = FakeNet({a: [ok(1)]})
        self.col(net).run([a, a + "/", a])
        self.assertEqual(net.calls, [a])

    def test_interrupted_resume(self):
        urls = [BASE + x for x in "abcd"]
        routes = {u: [ok(i)] for i, u in enumerate(urls, 1)}
        routes[urls[2]] = [KeyboardInterrupt()]
        net = FakeNet(routes)
        with self.assertRaises(KeyboardInterrupt):
            self.col(net).run(urls)
        saved = json.loads((Path(self.out) / "progress.json").read_text(encoding="utf-8"))
        self.assertEqual({u for u, e in saved.items() if e["status"] == "ok"}, set(urls[:2]))
        net2 = FakeNet({u: [ok(i)] for i, u in enumerate(urls, 1)})
        c = self.col(net2)  # new process: reloads progress
        req, stopped = c.run(urls)
        self.assertIsNone(stopped)
        self.assertEqual(net2.calls, urls[2:], "completed URLs must not be re-requested")
        self.assertEqual([r["foody_id"] for r in c.records(req)], [1, 2, 3, 4])

    def test_resume_after_block_retries_blocked_only(self):
        urls = [BASE + "a", BASE + "b"]
        c = self.col(FakeNet({urls[0]: [ok(1)], urls[1]: [(429, {}, "")]}))
        c.run(urls)
        net2 = FakeNet({urls[1]: [ok(2)]})
        c2 = self.col(net2)
        c2.run(urls)
        self.assertEqual(net2.calls, [urls[1]])
        self.assertEqual(len(c2.records(urls)), 2)

    def test_cache_reparse_without_network(self):
        a = BASE + "a"
        c = self.col(FakeNet({a: [(200, {}, "<html>broken</html>")]}))
        c.run([a])
        self.assertEqual(c.progress[a]["status"], "parse_error")
        # cached body is reused on re-run with no network call
        net = FakeNet({})
        c2 = self.col(net)
        c2.run([a])
        self.assertEqual(net.calls, [])

    def test_progress_has_no_menu_or_ugc(self):
        a = BASE + "a"
        c = self.col(FakeNet({a: [ok(1)]}))
        c.run([a])
        self.assertEqual(set(c.progress[a]["record"]) & {"menu", "reviews", "images"}, set())


@unittest.skipUnless((FIX / "thanhvan.html").exists(), "local fixtures missing")
class SampleEndToEnd(Base):
    def test_sample5_via_simulated_network(self):
        routes = {s["source_url"]: [(200, {"Content-Type": "text/html; charset=utf-8"},
                                     (FIX / f"{s['key']}.html").read_bytes())] for s in SAMPLE}
        net = FakeNet(routes)
        c = self.col(net)
        req, stopped = c.run([s["source_url"] for s in SAMPLE])
        self.assertIsNone(stopped)
        recs = c.records(req)
        self.assertEqual(len(recs), 5)
        for r, s in zip(recs, SAMPLE):
            for k in ("foody_id", "name", "lat", "lon", "address", "opening_hours_raw",
                      "price_min_vnd", "price_max_vnd"):
                self.assertEqual(r[k], s[k])
        report = export_all(self.out, c.progress, recs, req)
        self.assertEqual(report["completeness"]["lat"]["present"], 5)



class CliCacheOnly(Base):
    def test_cli_runs_from_cache_without_network(self):
        from foody_tool.__main__ import main
        urls = [BASE + "a", BASE + "b"]
        seed = self.col(FakeNet({}))
        for i, u in enumerate(urls, 1):
            Path(seed.cache_path(u)).write_text(html_for(i), encoding="utf-8")
        uf = Path(self.out) / "urls.txt"
        uf.write_text("# comment\n" + "\n".join(urls) + "\n", encoding="utf-8")
        rc = main(["collect", "--urls-file", str(uf), "--out-dir", self.out])
        self.assertEqual(rc, 0)
        data = json.loads((Path(self.out) / "restaurants.json").read_text(encoding="utf-8"))
        self.assertEqual([r["foody_id"] for r in data], [1, 2])
        self.assertTrue((Path(self.out) / "report.json").exists())

class ReviewFixes(Base):
    def test_malformed_port_is_invalid_url_not_crash(self):
        for u in ("https://www.foody.vn:abc/ha-noi/a", "https://[::1/ha-noi/a", "https://www.foody.vn:99999/ha-noi/a"):
            with self.assertRaises(C.UrlError, msg=u):
                C.normalize_restaurant_url(u)
        net = FakeNet({})
        c = self.col(net)
        c.run(["https://www.foody.vn:abc/ha-noi/a"])
        self.assertEqual(net.calls, [])

    def test_challenge_page_mentioning_initdata_still_blocks(self):
        u, v = BASE + "a", BASE + "b"
        body = "<html>captcha required <script>var initData = {oops</script></html>"
        net = FakeNet({u: [(200, {}, body)], v: [ok(2)]})
        c = self.col(net)
        _, stopped = c.run([u, v])
        self.assertIn("blocked", stopped)
        self.assertEqual(net.calls, [u])

    def test_alias_only_invocation_resolves_canonical(self):
        a, b = BASE + "a", BASE + "b"
        net = FakeNet({a: [ok(9)], b: [ok(9)]})
        self.col(net).run([a, b])
        c2 = self.col(FakeNet({}))
        req, _ = c2.run([b])
        self.assertEqual(c2.progress[b]["status"], "duplicate_id")
        self.assertEqual([r["foody_id"] for r in c2.records(req)], [9])
        report = export_all(self.out, c2.progress, c2.records(req), req)
        self.assertEqual(report["records_exported"], 1)
        self.assertFalse(report["partial"])

    def test_report_marks_partial(self):
        a, b = BASE + "a", BASE + "b"
        c = self.col(FakeNet({a: [ok(1)], b: [(404, {}, "")]}))
        req, _ = c.run([a, b])
        report = export_all(self.out, c.progress, c.records(req), req)
        self.assertTrue(report["partial"])
        self.assertEqual(report["outcomes"], {"ok": 1, "http_error": 1})

    def test_numeric_validation(self):
        nan = float("nan")
        for kw in ({"min_interval": nan}, {"min_interval": -1}, {"timeout": 0}, {"timeout": nan},
                   {"max_retries": -1}, {"max_retries": 99}, {"backoff": -1}):
            with self.assertRaises(ValueError, msg=str(kw)):
                C.Collector(self.out, FakeNet({}), **kw)
        for mu in (0, -3, True):
            with self.assertRaises(ValueError):
                self.col(FakeNet({})).run([], max_urls=mu)

    def test_cli_rejects_bad_numbers(self):
        from foody_tool.__main__ import main
        uf = Path(self.out) / "u.txt"
        uf.write_text(BASE + "a" + chr(10), encoding="utf-8")
        for extra in (["--min-interval", "nan"], ["--min-interval", "0.5"], ["--max-retries", "-1"],
                      ["--timeout", "-5"], ["--max-urls", "0"]):
            rc = main(["collect", "--urls-file", str(uf), "--out-dir", self.out] + extra)
            self.assertEqual(rc, 1, extra)


if __name__ == "__main__":
    unittest.main()
