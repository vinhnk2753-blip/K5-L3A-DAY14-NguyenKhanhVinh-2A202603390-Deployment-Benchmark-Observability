# Deployment Information

## Public URL

https://k5-day14-production-agent-jhq5.onrender.com

## Platform

**Render** (Blueprint managed từ `render.yaml` / `06-lab-complete/render.yaml`, Region: `singapore`, Plan: `free`):
- Web Service: `k5-day14-production-agent` (Runtime: `Docker`, build từ `06-lab-complete/Dockerfile`, Health check: `/health`)
- Managed Redis: `k5-day14-agent-redis` (Valkey 8 / Redis compatible, private internal network, gắn tự động vào `REDIS_URL` qua `fromService`)

## Test Commands (CP6 Self-Test)

Đặt biến môi trường `BASE` và `AGENT_API_KEY` (lấy trên Render Dashboard → Environment; không ghi key thật vào code/repo):

```bash
export BASE="https://k5-day14-production-agent-jhq5.onrender.com"
export AGENT_API_KEY="YOUR_AGENT_API_KEY"

# 1. Health check (liveness) -> 200
curl -sS -o /dev/null -w '%{http_code}\n' "$BASE/health"

# 2. Readiness check (kiểm tra kết nối Redis trên Render) -> 200
curl -sS -o /dev/null -w '%{http_code}\n' "$BASE/ready"

# 3. Authentication required (không có X-API-Key) -> 401
curl -sS -o /dev/null -w '%{http_code}\n' -X POST "$BASE/ask" \
  -H 'Content-Type: application/json' \
  -d '{"question":"Hello"}'

# 4. API test (có X-API-Key hợp lệ) -> 200
curl -sS -o /dev/null -w '%{http_code}\n' -X POST "$BASE/ask" \
  -H 'Content-Type: application/json' \
  -H "X-API-Key: $AGENT_API_KEY" \
  -d '{"question":"Hello"}'
```

### Detailed API Test Examples

#### Health & Readiness
```bash
curl -sS https://k5-day14-production-agent-jhq5.onrender.com/health
# {"status":"ok","environment":"production","uptime_seconds":389.9}

curl -sS https://k5-day14-production-agent-jhq5.onrender.com/ready
# {"status":"ready","redis":"connected","environment":"production"}
```

#### Authenticated Request
```bash
curl -sS -X POST https://k5-day14-production-agent-jhq5.onrender.com/ask \
  -H "X-API-Key: $AGENT_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"user_id": "test", "question": "Hello"}'
# {"question":"Hello","answer":"Đây là câu trả lời từ AI agent (mock). Trong production, đây sẽ là response từ OpenAI/Anthropic.","environment":"production","usage":{"input_tokens":1,"output_tokens":24,"cost_usd":1.455e-05}}
```

#### Validation Error (no stack trace leaked)
```bash
curl -sS -i -X POST https://k5-day14-production-agent-jhq5.onrender.com/ask \
  -H "X-API-Key: $AGENT_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"invalid": "data"}'
# HTTP/1.1 422 Unprocessable Entity
```

> **Lưu ý Free Tier của Render:** Instance free sẽ ngủ đông (spin down) sau ~15 phút không có traffic; request đầu tiên đánh thức container có thể mất ~30–50 giây trước khi trả 200 bình thường.

## Environment Variables Set (trên Render Dashboard / Blueprint)

- `PORT` (Render tự cấp động — Dockerfile lắng nghe `${PORT:-8000}`)
- `ENVIRONMENT` (`production`)
- `LOG_LEVEL` (`INFO`)
- `AGENT_API_KEY` (tự sinh bằng `generateValue: true` trên Render, không commit vào Git)
- `REDIS_URL` (tự liên kết từ service `k5-day14-agent-redis` qua `fromService.connectionString`)
- `RATE_LIMIT_PER_MINUTE` (`10`)
- `DAILY_BUDGET_USD` (`1.0`)
- `MONTHLY_BUDGET_USD` (`10.0`)

## Screenshots

- [Deployment dashboard](screenshots/dashboard.png)
- [Service running (Live)](screenshots/running.png)
- [CP6 test results (`200 / 200 / 401 / 200`)](screenshots/test.png)
