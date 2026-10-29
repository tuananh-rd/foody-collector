# FoodTour Foody collector v0.4 — contract (coordinator: Claude)

Baseline: v0.3 commit 7057119. Everything here is additive. Legacy 18-column CSV/JSON,
`restaurants_raw.json`, `restaurants_normalized.*`, quality report and old jobs MUST stay
byte-identical for existing data and loadable by the new code.

## Source markup (verified on cached pages, 200/200 have the blocks below)

All fields are server-rendered in the detail-page HTML; **no new request is needed for
pages already in a job's `cache/`.**

| Field | Markup |
|---|---|
| Info rows | `div.new-detail-info-area` > `div.new-detail-info-label` (label) + sibling `div` (value). Labels seen: `Thích hợp` (suitable meals, links), `Giờ nhận khách cuối`, `Thời gian chuẩn bị`, `Nghỉ lễ`, `Thể loại` (venue type), `Sức chứa`, `Phong cách ẩm thực` (cuisine), `Phù hợp với` (audiences), `Phục vụ các món` (dish groups). Strip the `span.report-data-error` pencil widget. Entities (`&#250;`) must be decoded. |
| Aggregate rating | `[itemprop=ratingValue]` (scale 1..10 from `bestRating`), `[itemprop=reviewCount]`. |
| Criteria | `div.microsite-top-points`: `span.avg-txt-highlight` value + `div.label` in {Chất lượng, Vị trí, Phục vụ, Không gian, Giá cả}. |
| Amenities | `ul.micro-property > li`: colored item has `istrue="true"` on its `a.resproperties-report`; gray item has `li.none` + `color:#aaa` + `istrue="false"`. Label in `errorkeyname` / span text. |

## Tri-state rules (non-negotiable)

* Amenity `status`: `yes` when `istrue="true"` (basis `platform_true`); gray items
  (`li.none`, `color:#aaa`, `istrue="false"`) are `unknown` with basis `platform_gray_unconfirmed`;
  amenity absent from markup is `unknown` with basis `absent`. **`no` is never emitted.**
  Evidence (cached 200 pages, 2026-10-15): 28/83 pages with gray Wi-Fi nevertheless carry a
  contributed `initData.Wifi` entry, and 34 pages show colored Wi-Fi with no entry, so gray
  cannot be read as verified absence. Export column `amenities_no` is kept for schema
  compatibility and is always empty; UI shows gray as "chưa xác nhận".
* Any field that is absent/ambiguous → `null` / `[]` / `unknown`. Never infer.
* `dish_groups` are category links ("Phục vụ các món"), NOT an itemized menu.
* `price_*` stay venue ranges. `last_guest_time` and displayed hours are NOT a weekly schedule.
* Ratings are platform signals (`rating_scale_max` recorded), not verified quality or
  business status. Review count is an integer ≥0 or null.
* Preparation time kept as raw text + parsed `{min,max,unit}` only if pattern is exact
  (`Khoảng A - B phút`, `A phút`); else raw only. Capacity: raw text + integer + unit
  only when `\d+ người ...`; else raw only.
* Holiday (`Nghỉ lễ`): raw text only, no calendar inference.
* **Never store Wifi name/password or any user/credential-like field from `initData.Wifi`.**
  Only the amenity yes/no/unknown from `ul.micro-property` is kept.

## Schema: `details` object (new, additive)

Each normalized record gains `enrichment` (dict). Keys:

```
schema: "foody-enrichment/1"
parsed_from: "cached_html" | "live_html"
cuisine_styles: [{text, href}]          # Phong cách ẩm thực
venue_types: [{text, href}]             # Thể loại
dish_groups: [{text, href}]             # Phục vụ các món
suitable_meals: [{text, href}]          # Thích hợp
audiences: [{text, href}]               # Phù hợp với
last_guest_time_raw: str|null
prep_time_raw: str|null; prep_time_min: int|null; prep_time_max: int|null
capacity_raw: str|null; capacity_value: int|null
holiday_raw: str|null
rating: {value: float|null, scale_max: int|null, review_count: int|null,
         criteria: {quality, location, service, space, price: float|null}}
amenities: [{key, label, status: yes|no|unknown, status_basis}]
field_presence: {<field>: "present"|"absent"|"ambiguous"}   # measured, per field
warnings: [str]
```

