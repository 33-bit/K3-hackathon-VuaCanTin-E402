# Slide Tutor backend

Backend RAG cho Slide Tutor, dùng:

- PostgreSQL làm nguồn dữ liệu chuẩn cho deck, version, slide, chunk, quyền và hội thoại.
- Qdrant làm chỉ mục retrieval có thể dựng lại: dense vector + BM25 sparse + RRF.
- Redis chỉ làm cache; job và outbox luôn nằm trong PostgreSQL.
- OpenAI `text-embedding-3-large` (1536 chiều), GPT-4o và GPT-4o mini.

Frontend không nằm trong phạm vi của thư mục này.

## Chạy nhanh bằng Docker

Yêu cầu: Docker Desktop đang chạy, Docker Compose v2 và một OpenAI API key.

Trong PowerShell:

```powershell
Copy-Item .env.example .env
notepad .env
docker compose up --build -d
docker compose ps
```

Trong `.env`, tối thiểu phải thay:

```dotenv
OPENAI_API_KEY=sk-...
QDRANT_API_KEY=mot-chuoi-ngau-nhien-dai
```

Nếu máy đã có PostgreSQL hoặc Redis dùng cổng mặc định, chỉ đổi các cổng publish
trên host; URL nội bộ `postgres:5432` và `redis:6379` vẫn giữ nguyên:

```dotenv
POSTGRES_PORT=55432
REDIS_PORT=6380
```

Compose sẽ chạy theo thứ tự:

1. PostgreSQL sẵn sàng và `migrate` chạy `alembic upgrade head`.
2. `api` và `worker` bắt đầu mà không chờ Redis/Qdrant.
3. Worker vẫn parse/chunk vào PostgreSQL khi Qdrant tạm lỗi; vector outbox
   tiếp tục khi Qdrant phục hồi. `/api/ready` chỉ trả `ready` khi cả ba
   dependency hợp lệ.

Kiểm tra:

```powershell
Invoke-RestMethod http://127.0.0.1:8000/api/health
Invoke-RestMethod http://127.0.0.1:8000/api/ready
docker compose logs -f api worker
```

Swagger UI ở `http://127.0.0.1:8000/docs`.

Qdrant chỉ được publish tại `127.0.0.1:6333`, không nghe trên IP mạng
ngoài. Dữ liệu Qdrant dùng Docker named volume `qdrant_storage`, tránh
bind-mount thư mục Windows vào `/qdrant/storage`.

## Biến môi trường

| Biến | Giá trị MVP |
|---|---|
| `API_PORT` | Cổng API publish trên host, mặc định `8000` |
| `POSTGRES_PORT` | Cổng PostgreSQL publish trên host, mặc định `5432` |
| `REDIS_PORT` | Cổng Redis publish trên host, mặc định `6379` |
| `QDRANT_PORT` | Cổng Qdrant publish trên host, mặc định `6333` |
| `DATABASE_URL` | PostgreSQL async URL |
| `REDIS_URL` | Redis URL |
| `QDRANT_URL` | `http://qdrant:6333` trong Compose |
| `QDRANT_API_KEY` | Khóa admin Qdrant, không commit |
| `QDRANT_COLLECTION_ALIAS` | `slide_chunks` |
| `QDRANT_PHYSICAL_COLLECTION` | `slide_chunks_te3large_1536_bm25_v1` |
| `OPENAI_API_KEY` | Khóa OpenAI, không commit |
| `OPENAI_EMBEDDING_MODEL` | `text-embedding-3-large` |
| `OPENAI_EMBEDDING_DIMENSIONS` | `1536` |
| `EMBEDDING_VERSION` | `te3large_1536_v1` |
| `RETRIEVAL_SCHEMA_VERSION` | `qdrant_bm25_rrf_v1` |
| `OPENAI_ANSWER_MODEL` | `gpt-4o-2024-08-06` |
| `OPENAI_FAST_MODEL` | `gpt-4o-mini-2024-07-18` |
| `AUTH_PROXY_SHARED_SECRET` | Bắt buộc ngoài development |
| `UPLOAD_DIR` | `data/uploads` |
| `QUERY_UNDERSTANDING_CACHE_TTL_SECONDS` | `3600` |
| `RECONCILE_INTERVAL_SECONDS` | `900` |
| `OLD_VECTOR_RETENTION_SECONDS` | `3600` |

`.env.example` chứa URL theo tên service của Compose. Nếu chạy Python trực
tiếp trên máy, đặt lại host thành `localhost`.

Các giá trị PostgreSQL mặc định của Compose là
`slide_tutor/slide_tutor/slide_tutor`. Có thể đổi bằng `POSTGRES_USER`,
`POSTGRES_PASSWORD`, `POSTGRES_DB`; khi đổi phải cập nhật `DATABASE_URL`
tương ứng.

## Chạy trực tiếp trên máy

Python 3.12 được khuyến nghị. PostgreSQL, Redis và Qdrant vẫn có thể chạy bằng
Docker:

