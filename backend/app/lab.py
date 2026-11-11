from __future__ import annotations

import hashlib
import uuid
from datetime import timedelta
from typing import Any

from fastapi import APIRouter, Depends, Request, Response
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from .db import PRODUCT_SEED, Database, utcnow
from .events import delete_run, iso8601, purge_expired_runs
from .models import EventRecord, Notification, Order, Product, Run
from .schemas import LabRunCreate
from .security import ApiError, get_session, require_lab_key

router = APIRouter(prefix="/_lab", dependencies=[Depends(require_lab_key)])

RUN_CREATION_LOCK = int.from_bytes(
    hashlib.sha256(b"flash-sale:lab:runs").digest()[:8],
    "big",
    signed=True,
)


def _parse_run_id(value: str) -> uuid.UUID:
    try:
        return uuid.UUID(value)
    except (ValueError, AttributeError, TypeError):
        raise ApiError(404, "NOT_FOUND", "Run not found") from None


def _get_database(request: Request) -> Database:
    return request.app.state.db


@router.post("/runs", status_code=201)
async def create_run(
    payload: LabRunCreate,
    request: Request,
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    database = _get_database(request)
    await purge_expired_runs(database.session_factory, database.settings)
    now = utcnow()
    run_id = uuid.uuid4()
    expires_at = now + timedelta(seconds=database.settings.run_ttl_seconds)

    async with session.begin():
        await session.execute(
            text("SELECT pg_advisory_xact_lock(:lock_key)"),
            {"lock_key": RUN_CREATION_LOCK},
        )
        active_runs = await session.scalar(
            select(func.count()).select_from(Run).where(Run.expires_at > now)
        )
        if active_runs is not None and active_runs >= database.settings.max_active_runs:
            raise ApiError(429, "RATE_LIMITED", "Active run limit reached")

        session.add(
            Run(
                run_id=run_id,
                stock=payload.stock,
                notification_delay_ms=payload.notification_delay_ms,
                created_at=now,
                expires_at=expires_at,
            )
        )
        for seed in PRODUCT_SEED:
            session.add(
                Product(
                    dataset_id=str(run_id),
                    id=seed["id"],
                    name=seed["name"],
                    description=seed["description"],
                    category=seed["category"],
                    price_cents=seed["price_cents"],
                    original_price_cents=seed["original_price_cents"],
                    stock=payload.stock,
                    image=seed["image"],
                    sort_order=seed["sort_order"],
                )
            )

    return {"run_id": str(run_id), "expires_at": iso8601(expires_at)}


@router.get("/runs/{run_id}")
async def get_run(
    run_id: str,
    request: Request,
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    identifier = _parse_run_id(run_id)
    database = _get_database(request)
    run = await session.get(Run, identifier)
    if run is None:
        raise ApiError(404, "NOT_FOUND", "Run not found")
    if run.expires_at <= utcnow():
        await delete_run(database.session_factory, identifier)
        raise ApiError(404, "NOT_FOUND", "Run not found")

    dataset_id = str(run.run_id)
    products = (
        await session.execute(
            select(Product)
            .where(Product.dataset_id == dataset_id)
            .order_by(Product.sort_order, Product.id)
        )
    ).scalars().all()
    orders = (
        await session.execute(
            select(Order)
            .where(Order.dataset_id == dataset_id)
            .order_by(Order.created_at.desc())
            .limit(200)
        )
    ).scalars().all()
    events = (
        await session.execute(
            select(EventRecord)
            .where(EventRecord.dataset_id == dataset_id)
            .order_by(EventRecord.created_at.desc())
            .limit(200)
        )
    ).scalars().all()
    notifications = (
        await session.execute(
            select(Notification)
            .where(Notification.dataset_id == dataset_id)
            .order_by(Notification.created_at.desc())
            .limit(200)
        )
    ).scalars().all()

    order_objects: list[dict[str, Any]] = []
    for order in orders:
        snapshot = dict(order.snapshot)
        snapshot["notification_status"] = order.notification_status
        order_objects.append(snapshot)

    event_objects: list[dict[str, Any]] = []
    for event in events:
        item: dict[str, Any] = {
            "event_id": str(event.event_id),
            "payload": event.payload,
            "status": event.status,
        }
        if event.error is not None:
            item["error"] = event.error
        event_objects.append(item)

    return {
        "run_id": dataset_id,
        "products": [{"id": product.id, "stock": product.stock} for product in products],
        "orders": order_objects,
        "events": event_objects,
        "notifications": [
            {"order_id": str(notification.order_id), "event_id": str(notification.event_id)}
            for notification in notifications
        ],
        "notification_delay_ms": run.notification_delay_ms,
    }


@router.delete("/runs/{run_id}", status_code=204)
async def remove_run(
    run_id: str,
    request: Request,
) -> Response:
    identifier = _parse_run_id(run_id)
    database = _get_database(request)
    deleted = await delete_run(database.session_factory, identifier)
    if not deleted:
        raise ApiError(404, "NOT_FOUND", "Run not found")
    return Response(status_code=204)
