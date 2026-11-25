# Benchmark & Observability Report — Day 14

> Mọi con số dưới đây được đo trực tiếp từ lệnh chạy thật và khớp với các file bằng chứng trong `reports/`, `benchmark-results/` và `screenshots/`.

**Họ tên:** Nguyễn Khánh Vinh (MSSV: 2A202603390)
**Ngày chạy:** 25/11/2026
**Môi trường:** Windows 11 + Docker Desktop 29.9.3 (WSL2 backend, 12 CPU / 8 GB RAM), Python 3.11 (container POSIX)

---

## 1. SLO của agent

| SLI | SLO | Lý do chọn ngưỡng này |
|---|---|---|
| p95 latency `/ask` | < 500 ms | Latency cơ bản của agent v2 (retrieval ~20 ms + mock LLM ~120–180 ms) nằm quanh ~190–220 ms; ngưỡng p95 < 500 ms đảm bảo 95% người dùng nhận phản hồi mượt mà trong nửa giây và phát hiện sớm hiện tượng nghẽn cổ chai hoặc tail latency lan rộng (khi `MOCK_SLOW_RATE > 5%`). |
| Error rate `/ask` | < 2.0 % | Mock LLM có tỉ lệ lỗi upstream ngẫu nhiên ~1% (`MOCK_ERROR_RATE=0.01`); đặt SLO < 2.0% cho phép dao động thống kê nhỏ ở mẫu 300 request nhưng chặn ngay khi upstream suy giảm thực sự (alert `AgentHighErrorRate` cảnh báo mạnh ở ngưỡng > 5% trong 1 phút để tránh alert fatigue). |
| Accuracy trên golden dataset | ≥ 85 % (mục tiêu 100%) | Với 23 câu hỏi cốt lõi về vận hành AI Agent, dưới 85% nghĩa là agent bỏ sót nhiều kiến thức trọng yếu (như v1 chỉ đạt 4.3%). Mức 85% dùng làm ngưỡng tối thiểu trong CI quality gate (`.github/workflows/eval.yml`), còn mục tiêu sau khi hoàn thiện knowledge base là 100% (23/23) và **0 regression**. |

---

## 2. Benchmark hiệu năng (develop, `load_test.py`)

### 2.1 Concurrency vs latency (agent v2)

Chạy `python load_test.py --url http://127.0.0.1:8002 --requests 300 --concurrency <c> --out reports/load_v2_c<c>.json` (bằng chứng: `reports/load_v2_c1.json`, `load_v2_c10.json`, `load_v2_c50.json`, `load_v2_c100.json`):

| Concurrency | RPS | p50 (ms) | p95 (ms) | p99 (ms) | Error rate | SLO |
|---:|---:|---:|---:|---:|---:|---|
| 1 | 4.31 | 188.7 | 220.4 | 1693.9 | 1.67% | PASS |
| 10 | 38.59 | 189.4 | 218.0 | 1690.5 | 2.00% | PASS |
| 50 | 174.25 | 197.7 | 251.9 | 377.3 | 1.67% | PASS |
| 100 | 55.30 | 358.1 | 3497.0 | 3797.3 | 0.33% | FAIL |

**Nhận xét:** RPS có tăng tuyến tính theo concurrency không? Vì sao?

RPS **chỉ tăng gần tuyến tính trong vùng chưa bão hoà** (`c=1 → 10 → 50`: từ `4.31` lên `38.59` rồi `174.25 req/s`) nhờ FastAPI + Uvicorn chạy bất đồng bộ (`async/await`), trong lúc chờ I/O (`await asyncio.sleep` mô phỏng retrieval và LLM), event loop xử lý đồng thời nhiều request khác nên p50 gần như giữ nguyên (~189–198 ms). Tuy nhiên khi tăng lên `c=100`, hệ thống chạm **điểm bão hoà (saturation knee)** của 1 process đơn (tranh chấp event loop, socket/connection pool và hàng đợi TCP listen backlog): các request phải xếp hàng chờ xử lý nên p50 tăng lên `358.1 ms`, p95 vọt lên `3497.0 ms` (vượt xa SLO 500 ms → **FAIL**) và thông lượng thực tế tụt mạnh từ `174.25 req/s` xuống còn `55.30 req/s`. Vì vậy RPS không tăng tuyến tính mãi theo concurrency.

