# Individual Reflection — Nguyễn Quang Huy

**Mã học viên:** 2A202601954  
**Vai trò trong nhóm:** Frontend, tích hợp và validation

## Phần tôi đã làm

Tôi xây giao diện Slide Tutor và hoàn thiện flow upload deck, xem slide gốc, chọn đoạn văn, dùng `@slide`/dải slide, gửi câu hỏi và mở citation để quay lại nguồn. Sau bản mock đầu tiên, tôi nối frontend với backend thật, bổ sung trạng thái khi backend chưa sẵn sàng, lưu deck và lịch sử chat sau khi refresh, đồng thời hiển thị response có cấu trúc thay vì dồn mọi thứ thành một đoạn text.

Tôi cũng phụ trách phần validation: chuẩn bị task cho người thử, ghi lại kết quả của năm phiên sử dụng, tổng hợp quote và đưa phản hồi vào changelog. Qua các phiên này, nhóm xác nhận được những flow quan trọng như tóm tắt toàn deck, cảnh báo dải slide không tồn tại, hỏi lại câu mơ hồ, từ chối làm hộ quiz và không trộn citation giữa hai deck.

## AI đã hỗ trợ tôi như thế nào?

Tôi dùng AI để dựng nhanh component, gợi ý trạng thái UI, viết test Playwright và rà luồng tích hợp API. AI hữu ích khi tạo khung và phát hiện trường hợp còn thiếu, nhưng đôi lúc đề xuất giao diện giả định backend luôn trả nhanh hoặc dữ liệu luôn sạch. Tôi phải kiểm lại bằng E2E, chạy với backend thật và sửa UI theo response thực tế như `confidence`, `insufficient_evidence`, citation và thông báo lỗi.

## Bài học từ một case fail của nhóm

Trong validation kỹ thuật, tóm tắt toàn deck trả đúng và có 11–12 citation nhưng mất khoảng 21 giây; một câu trả lời khác từng hiện chuỗi `Nguồn: chunk_id ""`. Nội dung có thể đúng nhưng trải nghiệm như vậy vẫn làm người dùng nghi ngờ hệ thống. Tôi học được rằng trust không chỉ đến từ model: trạng thái chờ, cách hiển thị citation và việc cho người dùng quay lại đúng slide cũng là một phần của chất lượng AI product.

## Điều tôi sẽ làm khác nếu có thêm thời gian

Tôi sẽ đưa validation vào sớm hơn ngay sau khi có flow bấm được, thay vì đợi hệ thống gần hoàn chỉnh. Tôi cũng sẽ thêm tiến trình rõ cho whole-deck, làm nổi bật deck đang active và chạy smoke test end-to-end với backend thật cho mọi đường demo trước CP6.
