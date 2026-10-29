"""v0.5 menu and photo collection: parsing, guarded fetching and a per-job media store.

Everything here is source-supplied or explicitly labelled. Dish *groups* and venue price ranges are
never treated as menu items. Image menus are listed and downloadable; no OCR text is produced.
"""
import csv
import hashlib
import io
import ipaddress
import json
import os
import re
import socket
import threading
import time
import unicodedata
import urllib.error
import urllib.request
import zipfile
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urljoin, urlsplit

from .collector import (BLOCK_MARKERS, MAX_REDIRECTS, USER_AGENT, UrlError,
                        normalize_restaurant_url)

MEDIA_SCHEMA_VERSION = 1
PAGE_SUFFIXES = {"", "/thuc-don", "/album-thuc-don", "/album-mon-an", "/album-khong-gian",
                 "/album-tong-hop", "/album-professional", "/album-anh"}
ALBUMS = {  # source-supplied album slug -> Vietnamese label
    "album-thuc-don": "Thực đơn", "album-mon-an": "Món ăn", "album-khong-gian": "Không gian",
    "album-tong-hop": "Tổng hợp", "album-professional": "Chuyên nghiệp",
}
IMAGE_HOST_SUFFIXES = (".susercontent.com", ".foody.vn")
MAX_PAGE_BYTES = 5 * 1024 * 1024
ALBUM_PAGE_SIZE = 20  # the first server-rendered page of an album; later pages need the site's own scripts
MIN_PAGE_INTERVAL = 2.0
MIN_IMAGE_INTERVAL = 0.5
MAX_FAILURE_STREAK = 5
DEFAULT_LIMITS = {
    "max_images_per_venue": 8, "max_total_images": 200, "max_bytes_per_image": 8 * 1024 * 1024,
    "max_total_mb": 400, "max_pages": 300,
}
HARD_LIMITS = {
    "max_images_per_venue": 100, "max_total_images": 20000, "max_bytes_per_image": 25 * 1024 * 1024,
    "max_total_mb": 20000, "max_pages": 20000,
}
_SIGNATURES = (
    (b"\xff\xd8\xff", "image/jpeg", "jpg"), (b"\x89PNG\r\n\x1a\n", "image/png", "png"),
    (b"GIF87a", "image/gif", "gif"), (b"GIF89a", "image/gif", "gif"),
)


def utcnow():
    return datetime.now(timezone.utc).isoformat()


def atomic_json(path, value):
    path = Path(path)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(value, ensure_ascii=False, indent=1), encoding="utf-8")
    # Windows refuses to replace a file another process (a status poll, an indexer) has open: retry briefly.
    for attempt in range(40):
        try:
            os.replace(temp, path)
            return
        except PermissionError:
            if attempt == 39:
                raise
            time.sleep(0.25)


def sniff_image(head):
    """Return (mime, extension) from magic bytes, or None. Content-Type alone is never trusted."""
    for sig, mime, ext in _SIGNATURES:
        if head.startswith(sig):
            return mime, ext
    if head[:4] == b"RIFF" and head[8:12] == b"WEBP":
        return "image/webp", "webp"
    return None


# ---------------------------------------------------------------- URL guards
def page_url(venue_url, suffix=""):
    base = normalize_restaurant_url(venue_url)
    if suffix not in PAGE_SUFFIXES:
        raise UrlError("page type not allowed")
    return base + suffix


def _public_address(addr):
    ip = ipaddress.ip_address(addr)
    return not (ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_multicast
                or ip.is_reserved or ip.is_unspecified)


def check_image_url(url, resolver=None):
    """Allow only https image URLs on known CDN hosts that resolve to public addresses."""
    if not isinstance(url, str):
        raise UrlError("URL is not text")
    try:
        p = urlsplit(url.strip())
        port = p.port
    except ValueError as exc:
        raise UrlError(f"malformed URL: {exc}") from None
    host = (p.hostname or "").lower()
    if p.scheme != "https" or p.username or p.password or port not in (None, 443):
        raise UrlError("image URL must be plain https")
    try:
        ipaddress.ip_address(host)
        raise UrlError("IP-literal hosts are not allowed")
    except ValueError as exc:
        if isinstance(exc, UrlError):
            raise
    if not host or not any(host.endswith(s) for s in IMAGE_HOST_SUFFIXES):
        raise UrlError(f"image host not allowed: {host}")
    if p.fragment or len(url) > 1000 or any(c in url for c in "\r\n\t "):
        raise UrlError("image URL malformed")
    resolve = resolver or (lambda h: [i[4][0] for i in socket.getaddrinfo(h, 443, proto=socket.IPPROTO_TCP)])
    try:
        addresses = resolve(host)
    except OSError as exc:
        raise UrlError(f"cannot resolve image host: {exc}") from None
    if not addresses or not all(_public_address(a) for a in addresses):
        raise UrlError("image host resolves to a non-public address")
    return url.strip()


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *a, **kw):
        return None


def default_fetcher(url, timeout, max_bytes, accept):
    """Single GET, no automatic redirects. Returns (status, headers, body, truncated)."""
    opener = urllib.request.build_opener(_NoRedirect)
    req = urllib.request.Request(url, headers={
        "User-Agent": USER_AGENT, "Accept": accept, "Accept-Language": "vi,en;q=0.5"})
    try:
        resp = opener.open(req, timeout=timeout)
    except urllib.error.HTTPError as exc:
        resp = exc
    with resp:
        status = getattr(resp, "status", None) or resp.code
        headers = {k.lower(): v for k, v in resp.headers.items()}
        body = resp.read(max_bytes + 1)
    return status, headers, body[:max_bytes], len(body) > max_bytes


