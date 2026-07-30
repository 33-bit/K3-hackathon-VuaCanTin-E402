# Tích hợp RAG vào VLearn AI Tutor · Nhóm VuaCanTin · Zone E402

Hướng: [x] A — VLearn  [ ] B — Trợ lý Học viên  [ ] C — Làn mở  
Loại: [x] Tối ưu tính năng có sẵn  [ ] Tính năng mới  
Ngày chốt quality bar: 30/07/2026, trước 23:59 N1

---

## §1. User & Job

### 1.1 Job executor và workflow

- **Job executor:** Học viên đang học hoặc xem lại bài giảng trên VLearn, đang ở một slide cụ thể và cần hiểu một đoạn nội dung, một khái niệm hoặc một chủ đề có liên quan đến nhiều slide trong cùng bài giảng.

- **Bối cảnh workflow hiện tại:**
  1. Học viên mở một slide trong bài giảng.
  2. Học viên bôi đen một đoạn chưa hiểu rồi đặt câu hỏi, hoặc đặt câu hỏi trực tiếp dựa trên slide đang mở.
  3. Câu trả lời hiện tại chủ yếu dựa trên đoạn được chọn hoặc nội dung của slide hiện tại.
  4. Khi kiến thức liên quan nằm ở slide trước, slide sau hoặc một slide khác trong cùng bài, học viên phải tự chuyển qua lại giữa các slide để tìm và nối các ý.
  5. Học viên phải tự kiểm tra câu trả lời đã đầy đủ hay chưa và nội dung được lấy từ slide nào.

- **Điểm vướng và hậu quả:** Nhiều khái niệm trong bài giảng được trình bày xuyên suốt qua nhiều slide, nhưng ngữ cảnh cục bộ chỉ gồm đoạn được bôi đen hoặc slide đang mở. Vì vậy, câu trả lời có thể đúng với một phần nội dung nhưng vẫn thiếu định nghĩa, giải thích, ví dụ hoặc mối liên hệ nằm ở các slide khác. Học viên khó nhận biết phần bị thiếu, phải tự tìm lại nguồn, mất thời gian và bị gián đoạn mạch học.

- **Đầu vào theo ngữ cảnh của học viên:**
  - Câu hỏi của học viên.
  - Slide hiện tại.
  - Đoạn text được bôi đen, nếu có.
  - Bộ slide và phiên bản tài liệu đang được học.
  - Một số lượt hội thoại gần nhất nếu đây là câu hỏi tiếp nối.

- **Workflow mong muốn:**
  1. Nếu học viên bôi đen text, sử dụng đoạn đó làm trọng tâm và slide hiện tại làm ngữ cảnh gần.
  2. Nếu học viên không bôi đen text, sử dụng toàn bộ slide hiện tại làm ngữ cảnh chính.
  3. Tìm thêm các đoạn text liên quan từ những slide khác trong cùng bộ slide.
  4. Kết nối các nội dung tìm được theo đúng ngữ cảnh và thứ tự bài giảng.
  5. Trả lời dựa trên nội dung slide và chỉ rõ slide nguồn cho các ý quan trọng.
  6. Nếu tài liệu dạng text không cung cấp đủ căn cứ, thông báo rõ giới hạn thay vì tự suy đoán.

- **Phạm vi dữ liệu của phiên bản hiện tại:** Chỉ sử dụng text trích xuất trực tiếp từ PPTX có text box, PDF có text layer và đoạn text học viên bôi đen. Chưa xử lý nội dung chỉ tồn tại trong hình ảnh, biểu đồ, sơ đồ, công thức dạng ảnh, video, speaker notes hoặc tài liệu ngoài bài giảng.

- Sơ đồ workflow của hệ thống RAG text-only cho VLearn AI Tutor:

![Workflow hệ thống RAG Text-Only cho VLearn AI Tutor](assets/jtbd-workflow-rag-text-only-vlearn-ai-tutor.png)

### 1.2 Core JTBD

- **Job statement:** Hiểu chính xác một khái niệm hoặc chủ đề trong bài giảng bằng cách kết nối nội dung của slide hiện tại với các slide liên quan, đồng thời biết nguồn để kiểm tra lại khi cần.

- **Job story 1 — Giải thích đoạn được chọn:** Khi gặp một đoạn text chưa hiểu trên slide, tôi muốn được giải thích dựa trên chính đoạn đó và các nội dung liên quan trong bài giảng, để hiểu đầy đủ ý nghĩa của đoạn mà không phải tự tìm qua nhiều slide.

