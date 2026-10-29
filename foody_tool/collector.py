"""Conservative sequential collector with cache, persistent progress and resume."""
import hashlib
import json
import math
import os
import re
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from urllib.parse import urljoin, urlsplit

from .parser import ParseError, parse_restaurant, _INIT_RE

PARSER_VERSION = "0.3.0"
SOURCE_KEYS = {
    "foody_id": "RestaurantID", "name": "Name", "address": "Address",
    "district": "District", "city": "City", "lat": "Latitude", "lon": "Longtitude",
    "price_min_vnd": "PriceMin", "price_max_vnd": "PriceMax",
    "opening_hours_raw": "OpeningTime",
}


def _safe_source_value(value):
    """Represent non-finite source numbers explicitly without invalid JSON tokens."""
    if isinstance(value, float) and not math.isfinite(value):
        return "NaN" if math.isnan(value) else ("Infinity" if value > 0 else "-Infinity")
    if isinstance(value, dict):
        return {key: _safe_source_value(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_safe_source_value(item) for item in value]
    return value

ALLOWED_HOST = "www.foody.vn"
CITY_PREFIX = "/ha-noi/"
MAX_URLS = 50
MIN_INTERVAL = 2.0
MAX_REDIRECTS = 3
MAX_BODY_BYTES = 5 * 1024 * 1024
USER_AGENT = "FoodTourFeasibilityBot/0.1 (private feasibility test; sequential, rate-limited)"
NON_VENUE_SLUGS = {"o-dau", "an-gi", "thuc-don", "binh-luan", "album-anh", "dang-nhap",
                   "dang-ky", "tim-kiem", "bai-viet", "blog", "video"}
BLOCK_MARKERS = ("captcha", "cf-challenge", "access denied", "unusual traffic")
_SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9._-]*$")

# Statuses that a plain re-run will not retry (use retry_failed to force).
FINAL_STATUSES = {"ok", "duplicate_id", "http_error", "unsafe_redirect", "invalid_url"}


class UrlError(ValueError):
    pass


def normalize_restaurant_url(url):
    """Return the canonical restaurant URL or raise UrlError."""
    if not isinstance(url, str):
        raise UrlError("URL is not text")
    try:
        p = urlsplit(url.strip())
        port = p.port
    except ValueError as e:
        raise UrlError(f"malformed URL: {e}") from None
    if p.scheme != "https":
        raise UrlError("scheme must be https")
    if p.username or p.password or port not in (None, 443):
        raise UrlError("credentials/port not allowed")
    if (p.hostname or "").lower() != ALLOWED_HOST:
        raise UrlError(f"host must be {ALLOWED_HOST}")
    if p.query or p.fragment:
        raise UrlError("query/fragment not allowed")
    path = p.path.rstrip("/")
    if not path.startswith(CITY_PREFIX):
        raise UrlError("path must be /ha-noi/<venue>")
    slug = path[len(CITY_PREFIX):]
    if "/" in slug or not _SLUG_RE.match(slug) or slug in NON_VENUE_SLUGS:
        raise UrlError("path is not a restaurant detail page")
    return f"https://{ALLOWED_HOST}{CITY_PREFIX}{slug}"


def load_url_file(path):
    """One URL per line; blank lines and #-comments ignored; order-preserving dedup."""
    urls, seen = [], set()
    with open(path, encoding="utf-8-sig") as f:
        for line in f:
            line = line.split("#", 1)[0].strip()
            if line and line not in seen:
                seen.add(line)
                urls.append(line)
    return urls


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *a, **kw):
        return None


def default_fetcher(url, timeout):
    """Single GET, no automatic redirects. Returns (status, headers, body_bytes)."""
    opener = urllib.request.build_opener(_NoRedirect)
    req = urllib.request.Request(url, headers={
        "User-Agent": USER_AGENT, "Accept": "text/html", "Accept-Language": "vi,en;q=0.5"})
    try:
        resp = opener.open(req, timeout=timeout)
    except urllib.error.HTTPError as e:
        resp = e
    with resp:
        body = resp.read(MAX_BODY_BYTES + 1)
        headers = {k.lower(): v for k, v in resp.headers.items()}
        return resp.status if hasattr(resp, "status") else resp.code, headers, body


