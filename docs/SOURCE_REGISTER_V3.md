# Hồ sơ nguồn cho v0.3

Ngày kiểm tra: 2026-10-14. Đây là ghi nhận bằng chứng công bố, không thay thế đánh giá pháp lý theo mục đích sử dụng.

| Nguồn | Bằng chứng | Trạng thái quyền | Bước tiếp theo |
|---|---|---|---|
| Foody | [Quy định sử dụng](https://www.foody.vn/dieu-khoan-su-dung), các phần hành động không được phép và quyền sở hữu; trang được đọc lại ngày kiểm tra | Chưa nhận giấy phép hoặc sự đồng ý bằng văn bản cho việc tái sử dụng trong FoodTour AI | Xác nhận quyền theo mục đích trước thu thập mở rộng hoặc cung cấp dataset/chatbot cho người dùng |
| Foody robots | https://www.foody.vn/robots.txt: công cụ web không đọc được lần này; lần kiểm tra trước trả HTML trang lỗi thay vì quy tắc robots | Chưa xác định; không suy ra quyền từ lỗi đọc hoặc HTTP 200 | Kiểm tra lại nếu mở rộng; robots không thay thế giấy phép |
| Website/menu của từng quán | Chưa điều tra lại trong bản nâng cấp chất lượng này | Chưa xác nhận riêng từng nguồn | Lưu URL, ngày đọc, phạm vi giá/phần ăn và quyền tương ứng trước nhập dữ liệu bổ sung |
| OSM | Đã có audit dữ liệu và giấy phép ODbL trong báo cáo nghiên cứu trước | Giấy phép mở có điều kiện; không áp cho dữ liệu Foody | Nếu bổ sung adapter, giữ nguồn riêng và thực hiện nghĩa vụ ODbL/attribution |

Không gửi email hoặc yêu cầu cấp quyền trong đợt nâng cấp này. Không coi kho GitHub riêng tư là giấy phép nguồn. Không thu thập review, người dùng, ảnh hoặc gọi API không được công bố để bổ sung menu.

## Ngữ nghĩa chưa xác định

- `OpeningTime.DayOfWeek=3` xuất hiện trong audit được bàn giao, nhưng chưa chứng minh mapping ngày hay khả năng đại diện lịch tuần. Giữ nguyên mã và nhiều ca; lịch chuẩn hóa chưa biết là NULL.
- `IsActive`, `IsInactive`, `RestaurantStatus`, `IsVerifiedMap` là cờ nguồn. Không đủ bằng chứng để ánh xạ sang tình trạng kinh doanh hoặc xác minh ngoài đời.
- `PriceMin/PriceMax` là khoảng giá cấp quán chưa xác minh. Không chuyển thành giá món, chi phí mỗi người hoặc ngân sách cam kết.
- Hash nội dung dùng để đối chiếu snapshot; không chứng minh độ mới ngoài đời. Thời điểm tải không phải thời điểm xác minh.

## Pilot tiếp theo

Chọn 20–30 quán gần nhau trong vùng Hoàn Kiếm sau khi kiểm tra nguồn bổ sung và quyền tương ứng. Báo cáo mức đáp ứng riêng cho tên/địa chỉ/tọa độ, món, giá phần ăn, lịch tuần và tình trạng kiểm chứng. Dữ liệu thiếu giữ unknown; không đặt mục tiêu 100% bằng suy đoán. Tập này chưa được thu thập hay xác minh trong hồ sơ nguồn hiện tại.