- **Job story 2 — Hỏi theo slide hiện tại:** Khi đặt câu hỏi mà không chọn một đoạn cụ thể, tôi muốn câu trả lời bám vào nội dung của slide đang mở và kết nối thêm các slide cần thiết, để hiểu vấn đề trong đúng bối cảnh của bài học.

- **Job story 3 — Tóm tắt nhiều slide:** Khi xem lại một chủ đề hoặc mục học trải dài qua nhiều slide, tôi muốn các ý chính được tổng hợp theo đúng mạch nội dung và có nguồn slide, để không phải tự lật và ghép từng phần kiến thức.

- **Job story 4 — Kiểm tra độ tin cậy:** Khi nội dung bài giảng không cung cấp đủ thông tin để trả lời, tôi muốn được thông báo rõ phần nào còn thiếu hoặc phụ thuộc vào hình ảnh, để không hiểu nhầm một câu trả lời suy đoán là kiến thức trong tài liệu.

### 1.3 Problem statement

Học viên đang học hoặc xem lại bài giảng thường chỉ có ngữ cảnh từ slide hiện tại hoặc đoạn text đang được chọn, trong khi nhiều khái niệm được giải thích xuyên suốt qua nhiều slide. Vì vậy, học viên phải tự tìm kiếm, nối các ý và kiểm tra nguồn, dễ bỏ sót nội dung quan trọng, mất thời gian và bị gián đoạn mạch học. Khi thông tin chỉ tồn tại trong hình ảnh hoặc không có trong phần text của tài liệu, học viên cũng cần được thông báo rõ thay vì nhận một câu trả lời không đủ căn cứ.
### 1.4 Evidence

**Đường bằng chứng sử dụng:** B — mining chatlog

#### Mining dữ liệu

- **Nguồn dữ liệu:** `data/vlearn-pack/chatlog/chat_history_anonymized_for_hackathon.csv`.
- **Quy mô mẫu:** 2.522 dòng tin nhắn, ghép thành 1.261 lượt hỏi-đáp học viên/tutor.
- **Phương pháp đếm:** Tách câu hỏi học viên khỏi wrapper “đoạn được chọn”, rồi đánh dấu lượt có phạm vi nhiều slide/rộng (ví dụ: toàn bộ slide/tài liệu/buổi học, dải trang/slide) hoặc ý định tổng hợp rộng (tóm tắt, nội dung chính, ý chính, tổng quan). Loại các yêu cầu không phục vụ học tập như tải file, mã hóa base64 hoặc chép nguyên văn toàn bộ tài liệu.
- **Kết quả đếm:** 71 / 1.261 = 5,6% lượt hỏi-đáp là bằng chứng mạnh cho nhu cầu ngữ cảnh nhiều slide/multi-context. Trong nhóm này, 34 / 71 = 47,9% phản hồi của tutor được phân loại là lỗi truy xuất hoặc vượt phạm vi tóm tắt.
- **Log / script / bảng evidence:** `data/vlearn-pack/chatlog/multi_slide_context_analysis.md` và `data/vlearn-pack/chatlog/multi_slide_context_evidence.csv`.

#### Ví dụ nguyên văn (ít nhất 5)

| # | Quote/ví dụ nguyên văn | Nguồn (conversation/row/link) | Pattern/pain được chứng minh |
|---|---|---|---|
| 1 | “Giúp tôi viết summary chi tiết và đầy đủ nhất về toàn bộ slide bài giảng ngày hôm nay” | `E001` · lượt `T0541` | Nhu cầu tóm tắt toàn bộ slide, không phải một trang đơn lẻ. |
| 2 | “tóm tắt toàn bộ slide sau đó đưa ra các ý chính” | `E002` · lượt `T0699` | Nhu cầu tổng hợp và xác định ý chính trên phạm vi toàn bộ slide. |
| 3 | “tóm tắt tất cả slide” | `E004` · lượt `T0213` | Nhu cầu tổng hợp phạm vi rộng; tutor không thể tự động tổng hợp toàn bộ trong một lần. |
| 4 | “tóm tắt cho t tất cả từ trang 1 đến trang 44 bài này học về gì” | `E010` · lượt `T1164` | Nhu cầu hiểu một tài liệu qua dải 44 trang; tutor báo không truy xuất được tóm tắt tổng thể. |
| 5 | “Hãy giải thích slide 21 đến slide 32. Hướng dẫn tôi chi tiết cách hoàn thành bài lab và cách nộp” | `E016` · lượt `T1027` | Nhu cầu giải thích một dải slide liên tiếp; tutor không tìm được nội dung chi tiết của các slide trong dải. |

