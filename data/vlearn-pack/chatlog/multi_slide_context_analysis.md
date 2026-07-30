# Phân tích nhu cầu sử dụng ngữ cảnh nhiều slide

Ngày tạo: 2026-07-30

CSV nguồn: `/Users/tranquangtrong/Desktop/Batch03-K3-AI-Product-Hackathon/data/vlearn-pack/chatlog/chat_history_anonymized_for_hackathon.csv`

CSV bằng chứng: `/Users/tranquangtrong/Desktop/Batch03-K3-AI-Product-Hackathon/data/vlearn-pack/chatlog/multi_slide_context_evidence.csv`

## Câu hỏi cần kiểm tra

Tìm trong lịch sử chat các nội dung liên quan đến những câu trả lời cần sử dụng ngữ cảnh từ nhiều slide/trang, ví dụ như tóm tắt, nội dung chính, các mục chính, hoặc tổng quan toàn bộ bài học.

## Phương pháp

1. Parse `chat_history_anonymized_for_hackathon.csv` như một file CSV chuẩn, giữ nguyên các xuống dòng nằm trong ô `content`.
2. Gom các dòng theo `turn_id`, ghép mỗi tin nhắn `student` với phản hồi `tutor` tương ứng.
3. Tách phần câu hỏi thật của học viên khỏi wrapper “đoạn được chọn”, để không đếm nhầm số trang nằm trong nội dung slide được copy.
4. Đánh dấu một lượt hỏi-đáp là bằng chứng cần ngữ cảnh nhiều slide khi khớp ít nhất một nhóm mẫu sau:
   - phạm vi rõ ràng hoặc số nhiều: `slide 21 đến slide 32`, `từ trang 1 đến trang 44`, `các slide`, `nhiều trang`
   - phạm vi tổng hợp rộng: `toàn bộ slide`, `toàn bộ tài liệu`, `bài học này`, `buổi học này`, `Day 2`
   - ý định tổng hợp đi kèm phạm vi rộng: `tóm tắt`, `summary`, `tổng hợp`, `nội dung chính`, `ý chính`, `các phần chính`, `kiến thức trọng tâm`, `quiz/quizz`
5. Loại khỏi nhóm bằng chứng chính các yêu cầu không phục vụ học tập như tải file, mã hóa base64, hoặc chép nguyên văn toàn bộ tài liệu.

## Tóm tắt

| Chỉ số | Số lượng |
|---|---:|
| Dòng trong CSV nguồn | 2522 |
| Lượt hỏi-đáp student/tutor | 1261 |
| Lượt hỏi của học viên có keyword tổng hợp rộng | 137 |
| Lượt bằng chứng mạnh về nhu cầu multi-slide/multi-context | 71 |
| Lượt bằng chứng có dẫn chứng từ 2+ trang | 12 |
| Lượt bằng chứng chỉ có dẫn chứng từ đúng 1 trang | 16 |
| Lượt bằng chứng không có citation | 43 |
| Lượt bằng chứng được phân loại là lỗi truy xuất/vượt phạm vi | 34 |
| Lượt tóm tắt một slide riêng lẻ, tách khỏi nhu cầu multi-slide | 20 |

## Tần suất keyword trong câu hỏi của học viên

| Keyword | Số lượng |
|---|---:|
| tóm tắt | 120 |
| nội dung chính | 7 |
| ý chính | 15 |
| tổng quan | 1 |
| khái quát | 1 |
| toàn bộ | 41 |
| các slide | 2 |
| các trang | 0 |
| các mục | 0 |
| so sánh | 7 |
| phân biệt | 4 |

## Phân bố kết quả phản hồi của tutor trong nhóm bằng chứng

| Kết quả | Số lượng |
|---|---:|
| lỗi truy xuất hoặc vượt phạm vi tóm tắt | 34 |
| trả lời chỉ có dẫn chứng từ một trang | 15 |
| trả lời có dẫn chứng từ nhiều trang | 12 |
| trả lời không có dẫn chứng | 10 |

## Diễn giải