### 2.2 Tail latency

Chạy agent v2 với 3 mức `MOCK_SLOW_RATE`, mỗi lần `--requests 300 --concurrency 20` (bằng chứng: `reports/load_v2_slow_0.json`, `load_v2_slow_0.03.json`, `load_v2_slow_0.1.json`):

| `MOCK_SLOW_RATE` | avg (ms) | p95 (ms) | p99 (ms) |
|---|---:|---:|---:|
| 0 | 189.0 | 218.8 | 222.5 |
| 0.03 (mặc định) | 224.6 | 222.5 | 1683.2 |
| 0.1 | 284.3 | 1679.8 | 1713.3 |

**Nhận xét:** Chỉ số nào nhạy nhất với request chậm? Vì sao SLO không nên đặt theo average?

- **Chỉ số nhạy nhất là `p99` (và tiếp theo là `p95` khi tỉ lệ request chậm vượt 5%):**
  - Khi `MOCK_SLOW_RATE` tăng từ `0` lên `0.03` (3% request chậm thêm ~1500 ms), `avg` chỉ tăng nhẹ `+35.6 ms` (`189.0 → 224.6 ms`) và `p95` gần như không đổi (`218.8 → 222.5 ms`), nhưng `p99` lập tức nhảy vọt gấp **7.6 lần** (`222.5 → 1683.2 ms`).
  - Khi `MOCK_SLOW_RATE` lên `0.1` (10% request chậm > 5%), `avg` vẫn trông "rất ổn" ở `284.3 ms` (vẫn dưới ngưỡng 500 ms), trong khi cả `p95` (`1679.8 ms`) lẫn `p99` (`1713.3 ms`) đều chạm ~1.7 giây (vi phạm SLO).
- **Vì sao không đặt SLO theo average:** Giá trị trung bình bị 90–97% request nhanh kéo xuống nên **che giấu hoàn toàn trải nghiệm tệ của nhóm người dùng gặp tail latency**. Đặt SLO theo `p95`/`p99` bảo đảm cam kết chất lượng trực tiếp cho phần đuôi phân phối mà người dùng cảm nhận rõ nhất.

---

## 3. Benchmark chất lượng (develop, `eval/run_eval.py`)

Bằng chứng: `reports/eval_v1.json`, `reports/eval_v2.json`, `reports/eval_v2_fixed.json`:

| Chỉ số | Agent v1 | Agent v2 | Agent v2 (sau khi sửa KB) |
|---|---|---|---|
| Accuracy | 4.35% (1/23) | 91.30% (21/23) | 100.00% (23/23) |
| Avg tokens / câu | 58.3 | 108.8 | 113.8 |
| Tổng cost (USD) | $0.000421 | $0.000757 | $0.000792 |
| Cost / câu đúng (USD) | $0.00042075 | $0.00003607 | $0.00003443 |
| Quality gate | FAIL | PASS | PASS |

**Những câu v2 trả lời sai ban đầu và cách bạn sửa:**

| ID | Keyword bị thiếu | Bạn đã sửa gì |
|---|---|---|
| `security-02` | `token`, `hết hạn`, `chữ ký` | Thêm entry vào `KNOWLEDGE_BASE` trong `06-lab-complete/benchmark-observability/develop/utils/mock_llm.py` (và đồng bộ sang `production/utils/mock_llm.py`) với từ khoá `["jwt"]` giải thích sự khác nhau giữa API key cố định và JWT là token có chữ ký số, chứa thông tin user và thời điểm hết hạn. |
| `scaling-03` | `cpu`, `memory`, `custom metrics` | Thêm entry vào `KNOWLEDGE_BASE` với từ khoá `["hpa", "kubernetes", "autoscal"]` mô tả Kubernetes HPA tự động scale số pod dựa trên CPU, memory hoặc custom metrics (như RPS, độ dài hàng đợi). |

