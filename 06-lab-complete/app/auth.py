"""
API Key authentication (tiêu chí 6).

Client gửi header X-API-Key: <key> trùng với biến môi trường AGENT_API_KEY.
Thiếu hoặc sai key → HTTP 401.
"""
import secrets
from typing import Optional

from fastapi import HTTPException, Security
from fastapi.security.api_key import APIKeyHeader

from app.config import settings

api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)


def verify_api_key(api_key: Optional[str] = Security(api_key_header)) -> str:
    """Dependency cho FastAPI — xác thực header X-API-Key."""
    expected = settings.agent_api_key
    if not expected or not api_key or not secrets.compare_digest(api_key, expected):
        raise HTTPException(
            status_code=401,
            detail="Invalid or missing API key",
            headers={"WWW-Authenticate": "ApiKey"},
        )
    return api_key