Dữ liệu cho thấy có nhu cầu rõ ràng về xử lý ngữ cảnh nhiều slide. Tín hiệu mạnh nhất là 71 lượt hỏi mà học viên yêu cầu tóm tắt toàn bộ slide, toàn bộ tài liệu, toàn bộ bài/buổi học, tổng quan theo Day, các ý chính, hoặc giải thích một dải slide/trang cụ thể.

Hành vi hiện tại của tutor chưa ổn định:

- Chỉ 12 lượt trong nhóm bằng chứng có citation từ 2 trang trở lên.
- 16 lượt chỉ cite đúng 1 trang, có thể chưa đủ cho yêu cầu tổng hợp toàn bài/toàn tài liệu.
- 43 lượt không có citation; nhiều trường hợp tutor trả lời rằng không thể truy xuất hoặc không thể tóm tắt toàn bộ slide deck.
- 34 lượt được phân loại là lỗi truy xuất hoặc vượt phạm vi, dựa trên các cụm như “không thể”, “không tìm thấy”, hoặc “không truy xuất”.

Điều này ủng hộ một yêu cầu sản phẩm/UX: khi học viên hỏi tóm tắt, nội dung chính, các phần quan trọng, quiz ôn tập, hoặc giải thích theo dải trang/slide, hệ thống nên retrieve và suy luận trên nhiều slide liên quan thay vì chỉ dựa vào một slide đang chọn hoặc trả về lỗi chung chung.

## Ví dụ mạnh có citation nhiều trang