- Sau khi sửa `KNOWLEDGE_BASE` và khởi động lại agent v2, chạy:
  ```bash
  python eval/run_eval.py --url http://localhost:8002 --min-accuracy 1.0 --baseline reports/eval_v2.json --out reports/eval_v2_fixed.json
  ```
  Kết quả: **23/23 (100.0%)**, cải thiện +2 câu, **0 câu bị regression**, `Quality gate (accuracy ≥ 100%, không regression): ✅ PASS`.

**Nhận xét về trade-off chất lượng / chi phí / latency giữa v1 và v2:**

- **Chất lượng:** v2 (có bước retrieval RAG) nâng accuracy từ **4.35% (1/23)** lên **91.30% (21/23)** và đạt **100% (23/23)** sau khi bổ sung 2 tài liệu thiếu.
- **Chi phí:** Do phải đưa thêm đoạn context tìm được vào prompt, v2 dùng gần **gấp đôi số token/câu** (`108.8–113.8` so với `58.3` của v1) khiến tổng cost cho 23 câu tăng gần gấp đôi (`$0.000757–$0.000792` so với `$0.000421`). Tuy nhiên nếu tính theo **cost / câu trả lời đúng** (hiệu quả chi phí thực tế), v2 (`$0.00003443/câu đúng`) **rẻ hơn hơn 12 lần** so với v1 (`$0.00042075/câu đúng`).
- **Latency:** v2 chậm hơn một chút ở p50/p95 (`p50: 184.3–188.6 ms` so với `151.7 ms` của v1) do thêm bước retrieval (~20 ms) và prompt dài hơn. Đánh đổi ~35 ms latency và ~$0.000016/request để tăng độ chính xác từ 4.3% lên 100% là hoàn toàn xứng đáng.

**Quality gate trong CI/CD (Exercise 7.3):**

- Script `eval/run_eval.py` trả về **exit code `0`** khi vừa đạt `accuracy >= --min-accuracy` vừa có **0 câu regression** so với `--baseline`, và trả về **exit code `1`** nếu vi phạm bất kỳ điều kiện nào.
- Đã kiểm thử thực tế bằng cách chạy `python eval/run_eval.py --url http://127.0.0.1:8001 --baseline reports/eval_v2.json` (mô phỏng code mới bị tụt về chất lượng v1): script phát hiện **20 câu bị regression**, in `Quality gate: ❌ FAIL` và thoát với **`exit code 1`**.
- Đã tạo sẵn workflow GitHub Actions tại [`.github/workflows/eval.yml`](.github/workflows/eval.yml): mỗi khi có Pull Request, CI tự động khởi động agent v2 và chạy `python eval/run_eval.py --url http://localhost:8000 --min-accuracy 0.85`; khi exit code = 1, job fail và GitHub Branch Protection sẽ chặn không cho merge PR.

---

## 4. Observability stack (production)

### 4.1 Screenshot & trả lời Exercise 7.4

- [x] Dashboard Grafana khi đang có tải (thấy rõ Golden Signals): [`screenshots/grafana-dashboard.png`](screenshots/grafana-dashboard.png)
- [x] Một trace chậm trong Jaeger (thấy span nào chiếm thời gian): [`screenshots/jaeger-slow-trace.png`](screenshots/jaeger-slow-trace.png)
- [x] Một trace lỗi trong Jaeger (có event `exception`): [`screenshots/jaeger-error-trace.png`](screenshots/jaeger-error-trace.png)
- [x] Trang Alerts của Prometheus với ≥ 2 alert đang **firing**: [`screenshots/prometheus-alert-firing.png`](screenshots/prometheus-alert-firing.png)

**Trả lời câu hỏi Exercise 7.4 (quan sát với 2 instance agent + Locust 30 users / ramp up 5):**

