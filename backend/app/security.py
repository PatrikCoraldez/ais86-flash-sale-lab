from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import re
import time
import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Any

from fastapi import Depends, Header, Request
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.datastructures import Headers, MutableHeaders
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from .config import Settings
from .db import PUBLIC_DATASET, Database, utcnow
from .models import Run

IDEMPOTENCY_KEY_PATTERN = re.compile(r"^[A-Za-z0-9_-]{8,80}$")

CSP_VALUE = (
    "default-src 'self'; base-uri 'self'; object-src 'none'; frame-ancestors 'none'; "
    "img-src 'self' data:; style-src 'self' 'unsafe-inline'; script-src 'self'; "
    "connect-src 'self'; font-src 'self' data:; form-action 'self'"
)


class ApiError(Exception):
    def __init__(
        self,
        status_code: int,
        code: str,
        message: str,
        details: Any | None = None,
        headers: dict[str, str] | None = None,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.message = message
        self.details = details
        self.headers = headers or {}


def error_payload(code: str, message: str, details: Any | None = None) -> dict[str, Any]:
    error: dict[str, Any] = {"code": code, "message": message}
    if details is not None:
        error["details"] = details
    return {"error": error}


def constant_time_equals(left: str, right: str) -> bool:
    left_digest = hashlib.sha256(left.encode("utf-8")).digest()
    right_digest = hashlib.sha256(right.encode("utf-8")).digest()
    return hmac.compare_digest(left_digest, right_digest)


def validate_idempotency_key(value: str | None) -> str:
    if value is None:
        raise ApiError(422, "VALIDATION_ERROR", "Idempotency-Key header is required")
    if not IDEMPOTENCY_KEY_PATTERN.fullmatch(value):
        raise ApiError(
            422,
            "VALIDATION_ERROR",
            "Idempotency-Key must contain 8 to 80 ASCII letters, digits, hyphens or underscores",
        )
    return value


def sanitize_validation_errors(errors: list[dict[str, Any]]) -> list[dict[str, Any]]:
    sanitized: list[dict[str, Any]] = []
    for error in errors[:20]:
        location = error.get("loc") or ()
        sanitized.append(
            {
                "loc": [str(part) for part in location],
                "msg": str(error.get("msg") or "Invalid value"),
                "type": str(error.get("type") or "value_error"),
            }
        )
    return sanitized


@dataclass(frozen=True)
class DatasetContext:
    dataset_id: str
    notification_delay_ms: int
    run_id: uuid.UUID | None


def get_database(request: Request) -> Database:
    return request.app.state.db


async def get_session(request: Request) -> AsyncIterator[AsyncSession]:
    database = get_database(request)
    async with database.session_factory() as session:
        yield session


def get_settings_from_request(request: Request) -> Settings:
    return request.app.state.settings


async def require_lab_key(
    request: Request,
    x_lab_key: str | None = Header(default=None, alias="X-Lab-Key"),
) -> None:
    settings = get_settings_from_request(request)
    if x_lab_key is None or not constant_time_equals(x_lab_key, settings.lab_key_value()):
        raise ApiError(401, "UNAUTHORIZED", "Lab authentication required")


async def dataset_context(
    request: Request,
    x_lab_run: str | None = Header(default=None, alias="X-Lab-Run"),
    x_lab_key: str | None = Header(default=None, alias="X-Lab-Key"),
) -> DatasetContext:
    if x_lab_run is None:
        return DatasetContext(dataset_id=PUBLIC_DATASET, notification_delay_ms=0, run_id=None)
    settings = get_settings_from_request(request)
    if x_lab_key is None or not constant_time_equals(x_lab_key, settings.lab_key_value()):
        raise ApiError(401, "UNAUTHORIZED", "Lab authentication required")
    try:
        run_uuid = uuid.UUID(x_lab_run)
    except (ValueError, AttributeError, TypeError):
        raise ApiError(404, "NOT_FOUND", "Run not found") from None
    database = get_database(request)
    async with database.session_factory() as session:
        run = await session.get(Run, run_uuid)
        if run is None or run.expires_at <= utcnow():
            raise ApiError(404, "NOT_FOUND", "Run not found")
        return DatasetContext(
            dataset_id=str(run.run_id),
            notification_delay_ms=run.notification_delay_ms,
            run_id=run.run_id,
        )


class RateLimiter:
    def __init__(self, window_seconds: float = 60.0) -> None:
        self.window_seconds = window_seconds
        self._entries: dict[str, tuple[float, int]] = {}
        self._lock = asyncio.Lock()

    async def allow(self, key: str, limit: int) -> bool:
        now = time.monotonic()
        async with self._lock:
            window_start, count = self._entries.get(key, (now, 0))
            if now - window_start >= self.window_seconds:
                window_start = now
                count = 0
            if count >= limit:
                self._entries[key] = (window_start, count)
                return False
            self._entries[key] = (window_start, count + 1)
            if len(self._entries) > 50000:
                cutoff = now - self.window_seconds * 2
                self._entries = {
                    entry_key: entry_value
                    for entry_key, entry_value in self._entries.items()
                    if entry_value[0] >= cutoff
                }
            return True


class _BodyTooLarge(StarletteHTTPException):
    def __init__(self) -> None:
        super().__init__(status_code=413, detail="Request body exceeds the allowed size")


class HardeningMiddleware:
    def __init__(self, app: ASGIApp, settings: Settings) -> None:
        self.app = app
        self.settings = settings
        self.limiter = RateLimiter()

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        path = scope.get("path", "")
        method = scope.get("method", "GET")
        client = scope.get("client")
        client_ip = client[0] if client else "unknown"

        if method != "OPTIONS" and (path.startswith("/api/") or path.startswith("/_lab/")):
            if path == "/api/v1/orders" and method == "POST":
                limit = self.settings.rate_limit_orders_per_minute
                bucket = "orders"
            else:
                limit = self.settings.rate_limit_api_per_minute
                bucket = "api"
            allowed = await self.limiter.allow(f"{client_ip}:{bucket}", limit)
            if not allowed:
                await self._send_json(
                    send,
                    429,
                    "RATE_LIMITED",
                    "Too many requests",
                    path,
                    {"Retry-After": "60"},
                )
                return

        declared_length = Headers(scope=scope).get("content-length")
        if declared_length is not None:
            try:
                declared = int(declared_length)
            except ValueError:
                declared = None
            if declared is not None and declared > self.settings.body_limit_bytes:
                await self._send_json(
                    send,
                    413,
                    "PAYLOAD_TOO_LARGE",
                    "Request body exceeds the allowed size",
                    path,
                )
                return

        received = 0
        started = False

        async def limited_receive() -> Message:
            nonlocal received
            message = await receive()
            if message["type"] == "http.request":
                received += len(message.get("body", b""))
                if received > self.settings.body_limit_bytes:
                    raise _BodyTooLarge()
            return message

        async def wrapped_send(message: Message) -> None:
            nonlocal started
            if message["type"] == "http.response.start":
                started = True
                headers = MutableHeaders(scope=message)
                self._apply_headers(headers, path)
            await send(message)

        try:
            await self.app(scope, limited_receive, wrapped_send)
        except _BodyTooLarge:
            if not started:
                await self._send_json(
                    send,
                    413,
                    "PAYLOAD_TOO_LARGE",
                    "Request body exceeds the allowed size",
                    path,
                )

    def _apply_headers(self, headers: MutableHeaders, path: str) -> None:
        for name, value in self._security_headers(path).items():
            headers.setdefault(name, value)

    def _security_headers(self, path: str) -> dict[str, str]:
        headers = {
            "X-Content-Type-Options": "nosniff",
            "X-Frame-Options": "DENY",
            "Referrer-Policy": "no-referrer",
            "Permissions-Policy": "camera=(), microphone=(), geolocation=()",
            "Cross-Origin-Resource-Policy": "same-origin",
        }
        if path.startswith("/api/") or path.startswith("/_lab/") or path in ("/healthz", "/readyz"):
            headers["Cache-Control"] = "no-store"
        else:
            headers["Content-Security-Policy"] = CSP_VALUE
        return headers

    async def _send_json(
        self,
        send: Send,
        status: int,
        code: str,
        message: str,
        path: str,
        extra_headers: dict[str, str] | None = None,
    ) -> None:
        body = json.dumps(error_payload(code, message), separators=(",", ":")).encode("utf-8")
        headers = {
            "content-type": "application/json",
            "content-length": str(len(body)),
            **self._security_headers(path),
        }
        if extra_headers:
            headers.update(extra_headers)
        await send(
            {
                "type": "http.response.start",
                "status": status,
                "headers": [(name.lower().encode("latin-1"), value.encode("latin-1")) for name, value in headers.items()],
            }
        )
        await send({"type": "http.response.body", "body": body})