# ---------------------------------------------------------------- HTML parsing
def _json_after(html, marker):
    """Decode the JSON object following ``marker`` (e.g. ``var initDataNavBar = ``)."""
    i = html.find(marker)
    if i < 0:
        return None
    j = html.find("{", i + len(marker))
    if j < 0 or html[i + len(marker):j].strip():
        return None
    try:
        return json.JSONDecoder().raw_decode(html[j:])[0]
    except ValueError:
        return None


def parse_navbar(html):
    """Venue id, total photo count and source album counts from the microsite header."""
    nav = _json_after(html, "var initDataNavBar = ")
    if not isinstance(nav, dict):
        return None
    albums = []
    for a in nav.get("PredefineAlbums") or []:
        slug = a.get("UrlRewriteName")
        if slug in ALBUMS:
            albums.append({"slug": slug, "label": ALBUMS[slug], "source_name": a.get("Name"),
                           "count": a.get("Counts") if isinstance(a.get("Counts"), int) else None})
    return {"venue_id": nav.get("RestaurantID"), "total_pictures": nav.get("TotalPictures"),
            "total_videos": nav.get("TotalVideos"), "albums": albums}


def parse_delivery_hint(html):
    """Counts the source *claims* (TotalDishes / DeliveryId). They are indicators, not menu data."""
    dishes = re.search(r'"TotalDishes":(\d+)', html)
    delivery = re.search(r'"DeliveryId":(null|\d+)', html)
    return {"total_dishes_claimed": int(dishes.group(1)) if dishes else None,
            "delivery_listed": bool(delivery and delivery.group(1) != "null")}


def full_size_url(thumb):
    return thumb.split("@", 1)[0] if thumb else thumb


class _PhotoParser(HTMLParser):
    """Collect <a ... data-id=...><img> pairs inside one gallery container class."""

    def __init__(self, container_class, anchor_class=None):
        super().__init__(convert_charrefs=True)
        self.container_class, self.anchor_class = container_class, anchor_class
        self.depth = 0
        self.stack = []
        self.items = []
        self.cur = None
        self.title_div = False

    def _has(self, attrs, name):
        return name in (dict(attrs).get("class") or "").split()

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == "div":
            if self.depth == 0 and self._has(attrs, self.container_class):
                self.depth = 1
            elif self.depth:
                self.depth += 1
                if self._has(attrs, "edit-album-title") or self._has(attrs, "by"):
                    self.title_div = True
        if not self.depth:
            return
        if tag == "a" and a.get("data-id") and (self.anchor_class is None or self._has(attrs, self.anchor_class)):
            self.cur = {"source_photo_id": a["data-id"], "href": a.get("href"), "title": a.get("title"),
                        "size": a.get("data-size"), "group": a.get("data-group"), "thumb": None, "alt": None}
            self.items.append(self.cur)
        elif tag == "img" and self.cur is not None and not self.cur["thumb"]:
            self.cur["thumb"] = a.get("data-original") or a.get("src")
            self.cur["alt"] = a.get("title") or a.get("alt")

    def handle_endtag(self, tag):
        if tag == "div" and self.depth:
            self.depth -= 1
        if tag == "a":
            self.cur = None


def _photo_records(items, *, venue_id, venue_url, source_page, album_slug, method, fetched_at):
    out, seen = [], set()
    for it in items:
        thumb = it["thumb"] or ""
        href = it["href"] or ""
        derived = not href.startswith("https://")
        full = full_size_url(thumb) if derived else href
        if not full.startswith("https://") or it["source_photo_id"] in seen:
            continue
        seen.add(it["source_photo_id"])
        size = re.fullmatch(r"(\d+)x(\d+)", it["size"] or "")
        out.append({
            "photo_id": f"{venue_id}-{it['source_photo_id']}", "source_photo_id": it["source_photo_id"],
            "venue_id": venue_id, "venue_url": venue_url, "source_page": source_page,
            "image_url": full, "thumb_url": thumb or None, "image_url_derived_from_thumb": derived,
            "source_album": album_slug, "source_album_label": ALBUMS.get(album_slug),
            "source_group_raw": it["group"],
            "caption": (it["title"] or it["alt"] or "").strip() or None,
            "source_date": None,  # the public page supplies no photo date
            "width": int(size.group(1)) if size else None, "height": int(size.group(2)) if size else None,
            "is_menu_image": album_slug == "album-thuc-don",
            "extraction_method": method, "fetched_at": fetched_at,
        })
    return out


def parse_home_photos(html, **ctx):
    """Community photo strip on the venue home page (a source-chosen sample, not the full album)."""
    start = html.find('class="microsite-gallery')
    if start < 0:
        return []
    p = _PhotoParser("microsite-gallery", "foody-photo")
    p.feed(html[html.rfind("<div", 0, start):start + 60000])
    return _photo_records(p.items, album_slug=None, method="cached_home_gallery", **ctx)


def parse_album_page(html, album_slug, **ctx):
    """First server-rendered page of one album. ``more_available`` when the album is larger."""
    p = _PhotoParser("microGallery", "restaurant-img")
    p.feed(html)
    photos = _photo_records(p.items, album_slug=album_slug, method="album_page_live", **ctx)
    return photos


def _clean(text):
    return re.sub(r"\s+", " ", unicodedata.normalize("NFC", str(text or ""))).strip()


