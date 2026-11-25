# Day 14 Lab — Mission Answers

---

## Part 1: Localhost vs Production

### Exercise 1.1: Anti-patterns tìm thấy trong `01-localhost-vs-production/develop/app.py`

1. **Hardcode secrets trực tiếp trong mã nguồn (dòng 17–18):** `OPENAI_API_KEY = "sk-hardcoded-fake-key-never-do-this"` và `DATABASE_URL = "postgresql://admin:password123@localhost:5432/mydb"`. Nếu push lên GitHub (nhất là repo public), secret bị lộ ngay lập tức và nằm vĩnh viễn trong lịch sử git.
   - *Cách `production/` đã sửa:* `production/config.py` dòng 27, 32 đọc từ biến môi trường (`os.getenv("OPENAI_API_KEY", "")`, `os.getenv("AGENT_API_KEY", "")`) và fail-fast nếu thiếu key ở môi trường production (dòng 42–43).
2. **In secret ra log và dùng `print()` thay cho structured logging (dòng 33–34, 38, 48):** Dòng 34 ghi `print(f"[DEBUG] Using key: {OPENAI_API_KEY}")` làm rò rỉ API key vào hệ thống log; `print()` dạng text thuần không có timestamp, log level hay cấu trúc JSON để lọc/tìm kiếm trên Datadog/Loki.
   - *Cách `production/` đã sửa:* `production/app.py` dòng 28–32 cấu hình `logging` định dạng JSON và dòng 111–122 chỉ log metadata (`event`, `question_length`, `client_ip`), tuyệt đối không log secret.
3. **Hardcode cấu hình và bật chế độ debug/reload trong code (dòng 21–22, 53):** `DEBUG = True`, `MAX_TOKENS = 500`, `reload=True`. Reload tự động tiêu tốn tài nguyên, không an toàn và gây gián đoạn khi chạy production.
   - *Cách `production/` đã sửa:* `production/config.py` dòng 19, 29 đọc `DEBUG` (mặc định `false`) và `MAX_TOKENS` từ env; `production/app.py` dòng 198 chỉ bật `reload` khi `settings.debug=True`.
4. **Không có endpoint health check (`/health`) và readiness (`/ready`) (dòng 42–43):** Khi container bị treo hoặc chưa nạp xong model/DB, cloud platform và load balancer không biết để khởi động lại hoặc ngừng đẩy traffic.
   - *Cách `production/` đã sửa:* `production/app.py` dòng 135–161 bổ sung `GET /health` (liveness) và `GET /ready` (readiness trả `503` nếu `not is_ready`).
5. **Bind cứng `host="localhost"` và cố định `port=8000` (dòng 51–52):** Chạy trong Docker container với `localhost` (`127.0.0.1`) sẽ không nhận được kết nối từ ngoài container; cố định cổng `8000` sẽ lỗi trên Railway/Render vốn cấp động cổng qua biến `PORT`.
   - *Cách `production/` đã sửa:* `production/config.py` dòng 17–18 mặc định `HOST=0.0.0.0` và đọc `PORT` từ env; `production/app.py` dòng 196–197 dùng `settings.host` và `settings.port`.
6. **Không có graceful shutdown / lifecycle management:** Khi nhận `SIGTERM` lúc deploy mới hoặc restart, process tắt đột ngột làm cắt ngang request đang xử lý và không kịp đóng kết nối DB/Redis.
   - *Cách `production/` đã sửa:* `production/app.py` dòng 39–67 dùng `lifespan` của FastAPI để quản lý startup/shutdown (đổi `is_ready = False`, chờ request hiện tại hoàn thành).
7. **Không kiểm soát CORS và nhận `question` qua query param không validate (dòng 30–31):** Truyền câu hỏi dài qua query string dễ bị lộ trong access log/URL, giới hạn độ dài URL và trả 422 khi client gửi JSON body.
   - *Cách `production/` đã sửa:* `production/app.py` dòng 77–82 cấu hình `CORSMiddleware` theo `ALLOWED_ORIGINS` và dòng 102–108 đọc JSON body có kiểm tra rỗng (`422`).

### Exercise 1.2: Chạy bản `develop` và kiểm chứng

Chạy `01-localhost-vs-production/develop/app.py` và gọi thử bằng `curl -i`:

```text
$ curl -i -X POST 'http://localhost:8000/ask?question=Hello'
HTTP/1.1 200 OK
date: Wed, 25 Nov 2026 09:29:57 GMT
server: uvicorn
content-length: 126
content-type: application/json

{"answer":"Đây là câu trả lời từ AI agent (mock). Trong production, đây sẽ là response từ OpenAI/Anthropic."}
```

Kiểm chứng lưu ý K5 (gửi JSON body vào bản develop sẽ bị `422` vì endpoint khai báo `question: str` là query param):

