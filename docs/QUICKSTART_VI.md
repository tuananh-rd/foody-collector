# Dùng giao diện FoodTour v0.3

1. Trong worktree `foody-collector-mvp` hoặc thư mục đã giải nén, nhấp đúp **Start-Foody.cmd**.
2. Chờ giao diện mở tại **http://127.0.0.1:8765**. Lần đầu cần Internet để chuẩn bị môi trường và trình duyệt.
3. Chọn **Mẫu thử nghiệm** để lấy số quán cấu hình, hoặc **Toàn bộ Hà Nội** để quét danh sách Foody đến hết. Nhấn **Bắt đầu**; trình duyệt tự mở và tải thêm.
4. Theo dõi số quán đã tìm, đã xử lý và lỗi. Dùng **Tạm dừng**, **Tiếp tục**, **Dừng lại**; yêu cầu đang chạy có thể hoàn tất trước khi dừng.
5. Nhấn **Tải tệp CSV**, **Tải tệp JSON** hoặc **Báo cáo tổng kết**. Bảng giao diện chỉ xem trước; tệp tải xuống chứa toàn bộ dữ liệu đã lưu.
6. Dùng **Thoát ứng dụng** khi xong. Lần sau chọn phiên trong lịch sử để tiếp tục. Giữ nguyên `data/jobs/` để không mất dữ liệu và tiến độ.

Tool bỏ qua trang quán đã thu thập thành công khi tiếp tục, nhưng trình duyệt có thể duyệt lại danh sách từ đầu để tìm URL còn lại.

Giữ bật **Hiện cửa sổ trình duyệt thực tế** mặc định. Một đợt thử ẩn cửa sổ chưa tải được danh sách; nguyên nhân chưa xác định.

“Đã hết danh sách” chỉ áp dụng cho danh sách nguồn Foody trả về. Bị chặn, chờ quá lâu, không tăng thêm hoặc đạt giới hạn bảo vệ sẽ hiện chưa hoàn tất. Chế độ toàn Hà Nội chưa được nghiệm thu bằng một lần chạy hết nguồn; đợt thử thật v2 giới hạn 36 quán.

Giờ là khung giờ nguồn cung cấp, không phải lịch đủ 7 ngày. Khoảng giá của quán không phải giá từng món; `0–0` không đủ để lập ngân sách. Chưa xác minh độ mới hoặc trạng thái hoạt động ngoài thực tế. Quyền tái sử dụng dữ liệu Foody vẫn cần làm rõ trước khi đưa vào sản phẩm.

## Đọc chất lượng dữ liệu

Trong v0.3, ưu tiên tải dữ liệu **chuẩn hóa** để dùng cho bộ lọc. Tệp cũ 18 cột vẫn giữ nguyên để tương thích, kể cả giá nguồn chưa dùng được. Tệp raw mới là dữ liệu đã qua parser kèm provenance; không có nghĩa mọi nội dung trang đều được giữ trong bản ghi.

- `price_status=ok`: khoảng giá dương và đúng thứ tự; chưa xác minh giá hiện tại.
- `unknown_zero`, `partial_zero`, `invalid_range`, `missing`, `nonfinite`: giá chuẩn hóa là NULL; giữ raw và lý do trong danh sách vấn đề.
- `hours_schedule_norm=NULL` và `operating_status=unknown`: chưa đủ bằng chứng cho lịch ngày/tuần hoặc tình trạng hoạt động. Không diễn giải thành đóng cửa.
- `budget_eligible=false`: khoảng giá cấp quán chưa đủ để lập ngân sách món/phần ăn. Một quán vẫn có thể tìm theo tên khi giá có vấn đề.

Đợt cũ chưa có báo cáo chất lượng không được coi là đã đạt kiểm định. Không xóa dữ liệu cũ khi nâng cấp. Nếu ứng dụng đang chạy, dùng **Thoát ứng dụng**, sau đó mở lại **Start-Foody.cmd** để nạp mã mới.

Để kiểm định một phiên đã lưu: chọn **Xem dữ liệu** trong lịch sử, rồi bấm **Kiểm định dữ liệu đã lưu**. Thao tác chỉ đọc dữ liệu/cache trên máy, không tải lại Foody và không đổi CSV/JSON cũ. Phiên đang chạy hoặc tạm dừng cần dừng trước. Các cảnh báo thiếu provenance không đồng nghĩa quán đóng cửa hoặc mọi trường đều sai.

Nếu kiểm định một CSV/JSON riêng bằng lệnh:

```powershell
.\.venv\Scripts\python.exe -X utf8 -m foody_tool quality --input "restaurants.csv" --out-dir "quality-output"
```

Nếu cần mở bằng terminal:

```powershell
.\.venv\Scripts\python.exe -X utf8 -m foody_tool serve
```

CLI nhận danh sách URL cũ vẫn dùng được và giới hạn 50 URL/lần:

```powershell
python -X utf8 -m foody_tool collect --urls-file inputs/seed_sample5.txt --out-dir cache/my_test5
```