def parse_menu_page(html, venue_id, venue_url, source_url, fetched_at):
    """Structured text menu from the page's embedded ``window.intMenu`` model.

    Returns {"status", "items", "raw"}; status is menu_items | empty_confirmed | no_model.
    Each item keeps the raw dish dict; price_vnd is only set for a positive source price.
    """
    model = _json_after(html, "window.intMenu = ")
    if not isinstance(model, dict):
        return {"status": "no_model", "items": [], "raw": None}
    items = []
    for gi, group in enumerate(model.get("MenuItems") or []):
        for di, dish in enumerate(group.get("Dishes") or []):
            price = dish.get("Price")
            ok = isinstance(price, (int, float)) and not isinstance(price, bool) and price > 0
            items.append({
                "item_id": f"{venue_id}-m{dish.get('Id') if dish.get('Id') is not None else f'{gi}.{di}'}",
                "venue_id": venue_id, "venue_url": venue_url, "source_url": source_url,
                "fetched_at": fetched_at, "extraction_method": "foody_thuc_don_embedded_json",
                "group_raw": group.get("Name"), "name_raw": dish.get("Name"),
                "price_raw": price, "name": _clean(dish.get("Name")) or None,
                "group": _clean(group.get("Name")) or None,
                "price_vnd": int(price) if ok else None,
                "price_status": "source_supplied" if ok else "not_supplied",
                "image_thumb_url": dish.get("ImageThumbUrl") or None,
                "source_dish_raw": dish,
            })
    return {"status": "menu_items" if items else "empty_confirmed", "items": items,
            "raw": {k: model.get(k) for k in ("TotalItems", "TotalCount", "ResultCount", "LastUpdatedOn")}}


def looks_blocked(status, body_text):
    if status in (403, 429):
        return True
    if "initDataNavBar" in body_text:
        return False
    low = body_text[:20000].lower()
    return any(m in low for m in BLOCK_MARKERS)


# ---------------------------------------------------------------- store
class MediaStore:
    """Persistent media state for one crawl job: ``<job>/media/``."""

    FILES = {"venues": "venues.json", "photos": "photos.json", "menu": "menu_items.json",
             "pages": "pages.json", "ocr": "menu_ocr.json"}

    def __init__(self, job_dir):
        self.job_dir = Path(job_dir)
        self.dir = self.job_dir / "media"
        self.images = self.dir / "images"
        self.lock = threading.RLock()
        self.venues, self.photos, self.menu, self.pages, self.ocr = {}, {}, {}, {}, {}
        for key, name in self.FILES.items():
            path = self.dir / name
            for attempt in range(5):  # a concurrent atomic replace can briefly hide or lock the file
                try:
                    if path.is_file():
                        setattr(self, key, json.loads(path.read_text(encoding="utf-8")))
                    break
                except (OSError, ValueError):
                    time.sleep(0.1)

    def save(self):
        with self.lock:
            self.dir.mkdir(parents=True, exist_ok=True)
            for key, name in self.FILES.items():
                atomic_json(self.dir / name, getattr(self, key))

    @property
    def exists(self):
        return (self.dir / "venues.json").is_file()


def _cache_path(job_dir, url):
    return Path(job_dir) / "cache" / (hashlib.sha256(url.encode()).hexdigest()[:20] + ".html")


def _job_venues(job_dir):
    """Venue id -> {name, url} from the job's normalized/enriched/base exports; fall back to urls.json."""
    job_dir = Path(job_dir)
    for name in ("restaurants_enriched.json", "restaurants.json"):
        path = job_dir / name
        if path.is_file():
            try:
                rows = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            out = {}
            for r in rows:
                vid, url = r.get("foody_id"), r.get("source_url")
                if vid is not None and url:
                    out[str(vid)] = {"venue_id": str(vid), "name": r.get("name"), "venue_url": url,
                                     "district": r.get("district")}
            if out:
                return out
    return {}


def scan_cached(store, *, now=utcnow):
    """Offline: derive media availability and the community photo strip from cached venue pages.

    Zero network requests. Safe to re-run: live-collected photos/menu are preserved.
    """
    venues = _job_venues(store.job_dir)
    stamp = now()
    summary = {"venues_total": len(venues), "pages_cached": 0, "pages_missing": 0, "pages_unparsed": 0,
               "photos_from_cache": 0}
    with store.lock:
        for vid, base in venues.items():
            path = _cache_path(store.job_dir, base["venue_url"])
            rec = store.venues.setdefault(vid, {})
            rec.update(base)
            if not path.is_file():
                summary["pages_missing"] += 1
                rec.setdefault("cache_status", "missing")
                rec["cache_status"] = "missing"
                continue
            html = path.read_text(encoding="utf-8", errors="replace")
            nav = parse_navbar(html)
            if not nav:
                summary["pages_unparsed"] += 1
                rec["cache_status"] = "unparsed"
                continue
            summary["pages_cached"] += 1
            rec.update(parse_delivery_hint(html))
            rec.update(cache_status="ok", total_pictures=nav["total_pictures"], albums=nav["albums"],
                       menu_image_count=next((a["count"] for a in nav["albums"] if a["slug"] == "album-thuc-don"), None),
                       scanned_at=stamp)
            for ph in parse_home_photos(html, venue_id=vid, venue_url=base["venue_url"],
                                        source_page=base["venue_url"], fetched_at=stamp):
                old = store.photos.get(ph["photo_id"])
                if old:
                    continue
                store.photos[ph["photo_id"]] = dict(ph, download_status="not_downloaded", local_path=None)
                summary["photos_from_cache"] += 1
        store.save()
    return summary


def menu_status(rec, store=None):
    """Honest state label for a venue's text menu."""
    return (rec or {}).get("menu_text_status") or "not_collected"


# ---------------------------------------------------------------- live task
class StopRequested(Exception):
    pass


def _clamp_limits(opts):
    out = {}
    for key, default in DEFAULT_LIMITS.items():
        v = opts.get(key, default)
        if isinstance(v, bool) or not isinstance(v, (int, float)) or v != v or v <= 0:
            raise ValueError(f"{key} không hợp lệ.")
        out[key] = min(int(v), HARD_LIMITS[key])
    return out


