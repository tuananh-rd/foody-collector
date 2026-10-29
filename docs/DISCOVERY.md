# Foody Hanoi Restaurant Discovery Report & Specification

## 1. Executive Summary

This document specifies the discovery architecture, URL extraction contract, public listing behavior, and pagination evidence for Foody Hanoi restaurant pages (`www.foody.vn`).

Key findings:
- **Contract Fulfillment**: `foody_tool.discovery.extract_restaurant_urls(html, base_url)` implements a pure, zero-dependency, standard library HTML parser returning stable, unique, absolute HTTPS `www.foody.vn/ha-noi/<venue>` URLs with strict exclusion of non-venue and taxonomy pages, protected against malformed ports and template placeholders.
- **Client-Side Rendering Barrier & Plain HTTP Limits**: Direct raw HTTP GET requests to Foody listing pages (e.g. `https://www.foody.vn/ha-noi/o-dau`) return HTTP 200 with raw HTML containing unrendered AngularJS template directives (`ng-repeat` containing `{{item.Url}}`, `{{item.Name}}`, `{{item.PhotoUrl}}`). No dynamic venue listings are rendered server-side in the initial listing body; however, static promotional banner links (e.g. `sua-chua-tran-chau-tuoi-yofresh-nguyen-van-huyen`) can be extracted from raw HTML.
  - `dom_0.json`: 12 distinct venue URLs rendered initially.
  - `click_1.json` -> `dom_1.json`: 24 distinct venue URLs (+12 increment).
  - `click_2.json` -> `dom_2.json`: 36 distinct venue URLs (+12 increment).
  - `click_3.json` -> `dom_3.json`: 48 distinct venue URLs (+12 increment).
  - Result list: `reports/coordinator/urls48.txt` (48 verified candidate URLs).
- **Candidate Shape Heuristic Caveat**: Matching `/ha-noi/<slug>` verifies syntactic URL conformity only; it is not proof that the venue is an active, open, or existing restaurant.

---

## 2. Shared Contract: `extract_restaurant_urls`

```python
def extract_restaurant_urls(html: str, base_url: str) -> list[str]:
    ...
```

### 2.1 Properties & Invariants
1. **Pure Function**: Does not initiate network connections, execute JavaScript, or modify global state.
2. **Stable Unique**: Output preserves the document order of first appearance. Duplicate links are pruned immediately upon first encounter.
3. **Absolute Canonical HTTPS**: All relative links (e.g. `/ha-noi/some-venue`, `some-venue`) are resolved against `base_url` using `urllib.parse.urljoin`, scheme is normalized to `https`, host to `www.foody.vn`, and path to `/ha-noi/<slug>`.
4. **Resilient to Malformed Markup & Ports**: Safely handles broken HTML, truncated streams, non-string inputs, unescaped characters, and malformed/non-numeric port components without raising exceptions.
5. **Template Protection**: Unrendered template strings such as `{{item.Url}}` or `/ha-noi/{{item.Slug}}` are rejected.
6. **Syntactic Shape Heuristic**: Confirms URL shape conforms to `/ha-noi/<slug>`, excluding non-venues; does not verify venue operational status or existence.

### 2.2 Exclusion Rules
To prevent collection pollution, `extract_restaurant_urls` enforces strict multi-stage filtering:

| Category | Filter Mechanism | Examples Excluded |
|---|---|---|
| **External Domains** | Host must equal `www.foody.vn` | `shopeefood.vn`, `facebook.com`, `google.com` |
| **Subdomains** | Rejects other subdomains | `m.foody.vn`, `api.foody.vn` |
| **Non-Hanoi Cities** | Path must start with `/ha-noi/` | `/ho-chi-minh/...`, `/da-nang/...`, `/` |
| **Subpaths / Child Views** | Path after `/ha-noi/` must be a single segment | `/ha-noi/<slug>/thuc-don`, `/ha-noi/<slug>/binh-luan`, `/ha-noi/<slug>/album-anh`, `/ha-noi/<slug>/video`, `/ha-noi/<slug>/ban-do`, `/ha-noi/food/bai-viet` |
| **System & Listing Slugs** | Exact match on `NON_VENUE_SLUGS` | `o-dau`, `an-gi`, `thuc-don`, `binh-luan`, `hinh-anh`, `bo-suu-tap`, `dia-diem`, `coupon`, `bo-suu-tap-hinh-anh`, `khuyen-mai`, `su-kien`, `top-thanh-vien`, `dang-nhap`, `dang-ky`, `tim-kiem`, `bai-viet`, `blog`, `video`, `food`, `delivery`, `fresh` |
| **Taxonomy / Filter Categories** | Prefix match on `EXCLUDED_PREFIXES` | `khu-vuc-*` (districts, areas)<br>`dia-diem-*` (feature tags)<br>`quan-an-phuc-vu-*`, `quan-an-phu-hop-*`, `quan-an-phong-cach-*`, `quan-an-co-*`<br>`cafe-phuc-vu-*`, `cafe-phu-hop-*`, `cafe-phong-cach-*`, `cafe-co-*`<br>`nha-hang-*`<br>`bo-suu-tap-*`, `danh-sach-*`, `top-*` |
| **Fragments & Queries** | Stripped before path extraction | `?utm_source=...`, `#tab-footer`, `#tab-reviews` |

