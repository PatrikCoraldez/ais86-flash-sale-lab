from __future__ import annotations

import asyncio
import json
import logging
import re
import uuid
from datetime import datetime, timezone
from typing import Any

from redis.asyncio import Redis
from redis.exceptions import ResponseError
from sqlalchemy import delete, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from .config import Settings
from .db import PUBLIC_DATASET, utcnow
from .models import EventRecord, Notification, Order, OrderItem, Outbox, Product, Run

logger = logging.getLogger(__name__)

EVENT_SOURCE = "/services/orders"
EVENT_TYPE = "pe.unamba.flash.order.created.v1"
PRODUCT_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$")


def iso8601(value: datetime) -> str:
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")

def build_order_created_event(
    order_id: uuid.UUID,
    customer_id: str,
    items: list[dict[str, Any]],
    total_cents: int,
    created_at: datetime,
) -> dict[str, Any]:
    return {
        "specversion": "1.0",
        "id": str(uuid.uuid4()),
        "source": EVENT_SOURCE,
        "type": EVENT_TYPE,
        "time": iso8601(created_at),
        "datacontenttype": "application/json",
        "data": {
            "order_id": str(order_id),
            "customer_id": customer_id,
            "items": [
                {
                    "product_id": item["product_id"],
                    "name": item["name"],
                    "quantity": item["quantity"],
                    "unit_price_cents": item["unit_price_cents"],
                }
                for item in items
            ],
            "total_cents": total_cents,
            "created_at": iso8601(created_at),
        },
    }

def _parse_uuid(value: Any) -> uuid.UUID | None:
    if not isinstance(value, str):
        return None
    try:
        return uuid.UUID(value)
    except (ValueError, AttributeError):
        return None


def _parse_time(value: Any) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def validate_cloud_event(payload: Any) -> list[str]:
    if not isinstance(payload, dict):
        return ["payload must be a JSON object"]

    errors: list[str] = []

    if payload.get("specversion") != "1.0":
        errors.append("specversion must be 1.0")
    if _parse_uuid(payload.get("id")) is None:
        errors.append("id must be a UUID")
    if payload.get("source") != EVENT_SOURCE:
        errors.append("source is invalid")
    if payload.get("type") != EVENT_TYPE:
        errors.append("type is invalid")
    if _parse_time(payload.get("time")) is None:
        errors.append("time must be an ISO8601 timestamp")
    if payload.get("datacontenttype") != "application/json":
        errors.append("datacontenttype must be application/json")

    data = payload.get("data")
    if not isinstance(data, dict):
        errors.append("data must be an object")
        return errors

    if _parse_uuid(data.get("order_id")) is None:
        errors.append("data.order_id must be a UUID")

    items = data.get("items")
    if not isinstance(items, list):
        errors.append("data.items must be an array")
    elif not 1 <= len(items) <= 6:
        errors.append("data.items must contain between 1 and 6 items")
    else:
        seen: set[str] = set()
        for index, item in enumerate(items):
            if not isinstance(item, dict):
                errors.append(f"data.items[{index}] must be an object")
                continue
            product_id = item.get("product_id")
            if not isinstance(product_id, str) or not PRODUCT_ID_PATTERN.fullmatch(product_id):
                errors.append(f"data.items[{index}].product_id is invalid")
            elif product_id in seen:
                errors.append(f"data.items[{index}].product_id is duplicated")
            else:
                seen.add(product_id)
            quantity = item.get("quantity")
            if type(quantity) is not int or not 1 <= quantity <= 5:
                errors.append(f"data.items[{index}].quantity must be an integer between 1 and 5")

    total_cents = data.get("total_cents")
    if type(total_cents) is not int or total_cents < 0:
        errors.append("data.total_cents must be an integer greater than or equal to 0")

    return errors


def create_redis(settings: Settings) -> Redis:
    return Redis.from_url(
        settings.redis_url,
        decode_responses=True,
        socket_connect_timeout=5,
        socket_timeout=15,
        health_check_interval=30,
    )


