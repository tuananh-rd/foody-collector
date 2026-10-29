# v0.5 — Menu và ảnh (hợp đồng dữ liệu)

Phạm vi: nghiên cứu cá nhân, chạy cục bộ. Không đăng ảnh/dữ liệu lên GitHub hay nơi công khai.

## Nguồn thực tế (đã đo, xem `reports/v5/ACCEPTANCE_VI.md`)
| Loại | Nguồn | Cách lấy | Trạng thái |
|---|---|---|---|
| Danh sách album + số ảnh | `initDataNavBar` trong HTML trang quán (đã cache) | offline, 0 request | hoạt động |
| Ảnh cộng đồng (dải ảnh trang chủ) | khối `microsite-gallery` trong HTML đã cache | offline | hoạt động, mẫu do nguồn chọn |
| Ảnh theo album (Thực đơn, Món ăn, Không gian, Tổng hợp) | trang `/<quán>/album-<tên>` | 1 request trang | hoạt động; chỉ trang render đầu (tối đa ~20 ảnh/album) |
| Thực đơn chữ | `window.intMenu` trên `/<quán>/thuc-don` | 1 request trang | parser sẵn sàng; **0/66 quán thử có món** |
| Thực đơn giao hàng (ShopeeFood) | dịch vụ khác, cần API nội bộ/khóa | **không gọi** | `delivery_listed` chỉ là dấu hiệu |
| OCR ảnh thực đơn | Windows.Media.Ocr cục bộ (en-US) | cục bộ | thử nghiệm, luôn `ocr_needs_review` |

Không có API nội bộ nào được gọi (`api_requests` luôn 0). Không đăng nhập, không lấy khóa/cookie, không vượt CAPTCHA.
`TotalDishes`/`DeliveryId` trong trang chỉ là con số nguồn tuyên bố; **không phải món/giá**.

## Tệp trong `data/jobs/<job>/media/`
`venues.json`, `photos.json`, `menu_items.json`, `menu_ocr.json`, `pages.json`, `images/<venue_id>/<source_photo_id>.<jpg|png|gif|webp>`.

### Ảnh (`photos_manifest.csv/json`)
`photo_id` (`<venue_id>-<source_photo_id>`), `venue_id`, `venue_url`, `source_page`, `image_url`, `thumb_url`,
`image_url_derived_from_thumb` (URL gốc suy ra bằng bỏ hậu tố `@resize…`), `source_album`/`source_album_label`
(**danh mục do nguồn cung cấp**, null với dải ảnh trang chủ), `source_group_raw`, `caption`, `source_date` (luôn null: nguồn không cung cấp),
`width`,`height`, `is_menu_image`, `extraction_method`, `fetched_at`, `download_status`, `download_error`, `local_path`, `sha256`, `bytes`, `mime`, `duplicate_of`.
Không có danh mục suy luận. Ảnh review/avatar không được lấy (chỉ khối gallery của quán/album của quán).

### Thực đơn chữ (`menu_items.csv/json`)
`item_id, venue_id, venue_url, source_url, fetched_at, extraction_method, group_raw, name_raw, price_raw, name, group, price_vnd, price_status, image_thumb_url` (+ `source_dish_raw` trong JSON).
`price_vnd` chỉ khi nguồn cung cấp giá > 0; ngược lại null và `price_status=not_supplied`.
Trạng thái quán (`menu_text_status`): `not_collected` (chưa thu thập — **không phải không có**), `menu_items`, `empty_confirmed` (nguồn trả mô hình trống), `blocked`, `error`.

### OCR (`menu_ocr.csv/json`)
Tách riêng, không trộn vào `menu_items`. Mỗi dòng `status=ocr_needs_review`, `price_candidate_vnd` chỉ khi dòng có đúng một giá rõ ràng; tên món thiếu dấu do chỉ có bộ nhận dạng en-US.

## Giới hạn và an toàn
- Trang: giãn cách ≥2 giây, mặc định 3; ảnh ≥0,5 giây. Mặc định ≤8 ảnh/quán, ≤200 ảnh, ≤8 MB/ảnh, ≤400 MB, ≤300 trang. Trần cứng trong `media.HARD_LIMITS`.
- Dừng ngay khi 403/429, trang thử thách/CAPTCHA, chuyển hướng đăng nhập.
- Ảnh: chỉ https, host `*.susercontent.com` / `*.foody.vn`, không IP literal/cổng/userinfo, phân giải DNS phải ra địa chỉ công cộng, kiểm tra lại mỗi lần chuyển hướng (≤3), nhận diện định dạng bằng chữ ký byte (không tin Content-Type), loại ảnh vượt giới hạn.
- Tiếp tục: tệp ảnh hợp lệ đã có thì bỏ qua; tệp mồ côi từ lần chạy bị ngắt được đăng ký lại không cần tải.
- Không chạy khi đang có phiên thu thập; một tác vụ menu/ảnh tại một thời điểm.
- Tải CSV: tiền tố `'` cho ô bắt đầu bằng `= + - @`; ZIP chỉ chứa tệp do tool tạo.

## API
`GET /api/media/status|venues|venue|file|download`, `POST /api/media/scan|collect|images|ocr|control` (CSRF như các API khác).