---

## §2. Impact & quyết định chọn

### 2.1 Bảng impact: ít nhất 3 ứng viên

| Ứng viên | Bao nhiêu người gặp (trích evidence) | Tần suất | Tốn gì mỗi lần (phút / điểm / niềm tin) | Khả thi trong sự kiện | Điểm/nhận định | Chọn? |
|---|---|---|---|---|---|---|
| [Ứng viên 1] | [ ] | [ ] | [ ] | [ ] | [ ] | [ ] |
| [Ứng viên 2] | [ ] | [ ] | [ ] | [ ] | [ ] | [ ] |
| [Ứng viên 3] | [ ] | [ ] | [ ] | [ ] | [ ] | [ ] |

### 2.2 Ứng viên đã loại

| Ứng viên | Lý do loại (dựa trên bằng chứng / impact / tính khả thi) |
|---|---|
| [ ] | [ ] |
| [ ] | [ ] |

### 2.3 Ứng viên được chọn

- **Ứng viên chọn:** [ ]
- **Lý do chọn bằng số:** [Bao nhiêu người gặp x tần suất x chi phí mỗi lần; nêu rõ số liệu từ §1.]
- **Vì sao chọn thay vì ứng viên gần nhất:** [Bằng chứng mạnh hơn / impact cao hơn / khả thi hơn như thế nào?]

---

## §3. Giải pháp tương tự đã nghiên cứu

*Gợi ý: Mỗi thành viên nên trực tiếp dùng thử ít nhất một sản phẩm gần bài toán. Viết quan sát về flow cụ thể, không nhận xét chung kiểu “giao diện đẹp”.*

| Sản phẩm | Flow họ giải job này | Điều đáng học | Điều đáng né | Nhóm khác gì ở lát cắt này | Người nghiên cứu |
|---|---|---|---|---|---|
| [Sản phẩm 1] | [ ] | [ ] | [ ] | [ ] | [ ] |
| [Sản phẩm 2] | [ ] | [ ] | [ ] | [ ] | [ ] |
| [Sản phẩm 3] | [ ] | [ ] | [ ] | [ ] | [ ] |

---

## §4. Thiết kế

### 4.1 Lát cắt một câu

[Một user cụ thể] dùng [tính năng] để [một việc], AI đưa ra [một quyết định AI], nhằm đạt [một kết quả].

*Tự kiểm: phải đúng “1 user · 1 việc · 1 quyết định AI · 1 kết quả”.*

### 4.2 Phạm vi

- **Trong phạm vi build:** [Luồng/chức năng tối thiểu để demo được lát cắt.]
- **Non-goals 1:** [Thứ không build.] 
- **Non-goals 2:** [Thứ không build.] 
- **Non-goals 3:** [Thứ không build.] 

### 4.3 Mức prototype và phần thật/phần mock

- **Mức prototype:** [ ] Sketch  [ ] Mock  [ ] Working
- **AI call chạy thật ở quyết định trung tâm:** [Mô tả ngắn.] 
- **Phần chạy thật:** [ ]
- **Phần mock / data giả:** [ ]
- **Giới hạn kỹ thuật đã biết:** [ ]

### 4.4 Automation và cost-of-error

- **Mức automation:** [ ] Augment  [ ] Conditional  [ ] Automate
- **Quy tắc chuyển case (nếu conditional):** [Case nào tự xử lý; case nào hỏi lại/chuyển người.] 
- **Lý do theo cost-of-error:** Nếu sai, [ai] chịu [hậu quả]; việc sửa [rẻ/đắt] vì [lý do]. Do đó chọn [mức automation].

### 4.5 Nguyên tắc HAX/PAIR đã áp dụng (ít nhất 4)

*Bắt buộc có G10 và ít nhất một trong G8/G9/G11. Mỗi nguyên tắc phải trỏ vào màn hình, trạng thái hoặc hành vi cụ thể trong prototype.*

| Nguyên tắc | Vị trí/hành vi áp dụng cụ thể trong prototype | Cách người dùng nhìn thấy hoặc dùng được |
|---|---|---|
| G1 — Làm rõ hệ thống làm được gì | [ ] | [ ] |
| G2 — Làm rõ hệ thống làm tốt đến đâu | [ ] | [ ] |
| G10 — Thu hẹp phạm vi khi nghi ngờ | [ ] | [ ] |
| G8/G9/G11 — Gạt bỏ / sửa / giải thích | [ ] | [ ] |
| [Nguyên tắc bổ sung] | [ ] | [ ] |

