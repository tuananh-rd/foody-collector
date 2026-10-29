# FoodTour Hà Nội — tool thu thập dữ liệu v0.3

Ứng dụng chạy cục bộ, tự mở trình duyệt, tải thêm danh sách Foody Hà Nội, lấy thông tin cơ bản của quán và xuất CSV/JSON. Có giao diện tiếng Việt, lưu tiến độ, tạm dừng, dừng và tiếp tục phiên cũ.

v0.3 bổ sung lớp kiểm định dữ liệu: giữ raw, tách giá chuẩn hóa, ghi danh sách vấn đề và nguồn gốc từng trường. Khoảng giá `0–0` hoặc đảo chiều không tham gia lọc giá; lịch tuần và trạng thái kinh doanh chưa rõ giữ unknown. CSV/JSON cũ 18 cột vẫn được giữ để tương thích; ưu tiên tệp chuẩn hóa khi dùng dữ liệu phía sau.

## Mở giao diện trên Windows

1. Nhấp đúp **Start-Foody.cmd** trong thư mục dự án. Lần đầu chương trình chuẩn bị môi trường riêng `.venv`, cài Playwright và tải Chromium nếu máy chưa có Edge/Chromium phù hợp. Cần Python và Internet trong bước thiết lập này.
2. Giao diện mở tại **http://127.0.0.1:8765**. Chọn **Mẫu thử nghiệm** hoặc **Toàn bộ Hà Nội**, rồi nhấn **Bắt đầu**.
3. Dùng **Tạm dừng**, **Tiếp tục**, **Dừng lại** khi cần. Tải CSV/JSON/báo cáo trong giao diện. Dùng **Thoát ứng dụng** để lưu và đóng máy chủ cục bộ; đóng tab trình duyệt đơn thuần không dừng phiên đang chạy.

Khởi chạy bằng terminal nếu cần:

```powershell
.\.venv\Scripts\python.exe -X utf8 -m foody_tool serve
```

Nếu tự thiết lập trên hệ thống khác: cài Python >=3.9, tạo môi trường, `pip install -e ".[browser]"`, `python -m playwright install chromium`, rồi `python -m foody_tool serve`. Hướng dẫn Playwright chính thức: https://playwright.dev/python/docs/library và https://playwright.dev/python/docs/browsers.

## Chế độ quét

- **Mẫu thử nghiệm:** lấy đến số quán cấu hình; mặc định 48.
- **Toàn bộ Hà Nội:** duyệt danh sách công khai `https://www.foody.vn/ha-noi/o-dau` đến khi nguồn cho biết đã hết. Không bị giới hạn 50 URL của CLI cũ. Không có tổng số quán đã biết trước, nên giao diện hiện số đếm thay vì phần trăm toàn thành phố.
- Trình duyệt dùng hồ sơ tạm, không dùng tài khoản/cookie trình duyệt của người dùng. Edge được ưu tiên trên máy này; có thể dùng Chromium đã cài. Hiện cửa sổ mặc định.
- Quét tuần tự, mặc định chờ 3 giây giữa các thao tác, tối thiểu 2 giây. Một phiên chạy tại một thời điểm; giới hạn bảo vệ 10.000 lần bấm tải thêm. Đạt giới hạn bảo vệ, bị chặn, hết thời gian chờ hoặc danh sách đứng yên đều báo chưa hoàn tất.
- Chỉ đánh dấu đã hết nguồn khi trang đã hiển thị quán, không đang tải và trạng thái nguồn xác nhận không còn tải thêm. Đây là hết danh sách Foody trả về, không chứng minh mọi quán ngoài thực tế đã được liệt kê.

## Dữ liệu và tiếp tục

Mỗi phiên ở `data/jobs/<mã-phiên>/`: `restaurants.csv`, `restaurants.json`, `report.json`, `job.json`, `urls.json`, `progress.json` và cache HTML riêng. Không xóa thư mục này nếu muốn tiếp tục. Sau khi đóng/mở ứng dụng, phiên bị gián đoạn hiện trong lịch sử và cần nhấn **Tiếp tục**. Trình duyệt có thể duyệt lại danh sách từ đầu; trang quán đã thành công được bỏ qua. Yêu cầu mạng đang chạy có thể phải hoàn tất trước khi dừng.

Trường dữ liệu: ID, tên, tọa độ, địa chỉ/quận/thành phố, khung giờ nguồn cung cấp, khoảng giá, URL và thời điểm lấy. Thiếu thì null/trống. Không suy ra lịch 7 ngày, giá từng món, quán còn hoạt động hay độ mới dữ liệu. Giá `0–0` được giữ nguyên trong dữ liệu và hiện chưa có giá tham khảo trên giao diện. CSV xử lý chuỗi dễ bị bảng tính hiểu là công thức; JSON là dữ liệu chuẩn.

