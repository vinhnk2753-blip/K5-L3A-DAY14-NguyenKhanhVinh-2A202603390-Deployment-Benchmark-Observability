"""
Cost guard (tiêu chí 8) — Cộng dồn chi phí LLM trong Redis.

Tổng chi phí vượt DAILY_BUDGET_USD hoặc MONTHLY_BUDGET_USD → HTTP 402.
"""
from datetime import datetime, timezone

from fastapi import HTTPException
from redis.exceptions import RedisError

from app.config import settings
from app.redis_client import get_redis

# Giá USD / 1K tokens (tham khảo gpt-4o-mini)
PRICE_INPUT_PER_1K = 0.00015
PRICE_OUTPUT_PER_1K = 0.0006

DAILY_TTL_SECONDS = 2 * 24 * 3600
MONTHLY_TTL_SECONDS = 35 * 24 * 3600


def _budget_keys(scope: str = "global") -> tuple[str, str]:
    now = datetime.now(timezone.utc)
    day_key = f"cost:daily:{scope}:{now.strftime('%Y-%m-%d')}"
    month_key = f"cost:monthly:{scope}:{now.strftime('%Y-%m')}"
    return day_key, month_key


def estimate_tokens(text: str) -> int:
    """Ước lượng số token (~4 ký tự / token)."""
    return max(1, len(text) // 4)


def check_budget(scope: str = "global") -> None:
    """Gọi TRƯỚC khi gọi LLM. Hết budget → raise HTTPException(status_code=402)."""
    day_key, month_key = _budget_keys(scope)
    try:
        client = get_redis()
        daily_spent = float(client.get(day_key) or 0.0)
        monthly_spent = float(client.get(month_key) or 0.0)
    except RedisError:
        raise HTTPException(
            status_code=503,
            detail="Cost guard storage unavailable",
        )

    if daily_spent >= settings.daily_budget_usd:
        raise HTTPException(
            status_code=402,
            detail={
                "error": "Daily budget exceeded",
                "spent_usd": round(daily_spent, 6),
                "daily_budget_usd": settings.daily_budget_usd,
            },
        )

    if monthly_spent >= settings.monthly_budget_usd:
        raise HTTPException(
            status_code=402,
            detail={
                "error": "Monthly budget exceeded",
                "spent_usd": round(monthly_spent, 6),
                "monthly_budget_usd": settings.monthly_budget_usd,
            },
        )


def record_cost(input_tokens: int, output_tokens: int, scope: str = "global") -> float:
    """Gọi SAU khi gọi LLM. Cộng chi phí request vào Redis, trả về chi phí request (USD)."""
    cost = (
        (input_tokens / 1000.0) * PRICE_INPUT_PER_1K
        + (output_tokens / 1000.0) * PRICE_OUTPUT_PER_1K
    )
    day_key, month_key = _budget_keys(scope)
    try:
        client = get_redis()
        pipe = client.pipeline()
        pipe.incrbyfloat(day_key, cost)
        pipe.expire(day_key, DAILY_TTL_SECONDS)
        pipe.incrbyfloat(month_key, cost)
        pipe.expire(month_key, MONTHLY_TTL_SECONDS)
        pipe.execute()
    except RedisError:
        pass
    return cost