---

## 3. Public Listing & Pagination Evidence

### 3.1 Separation of Evidence: Direct HTTP GET vs Browser Actions vs Subrequests

Evidence must strictly distinguish between direct script HTTP requests, browser UI actions, and unmeasured browser network subrequests:

#### A. Direct Script HTTP GET (Measured & Saved)
Measured via Python `urllib.request` scripts with >= 2.5s spacing between requests:
- `GET https://www.foody.vn/ha-noi`: HTTP 200, 117,375 bytes, saved to `cache/hanoi_home.html`. Contains 48 Angular placeholders, 0 venue listings.
- `GET https://www.foody.vn/ha-noi/o-dau`: HTTP 200, 127,456 bytes, saved to `cache/hanoi_odau.html`. Contains 55 Angular placeholders and 1 static top banner restaurant link (`sua-chua-tran-chau-tuoi-yofresh-nguyen-van-huyen`).
- `GET https://www.foody.vn/ha-noi/an-gi`: HTTP 200, 4,083 bytes, saved to `cache/hanoi_angi.html`. Error page ("Hệ thống không tìm thấy dữ liệu | Foody.vn").
- `GET https://www.foody.vn/ha-noi/khu-vuc-quan-hoan-kiem`: Timed out after 15s (no payload saved).

#### B. Browser DOM Actions & Unmeasured Background Subrequests
- Browser tab creation (`orca tab create --url https://www.foody.vn/ha-noi/o-dau`) and element clicks trigger internal browser network subrequests (AngularJS bundles, stylesheets, XHR data fetches, telemetry).
- **Honesty Note**: These subrequests are managed by the browser engine and were not directly captured as HTTP request/response tuples. Invented claims of "exact 8 requests" or "browser HTTP 200" and precise subrequest latencies are retracted. Only DOM evaluations and button click return statuses are verified.

---

### 3.2 Verified Coordinator Pagination Proof (Durable Receipts)


| Step | Receipt File | Observed Distinct Venue URLs | Delta | LoadMore Status |
|---|---|---:|---:|---|
| Initial Render | `reports/coordinator/dom_0.json` | 12 | 12 | Visible: true |
| Click 1 | `reports/coordinator/click_1.json` -> `dom_1.json` | 24 | +12 | Visible: true |
| Click 2 | `reports/coordinator/click_2.json` -> `dom_2.json` | 36 | +12 | Visible: true |
| Click 3 | `reports/coordinator/click_3.json` -> `dom_3.json` | 48 | +12 | Visible: true |

**Pagination Findings & Limitations**:
1. **Dynamic Client-Side Model**: Venues on `/ha-noi/o-dau` are appended dynamically by AngularJS `PlaceController` when clicking `<a href="javascript:void(0);" ng-click="LoadMore()">Xem thêm địa điểm</a>`.
2. **Observed Increment**: An increment of exactly **+12 venue cards** per LoadMore click was observed across 3 consecutive interactions in this specific session.
3. **Scope Limitation**: The +12 increment is an empirical observation for this listing page during this test; it cannot be claimed as a universal or immutable property across all Foody filters, search parameters, or infinite scroll depth.
4. **Environment Limitation**: The coordinator noted that `orca snapshot` failed with `runtime_unavailable` during their page inspection; this accessibility snapshot issue is recorded as a separate environment limitation that did not impede DOM evaluations.

---

### 3.3 Historic Worker Run Retraction & Clarification

- The prior claim of a `13 -> 25 -> 37 -> 49` batch progression was based on post-hoc candidate list indexing rather than saved per-step DOM snapshots.
- Intermediate step receipts for that worker run were not preserved in the shared workspace; hence that specific breakdown is marked **uncorroborated**.
- The coordinator's receipts (`reports/coordinator/dom_0.json`..`dom_3.json` and `urls48.txt`) serve as the authoritative verified evidence.

---

## 4. Discovered Candidates & Conformity

- Authoritative candidate list: `reports/coordinator/urls48.txt` (48 unique URLs).
- Historic candidate list: `inputs/candidates_49.txt` (49 URLs: 1 banner + 48 rendered; 47 overlap with `urls48.txt`).
- Both candidate lists pass `foody_tool.collector.normalize_restaurant_url` with 100% compliance (verified in `tests/test_independent.py`).

---

## 5. Bounded Discovery CLI Usage

`foody_tool/discovery.py` provides an offline extraction CLI:

```bash
# Offline mode: extract restaurant URLs from a saved HTML file
python -m foody_tool.discovery --file cache/hanoi_odau_rendered_paged.html --output inputs/candidates.txt

# Informational notes on listing architecture and limitations
python -m foody_tool.discovery --live
```

> [!NOTE]
> `--live` is informational only. It does not perform network or browser requests. As public listings rely on client-side rendering, live discovery requires external browser DOM automation to render pages and load pagination batches. Candidate URL shape matching is a syntax heuristic and does not guarantee that a venue is an active or open restaurant.