1. **p95 và avg đang là bao nhiêu? Khoảng cách giữa chúng nói lên điều gì?**
   - Đo trực tiếp trên Prometheus/Grafana khi chạy ổn định 30 users: **p95 ≈ `291.6–294.5 ms`**, **avg ≈ `226.5–250 ms`** (trong khi `p50 ≈ 175 ms` và **`p99 ≈ 1.88 s`**).
   - Khoảng cách giữa `avg` (~227 ms) với `p95` (~294 ms) còn hẹp vì chỉ ~3% request chậm (`< 5%`), nhưng khoảng cách rất lớn giữa `avg` (~227 ms) và `p99` (~1880 ms) cho thấy phân phối latency **lệch phải mạnh (right-skewed / tail latency)**: đa số request nhanh (~175–220 ms), nhưng 1–3% người dùng phải chờ gần 2 giây.
2. **Panel "Requests/s theo instance": Nginx có chia đều traffic cho 2 instance không?**
   - **Có.** Nginx cân bằng tải rất đều giữa 2 container theo round-robin: `172.18.0.4:8000` nhận **`9.29 req/s`** và `172.18.0.8:8000` nhận **`9.27 req/s`** (tổng ~`18.6 req/s`). Khi gọi thử `curl -i http://localhost:8080/ask` 3 lần liên tiếp, header `X-Served-By` luân phiên giữa `172.18.0.8:8000` và `172.18.0.4:8000`.
3. **Vì sao input tokens/s lớn hơn output tokens/s?**
   - Đo thực tế từ Prometheus: **`input = 1420.4 tokens/s`**, **`output = 740.7 tokens/s`** (input gần gấp đôi output).
   - Nguyên nhân: với agent v2 (RAG), mỗi prompt gửi vào LLM bao gồm **system prompt + đoạn tài liệu context vừa retrieve được + câu hỏi của người dùng**, trong khi câu trả lời sinh ra ngắn gọn chỉ tương đương phần nội dung trả lời nên `input_tokens` luôn lớn hơn `output_tokens` đáng kể.
4. **`curl -i http://localhost:8080/metrics` trả về gì? Vì sao?**
   - Trả về **`HTTP/1.1 404 Not Found`** từ Nginx (`nginx/1.28.3`).
   - Nguyên nhân: trong `production/nginx/nginx.conf`, có block `location = /metrics { return 404; }` chủ đích **chặn public endpoint `/metrics` ra Internet** vì `/metrics` làm lộ thông tin nội bộ hệ thống (tên route, lưu lượng, tỉ lệ lỗi, model đang dùng, chi phí). Prometheus nằm chung mạng nội bộ Docker (`obs_net`) nên scrape trực tiếp `agent:8000/metrics` mà không cần đi qua Nginx.

**Unit test alert rules (`promtool`):**
Đã chạy `docker run --rm -v ".../prometheus:/p" --entrypoint promtool prom/prometheus:v3.16.0 test rules /p/alert_rules_test.yml` → kết quả **`SUCCESS`** (tất cả unit test trong `alert_rules_test.yml` đều pass).

### 4.2 Thí nghiệm "phá hệ thống"

Tất cả 5 thí nghiệm A–E được chạy thực tế trên stack `-p k5-day14-observability` (2 instance agent + Locust 30 users liên tục), đo thời gian thực từ lúc áp dụng cấu hình đến lúc Prometheus chuyển alert sang trạng thái `firing`:

