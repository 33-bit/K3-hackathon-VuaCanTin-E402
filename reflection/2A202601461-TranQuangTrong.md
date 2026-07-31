# Individual Reflection — Trần Quang Trọng

**Mã học viên:** 2A202601461  
**Vai trò trong nhóm:** Evidence, spec, kiểm thử và slide demo

## Phần tôi đã làm

Tôi phụ trách tìm evidence cho bài toán RAG bằng cách phân tích chatlog về nhu cầu tổng hợp nhiều slide, lưu phương pháp đếm và các ví dụ để nhóm có thể kiểm lại. Tôi tham gia viết và cập nhật `spec.md`, đặc biệt ở phần pain, impact, lát cắt sản phẩm, bốn lớp chỗ khó, kịch bản rủi ro, quality bar và kết quả eval.

Ở giai đoạn cuối, tôi phối hợp kiểm thử các nhánh range, câu hỏi mơ hồ, yêu cầu làm hộ quiz và các câu ngoài phạm vi deck. Tôi cũng cập nhật slide demo để phần trình bày bám đúng evidence, flow sản phẩm và kết quả đo thật thay vì chỉ giới thiệu tính năng.

## AI đã hỗ trợ tôi như thế nào?

Tôi dùng AI để hỗ trợ phân loại mẫu chatlog, kiểm tra tính nhất quán của spec, gợi ý case biên và rút gọn nội dung slide. AI giúp xử lý nhanh lượng thông tin lớn, nhưng các con số và claim quan trọng đều phải quay lại file nguồn hoặc log chạy thật để xác nhận. Khi AI viết câu quá chắc chắn hoặc biến giả định thành kết luận, tôi sửa lại để ghi rõ giới hạn của dữ liệu, ví dụ số lượt hỏi-đáp không đồng nghĩa với số học viên duy nhất.

## Bài học từ một case fail của nhóm

Lượt chạy đầu chỉ đạt 3/25 theo semantic judge, trong đó có cả lỗi sản phẩm thật và false negative do tiêu chí chấm chưa đủ rõ. Sau khi review thủ công và sửa pipeline, kết quả lên 22/25 nhưng nhóm vẫn ghi là chưa đạt vì hard gate `domain_harm` còn fail. Tôi học được rằng evaluation không phải một con số duy nhất: phải giữ raw output, định nghĩa pass/fail đủ cụ thể và review những kết quả bất thường trước khi kết luận sản phẩm tốt hay kém.

## Điều tôi sẽ làm khác nếu có thêm thời gian

Tôi sẽ cho hai thành viên chấm độc lập một tập nhỏ ngay khi viết rubric để phát hiện tiêu chí mơ hồ sớm hơn. Với slide demo, tôi sẽ dành thêm một lượt dry run bằng case lạ để kiểm tra xem mọi claim trên slide có thể truy ngược ngay về evidence, spec hoặc kết quả eval hay không.