class MediaTask:
    """One bounded, sequential media run (collect pages or download images)."""

    def __init__(self, store, kind, venue_ids, options, *, fetcher=default_fetcher, sleeper=time.sleep,
                 clock=time.monotonic, now=utcnow, resolver=None):
        self.store, self.kind, self.options = store, kind, dict(options)
        self.venue_ids = list(venue_ids)
        self.fetcher, self.sleeper, self.clock, self.now, self.resolver = fetcher, sleeper, clock, now, resolver
        self.limits = _clamp_limits(self.options)
        floor = MIN_PAGE_INTERVAL if kind == "collect" else (0 if kind == "ocr" else MIN_IMAGE_INTERVAL)
        interval = self.options.get("interval", 3.0 if kind == "collect" else 1.0)
        if isinstance(interval, bool) or not isinstance(interval, (int, float)) or interval != interval or interval < floor:
            raise ValueError(f"Khoảng chờ tối thiểu là {floor} giây.")
        self.interval = float(interval)
        self.state, self.message = "queued", ""
        self.counts = {"venues_total": len(self.venue_ids), "venues_done": 0, "page_requests": 0,
                       "image_requests": 0, "api_requests": 0, "page_bytes": 0, "image_bytes": 0,
                       "menu_items": 0, "photos_listed": 0, "images_ok": 0, "images_skipped_existing": 0,
                       "images_failed": 0, "images_duplicate": 0, "limit_hit": None}
        self.errors, self.stop_reason = [], None
        self._streak = 0  # consecutive failed requests; a flaky source makes us back off instead of hammering it
        self.started_at = self.finished_at = None
        self._stop, self._pause = threading.Event(), threading.Event()
        self._last = None
        self.thread = None

    # -- control
    def launch(self):
        self.state, self.started_at = "running", self.now()
        self.thread = threading.Thread(target=self._run, daemon=True)
        self.thread.start()

    def stop(self):
        self._stop.set()
        self._pause.clear()

    def pause(self):
        if self.state == "running":
            self._pause.set()

    def unpause(self):
        self._pause.clear()

    @property
    def active(self):
        return bool(self.thread and self.thread.is_alive())

    def snapshot(self):
        return {"kind": self.kind, "state": "paused" if self._pause.is_set() and self.state == "running" else self.state,
                "message": self.message, "counts": dict(self.counts), "limits": self.limits,
                "interval": self.interval, "stop_reason": self.stop_reason, "errors": self.errors[-20:],
                "started_at": self.started_at, "finished_at": self.finished_at,
                "options": {k: v for k, v in self.options.items() if k in
                            ("albums", "menu", "categories", "menu_images_only", "refresh")}}

    # -- helpers
    def _checkpoint(self):
        while self._pause.is_set() and not self._stop.is_set():
            time.sleep(0.2)
        if self._stop.is_set():
            raise StopRequested()

    def _pace(self):
        if self._last is not None:
            wait = self.interval - (self.clock() - self._last)
            if wait > 0:
                self.sleeper(wait)
        self._last = self.clock()

    def _error(self, text):
        self.errors.append(text)
        del self.errors[:-200]

    def _fetch(self, url, kind, max_bytes, accept):
        res = self._fetch_once(url, kind, max_bytes, accept)
        self._streak = 0 if res["kind"] == "ok" else self._streak + 1
        if self._streak >= MAX_FAILURE_STREAK and not self.stop_reason:
            self.stop_reason = f"source_unstable: {self._streak} lỗi liên tiếp"
            self.message = "Nguồn liên tục lỗi/quá tải. Đã dừng để không dồn thêm yêu cầu."
        return res

    def _fetch_once(self, url, kind, max_bytes, accept):
        """One guarded request with validated redirects. Returns dict(kind=ok|blocked|http_error|...)."""
        current = url
        for hop in range(MAX_REDIRECTS + 1):
            self._checkpoint()
            self._pace()
            counter = "page_requests" if kind == "page" else "image_requests"
            self.counts[counter] += 1
            try:
                status, headers, body, truncated = self.fetcher(current, 25, max_bytes, accept)
            except Exception as exc:  # transient network failure
                return {"kind": "network_error", "error": f"{type(exc).__name__}: {exc}"}
            self.counts["page_bytes" if kind == "page" else "image_bytes"] += len(body)
            if status in (301, 302, 303, 307, 308):
                loc = headers.get("location")
                try:
                    nxt = urljoin(current, loc or "")
                    if kind == "page":
                        p = urlsplit(nxt)
                        if "/dang-nhap" in p.path:
                            return {"kind": "blocked", "error": "login_required"}
                        if (p.scheme != "https" or (p.hostname or "").lower() != "www.foody.vn" or p.query
                                or not p.path.startswith("/ha-noi/")):
                            raise UrlError("redirect leaves the venue pages")
                    else:
                        check_image_url(nxt, self.resolver)
                except (UrlError, ValueError) as exc:
                    return {"kind": "unsafe_redirect", "error": str(exc)}
                current = nxt
                continue
            if status in (403, 429):
                return {"kind": "blocked", "error": f"HTTP {status}", "status": status}
            if status != 200:
                return {"kind": "http_error", "error": f"HTTP {status}", "status": status}
            return {"kind": "ok", "status": 200, "headers": headers, "body": body,
                    "truncated": truncated, "final_url": current}
        return {"kind": "unsafe_redirect", "error": "too many redirects"}

    def _fetch_page(self, venue_url, suffix):
        url = page_url(venue_url, suffix)
        res = self._fetch(url, "page", MAX_PAGE_BYTES, "text/html")
        if res["kind"] == "ok":
            if res["truncated"]:
                return {"kind": "http_error", "error": "page too large", "url": url}
            res["html"] = res["body"].decode("utf-8", errors="replace")
            if looks_blocked(200, res["html"]):
                return {"kind": "blocked", "error": "challenge page", "url": url}
        res["url"] = url
        return res

    # -- run
    def _run(self):
        try:
            if self.kind == "collect":
                self._collect()
            elif self.kind == "ocr":
                self._ocr()
            else:
                self._download()
            self.state = "completed" if not self.stop_reason else "stopped"
        except StopRequested:
            self.state, self.stop_reason = "stopped", self.stop_reason or "user_stop"
        except Exception as exc:
            self.state, self.stop_reason = "failed", f"{type(exc).__name__}: {exc}"
        finally:
            self.finished_at = self.now()
            try:
                self.store.save()
            except OSError as exc:
                self._error(f"save failed: {exc}")

    def _collect(self):
        store, opts = self.store, self.options
        albums = [a for a in opts.get("albums", ["album-thuc-don"]) if a in ALBUMS]
        want_menu = bool(opts.get("menu", True))
        refresh = bool(opts.get("refresh", False))
        for vid in self.venue_ids:
            self._checkpoint()
            rec = store.venues.get(vid)
            if not rec:
                self._error(f"{vid}: không có trong đợt này")
                continue
            plan = []
            if want_menu:
                plan.append(("/thuc-don", None))
            for slug in albums:
                count = next((a["count"] for a in rec.get("albums", []) if a["slug"] == slug), None)
                if count == 0:  # the venue's own header says the album is empty; no request needed
                    continue
                plan.append(("/" + slug, slug))
            for suffix, slug in plan:
                key = rec["venue_url"] + suffix
                if not refresh and store.pages.get(key, {}).get("status") in ("ok", "empty_confirmed", "menu_items"):
                    continue
                if self.counts["page_requests"] >= self.limits["max_pages"]:
                    self.counts["limit_hit"] = "max_pages"
                    self.stop_reason = "max_pages"
                    return
                self._collect_page(vid, rec, suffix, slug, key)
                if self.stop_reason:
                    return
            self.counts["venues_done"] += 1
            if self.counts["venues_done"] % 5 == 0:
                store.save()

    def _collect_page(self, vid, rec, suffix, slug, key):
        store = self.store
        res = self._fetch_page(rec["venue_url"], suffix)
        stamp = self.now()
        if res["kind"] != "ok":
            store.pages[key] = {"status": res["kind"], "error": res.get("error"), "fetched_at": stamp}
            if res["kind"] == "blocked":
                self.stop_reason = f"blocked: {res.get('error')}"
                self.message = "Nguồn chặn hoặc yêu cầu xác minh. Đã dừng, không vượt qua."
                if suffix == "/thuc-don":
                    rec["menu_text_status"] = "blocked"
            else:
                self._error(f"{vid}{suffix}: {res.get('error')}")
                if suffix == "/thuc-don":
                    rec["menu_text_status"] = "error"
            return
        html = res["html"]
        if suffix == "/thuc-don":
            parsed = parse_menu_page(html, vid, rec["venue_url"], res["url"], stamp)
            with store.lock:
                for k in [k for k, v in store.menu.items() if v["venue_id"] == vid]:
                    del store.menu[k]
                for it in parsed["items"]:
                    store.menu[it["item_id"]] = it
            rec["menu_text_status"] = parsed["status"]
            rec["menu_text_items"] = len(parsed["items"])
            rec["menu_text_checked_at"] = stamp
            self.counts["menu_items"] += len(parsed["items"])
            store.pages[key] = {"status": parsed["status"], "fetched_at": stamp, "raw": parsed["raw"],
                                "bytes": len(res["body"])}
            return
        photos = parse_album_page(html, slug, venue_id=vid, venue_url=rec["venue_url"],
                                  source_page=res["url"], fetched_at=stamp)
        nav = parse_navbar(html)
        declared = next((a["count"] for a in (nav or {}).get("albums", []) if a["slug"] == slug), None)
        added = 0
        with store.lock:
            for ph in photos:
                cur = store.photos.get(ph["photo_id"])
                if cur:  # keep download state; upgrade provenance to the album-specific listing
                    cur.update({k: ph[k] for k in ("image_url", "source_page", "source_album", "source_album_label",
                                                  "is_menu_image", "width", "height", "caption",
                                                  "image_url_derived_from_thumb", "extraction_method", "fetched_at")})
                else:
                    store.photos[ph["photo_id"]] = dict(ph, download_status="not_downloaded", local_path=None)
                    added += 1
        self.counts["photos_listed"] += len(photos)
        truncated = declared is not None and declared > len(photos)
        store.pages[key] = {"status": "ok", "fetched_at": stamp, "listed": len(photos), "declared": declared,
                            "truncated": truncated, "bytes": len(res["body"])}
        if slug == "album-thuc-don":
            rec["menu_images_listed"] = len(photos)
            rec["menu_images_truncated"] = truncated
        rec.setdefault("albums_listed", {})[slug] = {"listed": len(photos), "declared": declared,
                                                     "truncated": truncated}

    # -- local OCR of downloaded menu images (experimental, never merged into menu_items)
    def _ocr(self):
        from . import ocr
        store = self.store
        wanted = set(self.venue_ids)
        todo = [p for p in sorted(store.photos.values(), key=lambda p: p["photo_id"])
                if p["venue_id"] in wanted and p.get("is_menu_image") and p.get("download_status") == "ok"
                and (self.options.get("refresh") or p["photo_id"] not in store.ocr)]
        self.counts["images_selected"] = len(todo)
        if not todo:
            self.message = "Không có ảnh thực đơn đã tải nào cần OCR (hãy tải ảnh thực đơn trước)."
        for ph in todo[:self.limits["max_total_images"]]:
            self._checkpoint()
            self.counts["venues_done"] += 1
            path = (store.dir / ph["local_path"]).resolve()
            if store.images.resolve() not in path.parents:
                continue
            try:
                res = ocr.run_ocr(path)
            except Exception as exc:
                self.counts["images_failed"] += 1
                self._error(f"{ph['photo_id']}: {exc}")
                continue
            rows = ocr.rows_from_ocr(res)
            stamp = self.now()
            store.ocr[ph["photo_id"]] = {
                "photo_id": ph["photo_id"], "venue_id": ph["venue_id"], "image_sha256": ph.get("sha256"),
                "source_page": ph["source_page"], "image_url": ph["image_url"],
                "extraction_method": "windows_media_ocr_local", "engine_language": res.get("engine_language"),
                "status": "ocr_needs_review", "ocr_at": stamp,
                "note": "Văn bản do OCR; chưa kiểm chứng. Không phải giá/món đã xác minh.",
                "rows": [dict(r, status="ocr_needs_review") for r in rows]}
            self.counts["images_ok"] += 1
            self.counts["ocr_price_candidates"] = self.counts.get("ocr_price_candidates", 0) + sum(1 for r in rows if r["price_candidate_vnd"])

    # -- image download
    def _select_images(self):
        store, opts, lim = self.store, self.options, self.limits
        cats = opts.get("categories") or None  # list of album slugs; "home" = community strip (no album)
        menu_only = bool(opts.get("menu_images_only", False))
        per = {}
        chosen, seen_urls = [], set()
        wanted = set(self.venue_ids)
        for pid, ph in sorted(store.photos.items()):
            if ph["venue_id"] not in wanted:
                continue
            if menu_only and not ph.get("is_menu_image"):
                continue
            if cats:
                tag = ph.get("source_album") or "home"
                if tag not in cats:
                    continue
            if ph["image_url"] in seen_urls:
                continue
            seen_urls.add(ph["image_url"])
            if per.get(ph["venue_id"], 0) >= lim["max_images_per_venue"]:
                continue
            per[ph["venue_id"]] = per.get(ph["venue_id"], 0) + 1
            chosen.append(ph)
        return chosen[:lim["max_total_images"]]

    def _existing_file(self, ph):
        path = self.store.images / ph["venue_id"]
        if path.is_dir():
            for f in path.glob(f"{ph['source_photo_id']}.*"):
                head = f.read_bytes()[:16]
                if f.stat().st_size > 0 and sniff_image(head):
                    return f
        return None

    def _download(self):
        store, lim = self.store, self.limits
        chosen = self._select_images()
        self.counts["images_selected"] = len(chosen)
        if not chosen:
            self.message = "Không có ảnh phù hợp để tải (hãy thu thập danh sách ảnh cho các quán này trước)."
        budget = lim["max_total_mb"] * 1024 * 1024
        hashes = {p["sha256"]: pid for pid, p in store.photos.items() if p.get("sha256") and p.get("local_path")}
        venues_seen = set()
        for ph in chosen:
            self._checkpoint()
            venues_seen.add(ph["venue_id"])
            self.counts["venues_done"] = len(venues_seen)
            have = self._existing_file(ph)
            if have and ph.get("download_status") == "ok" and ph.get("local_path"):
                self.counts["images_skipped_existing"] += 1
                continue
            if have:  # file present from an interrupted run: re-register without a request
                data = have.read_bytes()
                self._register(ph, have, data, hashes)
                self.counts["images_skipped_existing"] += 1
                continue
            if self.counts["image_bytes"] >= budget:
                self.counts["limit_hit"] = "max_total_mb"
                self.stop_reason = "max_total_mb"
                return
            try:
                url = check_image_url(ph["image_url"], self.resolver)
            except UrlError as exc:
                ph["download_status"], ph["download_error"] = "rejected_url", str(exc)
                self.counts["images_failed"] += 1
                continue
            res = self._fetch(url, "image", lim["max_bytes_per_image"], "image/*")
            if self.stop_reason and res["kind"] != "ok":
                ph["download_status"], ph["download_error"] = res["kind"], res.get("error")
                return
            if res["kind"] == "blocked":
                self.stop_reason = f"blocked: {res.get('error')}"
                self.message = "Nguồn chặn tải ảnh. Đã dừng, không vượt qua."
                ph["download_status"], ph["download_error"] = "blocked", res.get("error")
                return
            if res["kind"] != "ok":
                ph["download_status"], ph["download_error"] = res["kind"], res.get("error")
                self.counts["images_failed"] += 1
                self._error(f"{ph['photo_id']}: {res.get('error')}")
                continue
            if res["truncated"]:
                ph["download_status"], ph["download_error"] = "too_large", f"> {lim['max_bytes_per_image']} bytes"
                self.counts["images_failed"] += 1
                continue
            sniffed = sniff_image(res["body"][:16])
            ctype = (res["headers"].get("content-type") or "").split(";")[0].strip().lower()
            if not sniffed or not ctype.startswith("image/"):
                ph["download_status"], ph["download_error"] = "not_an_image", ctype or "no content-type"
                self.counts["images_failed"] += 1
                continue
            mime, ext = sniffed
            folder = store.images / ph["venue_id"]
            folder.mkdir(parents=True, exist_ok=True)
            target = folder / f"{ph['source_photo_id']}.{ext}"
            temp = target.with_suffix(target.suffix + ".part")
            temp.write_bytes(res["body"])
            os.replace(temp, target)
            ph["content_type_header"] = ctype
            self._register(ph, target, res["body"], hashes)
            if self.counts["images_ok"] % 20 == 0:
                store.save()

    def _register(self, ph, path, data, hashes):
        digest = hashlib.sha256(data).hexdigest()
        ph.update(download_status="ok", local_path=path.relative_to(self.store.dir).as_posix(),
                  sha256=digest, bytes=len(data), mime=sniff_image(data[:16])[0], downloaded_at=self.now())
        ph.pop("download_error", None)
        first = hashes.get(digest)
        if first and first != ph["photo_id"]:
            ph["duplicate_of"] = first
            self.counts["images_duplicate"] += 1
        else:
            ph.pop("duplicate_of", None)
            hashes[digest] = ph["photo_id"]
        self.counts["images_ok"] += 1


