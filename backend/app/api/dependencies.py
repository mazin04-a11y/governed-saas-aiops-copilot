import time
from collections import defaultdict, deque

from fastapi import Header, HTTPException, Request, status

from app.core.config import get_settings

_request_windows: dict[str, deque[float]] = defaultdict(deque)


def require_ingest_api_key(x_api_key: str | None = Header(default=None)) -> None:
    keys = get_settings().api_key_set
    if keys and x_api_key not in keys:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="valid X-API-Key required")


def rate_limit(request: Request) -> None:
    settings = get_settings()
    actor = request.headers.get("x-api-key") or request.client.host if request.client else "unknown"
    now = time.monotonic()
    window = _request_windows[actor]
    while window and now - window[0] > settings.rate_limit_window_seconds:
        window.popleft()
    if len(window) >= settings.rate_limit_requests:
        raise HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail="rate limit exceeded")
    window.append(now)