```text
$ curl -i -X POST http://localhost:8000/ask -H 'Content-Type: application/json' -d '{"question":"Hello"}'
HTTP/1.1 422 Unprocessable Entity
content-type: application/json

{"detail":[{"type":"missing","loc":["query","question"],"msg":"Field required","input":null}]}
```

Kết quả chạy bản `production` (`01-localhost-vs-production/production/app.py`):

```text
$ curl -sS http://localhost:8000/health
{"status":"ok","uptime_seconds":0.6,"version":"1.0.0","environment":"development","timestamp":"2026-11-25T09:29:59.185890+00:00"}

$ curl -sS http://localhost:8000/ready
{"ready":true}

$ curl -sS -X POST http://localhost:8000/ask -H 'Content-Type: application/json' -d '{"question":"Hello"}'
{"question":"Hello","answer":"Tôi là AI agent được deploy lên cloud. Câu hỏi của bạn đã được nhận.","model":"gpt-4o-mini"}
```

### Exercise 1.3: Bảng so sánh Develop vs Production

| Feature | Develop | Production | Tại sao quan trọng? |
|---|---|---|---|
| **Config & Secrets** | Hardcode `OPENAI_API_KEY`, `DATABASE_URL`, `DEBUG`, `PORT` trực tiếp trong `app.py` | Đọc toàn bộ từ biến môi trường qua `config.py` (`Settings` + `validate()`) | Tuân thủ 12-Factor App: cùng một artifact/image chạy được ở dev/staging/prod chỉ bằng cách đổi env vars; tránh rò rỉ secret vào Git; fail-fast nếu thiếu cấu hình bắt buộc. |
| **Health & Readiness Check** | Không có `/health` và `/ready` | Có `GET /health` (liveness) và `GET /ready` (readiness trả `503` khi chưa sẵn sàng) | Cloud orchestrator cần `/health` để tự restart container bị treo và load balancer cần `/ready` để không đẩy traffic vào instance đang khởi động hoặc mất kết nối dependency. |
| **Logging** | `print()` text thuần, thậm chí in cả `OPENAI_API_KEY` | Structured JSON logging qua `logging`, tuyệt đối không in secret | Log JSON giúp hệ thống tập trung (Loki, Datadog, Cloud Logging) dễ parse, lọc theo field (`event`, `status`, `ms`) và không làm lộ credential. |
| **Shutdown** | Tắt đột ngột, không có cleanup | Quản lý lifecycle bằng `lifespan` + chuẩn bị graceful shutdown | Khi rolling deploy hoặc scale down, server ngừng nhận request mới, hoàn thành request đang chạy (in-flight) và đóng kết nối DB/Redis sạch sẽ để không mất dữ liệu hay trả lỗi 502 cho user. |
| **Host / Port Binding** | `host="localhost"`, `port=8000`, `reload=True` | `host="0.0.0.0"`, đọc `PORT` từ env, `reload=settings.debug` | Container cần lắng nghe trên `0.0.0.0` mới nhận được traffic từ bên ngoài; cloud PaaS cấp cổng động qua biến `PORT`; tắt `reload` ở production để đảm bảo hiệu năng và ổn định. |
| **CORS & Input Validation** | Không có CORS, nhận `question` qua query param | `CORSMiddleware` cấu hình theo `ALLOWED_ORIGINS`, đọc JSON body và validate | Kiểm soát domain gọi API trên trình duyệt, tránh lộ câu hỏi trong URL/access logs và trả mã lỗi `422` rõ ràng khi dữ liệu đầu vào sai. |

---

## Part 2: Docker

### Exercise 2.1: Câu hỏi về `02-docker/develop/Dockerfile`

1. **Base image là gì?** `python:3.11` (bản Debian đầy đủ kèm Python runtime và nhiều công cụ hệ thống, nặng ~1 GB; trong khi bản production dùng `python:3.11-slim` gọn nhẹ hơn nhiều).
2. **Working directory là gì?** `/app` (`WORKDIR /app` — thư mục làm việc mặc định trong container, mọi lệnh `COPY`, `RUN`, `CMD` sau đó đều chạy tương đối tại `/app`).
3. **Tại sao `COPY requirements.txt` đứng trước `COPY app.py` / `COPY . .`?** Nhờ cơ chế **Docker layer caching**: mỗi lệnh trong Dockerfile tạo một layer và nếu một layer thay đổi thì toàn bộ các layer phía sau phải build lại. `requirements.txt` ít thay đổi hơn source code rất nhiều, nên copy và `pip install` trước giúp Docker tái sử dụng cache của tầng dependencies mỗi khi chỉ sửa code, rút ngắn thời gian build từ vài phút xuống vài giây.
4. **`CMD` và `ENTRYPOINT` khác nhau thế nào?**
   - `CMD` định nghĩa lệnh (hoặc tham số) mặc định khi container khởi động và **dễ dàng bị ghi đè** bằng tham số truyền cuối lệnh `docker run <image> <command>`.
   - `ENTRYPOINT` cố định chương trình thực thi chính của container; các tham số truyền vào `docker run` sẽ được **nối thêm làm đối số** cho `ENTRYPOINT` (chỉ ghi đè được khi dùng cờ `--entrypoint`).