# ---------------------------------------------------------------- exports
PHOTO_COLUMNS = ["photo_id", "venue_id", "venue_url", "source_page", "image_url", "thumb_url",
                 "image_url_derived_from_thumb", "source_album", "source_album_label", "source_group_raw",
                 "caption", "source_date", "width", "height", "is_menu_image", "extraction_method",
                 "fetched_at", "download_status", "download_error", "local_path", "sha256", "bytes", "mime",
                 "duplicate_of"]
MENU_COLUMNS = ["item_id", "venue_id", "venue_url", "source_url", "fetched_at", "extraction_method",
                "group_raw", "name_raw", "price_raw", "name", "group", "price_vnd", "price_status",
                "image_thumb_url"]
OCR_COLUMNS = ["photo_id", "venue_id", "source_page", "image_url", "image_sha256", "extraction_method",
               "engine_language", "ocr_at", "ocr_row_text", "name_ocr", "price_candidate_vnd",
               "price_raw_text", "unit_ocr", "status"]
VENUE_COLUMNS = ["venue_id", "name", "venue_url", "district", "cache_status", "total_pictures",
                 "menu_image_count", "menu_images_listed", "menu_text_status", "menu_text_items",
                 "total_dishes_claimed", "delivery_listed", "menu_text_checked_at"]