---

## §5. Kiểu lỗi — bốn lớp chỗ khó và kịch bản

### 5.1 Bốn lớp chỗ khó

| Lớp | Câu hỏi cần trả lời cho lát cắt | Rủi ro đặc thù của nhóm |
|---|---|---|
| ① Nguồn sự thật | AI có thể bịa ở đâu? Không có căn cứ thì làm gì? | [ ] |
| ② Mơ hồ / thiếu thông tin | Input thiếu chắc thì hỏi lại, nêu giả định hay từ chối? | [ ] |
| ③ Ngoài phạm vi / thẩm quyền | User có thể đòi điều gì feature không được phép làm? | [ ] |
| ④ Đặc thù domain | Sai điều gì sẽ làm học sai, mất điểm hoặc mất niềm tin? | [ ] |

### 5.2 Kịch bản rủi ro (ít nhất 8, mỗi lớp ít nhất 2)

| # | Tình huống cụ thể | Lớp | Hành vi mong muốn: nói gì / hiện gì / bước tiếp theo | Nguyên tắc áp dụng | Golden-set case |
|---|---|---|---|---|---|
| 1 | [ ] | ① | [ ] | [ ] | [ ] |
| 2 | [ ] | ① | [ ] | [ ] | [ ] |
| 3 | [ ] | ② | [ ] | [ ] | [ ] |
| 4 | [ ] | ② | [ ] | [ ] | [ ] |
| 5 | [ ] | ③ | [ ] | [ ] | [ ] |
| 6 | [ ] | ③ | [ ] | [ ] | [ ] |
| 7 | [ ] | ④ | [ ] | [ ] | [ ] |
| 8 | [ ] | ④ | [ ] | [ ] | [ ] |

- **Kịch bản đáng lo nhất khi demo:** [ ]
- **Vì sao:** [ ]

---

## §6. Bốn đường đi của trải nghiệm

| Đường đi | Trigger/input mẫu | Hành vi của hệ thống | Căn cứ / UI hiển thị | Việc user có thể làm tiếp |
|---|---|---|---|---|
| Happy path | [ ] | [ ] | [ ] | [ ] |
| Low-confidence (②) | [ ] | [ ] | [ ] | [ ] |
| Failure / không có căn cứ (①) | [ ] | [ ] | [ ] | [ ] |
| Correction — user sửa | [ ] | [ ] | [ ] | [ ] |
| Bị đòi ngoài phạm vi (③) | [ ] | [ ] | [ ] | [ ] |
| Case đặc thù domain (④) | [ ] | [ ] | [ ] | [ ] |

---

## §7. Kiểm thử

### 7.1 Chiều chất lượng và định nghĩa kiểm chứng được

*Gợi ý: Bắt đầu từ output thật. Mỗi chiều phải có điều kiện pass/fail hoặc thang điểm mô tả rõ; không dùng “trả lời tốt” chung chung.*

| Chiều chất lượng | Định nghĩa đạt có thể kiểm chứng | Cách chấm | Điều kiện fail cứng |
|---|---|---|---|
| Đúng và có căn cứ | [ ] | [ ] | [ ] |
| Đúng mức / dễ hiểu | [ ] | [ ] | [ ] |
| An toàn / đúng phạm vi | [ ] | [ ] | [ ] |
| [Chiều riêng của lát cắt] | [ ] | [ ] | [ ] |

### 7.2 Golden set

- **Đường dẫn file golden set:** `eval/[ten-file]`
- **Tổng số case:** [ ] (tối thiểu 20)
- **Cơ cấu:** [ ] case thường; [ ] case hiếm; [ ] case lớp ①; [ ] lớp ②; [ ] lớp ③; [ ] lớp ④.
- **Case lấy hoặc phát triển từ chatlog thật:** [ ] (tối thiểu 10)
- **Hai người chấm độc lập 5 case khó:** [Tên 1] và [Tên 2]; kết quả/điều chỉnh rubric: [ ].

| Case ID | Loại case | Input | Kết quả mong đợi / rubric | Lớp rủi ro | Nguồn |
|---|---|---|---|---|---|
| [C01] | [Thường/hiếm] | [ ] | [ ] | [ ] | [ ] |
| [C02] | [ ] | [ ] | [ ] | [ ] | [ ] |
| [C03] | [ ] | [ ] | [ ] | [ ] | [ ] |

### 7.3 Quality bar (chốt trước khi đo)

