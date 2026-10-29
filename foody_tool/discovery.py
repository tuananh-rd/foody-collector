"""Pure discovery and URL extraction for Foody Hanoi restaurant pages.

Shared contract:
    extract_restaurant_urls(html: str, base_url: str) -> list[str]

Contract properties:
    - Pure discovery function: no network calls, no JavaScript execution.
    - Extracts stable, unique, absolute HTTPS www.foody.vn/ha-noi/<venue> URLs.
    - Filters out non-venue pages (listing, editorial, menu, reviews, photos, auth, categories).
    - Preserves document order of first appearance (stable unique).
    - Safe on malformed markup, invalid ports, and unrendered template placeholders (e.g. {{item.Url}}).
    - Candidate URL shape (/ha-noi/<slug>) is a heuristic syntax filter, not proof that a venue is an active or existing restaurant.
"""
import argparse
import re
import sys
from html.parser import HTMLParser
from urllib.parse import urljoin, urlsplit

ALLOWED_HOST = "www.foody.vn"
CITY_PREFIX = "/ha-noi/"

# Strict restaurant slug syntax: starts with alphanumeric, followed by alphanumeric, dot, underscore, or hyphen
_SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9._-]*$", re.IGNORECASE)

# Standard non-venue system and feature paths
NON_VENUE_SLUGS = {
    "o-dau",
    "an-gi",
    "thuc-don",
    "binh-luan",
    "album-anh",
    "dang-nhap",
    "dang-ky",
    "tim-kiem",
    "bai-viet",
    "blog",
    "video",
    "hinh-anh",
    "bo-suu-tap",
    "dia-diem",
    "coupon",
    "bo-suu-tap-hinh-anh",
    "khuyen-mai",
    "su-kien",
    "top-thanh-vien",
    "food",
    "delivery",
    "fresh",
    "app",
    "tro-giup",
    "quy-dinh",
    "lien-he",
    "gioi-thieu",
    "dieu-khoan-su-dung",
    "thoa-thuan-su-dung",
    "quan-an",
    "cafe",
    "karaoke",
    "bar-pub",
    "tiem-banh",
    "khu-am-thuc",
    "shop-online",
    "giao-hang",
    "dat-cho",
    "danh-sach",
}

# Taxonomy / filter category prefixes in Hanoi URLs that are not individual venues
EXCLUDED_PREFIXES = (
    "khu-vuc-",
    "dia-diem-",
    "bo-suu-tap-",
    "danh-sach-",
    "top-",
    "quan-an-phuc-vu-",
    "quan-an-phu-hop-",
    "quan-an-phong-cach-",
    "quan-an-co-",
    "cafe-phuc-vu-",
    "cafe-phu-hop-",
    "cafe-phong-cach-",
    "cafe-co-",
    "nha-hang-phuc-vu-",
    "nha-hang-phu-hop-",
    "nha-hang-phong-cach-",
    "nha-hang-co-",
)


class _HrefParser(HTMLParser):
    """Minimal HTML parser collecting href attributes from links and anchors."""

    def __init__(self):
        super().__init__()
        self.hrefs = []

    def handle_starttag(self, tag, attrs):
        if tag in ("a", "link"):
            for k, v in attrs:
                if k.lower() == "href" and v:
                    self.hrefs.append(v)


def extract_restaurant_urls(html: str, base_url: str, *, exclude_taxonomy=True) -> list[str]:
    """Extract stable unique absolute HTTPS www.foody.vn/ha-noi/<venue> URLs.

    Args:
        html: Raw HTML document string.
        base_url: Base URL for resolving relative links (e.g. 'https://www.foody.vn/ha-noi/').

    Returns:
        A list of verified-shape restaurant URLs, ordered by first appearance without duplicates.
    """
    if not isinstance(html, str) or not isinstance(base_url, str):
        return []

    parser = _HrefParser()
    try:
        parser.feed(html)
    except Exception:
        # Gracefully handle truncated or malformed HTML
        pass

    results = []
    seen = set()

    for raw_href in parser.hrefs:
        href = str(raw_href).strip()
        if not href or href.startswith(("javascript:", "mailto:", "tel:", "#")):
            continue

        try:
            full = urljoin(base_url, href)
            p = urlsplit(full)
            port = p.port
        except Exception:
            continue

        # Enforce scheme and host
        if p.scheme not in ("http", "https"):
            continue
        if (p.hostname or "").lower() != ALLOWED_HOST:
            continue
        if p.username or p.password or port not in (None, 80, 443):
            continue

        # Path must start with /ha-noi/ (case-insensitive)
        path = p.path.rstrip("/")
        if not path.lower().startswith(CITY_PREFIX):
            continue

        slug = path[len(CITY_PREFIX):]

        # Must be single segment (reject subpaths like /ha-noi/<venue>/thuc-don)
        if not slug or "/" in slug:
            continue

        # Angular placeholder protection (unrendered client-side templates)
        if "{{" in slug or "}}" in slug:
            continue

        # Check slug character regex
        if not _SLUG_RE.match(slug):
            continue

        slug_lower = slug.lower()

        # Filter out known non-venue slugs and taxonomy category prefixes
        if slug_lower in NON_VENUE_SLUGS:
            continue
        if exclude_taxonomy and any(slug_lower.startswith(prefix) for prefix in EXCLUDED_PREFIXES):
            continue

        canonical_url = f"https://{ALLOWED_HOST}{CITY_PREFIX}{slug_lower}"
        if canonical_url not in seen:
            seen.add(canonical_url)
            results.append(canonical_url)

    return results


def discover_from_file(path: str, base_url: str = "https://www.foody.vn/ha-noi/") -> list[str]:
    """Read local HTML file and extract restaurant URLs."""
    with open(path, encoding="utf-8", errors="replace") as f:
        content = f.read()
    return extract_restaurant_urls(content, base_url)


def main():
    """Bounded discovery CLI."""
    parser = argparse.ArgumentParser(
        description="Foody Hanoi Restaurant URL Discovery Tool"
    )
    parser.add_argument(
        "--file",
        help="Path to saved HTML file to extract URLs from (offline mode)"
    )
    parser.add_argument(
        "--base-url",
        default="https://www.foody.vn/ha-noi/",
        help="Base URL for resolving relative links (default: https://www.foody.vn/ha-noi/)"
    )
    parser.add_argument(
        "--output",
        help="Optional path to output file (one URL per line)"
    )
    parser.add_argument(
        "--live",
        action="store_true",
        help="Check live listing limitations and instructions"
    )

    args = parser.parse_args()

    if args.live and not args.file:
        print("Note: --live is informational only. Public Foody Hanoi listing pages (/ha-noi/o-dau)", file=sys.stderr)
        print("use client-side AngularJS rendering (ng-repeat with {{item.Url}}). Raw HTTP GET returns", file=sys.stderr)
        print("template placeholders (except occasional static banner links). Dynamic listings require", file=sys.stderr)
        print("browser automation to render DOM and load pagination batches.", file=sys.stderr)
        print("Candidate URL shape (/ha-noi/<slug>) is a heuristic syntax filter, not proof that a", file=sys.stderr)
        print("venue is an active, open, or verified restaurant.", file=sys.stderr)
        return

    if not args.file:
        parser.print_help()
        sys.exit(1)

    urls = discover_from_file(args.file, args.base_url)
    if args.output:
        with open(args.output, "w", encoding="utf-8") as f:
            for u in urls:
                f.write(u + "\n")
        print(f"Extracted {len(urls)} URLs to {args.output}")
    else:
        for u in urls:
            print(u)


if __name__ == "__main__":
    main()