def _csv_cell(value):
    if isinstance(value, bool):
        return "true" if value else "false"
    if value is None:
        return ""
    text = str(value)
    # Neutralise spreadsheet formulas in source-supplied text.
    return "'" + text if text[:1] in ("=", "+", "-", "@") and not re.fullmatch(r"-?\d+(\.\d+)?", text) else text


def _csv_bytes(rows, columns):
    buf = io.StringIO(newline="")
    w = csv.writer(buf, lineterminator="\r\n")
    w.writerow(columns)
    for r in rows:
        w.writerow([_csv_cell(r.get(c)) for c in columns])
    return ("﻿" + buf.getvalue()).encode("utf-8")


def _json_bytes(value):
    return json.dumps(value, ensure_ascii=False, indent=1).encode("utf-8")


def venue_rows(store):
    return [dict(r, venue_id=vid) for vid, r in sorted(store.venues.items())]


def export_bytes(store, fmt, venue_ids=None):
    """Return (filename, mime, bytes) for menu/photo/venue exports, optionally filtered by venue."""
    sel = set(venue_ids) if venue_ids else None
    keep = (lambda r: sel is None or r["venue_id"] in sel)
    menu = [r for r in store.menu.values() if keep(r)]
    photos = [r for r in store.photos.values() if keep(r)]
    menu.sort(key=lambda r: r["item_id"])
    photos.sort(key=lambda r: r["photo_id"])
    if fmt == "menu_csv":
        return "menu_items.csv", "text/csv; charset=utf-8", _csv_bytes(menu, MENU_COLUMNS)
    if fmt == "menu_json":
        return "menu_items.json", "application/json; charset=utf-8", _json_bytes(
            {"schema": "foody-menu-items/1", "generated_at": utcnow(), "items": menu,
             "note": "Chỉ gồm món do nguồn công khai cung cấp; nhóm món và khoảng giá quán không phải món/giá."})
    if fmt == "photos_csv":
        return "photos_manifest.csv", "text/csv; charset=utf-8", _csv_bytes(photos, PHOTO_COLUMNS)
    if fmt == "photos_json":
        return "photos_manifest.json", "application/json; charset=utf-8", _json_bytes(
            {"schema": "foody-photos/1", "generated_at": utcnow(), "photos": photos})
    if fmt == "menu_images_csv":
        return "menu_images_manifest.csv", "text/csv; charset=utf-8", _csv_bytes(
            [p for p in photos if p.get("is_menu_image")], PHOTO_COLUMNS)
    if fmt in ("menu_ocr_csv", "menu_ocr_json"):
        docs = [d for d in store.ocr.values() if keep(d)]
        docs.sort(key=lambda d: d["photo_id"])
        if fmt == "menu_ocr_json":
            return "menu_ocr.json", "application/json; charset=utf-8", _json_bytes(
                {"schema": "foody-menu-ocr/1", "generated_at": utcnow(), "images": docs,
                 "warning": "OCR cục bộ (en-US, không có tiếng Việt): tên món mất dấu/sai chữ, giá chỉ là ứng viên. Mọi dòng cần kiểm tra."})
        flat = [dict(d, **r) for d in docs for r in d["rows"]]
        return "menu_ocr.csv", "text/csv; charset=utf-8", _csv_bytes(flat, OCR_COLUMNS)
    if fmt == "venues_csv":
        return "venues_media.csv", "text/csv; charset=utf-8", _csv_bytes(
            [r for r in venue_rows(store) if sel is None or r["venue_id"] in sel], VENUE_COLUMNS)
    raise ValueError("Định dạng tải xuống không hợp lệ.")