### Exercise 2.2: Build & Run `my-agent:develop` (build từ gốc repo)

Lệnh chạy:
```bash
docker build -f 02-docker/develop/Dockerfile -t my-agent:develop .
docker run -d --rm -p 8000:8000 my-agent:develop
```

Kết quả test thực tế:
```text
$ curl -i http://localhost:8000/health
HTTP/1.1 200 OK
content-type: application/json

{"status":"ok","uptime_seconds":0.9,"container":true}

$ curl -i -X POST "http://localhost:8000/ask?question=What%20is%20Docker%3F"
HTTP/1.1 200 OK
content-type: application/json

{"answer":"Container là cách đóng gói app để chạy ở mọi nơi. Build once, run anywhere!"}
```

### Exercise 2.3: Multi-stage build & So sánh kích thước image

Phân tích `02-docker/production/Dockerfile`:
- **Stage 1 (`builder` — `FROM python:3.11-slim AS builder`):** Cài build tools (`gcc`, `libpq-dev`) và chạy `pip install --no-cache-dir --user -r requirements.txt` để biên dịch và cài toàn bộ gói Python vào `/root/.local`. Image stage này **không** được dùng để deploy.
- **Stage 2 (`runtime` — `FROM python:3.11-slim AS runtime`):** Khởi tạo từ image `slim` sạch, tạo user non-root (`appuser`), chỉ `COPY --from=builder /root/.local /home/appuser/.local` cùng source code (`main.py`, `utils/mock_llm.py`), thêm `HEALTHCHECK` và chạy `uvicorn` với 2 workers.
- **Vì sao image nhỏ hơn và an toàn hơn:** Loại bỏ hoàn toàn base Debian cồng kềnh (`python:3.11` full) và vứt bỏ toàn bộ compiler (`gcc`), header C (`libpq-dev`), cache apt/pip khỏi image runtime cuối cùng → giảm bề mặt tấn công (attack surface), tải/deploy nhanh hơn rất nhiều.

**Số đo thực tế bằng `docker images my-agent` và `docker image inspect`:**

```text
IMAGE               ID             DISK USAGE   CONTENT SIZE
my-agent:advanced   fd67e13aea82        240MB         57.4MB
my-agent:develop    773137a60149       1.67GB          426MB
```

- **Develop (`my-agent:develop`):** `1667.8 MB` (`1590.5 MiB`, `1.67 GB` hiển thị trong `docker images`)
- **Production (`my-agent:advanced`):** `239.8 MB` (`228.7 MiB`, `240 MB` hiển thị trong `docker images`)
- **Chênh lệch:** Giảm **85.6%** kích thước (nhỏ hơn gần **7 lần**, thấp hơn nhiều ngưỡng `< 500 MB`).

### Exercise 2.4: Docker Compose Stack (`02-docker/production/docker-compose.yml`)

**Sơ đồ kiến trúc stack:**

```text
                      ┌──────────────────────────────────────────────────┐
                      │         Docker bridge network: internal          │
  Client ──(:80)──▶ ┌─┴──────────┐                                       │
                    │   nginx    │ (reverse proxy, rate limit 10r/s,     │
                    │ nginx:alp. │  security headers)                    │
                    └─┬──────────┘                                       │
                      │ http://agent:8000                                │
                      ▼                                                  │
                    ┌────────────┐ ──redis://redis:6379/0──▶ ┌─────────┐ │
                    │   agent    │                           │  redis  │ │
                    │  (FastAPI) │                           │ :6379   │ │
                    └─┬──────────┘                           └─────────┘ │
                      │ http://qdrant:6333                               │
                      ▼                                                  │
                    ┌────────────┐                                       │
                    │   qdrant   │ (vector DB, volume qdrant_data)       │
                    │   :6333    │                                       │
                    └────────────┘                                       │
                      └──────────────────────────────────────────────────┘
```

- **Các service khởi động:** `nginx` (mở port `80` và `443` ra host), `agent` (chỉ mở nội bộ port `8000`, `depends_on` `redis` và `qdrant` ở trạng thái `service_healthy`), `redis` (`redis:7-alpine`, volume `redis_data`), `qdrant` (`qdrant/qdrant:v1.9.0`, volume `qdrant_data`).
- **Cách giao tiếp:** Cả 4 container gắn chung mạng bridge nội bộ `internal`, giao tiếp bằng **Docker DNS theo tên service** (`http://agent:8000`, `redis://redis:6379/0`, `http://qdrant:6333`); chỉ `nginx` expose cổng ra ngoài nên Redis và Qdrant được cách ly hoàn toàn.

**Kết quả test thực tế qua Nginx (`docker compose -p k5-day14-docker up -d --build`):**