```powershell
docker compose up -d postgres redis qdrant
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements-dev.txt

$env:DATABASE_URL = "postgresql+asyncpg://slide_tutor:slide_tutor@localhost:5432/slide_tutor"
$env:REDIS_URL = "redis://localhost:6379/0"
$env:QDRANT_URL = "http://localhost:6333"

alembic upgrade head
uvicorn app.main:app --reload
```

Mở terminal thứ hai, kích hoạt cùng virtual environment và chạy worker:

```powershell
python -m app.worker
```

Không bật `AUTO_CREATE_SCHEMA` trong môi trường dùng lâu dài; Alembic là
đường nâng cấp schema chính thức.

## Luồng dữ liệu

Upload trả `202 Accepted`. API lưu source file và tạo `deck_version` cùng
`ingestion_job` trong PostgreSQL. Worker parse, normalize và chunk tài liệu,
sau đó commit chunk canonical và event `vector_outbox` trong một transaction.

Index worker:

- embed theo batch 64;
- upsert dense vector và văn bản BM25 vào Qdrant với `wait=true`;
- đối soát toàn bộ `chunk_id:content_hash`;
- chỉ chuyển version sang `ready` và active khi parity đạt 100%.

Compose chạy một worker cho MVP. Nếu scale nhiều worker, cần bổ sung heartbeat
lease cho job dài trước khi giảm `WORKER_LOCK_TIMEOUT_SECONDS`.

Trong chat, PostgreSQL kiểm quyền và khóa `active_version_id` cho request.
Qdrant chạy dense + BM25 prefetch với filter
`course_id + deck_id + deck_version_id`, fuse bằng RRF. Text citation luôn
được hydrate lại từ PostgreSQL và kiểm `content_hash`; Qdrant không lưu full
chunk text.

## API

| Method | Endpoint | Mục đích |
|---|---|---|
| `POST` | `/api/decks` | Upload PDF/PPTX |
| `GET` | `/api/decks/{deck_id}/status` | Trạng thái version/index |
| `POST` | `/api/decks/{deck_id}/reindex` | Tạo version mới để reindex |
| `GET` | `/api/decks/{deck_id}/slides` | Slide canonical của active version |
| `POST` | `/api/chat/answer` | Hỏi đáp có citation |
| `POST` | `/api/chat/feedback` | Gửi feedback cho message |
| `GET` | `/api/debug/retrieval/{id}` | Debug retrieval có kiểm quyền |
| `GET` | `/api/health` | Liveness, không kiểm dependency |
| `GET` | `/api/ready` | PostgreSQL + Redis + Qdrant schema/alias/index |

Trong development, nếu không gửi `X-User-Id`, API dùng `DEV_USER_ID`.
`DEV_COURSE_ID` mặc định là
`00000000-0000-0000-0000-000000000010`. Đây chỉ là cơ chế phát triển, không
phải authentication cho production.

Ngoài development, API chỉ chấp nhận `X-User-Id` khi request còn có
`X-Auth-Proxy-Secret` khớp `AUTH_PROXY_SHARED_SECRET`. Reverse proxy phải
chạy trên private upstream/TLS và phải xóa rồi tự ghi đè cả hai header này;
không chuyển tiếp giá trị do browser gửi. Đây là integration point cho auth
gateway của MVP, không thay thế JWT/session verification ở một API public
trực tiếp.

### Upload và chờ ready

```powershell
$courseId = "00000000-0000-0000-0000-000000000010"
$accepted = curl.exe --silent --request POST `
  "http://127.0.0.1:8000/api/decks" `
  --form "course_id=$courseId" `
  --form "title=RAG căn bản" `
  --form "file=@C:\duong-dan\slides.pdf" | ConvertFrom-Json

$accepted
Invoke-RestMethod `
  "http://127.0.0.1:8000/api/decks/$($accepted.deck_id)/status"
```

Khi `status=ready` và `index_status=in_sync`, lấy slide:

```powershell
$slides = Invoke-RestMethod `
  "http://127.0.0.1:8000/api/decks/$($accepted.deck_id)/slides"
$slides.slides
```

### Chat

```powershell
$chatBody = @{
  course_id = $courseId
  deck_id = $accepted.deck_id
  current_slide_id = $slides.slides[0].id
  question = "Hãy giải thích ý chính của slide này"
  language = "vi"
  references = @()
} | ConvertTo-Json -Depth 5

$answer = Invoke-RestMethod `
  -Method Post `
  -Uri "http://127.0.0.1:8000/api/chat/answer" `
  -ContentType "application/json" `
  -Body $chatBody
$answer
```

### Feedback và retrieval debug

```powershell
$feedbackBody = @{
  message_id = $answer.message_id
  rating = "helpful"
  comment = "Citation đúng slide."
} | ConvertTo-Json

Invoke-RestMethod `
  -Method Post `
  -Uri "http://127.0.0.1:8000/api/chat/feedback" `
  -ContentType "application/json" `
  -Body $feedbackBody

Invoke-RestMethod `
  "http://127.0.0.1:8000/api/debug/retrieval/$($answer.retrieval_debug_id)"