def build_archive(store, venue_ids=None):
    """Zip downloaded images (only files this tool wrote) plus manifests. Arcnames are generated, never user text."""
    sel = set(venue_ids) if venue_ids else None
    buf = io.BytesIO()
    count = 0
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_STORED) as z:
        for ph in sorted(store.photos.values(), key=lambda p: p["photo_id"]):
            if sel is not None and ph["venue_id"] not in sel:
                continue
            rel = ph.get("local_path")
            if ph.get("download_status") != "ok" or not rel:
                continue
            path = (store.dir / rel).resolve()
            if store.images.resolve() not in path.parents or not path.is_file():
                continue
            z.write(path, f"images/{ph['venue_id']}/{path.name}")
            count += 1
        for fmt in ("photos_csv", "photos_json", "menu_images_csv"):
            name, _, data = export_bytes(store, fmt, venue_ids)
            z.writestr(name, data)
        z.writestr("README.txt", "Ảnh lưu cục bộ để nghiên cứu cá nhân. Không đăng công khai hay phân phối lại; "
                                 "bản quyền thuộc chủ sở hữu ảnh/nguồn.\n")
    return buf.getvalue(), count


def venue_summary(store, vid):
    rec = store.venues.get(vid, {})
    photos = [p for p in store.photos.values() if p["venue_id"] == vid]
    return {
        "venue_id": vid, "name": rec.get("name"), "venue_url": rec.get("venue_url"),
        "menu_text_status": menu_status(rec), "menu_text_items": rec.get("menu_text_items", 0),
        "menu_image_count": rec.get("menu_image_count"), "menu_images_listed": rec.get("menu_images_listed"),
        "total_pictures": rec.get("total_pictures"), "delivery_listed": rec.get("delivery_listed"),
        "total_dishes_claimed": rec.get("total_dishes_claimed"),
        "photos_known": len(photos), "photos_downloaded": sum(1 for p in photos if p.get("download_status") == "ok"),
        "cache_status": rec.get("cache_status"),
    }


