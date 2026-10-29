"""v0.5 menu/photo tests. HTML and images here are SYNTHETIC (structure copied from the live source)."""
import hashlib
import io
import json
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.request
import zipfile
from pathlib import Path

from foody_tool import media
from foody_tool.app import make_server
from foody_tool.jobs import JobManager
from foody_tool.ocr import parse_price, rows_from_ocr

JPEG = b"\xff\xd8\xff\xe0" + b"\x00" * 64
PNG = b"\x89PNG\r\n\x1a\n" + b"\x01" * 64
PUBLIC = lambda host: ["93.184.216.34"]  # noqa: E731
V_URL = "https://www.foody.vn/ha-noi/quan-thu"


def navbar(menu_count=2, food_count=3):
    nav = {"RestaurantID": 7, "TotalPictures": menu_count + food_count, "TotalVideos": 0, "PredefineAlbums": [
        {"Id": -1, "Name": "", "UrlRewriteName": None, "Counts": 5},
        {"Id": 2, "Name": "Món ăn", "UrlRewriteName": "album-mon-an", "Counts": food_count},
        {"Id": 3, "Name": "Thực đơn", "UrlRewriteName": "album-thuc-don", "Counts": menu_count}]}
    return f"<script>var initDataNavBar = {json.dumps(nav)}; </script>"


def home_html():
    return ("<html>" + navbar() + '<script>var x = {"TotalDishes":41,"DeliveryId":5801};</script>'
            '<div class="microsite-gallery"><div class="micro-home-album"><div class="micro-home-album-items">'
            '<a href="javascript:void(0);" class="foody-photo" data-group="2" data-id="900">'
            '<img src="https://down-vn.img.susercontent.com/abc@resize_ss180x180" alt="Bún" title="Bún chả"/></a></div></div>'
            '</div><div class="reviews"><a class="foody-photo" data-id="999"><img src="https://x.susercontent.com/rev@r"/></a></div>'
            "</html>")


def album_html(ids=("11", "12"), slug="album-thuc-don"):
    items = "".join(
        f'<div class="micro-home-album-img"><div class="thumb-image"><a href="https://down-vn.img.susercontent.com/full{i}" '
        f'title="cap{i}" data-id="{i}" data-size="800x600" data-group="5" class="restaurant-img foody-photo">'
        f'<img class="lazy" data-original="https://down-vn.img.susercontent.com/full{i}@resize_ss180x180"/></a></div></div>' for i in ids)
    return ("<html>" + navbar() + '<div class="microGallery" id="microGallery"><script>html = $(\'<div class="micro-home-album-img">'
            "<a href=\"' + item.FullSizeImageUrl + '\" data-id=\"' + item.Id + '\">\');</script>" + items + "</div></html>")


def menu_html(groups):
    model = {"RestaurantID": 7, "TotalItems": sum(len(g["Dishes"]) for g in groups), "MenuItems": groups,
             "LastUpdatedOn": None, "TotalCount": 0, "ResultCount": 0}
    return f"<script>window.intMenu = {json.dumps(model)}; </script>"


class FakeSource:
    """Records requests; maps URL -> (status, headers, body)."""

    def __init__(self, routes):
        self.routes, self.calls = routes, []

    def __call__(self, url, timeout, max_bytes, accept):
        self.calls.append(url)
        status, headers, body = self.routes.get(url, (404, {}, b""))
        return status, headers, body[:max_bytes], len(body) > max_bytes


def make_job(root, with_cache=True):
    job = Path(root) / ("a" * 32)
    (job / "cache").mkdir(parents=True)
    (job / "restaurants.json").write_text(json.dumps([{"foody_id": 7, "name": "Quán thử", "source_url": V_URL}]), "utf-8")
    if with_cache:
        (job / "cache" / (hashlib.sha256(V_URL.encode()).hexdigest()[:20] + ".html")).write_text(home_html(), "utf-8")
    return job


def run(task):
    task.launch()
    task.thread.join(10)
    return task


