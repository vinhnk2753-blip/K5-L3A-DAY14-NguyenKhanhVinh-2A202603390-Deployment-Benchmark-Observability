"""
Production AI Agent — Part 6 Final Project.

Tích hợp đủ 12 tiêu chí production:
  - Config 12-Factor từ biến môi trường (app/config.py)
  - Structured JSON logging
  - Health (/health) và Readiness (/ready kiểm tra Redis)
  - API Key authentication (X-API-Key → 401)
  - Sliding-window rate limiting trong Redis (→ 429 + Retry-After)
  - Cost guard trong Redis (→ 402)
  - Graceful shutdown (lifespan + xử lý SIGTERM qua uvicorn)
  - Xử lý lỗi an toàn không lộ stack trace
"""
from contextlib import asynccontextmanager
from datetime import datetime, timezone
import json
import logging
import sys
import time
from typing import Optional

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from app.auth import verify_api_key
from app.config import settings
from app.cost_guard import check_budget, estimate_tokens, record_cost
from app.rate_limiter import check_rate_limit
from app.redis_client import close_redis, redis_healthy
from utils.mock_llm import ask as llm_ask


class JsonFormatter(logging.Formatter):
    """Định dạng mỗi dòng log của ứng dụng thành 1 JSON object hợp lệ."""

    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "lvl": record.levelname,
            "logger": record.name,
            "env": settings.environment,
        }
        if isinstance(record.msg, dict):
            payload.update(record.msg)
        else:
            payload["msg"] = record.getMessage()
        extra_fields = getattr(record, "extra_fields", None)
        if isinstance(extra_fields, dict):
            payload.update(extra_fields)
        if record.exc_info:
            payload["exc_type"] = record.exc_info[0].__name__ if record.exc_info[0] else "Exception"
        return json.dumps(payload, ensure_ascii=False)


def _setup_logger() -> logging.Logger:
    app_logger = logging.getLogger("production_agent")
    app_logger.setLevel(getattr(logging, settings.log_level, logging.INFO))
    app_logger.handlers.clear()
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter())
    app_logger.addHandler(handler)
    app_logger.propagate = False
    return app_logger


logger = _setup_logger()

START_TIME = time.time()
_is_shutting_down = False


def log_event(event: str, level: int = logging.INFO, **fields) -> None:
    logger.log(level, {"event": event, **fields})


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Quản lý vòng đời app: startup và graceful shutdown khi nhận SIGTERM."""
    global _is_shutting_down
    _is_shutting_down = False
    log_event(
        "startup",
        port=settings.port,
        environment=settings.environment,
        rate_limit_per_minute=settings.rate_limit_per_minute,
        daily_budget_usd=settings.daily_budget_usd,
        monthly_budget_usd=settings.monthly_budget_usd,
    )
    yield
    _is_shutting_down = True
    log_event("graceful_shutdown", reason="lifespan_shutdown_sigterm")
    close_redis()
    log_event("shutdown_complete")


app = FastAPI(
    title="Production AI Agent",
    version="1.0.0",
    lifespan=lifespan,
    docs_url="/docs" if settings.environment != "production" else None,
)


@app.middleware("http")
async def request_logging_middleware(request: Request, call_next):
    start = time.perf_counter()
    status_code = 500
    try:
        response = await call_next(request)
        status_code = response.status_code
        return response
    finally:
        elapsed_ms = round((time.perf_counter() - start) * 1000, 2)
        log_event(
            "http_request",
            method=request.method,
            path=request.url.path,
            status=status_code,
            ms=elapsed_ms,
        )


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    """Không để lộ stack trace ra response client."""
    log_event(
        "unhandled_error",
        level=logging.ERROR,
        path=request.url.path,
        error_type=type(exc).__name__,
    )
    return JSONResponse(
        status_code=500,
        content={"detail": "Internal server error"},
    )


class AskRequest(BaseModel):
    question: str = Field(..., min_length=1, max_length=2000)
    user_id: Optional[str] = Field(default=None, max_length=128)


@app.get("/health")
def health():
    """Liveness probe: luôn trả 200 khi process còn chạy, kể cả khi Redis mất kết nối."""
    return {
        "status": "ok",
        "environment": settings.environment,
        "uptime_seconds": round(time.time() - START_TIME, 1),
    }


@app.get("/ready")
def ready():
    """Readiness probe: 200 khi sẵn sàng, 503 khi đang tắt hoặc Redis không kết nối được."""
    if _is_shutting_down or not redis_healthy():
        raise HTTPException(status_code=503, detail="Service not ready: Redis unavailable")
    return {
        "status": "ready",
        "redis": "connected",
        "environment": settings.environment,
    }


@app.post("/ask")
def ask(body: AskRequest, api_key: str = Depends(verify_api_key)):
    """Endpoint chính: xác thực API key → kiểm rate limit → kiểm budget → gọi LLM → ghi cost."""
    check_rate_limit(api_key)
    check_budget()

    answer = llm_ask(body.question)
    input_tokens = estimate_tokens(body.question)
    output_tokens = estimate_tokens(answer)
    cost_usd = record_cost(input_tokens, output_tokens)

    log_event(
        "ask_completed",
        user_id=body.user_id or "anonymous",
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        cost_usd=round(cost_usd, 6),
    )

    return {
        "question": body.question,
        "answer": answer,
        "environment": settings.environment,
        "usage": {
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "cost_usd": round(cost_usd, 8),
        },
    }