Tool dừng khi thấy chặn truy cập hoặc yêu cầu xác minh. Không đăng nhập, xoay proxy, vượt CAPTCHA hay gọi trực tiếp API nội bộ. Dữ liệu chỉ lưu trên máy. Chưa có quyền tái sử dụng Foody cho triển khai diện rộng hoặc xuất bản dữ liệu.

## CLI cũ vẫn dùng được

```powershell
python -X utf8 -m foody_tool collect --urls-file inputs/seed_sample5.txt --out-dir cache/my_test5
```

CLI `collect` vẫn giới hạn 50 URL/lần, có `--refresh`, `--retry-failed`. Bộ đọc HTML đã lưu vẫn là `python -m foody_tool.discovery --file listing.html --output urls.txt`.

## Kiểm thử và bằng chứng

```powershell
.\.venv\Scripts\python.exe -X utf8 -W error::ResourceWarning -m unittest discover -s tests -v
```

Kiểm thử trình duyệt cần Playwright và Edge/Chromium. HTML fixture gốc không nằm trong gói xuất; các kiểm thử phụ thuộc fixture sẽ bỏ qua khi thiếu. Các nguồn mô phỏng không phải số liệu Foody.

Đợt thử thật v2 qua giao diện: 36 quán, chuỗi Bắt đầu → Tạm dừng → Dừng → Tiếp tục; 36 ID riêng biệt, 36 yêu cầu tải trang quán, 0 lỗi JavaScript, khoảng 82,55 giây. Đây là thử có giới hạn, **chưa chạy đến hết Hà Nội**. Xem `reports/v2/live_ui_evidence.json`; báo cáo nghiệm thu mới ở `reports/v2/ACCEPTANCE_VI.md`. Các báo cáo v1 được giữ làm lịch sử.

Nghiệm thu v0.3: 160 kiểm thử đạt trong worktree có fixture; đối chiếu độc lập CSV gốc 200 quán giữ đủ ID/raw/220 khoảng giờ và phát hiện đúng 6 vấn đề giá. Kiểm thử máy chủ thật + giao diện trên dữ liệu đã lưu giữ nguyên CSV/JSON cũ, tải được các định dạng mới và có 0 lỗi JavaScript; không phải crawl mới 200 quán. Xem `reports/v3/ACCEPTANCE_VI.md`. Để kiểm định phiên cũ, chọn **Xem dữ liệu** trong lịch sử rồi **Kiểm định dữ liệu đã lưu**. Menu, giá phần ăn và lịch tuần còn cần nguồn bổ sung có bằng chứng.

## v0.4 — làm giàu dữ liệu từ HTML đã lưu

Bổ sung phong cách ẩm thực, loại hình, nhóm món phục vụ (không phải thực đơn), bữa phù hợp, đối tượng, điểm/số bình luận/5 tiêu chí, thời gian chuẩn bị, sức chứa, ngày nghỉ lễ và tiện ích. Chạy offline trên phiên đã lưu: `python -X utf8 -m foody_tool enrich --job-dir data/jobs/<mã>` (0 request mạng) hoặc nút **Làm giàu dữ liệu** trong giao diện. Tiện ích màu xám là *chưa xác nhận*, không phải “không có”. Điểm là tín hiệu nền tảng, không phải xác minh chất lượng hay tình trạng kinh doanh. Xem `docs/V4_CONTRACT.md`, `reports/v4/ACCEPTANCE_VI.md`.

## v0.5 — Menu và ảnh

Mục **Menu & Hình ảnh Địa điểm** trong phiên đã lưu: quét offline từ HTML đã lưu, thu thập danh sách album/menu (có giới hạn, giãn cách), tải ảnh về máy có tiếp tục, xem trước, tải manifest CSV/JSON và ZIP, OCR thử nghiệm cục bộ. Thực đơn chữ của Foody trống ở mọi mẫu thử; ảnh thực đơn dùng được; OCR chỉ là ứng viên cần kiểm tra. Xem `docs/V5_CONTRACT.md` và `reports/v5/ACCEPTANCE_VI.md`. Ảnh chỉ dùng cục bộ, không đăng công khai.


## Lưu ý về dữ liệu / Data notice
Repo này chỉ chứa mã nguồn, kiểm thử và tài liệu. Dữ liệu thu thập từ Foody/ShopeeFood, ảnh và bộ nhớ đệm **không** được đưa vào repo; điều khoản và quyền tái sử dụng dữ liệu của nguồn chưa được xác nhận. Chỉ dùng cho nghiên cứu cá nhân, chạy cục bộ. Một số test cần dữ liệu mẫu cục bộ (reference/sample5.json, tests/fixtures) và sẽ tự bỏ qua khi thiếu. Ghi chú trong docs/ có thể nhắc tới tệp báo cáo/bằng chứng không được đưa vào đây.
This repository contains source code, tests and docs only. Scraped Foody/ShopeeFood data, images and caches are not included; the sources terms and reuse permission are unconfirmed. Local personal research use only. Some tests need local sample data and skip when it is missing.