```text
$ curl -i http://localhost/health
HTTP/1.1 200 OK
Server: nginx
Content-Type: application/json
X-Frame-Options: DENY
X-Content-Type-Options: nosniff
X-XSS-Protection: 1; mode=block

{"status":"ok","uptime_seconds":0.4,"version":"2.0.0","timestamp":"2026-11-25T09:33:44.709333"}

$ curl -i -X POST http://localhost/ask -H "Content-Type: application/json" -d '{"question":"Explain microservices"}'
HTTP/1.1 200 OK
Server: nginx
Content-Type: application/json
X-Frame-Options: DENY
X-Content-Type-Options: nosniff
X-XSS-Protection: 1; mode=block

{"answer":"Agent đang hoạt động tốt! (mock response) Hỏi thêm câu hỏi đi nhé."}
```

---

## Part 3: Cloud Deployment

### Exercise 3.1 / 3.2: Deploy Agent Part 6 lên Cloud

- **Public URL:** *(Đang cập nhật sau bước deploy Railway/Render — xem [`DEPLOYMENT.md`](DEPLOYMENT.md))*
- **Screenshots:** `screenshots/dashboard.png`, `screenshots/running.png`, `screenshots/test.png`

### So sánh `railway.toml` và `render.yaml`

| Tiêu chí | `railway.toml` | `render.yaml` (Blueprint) | Lý do khác biệt |
|---|---|---|---|
| **Định dạng & phạm vi** | File **TOML**, cấu hình build & deploy cho **1 service** hiện tại | File **YAML** dạng **Infrastructure as Code (IaC)**, khai báo được **nhiều service cùng lúc** (web service + managed Redis/Postgres) | Railway tách quản lý dịch vụ/add-on (Redis, biến môi trường) sang Dashboard/CLI, còn Render Blueprint định nghĩa toàn bộ topology hạ tầng trong 1 file duy nhất để sync tự động từ Git. |
| **Cách build & chạy** | `[build]` chọn `builder = "DOCKERFILE"` (hoặc `NIXPACKS`), `dockerfilePath = "Dockerfile"`; `[deploy]` dùng `CMD` của Dockerfile hoặc `startCommand` | Mỗi service khai báo `type: web`, `runtime: docker` (hoặc `python`), `dockerfilePath`, `region`, `plan` (`free`/`starter`) | Render cho phép gắn cứng gói tài nguyên (`plan`) và `region` (vd `singapore`) ngay trong file cấu hình. |
| **Health check** | `healthcheckPath = "/health"` và `healthcheckTimeout = 30` trong mục `[deploy]` | `healthCheckPath: /health` ngay trong định nghĩa service | Cả hai đều gọi `/health` trước khi chuyển traffic sang bản deploy mới (zero-downtime deploy). |
| **Quản lý Secrets & Env vars** | Không khai báo env vars trong `railway.toml` mà đặt qua `railway variables set` hoặc Dashboard (tránh commit secret) | Khai báo danh sách `envVars` trực tiếp: biến thường dùng `value:`, secret dùng `generateValue: true` (Render tự sinh) hoặc `sync: false` (nhập tay trên Dashboard), liên kết Redis qua `fromService` | Cơ chế `generateValue` / `sync: false` của Render vừa cho phép versioning cấu trúc env vars trong Git, vừa đảm bảo không bao giờ commit giá trị secret thật. |
| **Restart & Auto-deploy** | `restartPolicyType = "ON_FAILURE"`, `restartPolicyMaxRetries = 3` | `autoDeploy: true` (tự build & deploy khi push lên GitHub) | Railway tập trung kiểm soát chính sách restart ở runtime, còn Render Blueprint quản lý luôn cơ chế trigger deploy theo nhánh Git. |

### Exercise 3.3: Phân tích CI/CD pipeline GCP Cloud Run (`cloudbuild.yaml` & `service.yaml`)

Đọc `03-cloud-deployment/production-cloud-run/cloudbuild.yaml` và `service.yaml`:
- **Pipeline CI/CD gồm 4 bước tuần tự (`waitFor`) khi push lên `main`:**
  1. **`test`** (`python:3.11-slim`): cài `requirements.txt` + `pytest` và chạy `pytest tests/ -v --tb=short` — nếu test fail thì dừng ngay pipeline.
  2. **`build`** (`gcr.io/cloud-builders/docker`): build Docker image gắn 2 tag (`$COMMIT_SHA` để truy vết chính xác phiên bản và `latest`), tái sử dụng layer cache qua `--cache-from`.
  3. **`push`**: đẩy toàn bộ tag image lên Google Container Registry (`gcr.io/$PROJECT_ID/ai-agent`).
  4. **`deploy`** (`gcloud run deploy`): deploy image theo `$COMMIT_SHA` lên Cloud Run managed tại `asia-southeast1` với `min-instances=1` (tránh cold start), `max-instances=10`, `512Mi` RAM / `1 CPU`, timeout `60s`, nạp `OPENAI_API_KEY` an toàn từ **Secret Manager**.
