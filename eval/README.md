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

## 5. Kết quả chạy thử lần đầu

**Trạng thái hiện tại: CHƯA CHẠY — chưa có điểm `x/25`.**

Không điền điểm giả. Lần chạy đầy đủ đầu tiên sẽ tạo bảng chứa đủ cả case đạt và case fail trong `eval/results/`, gồm:

- File JSONL giữ response và chi tiết kiểm tra của từng case.
- File CSV để lọc, review và nộp; có cột trống cho hai người review độc lập.
- File Markdown ghi kết quả `x/25`, điểm theo từng kiểu và danh sách case fail.
- `latest.csv` và `latest-summary.md` trỏ tới kết quả mới nhất.

Smoke/partial run không ghi đè `latest.*`. Sau lượt chạy đầy đủ đầu tiên có `--judge`, commit các file kết quả để trợ giảng kiểm tra được số thật.

## Chuẩn bị

1. Chạy backend và các service PostgreSQL, Redis, Qdrant.
2. Bảo đảm deck dùng để đánh giá đã ở trạng thái `ready`.
3. Chạy lệnh từ thư mục gốc repo.
4. Nếu dùng `--judge`, đặt `OPENAI_API_KEY` trong `slide-tutor/backend/.env`; không commit file `.env`.

Chỉ kiểm tra cấu trúc bộ câu, hoàn toàn không gọi backend hoặc OpenAI:

```powershell
.\slide-tutor\backend\.venv\Scripts\python.exe .\eval\run_eval.py --validate-only
```

Smoke test hai câu trước khi chạy chính thức:

```powershell
.\slide-tutor\backend\.venv\Scripts\python.exe .\eval\run_eval.py `
  --course-id "00000000-0000-0000-0000-000000000010" `
  --deck-id "512ccb4f-f80b-41e8-a974-3cd5195299ee" `
  --limit 2 `
  --judge
```

Lần chạy chính thức đủ 25 câu:

```powershell
.\slide-tutor\backend\.venv\Scripts\python.exe .\eval\run_eval.py `
  --course-id "00000000-0000-0000-0000-000000000010" `
  --deck-id "512ccb4f-f80b-41e8-a974-3cd5195299ee" `
  --judge
```

`--judge` dùng `gpt-4o-mini-2024-07-18` để chấm ý nghĩa sau các kiểm tra xác định như HTTP status và citation. Lệnh chính thức sẽ gọi endpoint answer 25 lần và judge 25 lần, nên có sử dụng OpenAI API và phát sinh chi phí nhỏ.

Xem báo cáo mới nhất:

```powershell
Get-Content -Encoding UTF8 .\eval\results\latest-summary.md
Import-Csv .\eval\results\latest.csv | Format-Table case_id,final_pass,reason -AutoSize
```

Kết quả judge tự động là hỗ trợ, không thay thế review. Hai thành viên nên kiểm tra độc lập ít nhất toàn bộ case fail và các nhóm `source_truth`, `authority`, `domain_harm`, sau đó ghi quyết định cuối vào bảng kết quả nếu cần.