def _utcnow():
    return datetime.now(timezone.utc).isoformat()


def _decode(body, headers):
    m = re.search(r"charset=([\w-]+)", headers.get("content-type", ""), re.I)
    for enc in ([m.group(1)] if m else []) + ["utf-8"]:
        try:
            return body.decode(enc, errors="replace")
        except LookupError:
            continue
    return body.decode("utf-8", errors="replace")


class Collector:
    def __init__(self, out_dir, fetcher=default_fetcher, *, min_interval=MIN_INTERVAL,
                 timeout=20.0, max_retries=2, backoff=5.0, clock=time.monotonic,
                 sleeper=time.sleep, now=_utcnow):
        def _num(v, name):
            if isinstance(v, bool) or not isinstance(v, (int, float)) or v != v or abs(v) == float("inf"):
                raise ValueError(f"{name} must be a finite number")
            return v
        _num(min_interval, "min_interval")
        _num(timeout, "timeout")
        _num(backoff, "backoff")
        if min_interval < 0 or backoff < 0 or timeout <= 0:
            raise ValueError("min_interval/backoff must be >= 0 and timeout > 0")
        if not isinstance(max_retries, int) or isinstance(max_retries, bool) or not 0 <= max_retries <= 5:
            raise ValueError("max_retries must be an integer in 0..5")
        if min_interval < MIN_INTERVAL and fetcher is default_fetcher:
            raise ValueError(f"min_interval must be >= {MIN_INTERVAL}s for live requests")
        self.out_dir = out_dir
        self.cache_dir = os.path.join(out_dir, "cache")
        self.progress_path = os.path.join(out_dir, "progress.json")
        self.fetcher, self.min_interval = fetcher, min_interval
        self.timeout, self.max_retries, self.backoff = timeout, max_retries, backoff
        self.clock, self.sleeper, self.now = clock, sleeper, now
        self._last_start = None
        self.request_count = 0
        os.makedirs(self.cache_dir, exist_ok=True)
        self.progress = self._load_progress()

    # -- persistence -----------------------------------------------------
    def _load_progress(self):
        try:
            with open(self.progress_path, encoding="utf-8") as f:
                data = json.load(f)
            return data if isinstance(data, dict) else {}
        except FileNotFoundError:
            return {}

    def _save(self):
        tmp = self.progress_path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(self.progress, f, ensure_ascii=False, indent=1)
        os.replace(tmp, self.progress_path)

    def _set(self, url, **fields):
        e = self.progress.setdefault(url, {})
        e.update(fields)
        self._save()
        return e

    def cache_path(self, url):
        return os.path.join(self.cache_dir, hashlib.sha256(url.encode()).hexdigest()[:20] + ".html")

    # -- network ---------------------------------------------------------
    def _throttle(self):
        if self._last_start is not None:
            wait = self.min_interval - (self.clock() - self._last_start)
            if wait > 0:
                self.sleeper(wait)
        self._last_start = self.clock()
        self.request_count += 1

    def _get(self, url):
        """GET with validated redirects. Returns dict(kind, ...) describing the outcome."""
        current, attempts = url, 0
        hops = 0
        retries = 0
        while True:
            for attempt in range(self.max_retries + 1):
                if attempt:
                    retries += 1
                attempts += 1
                self._throttle()
                try:
                    status, headers, body = self.fetcher(current, self.timeout)
                except Exception as e:  # network/timeouts are transient
                    err = f"{type(e).__name__}: {e}"
                    status = None
                else:
                    err = f"HTTP {status}"
                if status is not None and not (500 <= status < 600 or status == 408):
                    break
                if attempt < self.max_retries:
                    self.sleeper(self.backoff * (2 ** attempt))
            else:
                return {"kind": "transient_failed", "http_status": status, "error": err,
                        "attempts": attempts, "retry_count": retries, "redirect_count": hops}
            if status in (403, 429):
                return {"kind": "blocked", "http_status": status, "error": f"HTTP {status}",
                        "attempts": attempts, "retry_count": retries, "redirect_count": hops}
            if status in (301, 302, 303, 307, 308):
                hops += 1
                loc = headers.get("location")
                if not loc or hops > MAX_REDIRECTS:
                    return {"kind": "unsafe_redirect", "http_status": status, "attempts": attempts,
                            "retry_count": retries, "redirect_count": hops,
                            "error": "missing Location" if not loc else "too many redirects"}
                try:
                    current = normalize_restaurant_url(urljoin(current, loc))
                except UrlError as e:
                    return {"kind": "unsafe_redirect", "http_status": status, "attempts": attempts,
                            "retry_count": retries, "redirect_count": hops,
                            "error": f"redirect to {loc!r} rejected: {e}"}
                continue
            if status != 200:
                return {"kind": "http_error", "http_status": status, "error": f"HTTP {status}",
                        "attempts": attempts, "retry_count": retries, "redirect_count": hops}
            if len(body) > MAX_BODY_BYTES:
                return {"kind": "http_error", "http_status": status, "attempts": attempts,
                        "retry_count": retries, "redirect_count": hops,
                        "error": "response body too large"}
            return {"kind": "ok", "http_status": 200, "body": body, "headers": headers,
                    "final_url": current, "attempts": attempts,
                    "retry_count": retries, "redirect_count": hops}

    # -- per-URL pipeline ------------------------------------------------
    def _parse_and_store(self, url, html, fetched_at, entry_fields):
        # Keep provenance outside the legacy 18-column record contract.
        entry_fields = dict(entry_fields)
        entry_fields.update(parser_version=PARSER_VERSION, parsed_at=self.now(),
                            text_snapshot_hash="sha256:" + hashlib.sha256(html.encode("utf-8")).hexdigest(),
                            hash_basis="http_body_bytes" if entry_fields.get("raw_content_hash") else "text_snapshot")
        match = _INIT_RE.search(html)
        if match:
            try:
                source, _ = json.JSONDecoder().raw_decode(html[match.end():])
                if isinstance(source, dict):
                    entry_fields["field_presence"] = {
                        field: {"source_key": key, "present": key in source}
                        for field, key in SOURCE_KEYS.items()
                    }
                    flags = ("IsActive", "IsInactive", "IsDelete", "RestaurantStatus", "IsVerifiedMap")
                    entry_fields["source_keys"] = {
                        key: {"present": key in source, "raw": _safe_source_value(source.get(key))}
                        for key in (*SOURCE_KEYS.values(), *flags)}
                    entry_fields["field_presence"]["source_flags"] = {
                        "source_key": ",".join(flags), "present": any(key in source for key in flags)}
            except ValueError:
                pass
        try:
            from .enrich import parse_enrichment
            source_kind = "cached_html" if entry_fields.get("from_cache") else "live_html"
            en = parse_enrichment(html, parsed_from=source_kind)
            if any(v == "present" for v in en.get("field_presence", {}).values()):
                entry_fields["enrichment"] = en
        except Exception:
            pass
        try:
            rec = parse_restaurant(html, url, fetched_at)
        except ParseError as e:
            low = html.lower()
            if any(m in low for m in BLOCK_MARKERS):  # only reached when no valid record parsed
                self._set(url, status="blocked", error="challenge/captcha page", **entry_fields)
                return "blocked"
            self._set(url, status="parse_error", error=str(e), record=None, **entry_fields)
            return "parse_error"
        if "enrichment" in entry_fields:
            rec["enrichment"] = entry_fields["enrichment"]
        for other, e in self.progress.items():
            if other != url and e.get("status") == "ok" and e.get("foody_id") == rec["foody_id"]:
                self._set(url, status="duplicate_id", duplicate_of=other, foody_id=rec["foody_id"],
                          error=None, record=None, **entry_fields)
                return "duplicate_id"
        self._set(url, status="ok", foody_id=rec["foody_id"], record=rec, error=None,
                  duplicate_of=None, **entry_fields)
        return "ok"

    def process(self, url, refresh=False):
        """Process one valid URL. Returns final status string."""
        cache = self.cache_path(url)
        if not refresh and os.path.exists(cache):
            with open(cache, encoding="utf-8") as f:
                html = f.read()
            prev = self.progress.get(url, {})
            text_hash = "sha256:" + hashlib.sha256(html.encode("utf-8")).hexdigest()
            retained_body_hash = (prev.get("raw_content_hash")
                                  if prev.get("text_snapshot_hash") == text_hash else None)
            fetched_at = prev.get("fetched_at") or datetime.fromtimestamp(
                os.path.getmtime(cache), timezone.utc).isoformat()
            return self._parse_and_store(url, html, fetched_at, {
                "cache_file": os.path.basename(cache), "fetched_at": fetched_at,
                "http_status": prev.get("http_status", 200), "attempts": prev.get("attempts", 0),
                "raw_content_hash": retained_body_hash,
                "fetch_count": prev.get("fetch_count", 0),
                "retry_count": prev.get("retry_count"), "redirect_count": prev.get("redirect_count"),
                "from_cache": True})
        res = self._get(url)
        if res["kind"] != "ok":
            self._set(url, status=res["kind"], http_status=res.get("http_status"),
                      error=res.get("error"), attempts=res["attempts"], record=None,
                      retry_count=res.get("retry_count"), redirect_count=res.get("redirect_count"))
            return res["kind"]
        html = _decode(res["body"], res["headers"])
        fetched_at = self.now()
        tmp = cache + ".tmp"
        with open(tmp, "w", encoding="utf-8", newline="") as f:
            f.write(html)
        os.replace(tmp, cache)
        return self._parse_and_store(url, html, fetched_at, {
            "cache_file": os.path.basename(cache), "fetched_at": fetched_at,
            "http_status": 200, "attempts": res["attempts"], "final_url": res["final_url"],
            "raw_content_hash": "sha256:" + hashlib.sha256(res["body"]).hexdigest(),
            "fetch_count": self.progress.get(url, {}).get("fetch_count", 0) + 1,
            "retry_count": res.get("retry_count"), "redirect_count": res.get("redirect_count"),
            "from_cache": False})

    def run(self, urls, max_urls=MAX_URLS, refresh=False, retry_failed=False):
        """Collect. Returns (requested_urls, stopped_reason)."""
        if not isinstance(max_urls, int) or isinstance(max_urls, bool) or max_urls < 1:
            raise ValueError("max_urls must be a positive integer")
        max_urls = min(max_urls, MAX_URLS)
        requested, seen = [], set()
        for raw in urls:
            try:
                u = normalize_restaurant_url(raw)
            except UrlError as e:
                self._set(raw, status="invalid_url", error=str(e), record=None)
                requested.append(raw)
                continue
            if u not in seen:
                seen.add(u)
                requested.append(u)
        requested = requested[:max_urls]
        stopped = None
        for url in requested:
            entry = self.progress.get(url, {})
            st = entry.get("status")
            if st == "invalid_url":
                continue
            if st in FINAL_STATUSES and not retry_failed and not (refresh and st == "ok"):
                continue
            result = self.process(url, refresh=refresh)
            if result == "blocked":
                stopped = f"blocked at {url}: {self.progress[url].get('error')}"
                break
        return requested, stopped

    def records(self, requested):
        """Unique restaurants for the requested URLs, in request order.

        A duplicate_id alias resolves to its canonical record (even if the canonical URL
        was fetched in an earlier invocation); each foody_id appears once.
        """
        out, seen = [], set()
        for u in requested:
            e = self.progress.get(u, {})
            if e.get("status") == "ok":
                rec = e.get("record")
            elif e.get("status") == "duplicate_id":
                canon = self.progress.get(e.get("duplicate_of"), {})
                rec = canon.get("record") if canon.get("status") == "ok" else None
            else:
                rec = None
            if rec and rec["foody_id"] not in seen:
                seen.add(rec["foody_id"])
                out.append(rec)
        return out
