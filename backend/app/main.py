from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, AsyncIterator

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.staticfiles import StaticFiles

from .config import get_settings
from .db import Database
from .events import create_redis
from .lab import router as lab_router
from .orders import router as orders_router
from .security import (
    ApiError,
    HardeningMiddleware,
    error_payload,
    sanitize_validation_errors,
)

logger = logging.getLogger(__name__)

settings = get_settings()


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    database = Database(settings)
    redis_client = create_redis(settings)
    app.state.settings = settings
    app.state.db = database
    app.state.redis = redis_client
    await database.initialize()
    try:
        yield
    finally:
        await redis_client.aclose()
        await database.close()


docs_url = "/docs" if settings.enable_docs else None
redoc_url = "/redoc" if settings.enable_docs else None
openapi_url = "/openapi.json" if settings.enable_docs else None

app = FastAPI(
    title="Flash Sale",
    version="1.0.0",
    docs_url=docs_url,
    redoc_url=redoc_url,
    openapi_url=openapi_url,
    lifespan=lifespan,
)

app.add_middleware(HardeningMiddleware, settings=settings)
app.include_router(orders_router)
app.include_router(lab_router)


@app.exception_handler(ApiError)
async def api_error_handler(request: Request, exc: ApiError) -> JSONResponse:
    return JSONResponse(
        status_code=exc.status_code,
        content=error_payload(exc.code, exc.message, exc.details),
        headers=exc.headers,
    )


@app.exception_handler(RequestValidationError)
async def validation_error_handler(
    request: Request,
    exc: RequestValidationError,
) -> JSONResponse:
    return JSONResponse(
        status_code=422,
        content=error_payload(
            "VALIDATION_ERROR",
            "Request validation failed",
            sanitize_validation_errors(exc.errors()),
        ),
    )


@app.exception_handler(StarletteHTTPException)
async def http_error_handler(
    request: Request,
    exc: StarletteHTTPException,
) -> JSONResponse:
    codes = {
        401: "UNAUTHORIZED",
        403: "FORBIDDEN",
        404: "NOT_FOUND",
        405: "METHOD_NOT_ALLOWED",
        413: "PAYLOAD_TOO_LARGE",
        429: "RATE_LIMITED",
    }
    message = exc.detail if isinstance(exc.detail, str) else "Request failed"
    if exc.status_code == 404 and message == "Not Found":
        message = "Not found"
    return JSONResponse(
        status_code=exc.status_code,
        content=error_payload(codes.get(exc.status_code, "HTTP_ERROR"), message),
        headers=exc.headers,
    )


@app.exception_handler(Exception)
async def unhandled_error_handler(request: Request, exc: Exception) -> JSONResponse:
    logger.error("unhandled error type=%s", type(exc).__name__)
    return JSONResponse(
        status_code=500,
        content=error_payload("INTERNAL_ERROR", "Internal server error"),
    )


@app.get("/healthz")
async def healthz() -> dict[str, Any]:
    return {
        "status": "ok",
        "service": "flash-sale",
        "protocol": "ais86.s09.v1",
        "instance_id": settings.instance_id,
    }


@app.get("/readyz")
async def readyz(request: Request) -> JSONResponse:
    checks: dict[str, str] = {}
    try:
        await asyncio.wait_for(request.app.state.db.ping(), timeout=3)
        checks["database"] = "ok"
    except Exception:
        checks["database"] = "down"
    try:
        await asyncio.wait_for(request.app.state.redis.ping(), timeout=3)
        checks["redis"] = "ok"
    except Exception:
        checks["redis"] = "down"

    ready = all(value == "ok" for value in checks.values())
    return JSONResponse(
        status_code=200 if ready else 503,
        content={"status": "ready" if ready else "not_ready", "checks": checks},
    )


frontend_dist = Path(settings.frontend_dist)
if frontend_dist.is_dir():
    app.mount("/", StaticFiles(directory=str(frontend_dist), html=True), name="frontend")