class Parsing(unittest.TestCase):
    def test_navbar_and_delivery_hint(self):
        nav = media.parse_navbar(home_html())
        self.assertEqual(nav["venue_id"], 7)
        self.assertEqual({a["slug"]: a["count"] for a in nav["albums"]}, {"album-mon-an": 3, "album-thuc-don": 2})
        self.assertEqual(media.parse_delivery_hint(home_html()), {"total_dishes_claimed": 41, "delivery_listed": True})

    def test_home_photos_only_from_gallery_container(self):
        photos = media.parse_home_photos(home_html(), venue_id="7", venue_url=V_URL, source_page=V_URL, fetched_at="t")
        self.assertEqual([p["source_photo_id"] for p in photos], ["900"])  # review photo 999 excluded
        p = photos[0]
        self.assertEqual(p["image_url"], "https://down-vn.img.susercontent.com/abc")
        self.assertTrue(p["image_url_derived_from_thumb"])
        self.assertIsNone(p["source_album"])  # no source category on the home strip
        self.assertEqual(p["caption"], "Bún chả")

    def test_album_page_ignores_script_templates(self):
        photos = media.parse_album_page(album_html(), "album-thuc-don", venue_id="7", venue_url=V_URL,
                                        source_page=V_URL + "/album-thuc-don", fetched_at="t")
        self.assertEqual([p["source_photo_id"] for p in photos], ["11", "12"])
        self.assertTrue(all(p["is_menu_image"] and p["source_album"] == "album-thuc-don" for p in photos))
        self.assertEqual((photos[0]["width"], photos[0]["height"]), (800, 600))
        self.assertFalse(photos[0]["image_url_derived_from_thumb"])

    def test_menu_items_keep_raw_and_null_unsupplied_prices(self):
        html = menu_html([{"Name": "Phở", "Dishes": [{"Id": 1, "Name": " Phở  bò ", "Price": 55000},
                                                      {"Id": 2, "Name": "Nước", "Price": 0}]}])
        r = media.parse_menu_page(html, "7", V_URL, V_URL + "/thuc-don", "t")
        self.assertEqual(r["status"], "menu_items")
        a, b = r["items"]
        self.assertEqual((a["name"], a["price_vnd"], a["price_status"]), ("Phở bò", 55000, "source_supplied"))
        self.assertEqual(a["name_raw"], " Phở  bò ")
        self.assertEqual((b["price_vnd"], b["price_status"]), (None, "not_supplied"))
        self.assertEqual(a["group"], "Phở")

    def test_empty_menu_and_missing_model_are_distinct(self):
        self.assertEqual(media.parse_menu_page(menu_html([]), "7", V_URL, "u", "t")["status"], "empty_confirmed")
        self.assertEqual(media.parse_menu_page("<html></html>", "7", V_URL, "u", "t")["status"], "no_model")


class UrlGuards(unittest.TestCase):
    def test_image_url_allow_and_reject(self):
        ok = "https://down-vn.img.susercontent.com/x"
        self.assertEqual(media.check_image_url(ok, PUBLIC), ok)
        bad = ["http://down-vn.img.susercontent.com/x", "https://127.0.0.1/x", "https://localhost/x",
               "https://evil.com/x", "https://a.susercontent.com.evil.com/x", "https://u:p@a.susercontent.com/x",
               "https://a.susercontent.com:8443/x", "https://[::1]/x", "file:///etc/passwd", "ftp://a.susercontent.com/x",
               "https://a.susercontent.com/x y", "https://a.susercontent.com/x#f"]
        for url in bad:
            with self.assertRaises(media.UrlError, msg=url):
                media.check_image_url(url, PUBLIC)

    def test_allowed_host_resolving_to_private_address_is_rejected(self):
        for addr in ("10.0.0.5", "127.0.0.1", "169.254.169.254", "192.168.1.1", "::1"):
            with self.assertRaises(media.UrlError):
                media.check_image_url("https://a.susercontent.com/x", lambda h, a=addr: [a])

    def test_page_url_only_known_suffixes(self):
        self.assertEqual(media.page_url(V_URL, "/thuc-don"), V_URL + "/thuc-don")
        with self.assertRaises(media.UrlError):
            media.page_url("https://evil.com/ha-noi/x", "/thuc-don")
        with self.assertRaises(media.UrlError):
            media.page_url(V_URL, "/../../admin")