- File **`service.yaml`** (Knative IaC) khai báo cấu hình chuẩn của service Cloud Run gồm autoscale `minScale: 1` / `maxScale: 10`, `containerConcurrency: 80` request/instance, giới hạn CPU/RAM, tham chiếu secret qua `secretKeyRef` (không hardcode), cùng `livenessProbe` (`/health`) và `startupProbe` (`/ready`).

---

## Part 4: API Security

### Exercise 4.1: API Key Authentication (`04-api-gateway/develop/app.py`)

- **API key được kiểm tra ở đâu?** Tại hàm dependency `verify_api_key` (dòng 39–54) đọc header `X-API-Key` qua `APIKeyHeader(name="X-API-Key", auto_error=False)` và được inject vào endpoint `/ask` bằng `Depends(verify_api_key)` (dòng 70), so sánh với biến môi trường `AGENT_API_KEY`.
- **Điều gì xảy ra nếu thiếu hoặc sai key?** Thiếu header → trả **`401 Unauthorized`**; gửi sai key → bản develop mẫu trả **`403 Forbidden`** (trong Part 6 theo hợp đồng chấm, cả thiếu lẫn sai key đều trả thống nhất **`401 Unauthorized`** và so sánh bằng `secrets.compare_digest` chống timing attack).
- **Làm sao rotate key an toàn không gây downtime?** Áp dụng cơ chế **dual-key / overlap window**: cho phép app chấp nhận danh sách key từ biến môi trường (vd `AGENT_API_KEYS=old_key,new_key`) → phát hành `new_key` và cập nhật toàn bộ client → theo dõi log xác nhận không còn traffic dùng `old_key` → gỡ `old_key` khỏi cấu hình env và restart/redeploy.

**Output `curl -i` thực tế (`AGENT_API_KEY=secret-key-123`):**

```text
--- Không có API key (401) ---
HTTP/1.1 401 Unauthorized
content-type: application/json

{"detail":"Missing API key. Include header: X-API-Key: <your-key>"}

--- Sai API key (403 ở bản develop mẫu) ---
HTTP/1.1 403 Forbidden
content-type: application/json

{"detail":"Invalid API key."}

--- Có API key hợp lệ (200) ---
HTTP/1.1 200 OK
content-type: application/json

{"question":"Hello","answer":"Đây là câu trả lời từ AI agent (mock). Trong production, đây sẽ là response từ OpenAI/Anthropic."}
```

### Exercise 4.2 & 4.3: JWT Authentication & Rate Limiting (`04-api-gateway/production/`)

- **JWT Flow (`auth.py`):** Client gửi `username`/`password` tới `POST /auth/token` → server xác thực và ký JWT (HS256) chứa payload `sub`, `role`, `iat`, `exp` (hết hạn sau 60 phút) bằng `JWT_SECRET`. Ở các request sau, client gửi `Authorization: Bearer <token>`; `verify_token` kiểm tra chữ ký và thời hạn không cần truy vấn DB (stateless).
- **Rate Limiter (`rate_limiter.py`):**
  - **Thuật toán:** **Sliding Window** (lưu `deque` các timestamp request của từng user, loại bỏ các timestamp cũ hơn `now - 60s`, nếu `len(window) >= max_requests` thì trả `429 Too Many Requests` kèm header `Retry-After`, `X-RateLimit-Limit`, `X-RateLimit-Remaining`, `X-RateLimit-Reset`).
  - **Giới hạn:** Role `user` (`student`/`demo123`) là **10 req/phút** (`rate_limiter_user`); role `admin` (`teacher`/`teach456`) là **100 req/phút** (`rate_limiter_admin`).
  - **Bypass / nâng giới hạn cho admin:** Trong `app.py` dòng 141, hệ thống đọc `role` từ JWT payload (`limiter = rate_limiter_admin if role == "admin" else rate_limiter_user`), hoặc có thể bỏ qua bước `limiter.check()` hoàn toàn cho role `admin` / internal service key.

**Output `curl -i` thực tế (token đã che):**

```text
--- Không có Bearer token (401) ---
HTTP/1.1 401 Unauthorized
www-authenticate: Bearer
content-type: application/json
x-content-type-options: nosniff
x-frame-options: DENY

{"detail":"Authentication required. Include: Authorization: Bearer <token>"}

--- Lấy JWT tại POST /auth/token (student / demo123) ---
{
  "access_token": "eyJhbGciOiJI***REDACTED***",
  "token_type": "bearer",
  "expires_in_minutes": 60,
  "hint": "Include in header: Authorization: Bearer <REDACTED>"
}

--- Request #1 (200 OK) ---
HTTP/1.1 200 OK
content-type: application/json
x-content-type-options: nosniff
x-frame-options: DENY

{"question":"Test 1","answer":"Tôi là AI agent được deploy lên cloud. Câu hỏi của bạn đã được nhận.","usage":{"requests_remaining":9,"budget_remaining_usd":1.9e-05}}

Request #2..#9 -> HTTP 200

--- Request #10 (200 OK — hết quota phút) ---
HTTP/1.1 200 OK
content-type: application/json

{"question":"Test 10","answer":"Tôi là AI agent được deploy lên cloud. Câu hỏi của bạn đã được nhận.","usage":{"requests_remaining":0,"budget_remaining_usd":0.000179}}

--- Request #11 (429 Too Many Requests) ---
HTTP/1.1 429 Too Many Requests
x-ratelimit-limit: 10
x-ratelimit-remaining: 0
x-ratelimit-reset: 1795599062
retry-after: 59
content-type: application/json

{"detail":{"error":"Rate limit exceeded","limit":10,"window_seconds":60,"retry_after_seconds":59}}

Request #12 -> HTTP 429
```