async def ensure_consumer_group(client: Redis, settings: Settings) -> None:
    try:
        await client.xgroup_create(
            settings.stream_name,
            settings.consumer_group,
            id="0",
            mkstream=True,
        )
    except ResponseError as exc:
        if "BUSYGROUP" not in str(exc):
            raise


async def publish_outbox_batch(
    session_factory: async_sessionmaker[AsyncSession],
    client: Redis,
    settings: Settings,
    batch_size: int | None = None,
) -> int:
    limit = batch_size or settings.outbox_batch_size
    published = 0
    async with session_factory() as session:
        async with session.begin():
            rows = (
                await session.execute(
                    select(Outbox)
                    .where(Outbox.status == "pending")
                    .order_by(Outbox.id)
                    .limit(limit)
                    .with_for_update(skip_locked=True)
                )
            ).scalars().all()

            for row in rows:
                body = json.dumps(row.payload, separators=(",", ":"), ensure_ascii=False)
                await client.xadd(
                    settings.stream_name,
                    {"payload": body},
                    maxlen=settings.stream_maxlen,
                    approximate=True,
                )
                row.status = "published"
                row.published_at = utcnow()
                await session.execute(
                    pg_insert(EventRecord)
                    .values(
                        event_id=row.event_id,
                        dataset_id=row.dataset_id,
                        order_id=row.order_id,
                        payload=row.payload,
                        status="published",
                        created_at=utcnow(),
                    )
                    .on_conflict_do_nothing(index_elements=["event_id"])
                )
                published += 1
    return published


async def _upsert_event(
    session: AsyncSession,
    event_id: uuid.UUID,
    dataset_id: str,
    order_id: uuid.UUID | None,
    payload: dict[str, Any],
    status: str,
    error: str | None,
) -> None:
    await session.execute(
        pg_insert(EventRecord)
        .values(
            event_id=event_id,
            dataset_id=dataset_id,
            order_id=order_id,
            payload=payload,
            status=status,
            error=error,
            created_at=utcnow(),
            processed_at=utcnow(),
        )
        .on_conflict_do_update(
            index_elements=["event_id"],
            set_={
                "dataset_id": dataset_id,
                "order_id": order_id,
                "payload": payload,
                "status": status,
                "error": error,
                "processed_at": utcnow(),
            },
        )
    )


async def _mark_rejected(
    session_factory: async_sessionmaker[AsyncSession],
    event_id: uuid.UUID | None,
    order_id: uuid.UUID | None,
    payload: Any,
    error: str,
) -> None:
    if event_id is None:
        logger.warning("event rejected without usable id")
        return
    async with session_factory() as session:
        async with session.begin():
            dataset_id = "orphan"
            if order_id is not None:
                order = await session.get(Order, order_id)
                if order is not None:
                    dataset_id = order.dataset_id
                    await session.execute(
                        update(Order)
                        .where(Order.id == order_id, Order.notification_status != "sent")
                        .values(notification_status="failed")
                    )
            await _upsert_event(
                session,
                event_id,
                dataset_id,
                order_id,
                payload if isinstance(payload, dict) else {"invalid_payload": True},
                "rejected",
                error[:1000],
            )


async def _process_valid_event(
    session_factory: async_sessionmaker[AsyncSession],
    event_id: uuid.UUID,
    order_id: uuid.UUID,
    payload: dict[str, Any],
    settings: Settings,
) -> None:
    async with session_factory() as session:
        order = await session.get(Order, order_id)
        if order is None:
            logger.warning("event for unknown order")
            return
        dataset_id = order.dataset_id

        delay_ms = 0
        if dataset_id != PUBLIC_DATASET:
            try:
                run_id = uuid.UUID(dataset_id)
            except ValueError:
                await _upsert_event(
                    session,
                    event_id,
                    dataset_id,
                    order_id,
                    payload,
                    "rejected",
                    "run is invalid",
                )
                await session.commit()
                return
            run = await session.get(Run, run_id)
            if run is None or run.expires_at <= utcnow():
                return
            delay_ms = run.notification_delay_ms

    if delay_ms > 0:
        await asyncio.sleep(delay_ms / 1000)

    async with session_factory() as session:
        async with session.begin():
            order = await session.get(Order, order_id)
            if order is None:
                return
            dataset_id = order.dataset_id
            if dataset_id != PUBLIC_DATASET:
                try:
                    run_id = uuid.UUID(dataset_id)
                except ValueError:
                    return
                run = await session.get(Run, run_id)
                if run is None or run.expires_at <= utcnow():
                    return
            await session.execute(
                pg_insert(Notification)
                .values(
                    dataset_id=dataset_id,
                    order_id=order_id,
                    event_id=event_id,
                    created_at=utcnow(),
                )
                .on_conflict_do_nothing(index_elements=["dataset_id", "order_id"])
            )
            await session.execute(
                update(Order)
                .where(Order.id == order_id)
                .values(notification_status="sent")
            )
            await _upsert_event(
                session,
                event_id,
                dataset_id,
                order_id,
                payload,
                "processed",
                None,
            )


