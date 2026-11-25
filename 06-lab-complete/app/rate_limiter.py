"""
Rate limiting (tiêu chí 7) — Sliding Window dùng Redis Sorted Set.

Mỗi API key tối đa RATE_LIMIT_PER_MINUTE request trong 60 giây.
Vượt giới hạn → HTTP 429 kèm header Retry-After.
State lưu trong Redis nên dùng chung giữa nhiều worker/instance và bền qua restart.
"""
import hashlib
import time
import uuid

from fastapi import HTTPException
from redis.exceptions import RedisError

from app.config import settings
from app.redis_client import get_redis

WINDOW_SECONDS = 60


def _key_hash(raw_key: str) -> str:
    """Hash API key trước khi dùng làm Redis key để tránh lưu secret dạng plain text."""
    return hashlib.sha256(raw_key.encode("utf-8")).hexdigest()[:24]


def check_rate_limit(key: str) -> None:
    """Kiểm tra và ghi nhận request theo sliding window 60 giây trong Redis."""
    limit = settings.rate_limit_per_minute
    now = time.time()
    window_start = now - WINDOW_SECONDS
    redis_key = f"ratelimit:{_key_hash(key)}"

    try:
        client = get_redis()
        pipe = client.pipeline()
        pipe.zremrangebyscore(redis_key, 0, window_start)
        pipe.zcard(redis_key)
        _, current_count = pipe.execute()

        if current_count >= limit:
            oldest = client.zrange(redis_key, 0, 0, withscores=True)
            if oldest:
                retry_after = max(1, int(oldest[0][1] + WINDOW_SECONDS - now) + 1)
            else:
                retry_after = WINDOW_SECONDS
            raise HTTPException(
                status_code=429,
                detail={
                    "error": "Rate limit exceeded",
                    "limit_per_minute": limit,
                    "retry_after_seconds": retry_after,
                },
                headers={
                    "Retry-After": str(retry_after),
                    "X-RateLimit-Limit": str(limit),
                    "X-RateLimit-Remaining": "0",
                },
            )

        member = f"{now}:{uuid.uuid4().hex}"
        pipe = client.pipeline()
        pipe.zadd(redis_key, {member: now})
        pipe.expire(redis_key, WINDOW_SECONDS + 5)
        pipe.execute()
    except HTTPException:
        raise
    except RedisError:
        raise HTTPException(
            status_code=503,
            detail="Rate limiter storage unavailable",
        )