> **Quality bar:** Đạt khi >= [ ]% case qua toàn bộ tiêu chí, và [điều kiện cứng, ví dụ: không có case nào bịa nguồn / không vượt thẩm quyền].

- **Thời điểm chốt:** [dd/mm/yyyy hh:mm]
- **Người xác nhận:** [ ]
- **Cam kết:** Không sửa quality bar sau thời điểm chốt; nếu thay đổi định nghĩa chấm, ghi rõ trong changelog cùng lý do và ảnh hưởng.

### 7.4 Kết quả các lượt chạy

| Lượt chạy | Thời điểm | Phiên bản prompt/prototype | Số case đạt / tổng | Tỷ lệ | Failure chính | Thay đổi sau lượt chạy |
|---|---|---|---|---|---|---|
| 1 | [ ] | [ ] | [ ] | [ ]% | [ ] | [ ] |
| 2 | [ ] | [ ] | [ ] | [ ]% | [ ] | [ ] |
| 3 | [ ] | [ ] | [ ] | [ ]% | [ ] | [ ] |

---

## §8. Phân công & kế hoạch

### 8.1 Phân công có tên

| Hạng mục | Người phụ trách | Deliverable / đường dẫn | Trạng thái |
|---|---|---|---|
| Spec | [ ] | [ ] | [ ] |
| Evidence | [ ] | [ ] | [ ] |
| Prompt / AI behavior | [ ] | [ ] | [ ] |
| Code / prototype | [ ] | [ ] | [ ] |
| Demo / slides | [ ] | [ ] | [ ] |

### 8.2 Willing users và validation CP5

| Người thử (tên/vai) | Willing user? | Task thật giao cho họ | Người quan sát/log | Thời điểm |
|---|---|---|---|---|
| [ ] | [Có/Không] | [ ] | [ ] | [ ] |
| [ ] | [Có/Không] | [ ] | [ ] | [ ] |
| [ ] | [Có/Không] | [ ] | [ ] | [ ] |

- **Mục tiêu validation:** Ít nhất 5 người ngoài nhóm; ưu tiên 3 willing users đã nêu ở CP1.
- **Đường dẫn feedback log:** `validation/[ten-file]`
- **Ba câu hỏi sau khi họ làm task:**
  1. Điều gì khó hiểu hoặc khó chịu nhất?
  2. Bạn có tin kết quả này không? Vì sao?
  3. Bạn có dùng thật không? Vì sao / vì sao chưa?
- **Cách ghi nhận:** Quan sát im lặng khi người thử làm task; lưu hành vi, quote nguyên văn và mức nghiêm trọng.

### 8.3 Multi-prototype (nếu thực hiện)

| Phương án | Trục khác biệt có tên | Điều đã thử | Kết quả/bằng chứng | Chọn hay loại và vì sao |
|---|---|---|---|---|
| A | [Ví dụ: hỏi trước vs làm luôn] | [ ] | [ ] | [ ] |
| B | [Cùng trục ở phương án A] | [ ] | [ ] | [ ] |

---

## §9. Changelog

| Thời điểm | Đổi gì | Vì sao (trỏ về feedback/case/evidence nào) | Ai thực hiện |
|---|---|---|---|
| [ ] | [ ] | [ ] | [ ] |
| [ ] | [ ] | [ ] | [ ] |
| [ ] | [ ] | [ ] | [ ] |

---

## Checklist tự soát trước CP4/nộp

- [ ] Đủ §1 đến §9.
- [ ] Evidence đạt chuẩn A và/hoặc B, có log đầy đủ và ít nhất 5 quote/ví dụ nguyên văn.
- [ ] Bảng impact có ít nhất 3 ứng viên, kèm ứng viên bị loại và lý do.
- [ ] Lát cắt là một câu: 1 user · 1 việc · 1 quyết định AI · 1 kết quả.
- [ ] Có ít nhất 3 non-goals; nêu rõ phần thật và phần mock.
- [ ] Chọn automation bằng cost-of-error, không chỉ vì tiện.
- [ ] Có ít nhất 4 nguyên tắc HAX/PAIR, gồm G10 và ít nhất một trong G8/G9/G11.
- [ ] Có ít nhất 8 kịch bản lỗi, đủ 4 lớp và mỗi lớp ít nhất 2 case.
- [ ] Golden set có ít nhất 20 case, ít nhất 10 case lấy/phát triển từ chatlog thật.
- [ ] Quality bar theo % và điều kiện cứng đã chốt trước 23:59 N1.
- [ ] Có log validation ít nhất 5 người ngoài nhóm và changelog trỏ về feedback/case.