def coverage_summary(store):
    """Counts only; denominators are venues in this job, never 'all of Hanoi'."""
    v = store.venues
    menu_states = {}
    for r in v.values():
        s = menu_status(r)
        menu_states[s] = menu_states.get(s, 0) + 1
    photos = list(store.photos.values())
    dl = {}
    for p in photos:
        dl[p.get("download_status", "not_downloaded")] = dl.get(p.get("download_status", "not_downloaded"), 0) + 1
    return {
        "venues_total": len(v),
        "venues_with_cached_page": sum(1 for r in v.values() if r.get("cache_status") == "ok"),
        "venues_menu_album_declared": sum(1 for r in v.values() if (r.get("menu_image_count") or 0) > 0),
        "venues_with_photos_declared": sum(1 for r in v.values() if (r.get("total_pictures") or 0) > 0),
        "venues_delivery_listed": sum(1 for r in v.values() if r.get("delivery_listed")),
        "menu_text_states": menu_states,
        "menu_items_total": len(store.menu),
        "venues_with_menu_items": len({m["venue_id"] for m in store.menu.values()}),
        "photos_known": len(photos), "photo_download_states": dl,
        "venues_with_photos_known": len({p["venue_id"] for p in photos}),
        "menu_images_ocr_done": len(store.ocr), "menu_images_known": sum(1 for p in photos if p.get("is_menu_image")),
        "bytes_downloaded": sum(p.get("bytes") or 0 for p in photos if p.get("download_status") == "ok"),
        "pages_fetched": len(store.pages),
    }


class MediaManager:
    """One media task at a time, never alongside a crawl."""

    def __init__(self, jobs):
        self.jobs = jobs
        self.lock = threading.RLock()
        self.task = None
        self.task_job = None
        self.factory = {}  # tests inject fetcher/sleeper/resolver here

    def store(self, job_id):
        job = self.jobs.get(job_id)
        return MediaStore(job.directory)

    def _guard(self, job_id):
        job = self.jobs.get(job_id)
        if any(j.thread and j.thread.is_alive() for j in self.jobs.jobs.values()):
            raise ValueError("Đang có đợt thu thập chạy hoặc tạm dừng. Hãy chờ xong rồi thu thập menu/ảnh.")
        if self.task and self.task.active:
            raise ValueError("Một tác vụ menu/ảnh khác đang chạy. Hãy dừng nó trước.")
        return job

    def scan(self, job_id):
        with self.lock:
            job = self._guard(job_id)
            store = MediaStore(job.directory)
            return scan_cached(store)

    def start(self, job_id, kind, venue_ids, options):
        with self.lock:
            job = self._guard(job_id)
            store = MediaStore(job.directory)
            if not store.venues:
                scan_cached(store)
            ids = [str(v) for v in venue_ids] if venue_ids else sorted(store.venues)
            unknown = [v for v in ids if v not in store.venues]
            if unknown:
                raise ValueError("Có quán không thuộc đợt này.")
            if not ids:
                raise ValueError("Đợt này chưa có quán nào.")
            task = MediaTask(store, kind, ids, options, **self.factory)
            self.task, self.task_job = task, job_id
            task.launch()
            return task

    def status(self, job_id):
        t = self.task if self.task_job == job_id else None
        return t.snapshot() if t else None

    def control(self, action):
        t = self.task
        if not t or not t.active:
            raise ValueError("Không có tác vụ menu/ảnh đang chạy.")
        {"stop": t.stop, "pause": t.pause, "resume": t.unpause}[action]()
        return t

    def shutdown(self):
        if self.task and self.task.active:
            self.task.stop()
            self.task.thread.join(timeout=35)