class Tasks(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.job = make_job(self.temp.name)
        self.store = media.MediaStore(self.job)
        self.summary = media.scan_cached(self.store)

    def tearDown(self):
        self.temp.cleanup()

    def task(self, kind, routes, opts=None, **kw):
        self.src = FakeSource(routes)
        base = {"interval": 2.5 if kind == "collect" else 1.0}
        return media.MediaTask(self.store, kind, ["7"], dict(base, **(opts or {})), fetcher=self.src,
                               sleeper=lambda s: None, resolver=PUBLIC, **kw)

    def test_scan_is_offline_and_reports_counts(self):
        self.assertEqual(self.summary["photos_from_cache"], 1)
        rec = self.store.venues["7"]
        self.assertEqual((rec["menu_image_count"], rec["delivery_listed"], rec["menu_text_status"] if "menu_text_status" in rec else None),
                         (2, True, None))
        self.assertEqual(media.coverage_summary(self.store)["menu_text_states"], {"not_collected": 1})

    def test_collect_menu_and_album(self):
        menu = menu_html([{"Name": "G", "Dishes": [{"Id": 1, "Name": "Phở", "Price": 50000}]}])
        t = run(self.task("collect", {
            V_URL + "/thuc-don": (200, {}, menu.encode()),
            V_URL + "/album-thuc-don": (200, {}, album_html().encode())}))
        self.assertEqual(t.state, "completed")
        self.assertEqual(t.counts["page_requests"], 2)
        self.assertEqual(t.counts["api_requests"], 0)
        self.assertEqual(len(self.store.menu), 1)
        self.assertEqual(self.store.venues["7"]["menu_text_status"], "menu_items")
        self.assertEqual(self.store.venues["7"]["menu_images_listed"], 2)
        self.assertTrue(media.MediaStore(self.job).photos["7-11"]["is_menu_image"])  # persisted
        # resume: nothing re-requested
        t2 = run(self.task("collect", {}))
        self.assertEqual(self.src.calls, [])

    def test_collect_empty_menu_is_not_reported_as_items(self):
        t = run(self.task("collect", {V_URL + "/thuc-don": (200, {}, menu_html([]).encode())}, {"albums": []}))
        self.assertEqual(self.store.venues["7"]["menu_text_status"], "empty_confirmed")
        self.assertEqual(len(self.store.menu), 0)

    def test_blocked_stops_and_is_not_retried(self):
        t = run(self.task("collect", {V_URL + "/thuc-don": (429, {}, b"")}))
        self.assertEqual(t.state, "stopped")
        self.assertTrue(t.stop_reason.startswith("blocked"))
        self.assertEqual(len(self.src.calls), 1)
        self.assertEqual(self.store.venues["7"]["menu_text_status"], "blocked")

    def test_challenge_page_and_login_redirect_block(self):
        t = run(self.task("collect", {V_URL + "/thuc-don": (200, {}, b"<html>Please solve the CAPTCHA</html>")}))
        self.assertTrue(t.stop_reason.startswith("blocked"))
        t = run(self.task("collect", {V_URL + "/thuc-don": (302, {"location": "/dang-nhap?returnUrl=x"}, b"")}))
        self.assertEqual(t.stop_reason, "blocked: login_required")

    def test_page_redirect_off_site_rejected(self):
        t = run(self.task("collect", {V_URL + "/thuc-don": (302, {"location": "https://evil.com/x"}, b"")}, {"albums": []}))
        self.assertEqual(self.store.pages[V_URL + "/thuc-don"]["status"], "unsafe_redirect")

    def test_max_pages_budget(self):
        t = run(self.task("collect", {V_URL + "/thuc-don": (200, {}, menu_html([]).encode()),
                                      V_URL + "/album-thuc-don": (200, {}, album_html().encode())}, {"max_pages": 1}))
        self.assertEqual((t.counts["page_requests"], t.stop_reason), (1, "max_pages"))

    def test_interval_floor_enforced(self):
        with self.assertRaises(ValueError):
            self.task("collect", {}, {"interval": 0.5})

    def _collect_album(self):
        run(self.task("collect", {V_URL + "/album-thuc-don": (200, {}, album_html().encode())}, {"menu": False}))

    def test_download_validates_content_and_resumes(self):
        self._collect_album()
        routes = {"https://down-vn.img.susercontent.com/full11": (200, {"content-type": "image/jpeg"}, JPEG),
                  "https://down-vn.img.susercontent.com/full12": (200, {"content-type": "image/jpeg"}, b"<html>not an image</html>")}
        t = run(self.task("download", routes, {"menu_images_only": True}))
        ph = self.store.photos
        self.assertEqual(ph["7-11"]["download_status"], "ok")
        self.assertEqual(ph["7-12"]["download_status"], "not_an_image")
        self.assertEqual((t.counts["images_ok"], t.counts["images_failed"]), (1, 1))
        saved = self.store.dir / ph["7-11"]["local_path"]
        self.assertEqual(saved.name, "11.jpg")
        self.assertEqual(hashlib.sha256(saved.read_bytes()).hexdigest(), ph["7-11"]["sha256"])
        # resume: the valid file is skipped, the failed one is retried
        routes["https://down-vn.img.susercontent.com/full12"] = (200, {"content-type": "image/png"}, PNG)
        t2 = run(self.task("download", routes, {"menu_images_only": True}))
        self.assertEqual(t2.counts["images_skipped_existing"], 1)
        self.assertEqual(self.src.calls, ["https://down-vn.img.susercontent.com/full12"])
        self.assertEqual(self.store.photos["7-12"]["download_status"], "ok")

    def test_download_resume_registers_orphan_file_without_request(self):
        self._collect_album()
        folder = self.store.images / "7"
        folder.mkdir(parents=True)
        (folder / "11.jpg").write_bytes(JPEG)  # interrupted run left the file, state not saved
        t = run(self.task("download", {}, {"menu_images_only": True, "max_images_per_venue": 1}))
        self.assertEqual(self.src.calls, [])
        self.assertEqual(self.store.photos["7-11"]["download_status"], "ok")

    def test_download_limits_and_size_cap(self):
        self._collect_album()
        big = JPEG + b"0" * 5000
        routes = {f"https://down-vn.img.susercontent.com/full{i}": (200, {"content-type": "image/jpeg"}, big) for i in (11, 12)}
        t = run(self.task("download", routes, {"menu_images_only": True, "max_bytes_per_image": 1000}))
        self.assertEqual(self.store.photos["7-11"]["download_status"], "too_large")
        self.assertEqual(t.counts["images_failed"], 2)
        t = run(self.task("download", routes, {"menu_images_only": True, "max_images_per_venue": 1}))
        self.assertEqual(t.counts["images_selected"], 1)

    def test_download_rejects_private_redirect_and_blocks_on_403(self):
        self._collect_album()
        routes = {"https://down-vn.img.susercontent.com/full11": (302, {"location": "https://127.0.0.1/secret.jpg"}, b""),
                  "https://down-vn.img.susercontent.com/full12": (403, {}, b"")}
        t = run(self.task("download", routes, {"menu_images_only": True}))
        self.assertEqual(self.store.photos["7-11"]["download_status"], "unsafe_redirect")
        self.assertTrue(t.stop_reason.startswith("blocked"))
        self.assertNotIn("https://127.0.0.1/secret.jpg", self.src.calls)

    def test_duplicate_content_is_flagged_not_duplicated_silently(self):
        self._collect_album()
        routes = {f"https://down-vn.img.susercontent.com/full{i}": (200, {"content-type": "image/jpeg"}, JPEG) for i in (11, 12)}
        run(self.task("download", routes, {"menu_images_only": True}))
        self.assertEqual(self.store.photos["7-12"]["duplicate_of"], "7-11")

    def test_home_category_and_derived_url_download(self):
        routes = {"https://down-vn.img.susercontent.com/abc": (200, {"content-type": "image/jpeg"}, JPEG)}
        t = run(self.task("download", routes, {"categories": ["home"]}))
        self.assertEqual(self.store.photos["7-900"]["download_status"], "ok")

    def test_exports_neutralise_formulas_and_archive_is_clean(self):
        self._collect_album()
        self.store.photos["7-11"]["caption"] = "=HYPERLINK(\"http://x\")"
        routes = {"https://down-vn.img.susercontent.com/full11": (200, {"content-type": "image/jpeg"}, JPEG)}
        run(self.task("download", routes, {"menu_images_only": True, "max_images_per_venue": 1}))
        name, mime, data = media.export_bytes(self.store, "photos_csv")
        self.assertIn("'=HYPERLINK", data.decode("utf-8-sig"))
        self.assertTrue(data.startswith(b"\xef\xbb\xbf"))
        blob, count = media.build_archive(self.store)
        names = zipfile.ZipFile(io.BytesIO(blob)).namelist()
        self.assertEqual(count, 1)
        self.assertIn("images/7/11.jpg", names)
        self.assertTrue(all(not n.startswith(("/", "..")) and ".." not in n for n in names))


class OcrParsing(unittest.TestCase):
    def test_price_shapes(self):
        self.assertEqual(parse_price("Giò bò 45,000 VND/ Bát")[0], 45000)
        self.assertEqual(parse_price("Trà đá 5.000 VND/ Ly")[0], 5000)
        self.assertEqual(parse_price("Cà phê 25k")[0], 25000)
        self.assertIsNone(parse_price("Phở 45")[0])  # bare number: ambiguous
        self.assertIsNone(parse_price("Tel 0967 915565")[0])
        self.assertIsNone(parse_price("45.000 PATE 60.000")[0])  # two prices in a row: ambiguous

    def test_rows_group_words_by_y(self):
        ocr = {"lines": [{"text": "a", "words": [{"text": "Phở", "x": 10, "y": 100, "w": 30, "h": 20},
                                                  {"text": "bò", "x": 50, "y": 101, "w": 20, "h": 20}]},
                         {"text": "b", "words": [{"text": "45,000", "x": 300, "y": 99, "w": 50, "h": 20}]}]}
        rows = rows_from_ocr(ocr)
        self.assertEqual(len(rows), 1)
        self.assertEqual((rows[0]["name_ocr"], rows[0]["price_candidate_vnd"]), ("Phở bò", 45000))


class MediaAPI(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        root = Path(self.temp.name)
        job = root / "jobs" / ("b" * 32)
        (job / "cache").mkdir(parents=True)
        (job / "restaurants.json").write_text(json.dumps([{"foody_id": 7, "name": "Quán thử", "source_url": V_URL}]), "utf-8")
        (job / "cache" / (hashlib.sha256(V_URL.encode()).hexdigest()[:20] + ".html")).write_text(home_html(), "utf-8")
        (job / "job.json").write_text(json.dumps({
            "id": "b" * 32, "mode": "sample", "limit": 1, "interval": 3.0, "show_browser": False, "state": "completed",
            "stage": "finished", "started_at": "2026-01-01T00:00:00+00:00"}), "utf-8")
        assets = root / "web"
        assets.mkdir()
        (assets / "index.html").write_text("x", "utf-8")
        self.manager = JobManager(root / "jobs")
        self.job_id = "b" * 32
        self.server = make_server(self.manager, port=0, web_root=assets)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.base = f"http://127.0.0.1:{self.server.server_port}"
        self.token = self.request("/api/status")[1]["csrf_token"]

    def tearDown(self):
        self.manager.shutdown()
        self.server.shutdown()
        self.server.server_close()
        self.temp.cleanup()

    def request(self, path, body=None, token=True):
        headers = {}
        data = None
        if body is not None:
            data = json.dumps(body).encode()
            headers["Content-Type"] = "application/json"
            if token:
                headers["X-CSRF-Token"] = self.token
        try:
            resp = urllib.request.urlopen(urllib.request.Request(self.base + path, data=data, headers=headers), timeout=5)
        except urllib.error.HTTPError as exc:
            resp = exc
        with resp:
            raw = resp.read()
            return resp.status, (json.loads(raw) if resp.headers.get_content_type() == "application/json" else raw)

    def test_scan_status_venues_detail_downloads(self):
        q = f"job_id={self.job_id}"
        self.assertEqual(self.request(f"/api/media/download?{q}&format=menu_csv")[0], 404)  # not scanned yet
        self.assertEqual(self.request("/api/media/scan", {"job_id": self.job_id}, token=False)[0], 403)
        code, res = self.request("/api/media/scan", {"job_id": self.job_id})
        self.assertEqual((code, res["summary"]["photos_from_cache"]), (200, 1))
        code, st = self.request(f"/api/media/status?{q}")
        self.assertTrue(st["scanned"])
        self.assertEqual(st["summary"]["menu_text_states"], {"not_collected": 1})
        code, v = self.request(f"/api/media/venues?{q}&filter=menu_images")
        self.assertEqual(v["total"], 1)
        code, d = self.request(f"/api/media/venue?{q}&venue_id=7")
        self.assertEqual(len(d["photos"]), 1)
        self.assertEqual(self.request(f"/api/media/venue?{q}&venue_id=nope")[0], 404)
        for fmt in ("menu_csv", "menu_json", "photos_csv", "photos_json", "venues_csv", "menu_ocr_csv", "menu_ocr_json"):
            code, body = self.request(f"/api/media/download?{q}&format={fmt}")
            self.assertEqual(code, 200, fmt)
        self.assertEqual(self.request(f"/api/media/download?{q}&format=archive")[0], 404)  # no images yet
        self.assertEqual(self.request(f"/api/media/download?{q}&format=../x")[0], 400)
        self.assertEqual(self.request(f"/api/media/file?{q}&photo_id=7-900")[0], 404)  # not downloaded

    def test_collect_rejects_unknown_venue_and_bad_limits(self):
        self.request("/api/media/scan", {"job_id": self.job_id})
        code, res = self.request("/api/media/collect", {"job_id": self.job_id, "venue_ids": ["999"]})
        self.assertEqual(code, 400)
        code, res = self.request("/api/media/collect", {"job_id": self.job_id, "interval": 0.1})
        self.assertEqual(code, 400)
        code, res = self.request("/api/media/images", {"job_id": self.job_id, "max_total_images": -3})
        self.assertEqual(code, 400)

    def test_served_image_requires_registered_local_file(self):
        self.request("/api/media/scan", {"job_id": self.job_id})
        store = media.MediaStore(self.manager.get(self.job_id).directory)
        store.images.mkdir(parents=True, exist_ok=True)
        (store.images / "7").mkdir(exist_ok=True)
        (store.images / "7" / "900.jpg").write_bytes(JPEG)
        store.photos["7-900"].update(download_status="ok", local_path="images/7/900.jpg", mime="image/jpeg")
        store.photos["7-901"] = dict(store.photos["7-900"], photo_id="7-901", local_path="../venues.json")
        store.save()
        q = f"job_id={self.job_id}"
        self.assertEqual(self.request(f"/api/media/file?{q}&photo_id=7-900")[0], 200)
        self.assertEqual(self.request(f"/api/media/file?{q}&photo_id=7-901")[0], 404)  # path escape refused


if __name__ == "__main__":
    unittest.main()


class FailureStreak(unittest.TestCase):
    def test_consecutive_failures_stop_the_task(self):
        with tempfile.TemporaryDirectory() as tmp:
            job = make_job(tmp)
            store = media.MediaStore(job)
            media.scan_cached(store)
            store.venues.update({str(i): dict(store.venues["7"], venue_url=f"https://www.foody.vn/ha-noi/q{i}", venue_id=str(i))
                                 for i in range(10, 30)})
            src = FakeSource({})  # every URL 404 -> http_error
            t = media.MediaTask(store, "collect", [str(i) for i in range(10, 30)], {"albums": []}, fetcher=src,
                                sleeper=lambda s: None, resolver=PUBLIC)
            run(t)
            self.assertTrue(t.stop_reason.startswith("source_unstable"))
            self.assertEqual(len(src.calls), media.MAX_FAILURE_STREAK)


class AtomicWrite(unittest.TestCase):
    def test_replace_retries_when_target_is_briefly_locked(self):
        import os
        calls = {"n": 0}
        real = os.replace

        def flaky(a, b):
            calls["n"] += 1
            if calls["n"] < 3:
                raise PermissionError(5, "Access is denied")
            return real(a, b)
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "x.json"
            media.os.replace, media.time.sleep = flaky, lambda s: None
            try:
                media.atomic_json(target, {"a": 1})
            finally:
                media.os.replace = real
                media.time.sleep = time.sleep
            self.assertEqual(json.loads(target.read_text("utf-8")), {"a": 1})
            self.assertEqual(calls["n"], 3)
