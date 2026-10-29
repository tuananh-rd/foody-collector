# Pilot FoodTour sau khi kiểm định export

Trạng thái: kế hoạch tiếp theo, chưa phải batch đã thu thập hoặc xác minh. Audit 200 quán ghi nhận 27 nhãn Hoàn Kiếm; đây là nhóm ứng viên, không phải 27 quán đã đủ điều kiện lập tour.

## Chọn 20–30 quán

1. Lọc tọa độ hợp lệ và xem cụm địa lý; không dùng tên quận một mình để xác định khả năng đi bộ.
2. Ưu tiên quán có nguồn chính thức nhận diện đúng chi nhánh, công bố món/phần ăn và lịch ngày. Kiểm tra quyền của từng nguồn.
3. Giữ cả quán đủ và thiếu dữ liệu trong coverage matrix, không chọn toàn quán dễ lấy rồi suy ra tỷ lệ cho Hà Nội.
4. Dành một phần quán chưa dùng để phát triển parser làm batch nghiệm thu mới.

## Coverage matrix cần đo

Mỗi quán có ID nguồn, tên/chi nhánh, địa chỉ/tọa độ, danh mục/món có nguồn, giá VND và đơn vị phần, dine-in/takeaway/delivery, ngày/tuần/nhiều ca/ngoại lệ, trạng thái kinh doanh và độ mới. Với từng nhóm ghi URL, ngày đọc, ngày nguồn cập nhật nếu có, phương pháp kiểm chứng và unknown khi thiếu. Dữ liệu website là kiểm chứng trực tuyến, không được gọi là xác minh thực địa.

Quy tắc ngân sách: chỉ xét phần ăn có giá và phạm vi rõ; không thay bằng khoảng giá quán. Quy tắc giờ: phải áp vào ngày/giờ tour cụ thể; mã ngày chưa mapping không được tham gia lọc mở cửa. Tọa độ nguồn chưa xác minh cổng vào và routing đi bộ cần đội planner kiểm tra riêng.

## Phân công

- Claude: đánh giá nguồn, chốt quy tắc đối chiếu chi nhánh, bằng chứng và điều kiện nghiệm thu.
- Antigravity: adapter theo hợp đồng đã chốt, thu batch nhỏ được phép, lập coverage matrix và các kiểm thử dữ liệu.
- Codex: kiểm tra độc lập mẫu mới, tổng hợp trường chưa lấy được, quyết định phạm vi tính năng MVP theo số liệu thực đo.

Không mở rộng crawl chỉ để tăng số dòng. Nếu không có nguồn phù hợp cho lịch tuần/giá phần ăn, báo cáo thiếu và chọn nguồn khác. Hồ sơ quyền Foody hiện vẫn chưa có xác nhận cho FoodTour AI; xem SOURCE_REGISTER_V3.md.