| Mã bằng chứng | Lượt | Số trang citation | Citation | Câu hỏi học viên | Bằng chứng từ câu trả lời tutor |
|---|---|---:|---|---|---|
| E008 | T1050 | 6 | [12, 27, 36, 52, 65, 69] | tóm tắt lại buổi học này | Dựa trên nội dung các slide bài giảng, buổi học này tập trung vào các kiến thức nền tảng về LLM, cách tối ưu hóa tương tác với AI và lộ trình phát triển từ mô hình ngôn ngữ đến ... |
| E011 | T0322 | 4 | [1, 6, 3, 40] | vậy tài liệu này đang dạy về gì | Dựa trên nội dung tài liệu, bài học này tập trung vào tư duy và quy trình xây dựng các sản phẩm AI thực tế [trang 1]. Nội dung chính bao gồm các phần sau: 1. **Product Thinking ... |
| E006 | T1019 | 3 | [4, 22, 13] | Tổng hợp toàn bộ những kiên thức chính trong bài này | Chào bạn, đây là tổng hợp các kiến thức trọng tâm của buổi học về "AI Product Thinking & Requirements": 1. **Tư duy sản phẩm AI**: Cần hiểu rõ sự khác biệt giữa AI product và cá... |
| E007 | T0690 | 2 | [22, 56] | TÓm tắt tài liệu tôi xem nào | Tài liệu này tập trung vào hai nội dung chính: 1. **Khởi nguồn bài toán (lấy từ các bài học thực tế):** Nhấn mạnh việc không bắt đầu từ AI mà phải dựa trên am hiểu lĩnh vực, xác... |
| E014 | T0236 | 2 | [5, 6] | Tóm tắt toàn bộ tài liệu này | Tài liệu này tập trung vào việc giới thiệu **Bức tranh tổng quan về AI** (AI Landscape) [trang 5]. Dưới đây là các nội dung chính được tóm tắt: * **Phân tầng công nghệ AI [trang... |

## Ví dụ gap

| Mã bằng chứng | Lượt | Số trang citation | Kết quả | Câu hỏi học viên | Bằng chứng từ câu trả lời tutor |
|---|---|---:|---|---|---|
| E001 | T0541 | 0 | trả lời không có dẫn chứng | Giúp tôi viết summary chi tiết và đầy đủ nhất về toàn bộ slide bài giảng ngày hôm nay | Rất tiếc, hiện tại trong nội dung slide bài giảng của ngày hôm nay không chứa thông tin chi tiết về khái niệm "ReAct Design Pattern" hay một bản tóm tắt tổng quát về toàn bộ các... |
| E003 | T0408 | 0 | lỗi truy xuất hoặc vượt phạm vi tóm tắt | tóm tắt các chủ đề chính của slide day05-lecture-slides-batch03.pdf này | Rất tiếc, tôi không thể tìm thấy tệp tin hoặc nội dung chi tiết của `day05-lecture-slides-batch03.pdf` trong hệ thống hiện tại để tóm tắt các chủ đề chính cho bạn. Bạn có thể cu... |
| E004 | T0213 | 0 | lỗi truy xuất hoặc vượt phạm vi tóm tắt | tóm tắt tất cả slide | Chào bạn, rất tiếc là hệ thống hiện không thể tự động tổng hợp toàn bộ nội dung của tất cả các slide trong một lần. Bạn có thể cho mình biết cụ thể hơn bạn đang quan tâm đến phầ... |
| E009 | T0739 | 0 | trả lời không có dẫn chứng | tóm tắt các điểm chính trong bài học hôm nay | Chào bạn! Hiện tại trong hệ thống slide bài giảng cho ngày học hôm nay (day05-slide-batch03-C401) không có một trang tổng kết cụ thể các điểm chính. Để mình có thể hỗ trợ bạn tố... |
| E010 | T1164 | 0 | lỗi truy xuất hoặc vượt phạm vi tóm tắt | tóm tắt cho t tất cả từ trang 1 đến trang 44 bài này học về gì | Chào bạn, rất tiếc là hệ thống hiện không thể truy xuất tóm tắt tổng thể cho toàn bộ tài liệu 44 trang cùng một lúc. Để hỗ trợ bạn tốt nhất, bạn có thể cho mình biết cụ thể chủ ... |
| E012 | T0345 | 0 | trả lời không có dẫn chứng | tóm tắt slide day 4 | Rất tiếc, mình hiện chưa có nội dung tóm tắt cụ thể cho toàn bộ ngày học thứ 4 trong hệ thống. Bạn có thể cho mình biết bạn đang quan tâm đến chủ đề nào trong phần Prompt Engine... |
| E015 | T0716 | 0 | lỗi truy xuất hoặc vượt phạm vi tóm tắt | tóm tắt cho tôi buổi học hôm nay - buổi đầu tiên | Rất tiếc là tôi chưa tìm thấy nội dung chi tiết trong slide để tóm tắt chính xác buổi học đầu tiên này cho bạn. Có vẻ như các từ khóa tìm kiếm của tôi chưa khớp với nội dung bài... |
| E016 | T1027 | 0 | lỗi truy xuất hoặc vượt phạm vi tóm tắt | Hãy giải thích slide 21 đến slide 32. Hướng dẫn tôi chi tiết cách hoàn thành bài lab và cách nộp | Xin lỗi, tôi không thể tìm thấy nội dung chi tiết của các slide từ 21 đến 32 hoặc hướng dẫn cụ thể về bài lab và cách nộp trong dữ liệu hiện có của ngày học này. Vui lòng kiểm t... |

## Các cột trong file evidence

File CSV đi kèm chứa audit trail cho từng lượt bằng chứng:

- `ma_bang_chung`, `ma_luot_hoi_dap`, `ma_hoi_thoai`, `ma_nguoi_dung`, `ma_tai_lieu_ngay_hoc`, `thoi_diem_tao_tin_nhan`
- `cau_hoi_da_lam_sach`: câu hỏi học viên sau khi tách khỏi wrapper “đoạn được chọn”
- `ly_do_phan_loai`: lý do lượt này được xếp vào nhóm cần multi-slide/multi-context
- `trich_dan_goc`, `cac_trang_duoc_trich_dan`, `so_luong_trang_trich_dan`
- `ket_qua_phan_loai`: phân loại thô về hành vi phản hồi của tutor
- `trich_doan_ngu_canh_duoc_chon`, `trich_doan_cau_tra_loi_gia_su`
- `noi_dung_hoc_vien_day_du`, `noi_dung_gia_su_day_du`
- `duong_dan_csv_nguon`