```

Các lỗi retrieval quan trọng:

- `deck_not_ready` và `stale_slide_context`: HTTP 409.
- `vector_index_unavailable`, `vector_index_inconsistent` và
  `embedding_provider_unavailable`: HTTP 503.

API fail closed khi Qdrant thiếu point hoặc hash lệch; không fallback sang
deck/version khác.

## Migration database

```powershell
docker compose run --rm migrate
docker compose run --rm migrate alembic current
docker compose run --rm migrate alembic history
```

Khi phát triển schema:

```powershell
alembic revision --autogenerate -m "mo ta thay doi"
alembic upgrade head
```

Luôn review migration sinh tự động trước khi commit.

## Đối soát và repair chỉ mục

Worker tự reconcile khi khởi động và mỗi 15 phút. Có thể chạy thủ công:

```powershell
docker compose exec api python -m scripts.reconcile_index
```

Kiểm một version:

```powershell
docker compose exec api python -m scripts.reconcile_index `
  --deck-version-id 00000000-0000-0000-0000-000000000000
```

Lệnh mặc định chỉ đọc và trả exit code `2` nếu lệch. Muốn đánh dấu version
`drifted` và enqueue event index idempotent:

```powershell
docker compose exec api python -m scripts.reconcile_index --enqueue-repair
```

## Rebuild collection và alias migration

Đổi embedding dimension/model hoặc BM25 schema phải dùng physical collection
mới, không sửa collection đang phục vụ. Script sau:

1. bootstrap collection và payload index;
2. backfill tất cả active version;
3. verify từng manifest và tổng point count;
4. kiểm lại active version không đổi trong lúc backfill;
5. nếu được yêu cầu, snapshot collection cũ rồi atomic alias switch;
6. ghi rollback metadata vào `data/qdrant-migrations` (named volume
   `migration_records` khi chạy Compose).

Backfill và verify trước, chưa switch:

```powershell
docker compose exec api python -m scripts.rebuild_collection `
  --new-collection slide_chunks_te3large_1536_bm25_v2
```

Sau khi review kết quả, verify lại mà không tốn embedding và switch:

```powershell
docker compose exec api python -m scripts.rebuild_collection `
  --new-collection slide_chunks_te3large_1536_bm25_v2 `
  --verify-only `
  --switch-alias
```

Ngay sau alias switch:

1. đổi `QDRANT_PHYSICAL_COLLECTION` trong `.env` sang collection mới để
   bootstrap/restore sau này dùng đúng target (runtime hiện tại vẫn resolve
   collection phục vụ qua alias);
2. recreate `api` và `worker`;
3. kiểm `/api/ready` và chạy `scripts.reconcile_index`;
4. giữ collection cũ tối thiểu 24 giờ để rollback.

```powershell
docker compose up -d --force-recreate api worker
Invoke-RestMethod http://127.0.0.1:8000/api/ready
docker compose exec api python -m scripts.reconcile_index
```

Script không xóa collection cũ. Nếu schema mới thay đổi dimension hoặc named
vector, code tạo schema và worker phải hỗ trợ schema mới trước khi chạy
migration.

## Test và kiểm tra chất lượng

Chạy local:

```powershell
.\.venv\Scripts\Activate.ps1
ruff check app tests scripts
ruff format --check app tests scripts
pytest -q
```

Test Qdrant thật (BM25 Việt/Anh, RRF, scope isolation, idempotency, snapshot
và alias rollback) chỉ chạy khi chủ động bật:

```powershell
$env:RUN_QDRANT_INTEGRATION = "1"
pytest -q -m integration
```

Chạy trong image development:

```powershell
docker compose --profile tools run --rm --build test
docker compose --profile tools run --rm test ruff check app tests scripts
```

Kiểm tra cấu hình Compose mà không khởi động container:

```powershell
docker compose config --quiet
```

## Backup, restore và bảo mật

- Backup bắt buộc: PostgreSQL, volume `uploads` và migration record trong
  volume `migration_records`.
- Qdrant snapshot giúp phục hồi nhanh và phải tạo trước migration/deploy quan
  trọng; Qdrant vẫn là index có thể dựng lại từ PostgreSQL + source file.
- Sau restore Qdrant, bootstrap lại alias và chạy reconciliation trước khi
  mở traffic.
- Không commit `.env`, OpenAI key hay Qdrant key.
- Qdrant self-hosted production cần private network, TLS và quản lý secret
  bên ngoài Compose.
- Redis không phải nguồn trạng thái job; container Redis trong Compose tắt
  persistence có chủ đích. Redis chỉ cache kết quả query-understanding theo
  model/schema với TTL; cache miss hoặc Redis outage không làm thay đổi dữ
  liệu chuẩn.

Xóa container nhưng giữ dữ liệu:

```powershell
docker compose down
```

`docker compose down --volumes` sẽ xóa PostgreSQL, Qdrant và source upload
trong named volume, vì vậy chỉ dùng khi chắc chắn muốn reset toàn bộ môi
trường local.