| # | Thay đổi | Alert nào firing | Thời gian từ lúc đổi → firing | Panel nào phản ánh rõ nhất |
|---|---|---|---|---|
| A | `MOCK_ERROR_RATE=0.2` | `AgentHighErrorRate` (severity: `critical`, `for: 1m`; value ~`18.4–20.2%`) | **81.1 s** (`pending` lúc `21.1 s` → `firing` lúc `81.1 s`) | Golden Signals **Error rate** (chuyển đỏ ~20%), **Requests/s theo status code** (đường `503` tăng mạnh), **LLM calls ok/error** |
| B | `MOCK_SLOW_RATE=0.3` (chạy đồng thời với A để chụp 2 alert cùng firing) | `AgentHighLatencyP95` (severity: `warning`, `for: 2m`; value ~`1.89 s`) | **144.1 s** (`pending` lúc `24.0 s` → `firing` lúc `144.1 s`) | Golden Signals **Latency p95** (chuyển đỏ > 1s), **Latency /ask — p50/p95/p99** (đường p95 nhảy lên sát p99 ~1.89s), **LLM latency p95** |
| C | `LLM_MODEL=mock-llm-large` | `LLMCostBurnRateHigh` (severity: `warning`, `for: 2m`; value `$15.79/giờ`) | **141.1 s** (`pending` lúc `21.0 s` → `firing` lúc `141.1 s`) | **Cost burn rate (USD/giờ)** (vọt lên > $15/giờ, vượt xa ngưỡng $2/giờ), **LLM latency p95** (tăng do `latency_factor = 2.5`), bảng **Instances / model** đổi sang `mock-llm-large` |
| D | `docker pause k5-day14-observability-agent-1` | `AgentInstanceDown` (severity: `critical`, `for: 30s`; `up == 0`) | **42.0 s** (`pending` lúc `12.0 s` → `firing` lúc `42.0 s`) | **Instances up** (giảm từ `2` xuống `1`), **Requests/s theo instance** (1 instance tụt về 0). Lưu ý: Locust ghi nhận **28 lỗi `504 Gateway Time-out`** ở Nginx nhưng panel Error rate của agent vẫn xanh vì request bị treo ở container bị pause không bao giờ ghi metric trên agent. |
| E | `AGENT_VERSION=v1` | **Không có alert nào mới firing** (hạ tầng báo xanh 100% dù accuracy tụt từ 100% xuống 4.3%) | Không firing (theo dõi 75s) | Bảng **Phiên bản đang chạy (`agent_info`)** đổi sang `v1`, **Retrieval hit ratio** mất (rate về 0), **Tokens/s** giảm gần một nửa (`input: 1420 → 697 tokens/s`, `output: 741 → 380 tokens/s`) |

**Thí nghiệm E không làm alert nào firing. Bạn sẽ phát hiện loại sự cố này trong production bằng cách nào?**

Observability hạ tầng (4 Golden Signals) chỉ đo được hệ thống có **chạy nhanh và không trả lỗi HTTP 5xx** hay không, chứ **không biết câu trả lời có đúng hay không**. Khi triển khai nhầm `AGENT_VERSION=v1`, latency thậm chí nhanh hơn và chi phí rẻ hơn, nhưng chất lượng trả lời giảm từ 100% xuống 4.3%. Trong production, để phát hiện và ngăn chặn loại sự cố chất lượng này cần kết hợp nhiều lớp:
1. **Chặn trước khi deploy (CI/CD Quality Gate):** Bắt buộc chạy `eval/run_eval.py` trên golden dataset kèm `--baseline` và `--min-accuracy` trong pipeline CI (`.github/workflows/eval.yml`) để chặn merge/deploy ngay nếu accuracy giảm hoặc có regression.
2. **Giám sát chỉ số nghiệp vụ / RAG đặc thù của AI (Domain Metrics + Alerts):** Đặt alert cho **retrieval hit ratio tụt đột ngột** (ví dụ `< 50%` trong 5 phút), **phân bố độ dài output/input token thay đổi bất thường** (drift), hoặc **tỉ lệ câu trả lời fallback/generic tăng cao**.
3. **Đánh giá chất lượng liên tục trên traffic thật (Online Evaluation):** Lấy mẫu (sampling 1–5% request production) chạy đánh giá tự động bằng **LLM-as-a-Judge** (groundedness, relevance, faithfulness) và chạy **canary/synthetic probe** định kỳ gọi các câu hỏi golden mẫu rồi kiểm tra nội dung.
4. **Tín hiệu phản hồi từ người dùng (User Feedback):** Theo dõi tỉ lệ thumbs-down / retry / bỏ phiên (abandonment rate) theo từng `agent_version`.

### 4.3 Debug bằng trace

Chọn 1 trace chậm nhất tìm được trong Jaeger ([`screenshots/jaeger-slow-trace.png`](screenshots/jaeger-slow-trace.png)):