async def handle_stream_message(
    message_id: str,
    fields: dict[str, Any],
    session_factory: async_sessionmaker[AsyncSession],
    client: Redis,
    settings: Settings,
) -> bool:
    raw = fields.get("payload")
    if not isinstance(raw, str):
        logger.warning("stream message without payload")
        await client.xack(settings.stream_name, settings.consumer_group, message_id)
        return True

    try:
        payload = json.loads(raw)
    except (ValueError, TypeError):
        logger.warning("stream message with invalid json")
        await client.xack(settings.stream_name, settings.consumer_group, message_id)
        return True

    event_id = _parse_uuid(payload.get("id")) if isinstance(payload, dict) else None
    data = payload.get("data") if isinstance(payload, dict) else None
    order_id = _parse_uuid(data.get("order_id")) if isinstance(data, dict) else None

    errors = validate_cloud_event(payload)
    if errors:
        await _mark_rejected(session_factory, event_id, order_id, payload, "; ".join(errors))
        await client.xack(settings.stream_name, settings.consumer_group, message_id)
        return True

    assert event_id is not None
    assert order_id is not None
    try:
        await _process_valid_event(session_factory, event_id, order_id, payload, settings)
    except Exception as exc:
        logger.warning("event processing failed type=%s", type(exc).__name__)
        return False

    await client.xack(settings.stream_name, settings.consumer_group, message_id)
    return True


async def delete_dataset_rows(session: AsyncSession, dataset_ids: list[str]) -> None:
    safe_ids = [dataset_id for dataset_id in dataset_ids if dataset_id != PUBLIC_DATASET]
    if not safe_ids:
        return
    order_ids = select(Order.id).where(Order.dataset_id.in_(safe_ids))
    await session.execute(delete(Notification).where(Notification.dataset_id.in_(safe_ids)))
    await session.execute(delete(EventRecord).where(EventRecord.dataset_id.in_(safe_ids)))
    await session.execute(delete(Outbox).where(Outbox.dataset_id.in_(safe_ids)))
    await session.execute(delete(OrderItem).where(OrderItem.order_id.in_(order_ids)))
    await session.execute(delete(Order).where(Order.dataset_id.in_(safe_ids)))
    await session.execute(delete(Product).where(Product.dataset_id.in_(safe_ids)))


async def purge_expired_runs(
    session_factory: async_sessionmaker[AsyncSession],
    settings: Settings,
) -> int:
    async with session_factory() as session:
        async with session.begin():
            run_ids = (
                await session.execute(
                    select(Run.run_id)
                    .where(Run.expires_at <= utcnow())
                    .with_for_update(skip_locked=True)
                )
            ).scalars().all()
            if not run_ids:
                return 0
            dataset_ids = [str(run_id) for run_id in run_ids]
            await delete_dataset_rows(session, dataset_ids)
            await session.execute(delete(Run).where(Run.run_id.in_(run_ids)))
            return len(run_ids)


async def delete_run(
    session_factory: async_sessionmaker[AsyncSession],
    run_id: uuid.UUID,
) -> bool:
    async with session_factory() as session:
        async with session.begin():
            run = await session.get(Run, run_id, with_for_update=True)
            if run is None:
                return False
            await delete_dataset_rows(session, [str(run_id)])
            await session.delete(run)
            return True
