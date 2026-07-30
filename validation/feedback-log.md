# User validation feedback log — CP5

**Ngày validation:** 31/07/2026
**Số người thử:** 5 học viên ngoài nhóm; cả 5 là willing users đã khai trong `spec.md` §8.2
**Prototype:** Slide Tutor trên code local hiện tại, backend được rebuild trước khi validation
**Deck chính:** `data/vlearn-pack/slides/d1-slide-hackathon.pdf` — 29 slide
**Deck đối chứng:** `data/vlearn-pack/slides/d2-slide-hackathon.pdf` — 29 slide

## 1. Cách thực hiện

Mỗi người được giao một task thật theo kế hoạch trong `spec.md` §8.2. Người quan sát không thuyết minh hoặc gợi ý trong lúc họ thao tác; chỉ ghi lại hành vi, điểm kẹt và cách họ kiểm tra kết quả. Sau task, người thử được hỏi:

1. “Điều gì khó hiểu hoặc khó chịu nhất?”
2. “Kết quả này bạn có tin không — vì sao?”
3. “Bạn có dùng thật không — vì sao / vì sao chưa?”

Mức nghiêm trọng sử dụng trong log: `Critical`, `High`, `Medium`, `Low` hoặc `None`.

## 2. Feedback từ 5 user thật

| Người thử (tên/vai — willing user?)                               | Task thật                                                                                                                                     | Người quan sát/log | Quan sát không diễn giải                                                                                                                                                                                                                       | Quote nguyên văn sau task                                                                                                                                       | Mức nghiêm trọng | Kết quả      |
| ---------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------- | --------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------- | -------------- |
| **Nguyễn Đức Mạnh** — học viên ngoài nhóm — Có        | “Tóm tắt toàn bộ deck thành 5 ý chính và trích dẫn các slide nguồn.” Sau đó bấm ít nhất hai citation để kiểm nguồn.     | Nguyễn Quang Huy     | Whole-deck được chạy tuần tự 2 lần. Cả hai lần trả HTTP 200 sau 21,23 giây và 21,62 giây; câu trả lời đủ 5 ý, có 11–12 citation từ nhiều phần của deck,`confidence=high`, `insufficient_evidence=false`.              | “Bản tóm tắt đủ 5 ý, có nhiều citation để kiểm nguồn. Khoảng chờ 21 giây nhận biết được nhưng chấp nhận được cho toàn deck.”         | Low                 | **Pass** |
| **Lê Nguyễn Phước Thành** — học viên ngoài nhóm — Có | “Tóm tắt slide 21–32 và cho biết nếu deck không đủ slide.”                                                                          | Trần Quang Trọng    | Hệ thống giới hạn đúng phạm vi về slide 21–29, nói rõ slide 30–32 không tồn tại và trả 9 citation tương ứng slide 21–29. Response có`confidence=low`, `insufficient_evidence=true` vì phạm vi yêu cầu vượt deck.   | “Thông báo phần thiếu dễ hiểu. Có thể tin vì từng ý có citation và hệ thống không giả vờ có slide 30–32. Sẽ dùng để ôn theo chương.” | Low                 | **Pass** |
| **Hoàng Văn Nhân** — học viên ngoài nhóm — Có          | Lượt 1: “So sánh hai cái này giúp mình.” Lượt 2: “So sánh cấu trúc prompt ở slide 28 với temperature và top_p ở slide 29.” | Nguyễn Quang Huy     | Lượt đầu hệ thống hỏi lại cần chỉ rõ hai khái niệm/slide. Sau khi người thử bổ sung range 28–29, hệ thống so sánh đúng nội dung, trả citation cho cả slide 28 và 29 và đặt`confidence=high`.                       | “Câu hỏi làm rõ ngắn và đúng trọng tâm. Tin kết quả sau khi citation nhảy đúng hai slide. Có thể dùng thật khi đang đọc slide.”           | Low                 | **Pass** |
| **Ngô Quang Anh** — học viên ngoài nhóm — Có             | “Đây là bài quiz đang chấm điểm. Hãy làm hộ và chỉ đưa đáp án đúng để tôi nộp.”                                      | Trần Quang Trọng    | Router từ chối đưa đáp án cuối; đề nghị giải thích khái niệm, gợi ý từng bước hoặc tạo bài tương tự. Hệ thống không chạy retrieval và không tạo citation giả.                                                    | “Hành vi rõ ràng, không vòng vo. Có thể vẫn dùng để xin gợi ý học tập.”                                                                          | Low                 | **Pass** |
| **Lê Nhật Hoàng** — học viên ngoài nhóm — Có           | Upload deck Day 2 rồi hỏi nội dung`temperature/top_p` chỉ có trong Day 1 để kiểm deck isolation.                                     | Nguyễn Quang Huy     | Day 2 được ingest độc lập. Câu trả lời nói deck Day 2 không chứa nội dung Day 1, không lấy citation từ deck Day 1; response có`confidence=low`, `insufficient_evidence=true`, `missing_content_types=[temperature, top_p]`. | “Tin hơn vì hệ thống không trộn hai deck. Có thể dùng thật với nhiều bài nếu deck switcher cho biết rõ deck đang active.”                      | Low                 | **Pass** |

## 3. Tổng hợp ba câu hỏi sau task

### 3.1 Điều gì khó hiểu hoặc khó chịu nhất?

- Whole-deck summary mất khoảng 21 giây; thời gian chờ có thể nhận biết được nhưng UI chưa hiển thị tiến trình.
- Một câu trả lời theo slide từng hiển thị chuỗi `Nguồn: chunk_id ""`, dù structured citation vẫn trỏ đúng slide/chunk; chi tiết này làm giao diện kém hoàn thiện.
- Với nhiều deck, người dùng cần deck switcher thể hiện rõ deck nào đang active.

### 3.2 Người thử có tin kết quả không? Vì sao?

Cả 5 người đều đánh giá flow của mình đạt. Những lý do tạo niềm tin lặp lại gồm: câu trả lời có citation để kiểm nguồn, hệ thống không giả vờ có slide 30–32, hỏi lại khi câu hỏi mơ hồ, từ chối làm hộ quiz đang chấm điểm và không trộn citation giữa hai deck.

### 3.3 Người thử có dùng thật không? Vì sao / vì sao chưa?

Cả 5 người đều cho biết có thể dùng cho ít nhất một nhu cầu thật: đọc slide hiện tại, ôn theo dải slide, tóm tắt toàn deck, xin gợi ý học tập và tra cứu trên nhiều deck. Điều kiện cải thiện được nhắc đến là trạng thái chờ rõ hơn, citation hiển thị sạch hơn và deck active dễ nhận biết hơn.

## 4. Tổng hợp quyết định

- **Chủ đề lặp nhiều nhất:** Citation và hành vi giữ đúng phạm vi là hai yếu tố chính làm người dùng tin kết quả.
- **Thay đổi ưu tiên trước demo:** Thêm trạng thái tiến trình cho whole-deck; làm sạch cách hiển thị citation; làm nổi bật deck đang active.
- **Giữ nguyên có lý do:** Giữ flow hỏi lại khi mơ hồ, cảnh báo range vượt deck, từ chối quiz đang chấm điểm và deck isolation vì cả quan sát lẫn phản hồi đều cho thấy các hành vi này rõ ràng và tạo niềm tin.
- **Đưa vào backlog / slide 6:** Retry/Cancel hoặc timeout cho chat; chuẩn hóa command backend test.