- `trace_id`: `a863e51b32e9e84f0f96fd9ca5d68c91`
- Tổng thời gian: **1712.61 ms** (`POST /ask`, HTTP 200)
- Chi tiết các span trong trace:
  - `POST /ask`: `1712.61 ms` (100.0%)
  - `agent.run`: `1710.92 ms` (99.9%)
  - `agent.retrieve_context`: `16.22 ms` (0.9%)
  - **`chat mock-llm-small` (span chiếm nhiều thời gian nhất): `1694.51 ms` (`98.9%`)** — chứng tỏ nút thắt nằm ở upstream LLM (tail latency), không phải do code FastAPI hay bước retrieval.
- Dòng log JSON tương ứng (grep từ `docker compose -p k5-day14-observability logs agent` theo `trace_id = a863e51b32e9e84f0f96fd9ca5d68c91`):

```json
{"ts": "2026-11-25T09:57:22.522488+00:00", "level": "INFO", "service": "observable-agent", "instance": "b2ab3e9847b5", "event": "llm_call", "trace_id": "a863e51b32e9e84f0f96fd9ca5d68c91", "span_id": "87edc23843096a3f", "request_id": "30d3f6289d7c", "model": "mock-llm-small", "agent_version": "v2", "input_tokens": 76, "output_tokens": 39, "cost_usd": 3.5e-05, "llm_ms": 1694.0}
{"ts": "2026-11-25T09:57:22.522927+00:00", "level": "INFO", "service": "observable-agent", "instance": "b2ab3e9847b5", "event": "http_request", "trace_id": "a863e51b32e9e84f0f96fd9ca5d68c91", "span_id": "87edc23843096a3f", "request_id": "30d3f6289d7c", "method": "POST", "route": "/ask", "status": 200, "ms": 1712.1}
```

*(Trace lỗi tương ứng trong [`screenshots/jaeger-error-trace.png`](screenshots/jaeger-error-trace.png) có `trace_id = 1067d71e88029d71e47c2165839cbf51`, tổng thời gian `116 ms`, span `chat mock-llm-small` `87.4 ms` ghi event `exception` với `utils.mock_llm.LLMError: Upstream LLM error: 503 Service Unavailable (mock)`, khớp dòng log `llm_error` có cùng `trace_id`.)*

---

## 5. Benchmark scaling (production, Locust headless, 100 users, 2 phút)

Bằng chứng: `benchmark-results/scale_1_stats.csv` (chạy đúng 1 container `agent-1` bằng `--scale agent=1` + `run --rm --no-deps locust`) và `benchmark-results/scale_3_stats.csv` (3 container `agent-1..3`).

**Endpoint `POST /ask`:**

| Số instance | RPS | p50 (ms) | p95 (ms) | p99 (ms) | Failures |
|---:|---:|---:|---:|---:|---|
| 1 | 59.00 | 190 | 240 | 1700 | 69 / 7043 (0.98%) |
| 3 | 59.90 | 190 | 220 | 1700 | 75 / 7149 (1.05%) |

**Tổng hợp (`Aggregated` — gồm `POST /ask` và `GET /health`):**

| Số instance | RPS | p50 (ms) | p95 (ms) | p99 (ms) | Failures |
|---:|---:|---:|---:|---:|---|
| 1 | 65.45 | 190 | 230 | 1700 | 69 / 7813 (0.88%) |
| 3 | 65.74 | 190 | 220 | 1700 | 75 / 7847 (0.96%) |

**Giải thích kết quả:** Scale có cải thiện p95 không? Nút thắt nằm ở đâu?