### Exercise 4.4: Cách thiết kế Cost Guard

- **Vì sao cần cả Rate Limit lẫn Cost Guard?** Rate limit chỉ giới hạn **tốc độ** (số request/phút) chống spam/DDoS, nhưng không kiểm soát được **số tiền tiêu thụ** (1 user gửi prompt cực dài hoặc dùng model đắt như `mock-llm-large` vẫn có thể đốt cạn ngân sách dù dưới rate limit). Cost guard bảo vệ trực tiếp **ngân sách USD** theo ngày/tháng.
- **Cách triển khai chuẩn production (dùng Redis để stateless giữa nhiều worker/instance):**
  1. Tạo key theo chu kỳ ngày/tháng trong Redis: `cost:daily:<scope>:YYYY-MM-DD` (TTL 48 giờ) và `cost:monthly:<scope>:YYYY-MM` (TTL 35 ngày).
  2. **Trước khi gọi LLM (`check_budget`):** Đọc tổng chi phí hiện tại từ Redis; nếu đã `>= DAILY_BUDGET_USD` hoặc `>= MONTHLY_BUDGET_USD`, chặn ngay bằng `HTTP 402 Payment Required` (không tốn thêm tiền gọi upstream LLM).
  3. **Sau khi gọi LLM (`record_cost`):** Tính chi phí thực tế `cost = (input_tokens/1000)*PRICE_INPUT + (output_tokens/1000)*PRICE_OUTPUT` và cộng dồn nguyên tử bằng `INCRBYFLOAT` + đặt `EXPIRE` trong pipeline Redis.

---

## Part 5: Scaling & Reliability

### Exercise 5.1 & 5.2: Health Check, Readiness Check & Graceful Shutdown

- **Liveness (`/health`) khác Readiness (`/ready`) ở đâu?**
  - **`GET /health` (Liveness):** Trả lời câu hỏi *"Process còn sống không?"*. Luôn trả `200 OK` miễn process không bị treo/deadlock — **kể cả khi Redis bị mất kết nối**. Nếu `/health` fail theo Redis, orchestrator sẽ restart toàn bộ container liên tục (crash loop) làm sự cố nặng thêm trong khi bản thân app không hỏng.
  - **`GET /ready` (Readiness):** Trả lời câu hỏi *"Instance đã sẵn sàng nhận traffic chưa?"*. Kiểm tra kết nối Redis/DB và cờ shutdown; trả `503 Service Unavailable` nếu Redis chết hoặc app đang tắt để Load Balancer ngừng route traffic vào instance đó mà **không** restart oan container.
- **Graceful Shutdown (`SIGTERM`):** Khi container nhận `SIGTERM` (lúc `docker stop` hoặc rolling deploy), Uvicorn ngừng nhận kết nối mới, chờ toàn bộ request in-flight xử lý xong trả `200 OK`, chạy phần shutdown của `lifespan` (đặt `is_ready = False`, đóng Redis pool), rồi thoát sạch với `exit code 0`. Nếu tự đăng ký `signal.signal(signal.SIGTERM, ...)` thì bắt buộc phải gọi lại handler trước đó của Uvicorn (hoặc giao việc xử lý tín hiệu cho Uvicorn + `lifespan`), nếu không process sẽ bị treo tới khi bị `SIGKILL` (`exit code 137`).

**Output thực tế trên `05-scaling-reliability/develop/app.py`:**

```text
--- GET /health ---
HTTP/1.1 200 OK
{"status":"ok","uptime_seconds":0.7,"version":"1.0.0","environment":"development","timestamp":"2026-11-25T09:30:03.260146+00:00","checks":{"memory":{"status":"ok","used_percent":10.0}}}

--- GET /ready ---
HTTP/1.1 200 OK
{"ready":true,"in_flight_requests":1}

--- Gửi POST /ask?question=Long%20task đồng thời kill -TERM $PID ---
HTTP/1.1 200 OK
{"answer":"Đây là câu trả lời từ AI agent (mock). Trong production, đây sẽ là response từ OpenAI/Anthropic."}

--- Server logs ---
INFO:     Shutting down
INFO:     127.0.0.1:51230 - "POST /ask?question=Long%20task HTTP/1.1" 200 OK
INFO:     Waiting for application shutdown.
2026-11-25 09:30:06,449 INFO 🔄 Graceful shutdown initiated...
2026-11-25 09:30:06,449 INFO ✅ Shutdown complete
INFO:     Application shutdown complete.
```