Flat export columns (CSV, new file `restaurants_enriched.csv`, JSON `restaurants_enriched.json`;
legacy files untouched, schema marker `schema_version: "foody-enriched-export/2"` and `columns` in `enrichment_report.json`):
Preserves the existing 25 v0.4 columns first in the same order, and appends the 18 normalized restaurant record fields:
1. `foody_id`
2. `name`
3. `cuisine_styles`
4. `venue_types`
5. `dish_groups`
6. `suitable_meals`
7. `audiences`
8. `prep_time_raw`
9. `prep_time_min`
10. `prep_time_max`
11. `capacity_raw`
12. `capacity_value`
13. `holiday_raw`
14. `rating_value`
15. `rating_scale_max`
16. `review_count`
17. `rating_quality`
18. `rating_location`
19. `rating_service`
20. `rating_space`
21. `rating_price`
22. `amenities_yes`
23. `amenities_no`
24. `amenities_unknown`
25. `source_url`
26. `address`
27. `district`
28. `city`
29. `lat`
30. `lon`
31. `geo_status`
32. `price_min_raw`
33. `price_max_raw`
34. `price_status`
35. `price_min_vnd_norm`
36. `price_max_vnd_norm`
37. `price_semantics`
38. `opening_hours_raw`
39. `hours_displayed`
40. `hours_status`
41. `hours_intervals_count`
42. `hours_day_codes_raw`
43. `fetched_at`

(multi-values joined with ` | `; amenities_* are label lists; in JSON `opening_hours_raw` and `hours_day_codes_raw` are lists, in CSV they are JSON strings with spreadsheet formula neutralization).
Source of truth: same v0.3 code paths (`parse_restaurant` + `quality.classify_price` / `classify_hours` / `classify_geo` or `normalize_record`).
Semantics: zero is not free (`unknown_zero`/`partial_zero`, norm null, raw kept), reversed ranges not swapped (`invalid_range`, norm null, raw kept), nonfinite stays null with status, never invent a weekly schedule or open_now (`hours_displayed` is only the text of the raw intervals joined with ` | `; `hours_status` passes through e.g. `day_mapping_unknown`, `missing`, `malformed`).

## Modules and ownership

* `foody_tool/enrich.py` (NEW, pure, no network): `parse_enrichment(html) -> dict`.
* `foody_tool/enrich_cache.py` (NEW): `enrich_job(job_dir, *, network=False)` reads
  `urls.json` + `cache/*.html`, writes enriched files + `enrichment_report.json`
  (counts: pages, parsed, per-field presence, `network_requests: 0`). Missing cache page
  → listed as `needs_fetch`, NOT fetched unless explicit `--fetch-missing` with ≥2 s
  interval and block stop-rules from `collector.py`.
* `foody_tool/exporter.py`: add enriched writers only; do not change legacy writers.
* `foody_tool/__main__.py`: add `enrich --job-dir DIR [--fetch-missing]` subcommand.
* `collector.py`/`jobs.py`: new live detail fetches also run `parse_enrichment` and store
  under `enrichment`; failure to enrich MUST NOT fail the legacy record.
* UI (`web/*`, `app.py`): see UI task. Vietnamese labels, source link per row.
* Tests: `tests/test_enrich.py`, `tests/test_enrich_cache.py`, UI tests in
  `tests/test_web_enrich.py`. Use small synthetic fixtures (anonymized) plus
  private-fixture-skipping tests for real cached pages. Do not commit raw source HTML.

## Out of scope

Menus/itemized dishes, per-person budgets, weekly schedules, login/CAPTCHA bypass,
full-Hanoi crawl, publishing data.
