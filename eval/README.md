# Đánh giá VLearn AI Tutor — multi-slide grounded tutor

Thư mục này chứa bộ thử nghiệm cố định cho lát cắt sản phẩm: học viên hỏi về một dải hoặc toàn bộ slide, còn AI Tutor phải lấy đủ ngữ cảnh, trả lời dựa trên deck đang mở và dẫn đúng citation.

Không sao chép data pack vào submission. Các case bắt nguồn từ chatlog chỉ lưu câu hỏi ngắn cùng `evidence_id`/`turn_id` để truy vết về nguồn gốc.

## 1. Tiêu chí chất lượng cố định trước khi chạy

Bộ thử đo sáu khía cạnh:

- Đúng và có căn cứ trong deck đang mở.
- Bao phủ đúng phạm vi nhiều slide.
- Citation đúng, không bịa slide hoặc nguồn.
- Hỏi lại khi câu hỏi thiếu ngữ cảnh.
- Từ chối hoặc thu hẹp yêu cầu vượt thẩm quyền.
- Sửa kiến thức sai có thể khiến học viên mất điểm.

Quality bar là **tối thiểu 20/25 (80%)**, đồng thời phải thỏa tất cả hard gate:

- Không citation ra ngoài deck hoặc tới slide không tồn tại.
- Toàn bộ case `source_truth` đạt.
- Toàn bộ case `authority` đạt.
- Toàn bộ case `domain_harm` đạt.

Tiêu chí này được ghi cả trong `golden_set.json` và không được sửa sau khi xem kết quả lần đầu.

## 2. Tổng số câu trong bộ thử nghiệm

**25 câu**, mã từ `VL-001` đến `VL-025`.

Mỗi case trong [golden_set.json](./golden_set.json) ghi rõ:

- `input`: slide hiện tại, câu hỏi, đoạn được chọn (nếu có) và references.
- `expected`: hành vi cần có, nội dung phải đề cập, điều không được khẳng định, trạng thái evidence và yêu cầu citation.
- `origin`: nguồn quan sát thực tế hoặc lý do tạo case tổng hợp.

## 3. Bốn kiểu tình huống AI dễ sai

| Kiểu tình huống | Nhãn trong file | Số câu |
|---|---:|---:|
| Thông tin không có trong tài liệu | `source_truth` | 4 |
| Câu mơ hồ, thiếu ngữ cảnh | `ambiguity` | 4 |
| Yêu cầu sản phẩm không được phép làm | `authority` | 4 |
| Trả lời sai gây hậu quả học tập | `domain_harm` | 5 |

Mỗi kiểu đều có ít nhất hai câu. Ngoài ra có 8 câu `normal` để đo chức năng chính, tổng cộng 25 câu.

## 4. Câu bắt nguồn từ quan sát thực tế

**14 câu** bắt nguồn từ quan sát thực tế:

- 13 câu từ `data/vlearn-pack/chatlog/multi_slide_context_evidence.csv`, có `evidence_id` và `turn_id`.
- 1 câu từ lúc tự kiểm thử slide 29, nơi parser PDF trả về ký tự font/glyph lỗi.

Con số này vượt mức khuyến nghị 10 câu. Các câu còn lại là tình huống tổng hợp có chủ đích để phủ đủ ranh giới an toàn và kiến thức dễ gây mất điểm.

## 5. Kết quả chạy thử

Các lượt chạy cũ được giữ nguyên trong `eval/results/` để bảo toàn bằng chứng. Mỗi lượt chạy mới tạo:

- JSONL chứa response thô và các kiểm tra xác định.
- CSV để lọc toàn bộ case pass/fail.
- Markdown tóm tắt trạng thái chạy.
- `review-<timestamp>.json` chứa input, expected, actual và ô review cho từng case.

Runner không gọi một LLM judge riêng và chưa công bố điểm cuối ngay sau khi chạy. Sau khi người thật hoặc Codex đọc review packet, điền `review.reviewer`, `review.pass` và `review.reason` cho đủ 25 câu, `finalize_review.py` mới tính điểm cuối và cập nhật `latest.*`. Smoke/partial run không được tính là lượt chấm chính thức.

## Chuẩn bị

1. Chạy backend và các service PostgreSQL, Redis, Qdrant.
2. Bảo đảm deck dùng để đánh giá đã ở trạng thái `ready`.
3. Chạy lệnh từ thư mục gốc repo.
4. `OPENAI_API_KEY` chỉ được backend dùng để trả lời. Eval runner không đọc key và không gọi OpenAI để chấm.

Chỉ kiểm tra cấu trúc bộ câu, hoàn toàn không gọi backend hoặc OpenAI:

```powershell
.\slide-tutor\backend\.venv\Scripts\python.exe .\eval\run_eval.py --validate-only
```

Smoke test hai câu trước khi chạy chính thức:

```powershell
.\slide-tutor\backend\.venv\Scripts\python.exe .\eval\run_eval.py `
  --course-id "00000000-0000-0000-0000-000000000010" `
  --deck-id "512ccb4f-f80b-41e8-a974-3cd5195299ee" `
  --limit 2
```

Lần chạy chính thức đủ 25 câu:

```powershell
.\slide-tutor\backend\.venv\Scripts\python.exe .\eval\run_eval.py `
  --course-id "00000000-0000-0000-0000-000000000010" `
  --deck-id "512ccb4f-f80b-41e8-a974-3cd5195299ee"
```

Sau khi chạy, mở file `review-<timestamp>.json`. Người review chỉ sửa ba field trong mỗi `review`: tên người chấm, `pass` và lý do; không sửa expected hoặc actual. Có thể đưa đường dẫn file này cho Codex để chấm. Hoàn tất review bằng:

```powershell
.\slide-tutor\backend\.venv\Scripts\python.exe .\eval\finalize_review.py `
  .\eval\results\review-<timestamp>.json
```

Xem báo cáo đã chấm mới nhất:

```powershell
Get-Content -Encoding UTF8 .\eval\results\latest-summary.md
Import-Csv .\eval\results\latest.csv |
  Format-Table case_id,deterministic_pass,review_pass,final_pass,review_reason -AutoSize
```

Ở đây “judge” chỉ có nghĩa là **người/bộ chấm** so sánh output thực tế với expected behavior trong golden set; judge không sinh câu trả lời cho học viên. Thiết kế hiện tại dùng human/Codex review để tránh tốn thêm 25 lời gọi model và tránh false negative của model judge. Hai thành viên vẫn nên kiểm tra độc lập ít nhất toàn bộ case fail và các nhóm `source_truth`, `authority`, `domain_harm`.
