import base64
import hashlib
import hmac
import json
import time
from collections import defaultdict, deque
from typing import Any

from fastapi import Header, HTTPException, Request, status

from app.core.config import get_settings

_request_windows: dict[str, deque[float]] = defaultdict(deque)
DEFAULT_PROJECT_ID = "default"


def require_ingest_api_key(x_api_key: str | None = Header(default=None)) -> None:
    keys = get_settings().api_key_set
    if keys and x_api_key not in keys:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="valid X-API-Key required")


def get_project_id(x_project_id: str | None = Header(default=None)) -> str:
    project_id = (x_project_id or DEFAULT_PROJECT_ID).strip()
    if not project_id:
        return DEFAULT_PROJECT_ID
    if len(project_id) > 80 or not all(char.isalnum() or char in {"-", "_"} for char in project_id):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="invalid X-Project-ID")
    return project_id


def require_operator_api_key(x_api_key: str | None = Header(default=None)) -> None:
    settings = get_settings()
    keys = settings.operator_key_set
    if keys and x_api_key in keys:
        return
    if settings.operator_password:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="valid operator credentials required")
    if keys:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="valid operator X-API-Key required")


def require_operator_session(
    authorization: str | None = Header(default=None),
    x_api_key: str | None = Header(default=None),
) -> dict[str, Any] | None:
    settings = get_settings()
    keys = settings.operator_key_set
    if keys and x_api_key in keys:
        return {"sub": "operator-api-key", "auth_type": "api_key"}
    if not settings.operator_password:
        if keys:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="valid operator X-API-Key required")
        return None
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="operator bearer token required")
    return verify_operator_token(authorization.split(" ", 1)[1])


def create_operator_token(username: str) -> str:
    settings = get_settings()
    payload = {"sub": username, "exp": int(time.time()) + settings.operator_session_ttl_seconds}
    payload_bytes = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
    encoded_payload = _base64url_encode(payload_bytes)
    signature = _sign(encoded_payload.encode("ascii"), settings.operator_session_secret)
    return f"{encoded_payload}.{signature}"


def verify_operator_token(token: str) -> dict[str, Any]:
    settings = get_settings()
    try:
        encoded_payload, signature = token.split(".", 1)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid operator token") from exc
    expected = _sign(encoded_payload.encode("ascii"), settings.operator_session_secret)
    if not hmac.compare_digest(signature, expected):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid operator token")
    try:
        payload = json.loads(_base64url_decode(encoded_payload))
    except (ValueError, json.JSONDecodeError) as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid operator token") from exc
    if int(payload.get("exp", 0)) < int(time.time()):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="operator token expired")
    return payload


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


def _sign(payload: bytes, secret: str) -> str:
    return _base64url_encode(hmac.new(secret.encode("utf-8"), payload, hashlib.sha256).digest())


def _base64url_encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode("ascii").rstrip("=")


def _base64url_decode(value: str) -> bytes:
    padding = "=" * (-len(value) % 4)
    return base64.urlsafe_b64decode(f"{value}{padding}")
