# Individual Reflection — Hoàng Danh Thái

**Mã học viên:** 2A202601527  
**Vai trò trong nhóm:** Backend, RAG và evaluation

## Phần tôi đã làm

Tôi phụ trách phần backend chính của Slide Tutor: ingest nội dung PDF/PPTX, chia chunk, lưu dữ liệu, tìm kiếm kết hợp dense retrieval với BM25/RRF và trả câu trả lời có citation. Tôi cũng tham gia xây router cho các nhánh trả lời, hỏi lại, từ chối và báo thiếu căn cứ; đồng thời bổ sung cơ chế giữ ngữ cảnh hội thoại bằng rolling summary.

Ở phần kiểm thử, tôi tham gia xây golden set 25 case, viết và sửa evaluation runner, lưu đầy đủ kết quả từng lượt chạy và cải thiện pipeline sau khi phát hiện lỗi. Sau lần đo đầu, tôi cùng nhóm bổ sung query policy, kiểm tra grounding và các guardrail để hệ thống không trả lời bừa khi câu hỏi mơ hồ, vượt phạm vi hoặc thiếu nguồn.

## AI đã hỗ trợ tôi như thế nào?

Tôi dùng AI để phác thảo cấu trúc FastAPI, rà các nhánh lỗi, viết test ban đầu và phản biện cách thiết kế retrieval/evaluation. AI giúp tăng tốc phần code lặp lại và gợi ý thêm edge case, nhưng tôi không dùng output trực tiếp mà kiểm lại qua unit test, full eval và log chạy thật. Những thay đổi ảnh hưởng đến grounding hoặc citation đều được đối chiếu với dữ liệu canonical của deck.

## Bài học từ một case fail của nhóm

Lượt eval được review đạt 22/25 nhưng vẫn không qua quality bar vì hard gate `domain_harm` chưa đạt 100%. Case `VL-024` cho thấy câu trả lời có thể giải thích token và xác suất nghe khá đúng nhưng vẫn thiếu ý quan trọng về hallucination, nên chưa đủ an toàn cho việc học. Tôi rút ra rằng điểm tổng cao không thay thế được hard gate: với lỗi kiến thức có hậu quả lớn, tiêu chí bắt buộc phải được kiểm tra riêng và pipeline phải fail closed khi chưa đủ căn cứ.

## Điều tôi sẽ làm khác nếu có thêm thời gian

Tôi sẽ chạy hai vòng chấm độc lập sớm hơn, tách rõ lỗi sản phẩm với false negative của evaluator và thêm retry/backoff cho giới hạn quota. Tôi cũng sẽ ưu tiên một full rerun sau remediation thay vì chỉ kiểm lại những case đã fail.
