"""
Kết nối Redis dùng chung cho rate limiter và cost guard.

App vẫn khởi động được khi Redis chưa sẵn sàng (không ping lúc import).
"""
from typing import Optional

import redis

from app.config import settings

r: Optional[redis.Redis] = (
    redis.from_url(
        settings.redis_url,
        decode_responses=True,
        socket_connect_timeout=1.5,
        socket_timeout=1.5,
    )
    if settings.redis_url
    else None
)


def get_redis() -> redis.Redis:
    """Trả về Redis client dùng chung."""
    if r is None:
        raise redis.ConnectionError("REDIS_URL is not configured")
    return r


def redis_healthy() -> bool:
    """Kiểm tra kết nối Redis cho GET /ready."""
    if r is None:
        return False
    try:
        return bool(r.ping())
    except Exception:
        return False


def close_redis() -> None:
    """Đóng connection pool Redis khi shutdown."""
    if r is not None:
        try:
            r.close()
        except Exception:
            pass