### Exercise 5.3–5.5: Stateless Design, Load Balancing (`--scale agent=3`) & `test_stateless.py`

- **Tại sao state trong RAM bị hỏng khi chạy nhiều instance?** Khi có 3 container đứng sau Nginx load balancer, request 1 của user có thể vào `instance A`, request 2 vào `instance B`. Nếu lưu lịch sử hội thoại hoặc bộ đếm rate limit trong dict RAM, `instance B` không thấy dữ liệu của `instance A` → mất ngữ cảnh hội thoại và vượt rate limit gấp N lần. Khi đưa toàn bộ state ra **Redis dùng chung**, mọi instance trở nên **stateless** và có thể scale lên/xuống hoặc thay thế bất kỳ lúc nào không mất dữ liệu.

**Kết quả chạy thực tế (`docker compose -p k5-day14-scaling up -d --build --scale agent=3` + `python test_stateless.py`):**

```text
============================================================
Stateless Scaling Demo
============================================================

Session ID: d3c72b99-64cc-4072-a7cc-06aaa1946077

Request 1: [instance-8485d0]
  Q: What is Docker?
  A: Container là cách đóng gói app để chạy ở mọi nơi. Build once, run anywhere!...

Request 2: [instance-b9fc5b]
  Q: Why do we need containers?
  A: Agent đang hoạt động tốt! (mock response) Hỏi thêm câu hỏi đi nhé....

Request 3: [instance-8485d0]
  Q: What is Kubernetes?
  A: Đây là câu trả lời từ AI agent (mock). Trong production, đây sẽ là response từ O...

Request 4: [instance-25fbb7]
  Q: How does load balancing work?
  A: Tôi là AI agent được deploy lên cloud. Câu hỏi của bạn đã được nhận....

Request 5: [instance-b9fc5b]
  Q: What is Redis used for?
  A: Đây là câu trả lời từ AI agent (mock). Trong production, đây sẽ là response từ O...

------------------------------------------------------------
Total requests: 5
Instances used: {'instance-b9fc5b', 'instance-8485d0', 'instance-25fbb7'}
✅ All requests served despite different instances!

--- Conversation History ---
Total messages: 10
  [user]: What is Docker?...
  [assistant]: Container là cách đóng gói app để chạy ở mọi nơi. Build once...
  [user]: Why do we need containers?...
  [assistant]: Agent đang hoạt động tốt! (mock response) Hỏi thêm câu hỏi đ...
  [user]: What is Kubernetes?...
  [assistant]: Đây là câu trả lời từ AI agent (mock). Trong production, đây...
  [user]: How does load balancing work?...
  [assistant]: Tôi là AI agent được deploy lên cloud. Câu hỏi của bạn đã đư...
  [user]: What is Redis used for?...
  [assistant]: Đây là câu trả lời từ AI agent (mock). Trong production, đây...

✅ Session history preserved across all instances via Redis!
```

**Giải thích kết quả:** Nginx trên cổng `8080` phân tán 5 request `POST /chat` tới đầy đủ cả **3 instance khác nhau** (`instance-8485d0`, `instance-b9fc5b`, `instance-25fbb7`, đều log `Storage: Redis ✅`), và khi đọc `GET /chat/d3c72b99-64cc-4072-a7cc-06aaa1946077/history`, toàn bộ **10 messages (5 turns)** đều còn nguyên vẹn vì state nằm tập trung trong Redis.

---

## Part 6: Final Project — Kết quả `check_production_ready.py`

Chạy bản đầy đủ (có Docker, trên môi trường POSIX `os.name = 'posix'`, Python 3.11) trong `06-lab-complete/`:

```text
================================================================
  📋 Checklist Deliverable
     ✅ Dockerfile (multi-stage, < 500 MB)
     ✅ docker-compose.yml (agent + redis)
     ✅ .dockerignore
     ✅ Health check endpoint (GET /health)
     ✅ Readiness endpoint (GET /ready)
     ✅ API Key authentication
     ✅ Rate limiting
     ✅ Cost guard
     ✅ Config từ environment variables
     ✅ Structured logging
     ✅ Graceful shutdown
     ✅ Public URL ready (Railway / Render config)
----------------------------------------------------------------
  Result: 12/12 tiêu chí đạt · 43/43 checks passed
  🎉 PASS 12/12 — PRODUCTION READY! Deploy nào!
================================================================
```