- Scale từ 1 lên 3 instance chỉ giảm nhẹ `p95` của `POST /ask` từ **`240 ms` xuống `220 ms`** (và `/health` p95 từ `6 ms` xuống `4 ms`) nhờ giảm chút ít thời gian xếp hàng ở event loop, còn `p50` (`190 ms`), `p99` (`1700 ms`), RPS (`~59–60 req/s` cho `/ask`) và error rate (`~1%`) gần như **không đổi**.
- **Nút thắt nằm ở 2 chỗ ngoài CPU của container agent:**
  1. **Upstream LLM I/O latency (~98.9% tổng thời gian request):** Các container agent chỉ chạy async chờ upstream LLM trả về (`~120–180 ms` bình thường, `~1700 ms` cho 3% slow tail và 1% lỗi `503`). Tăng số instance agent **không làm LLM phản hồi nhanh hơn** hay hết tail latency/lỗi upstream.
  2. **Tốc độ phát tải bị giới hạn bởi kịch bản Locust (100 users, `wait_time = between(0.5, 2)`):** Mỗi user trung bình gửi ~1 request mỗi ~1.47 giây nên 100 users chỉ tạo tối đa ~65–66 req/s — mức tải mà 1 instance FastAPI async vẫn gánh được chưa bị bão hoà CPU.
- **Kết luận kỹ thuật:** Để cải thiện latency p95/p99 thực sự phải tối ưu ở tầng LLM (streaming token, semantic caching câu hỏi trùng, timeout + hedged/retry request, chọn model nhanh hơn). Scale ngang 3 instance vẫn rất quan trọng cho **High Availability (chịu lỗi khi 1 instance chết)** và **mở rộng ngưỡng chịu tải đỉnh (headroom)** khi lượng user đồng thời tăng gấp nhiều lần.

---

## 6. Kết luận

- **3 điều học được về benchmark & observability:**
  1. **Average che giấu sự cố — phải đo bằng percentile (`p95`/`p99`) và phân biệt rõ tải đồng thời với tải thực tế:** Chỉ cần 3% request chậm là `p99` đã tăng gấp ~7.6 lần trong khi `avg` gần như đứng yên; còn khi vượt ngưỡng bão hoà (`c=100` trên 1 process) thì throughput giảm ngược đồng thời p95 vọt gấp 15 lần.
  2. **Observability hạ tầng không thay thế được Benchmark chất lượng (Eval):** Metrics/Traces/Alerts (Prometheus, Grafana, Jaeger) giúp phát hiện nhanh lỗi 5xx, latency cao, đốt tiền LLM hay sập instance, nhưng hoàn toàn "mù" trước lỗi suy giảm chất lượng trả lời (như thí nghiệm E đổi sang `v1`). Bắt buộc phải có Golden Dataset + Quality Gate trong CI/CD.
  3. **Liên kết 3 trụ cột Metrics → Traces → Logs và giám sát từ bên ngoài (Edge/LB):** Khi dashboard Grafana báo bất thường, mở Jaeger tìm span chiếm 98.9% thời gian (`chat mock-llm-small`) rồi lấy `trace_id` tra log JSON giúp khoanh vùng nguyên nhân trong vài giây; đồng thời thí nghiệm `docker pause` cho thấy lỗi `504` ở Nginx không hiện trong metric nội bộ của agent nên production cần giám sát cả tầng Load Balancer và synthetic check từ ngoài.
- **Nếu đưa agent này lên production thật, sẽ thêm các metric / alert sau:**
  - **Metrics & Alerts ở tầng Edge / Load Balancer (Nginx / Ingress):** theo dõi HTTP `502`/`504`, `429` (rate limit) và `402` (budget exhausted) ở tầng proxy để không bỏ sót lỗi khi container agent bị treo.
  - **AI Quality & RAG Drift Metrics:** `agent_retrieval_hit_ratio` (alert nếu giảm đột ngột < 50%), phân bố `agent_question_length_chars` & `output_tokens` (phát hiện prompt injection hoặc response rỗng/cụt), điểm online eval (groundedness/hallucination rate) và tỉ lệ phản hồi tiêu cực từ user.
  - **Dependency & Resource Saturation Metrics:** Redis latency & connection errors, container CPU throttling / memory RSS / open file descriptors, và **LLM Time-To-First-Token (TTFT)** khi bật streaming.
  - **Error Budget Burn-Rate Alert (multi-window):** kết hợp cửa sổ ngắn (5 phút) và dài (1 giờ) gửi qua Alertmanager tới Slack/PagerDuty để vừa phát hiện sớm sự cố nghiêm trọng vừa tránh alert fatigue.