Một số chỉ số chính ghi nhận từ script chấm:
- **Docker build & image size:** Build thành công trong `17s`, kích thước image cuối = **`238 MB`** (`< 500 MB`), non-root `appuser`, có `HEALTHCHECK`.
- **Rate limit & Stateless:** Bị chặn `429` sau đúng `5` request (`RATE_LIMIT_PER_MINUTE=5`) với header `Retry-After`; sau khi restart agent vẫn trả `429` (state bền vững trong Redis).
- **Readiness khi Redis down:** `/health` vẫn trả `200`, `/ready` trả `503`.
- **Cost guard:** Trả `402` ngay khi vượt ngân sách `0.000001 USD`.
- **Structured logging:** `17/17` dòng log ứng dụng đều là JSON hợp lệ.
- **Graceful shutdown:** In-flight request hoàn thành `200` khi nhận `SIGTERM`, process thoát `exit code 0`; `docker stop` tắt sạch với `exit code 0` trong **`0.8s`** (`< 10s`).

---

## AI Log

Theo quy định mục 1 trong `RULES.md`, dưới đây là nhật ký sử dụng trợ lý AI (Antigravity) trong quá trình thực hiện bài lab:

1. **Thiết kế và hoàn thiện mã nguồn Part 6 (`06-lab-complete/`):**
   - *Hỏi gì:* Nhờ AI rà soát hợp đồng chấm bài trong `06-lab-complete/README.md` và `check_production_ready.py`, sau đó hỗ trợ viết phần TODO cho `app/config.py`, `app/redis_client.py`, `app/auth.py`, `app/rate_limiter.py`, `app/cost_guard.py`, `app/main.py`, `Dockerfile`, `docker-compose.yml`, `.dockerignore`, `.env.example`, `railway.toml`, `render.yaml`.
   - *Nhận gì:* Code sử dụng `secrets.compare_digest` cho API key (trả 401 cho cả thiếu và sai key), Redis Sorted Set cho sliding-window rate limit (member kèm UUID tránh trùng timestamp), Redis `INCRBYFLOAT` + TTL cho cost guard (hỗ trợ cả daily & monthly budget), `JsonFormatter` cho log JSON, multi-stage `Dockerfile` cài gói vào `/install` rồi copy sang `/usr/local` cho non-root `appuser`, và `CMD ["sh", "-c", "exec uvicorn ... --port ${PORT:-8000} --workers 2"]`.
   - *Tự kiểm tra & xác nhận:* Chạy kiểm tra tĩnh `--static-only` rồi chạy bản đầy đủ `python check_production_ready.py` trong môi trường Linux POSIX + Docker Engine 29.9.3 và xác nhận đạt **`PASS 12/12` (43/43 checks, image 238 MB, `docker stop` 0.8s)**.

2. **Chạy thực nghiệm Parts 1–5 và gỡ lỗi môi trường:**
   - *Hỏi gì:* Hỗ trợ chạy các ví dụ Parts 1, 2, 4, 5 trên Windows + Docker Desktop và xử lý lỗi khi chạy script kiểm thử.
   - *Nhận gì & tự sửa:* Phát hiện 2 vấn đề thực tế: (a) `01-localhost-vs-production/production/app.py` ghi đè `signal.SIGTERM` không gọi lại handler cũ của uvicorn nên không tự tắt khi gửi SIGTERM; (b) `06-lab-complete/benchmark-observability/production/Dockerfile` tạo user `agent` với home `/app` nhưng copy packages vào `/home/agent/.local` thiếu `ENV PYTHONUSERBASE=/home/agent/.local` gây `ModuleNotFoundError: No module named 'uvicorn'`. Đã sửa bổ sung `ENV PYTHONUSERBASE=/home/agent/.local` vào Dockerfile Part 7 để stack observability chạy ổn định.
   - *Tự kiểm tra:* Chạy thật toàn bộ container, đo dung lượng thật (`1667.8 MB` vs `239.8 MB`), xác nhận output `401`/`200`/`429`, `test_stateless.py` trên 3 instance.

3. **Part 7 — Benchmark, Eval, Observability & Chaos Experiments:**
   - *Hỏi gì:* Hỗ trợ thêm metric `agent_question_length_chars` (Exercise 7.1), bổ sung 2 entry thiếu (`jwt`, `hpa`/`kubernetes`) vào `KNOWLEDGE_BASE` (Exercise 7.3), tạo CI workflow `.github/workflows/eval.yml`, và tự động hóa đo tải + thí nghiệm chaos A–E.
   - *Tự sửa & tự kiểm tra:* Phát hiện lệnh `docker compose run --rm locust` tự bật lại `agent-2` do `deploy.replicas: 2`, nên đã chạy lại `scale_1` với cờ `--no-deps` và kiểm tra bằng `docker compose ps agent` đảm bảo đúng 1 instance. Toàn bộ 10 file JSON (`reports/`), 2 file CSV (`benchmark-results/`), 4 ảnh screenshot (`screenshots/`), kết quả `promtool test rules` (`SUCCESS`) và dòng log JSON khớp `trace_id` đều được tạo từ lần chạy thật và đối chiếu từng con số với `BENCHMARK_REPORT.md`.
