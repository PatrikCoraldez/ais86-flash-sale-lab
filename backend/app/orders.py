from __future__ import annotations

import hashlib
import json
import uuid
from typing import Any

from fastapi import APIRouter, Depends, Header, Request
from fastapi.responses import JSONResponse
from sqlalchemy import select, text, update
from sqlalchemy.ext.asyncio import AsyncSession

from .db import CAMPAIGN, utcnow
from .events import build_order_created_event, iso8601
from .models import BillingInvoice, Order, OrderItem, Outbox, Product
from .schemas import OrderCreate
from .security import (
    ApiError,
    DatasetContext,
    dataset_context,
    get_session,
    validate_idempotency_key,
)

router = APIRouter()


def _canonical_request_hash(payload: OrderCreate) -> str:
    canonical = {
        "items": [
            {"product_id": item.product_id, "quantity": item.quantity}
            for item in sorted(payload.items, key=lambda entry: entry.product_id)
        ]
    }
    encoded = json.dumps(canonical, separators=(",", ":"), sort_keys=True)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _advisory_lock_key(dataset_id: str, idempotency_key: str) -> int:
    digest = hashlib.sha256(f"{dataset_id}:{idempotency_key}".encode("utf-8")).digest()
    return int.from_bytes(digest[:8], "big", signed=True)


async def _create_or_replay(
    session: AsyncSession,
    dataset_id: str,
    idempotency_key: str,
    request_hash: str,
    payload: OrderCreate,
) -> dict[str, Any]:
    lock_key = _advisory_lock_key(dataset_id, idempotency_key)
    async with session.begin():
        await session.execute(
            text("SELECT pg_advisory_xact_lock(:lock_key)"),
            {"lock_key": lock_key},
        )

        existing = (
            await session.execute(
                select(Order).where(
                    Order.dataset_id == dataset_id,
                    Order.idempotency_key == idempotency_key,
                )
            )
        ).scalar_one_or_none()
        if existing is not None:
            if existing.request_hash != request_hash:
                raise ApiError(
                    409,
                    "IDEMPOTENCY_CONFLICT",
                    "Idempotency key was already used with a different request",
                )
            return dict(existing.snapshot)

        identifiers = [item.product_id for item in payload.items]
        products = (
            await session.execute(
                select(Product).where(
                    Product.dataset_id == dataset_id,
                    Product.id.in_(identifiers),
                )
            )
        ).scalars().all()
        products_by_id = {product.id: product for product in products}

        missing = sorted(identifier for identifier in identifiers if identifier not in products_by_id)
        if missing:
            raise ApiError(
                404,
                "NOT_FOUND",
                "One or more products do not exist",
                {"product_ids": missing},
            )

        quantities = {item.product_id: item.quantity for item in payload.items}
        for product_id in sorted(quantities):
            quantity = quantities[product_id]
            result = await session.execute(
                update(Product)
                .where(
                    Product.dataset_id == dataset_id,
                    Product.id == product_id,
                    Product.stock >= quantity,
                )
                .values(stock=Product.stock - quantity)
                .returning(Product.stock)
            )
            if result.first() is None:
                raise ApiError(
                    409,
                    "OUT_OF_STOCK",
                    "Insufficient stock for one or more products",
                    {"product_id": product_id},
                )

        created_at = utcnow()
        order_id = uuid.uuid4()
        items_out = [
            {
                "product_id": item.product_id,
                "name": products_by_id[item.product_id].name,
                "quantity": item.quantity,
                "unit_price_cents": products_by_id[item.product_id].price_cents,
            }
            for item in payload.items
        ]
        total_cents = sum(item["unit_price_cents"] * item["quantity"] for item in items_out)
        snapshot = {
            "id": str(order_id),
            "status": "confirmed",
            "notification_status": "pending",
            "items": items_out,
            "total_cents": total_cents,
            "created_at": iso8601(created_at),
        }

        order = Order(
            id=order_id,
            dataset_id=dataset_id,
            idempotency_key=idempotency_key,
            request_hash=request_hash,
            status="confirmed",
            notification_status="pending",
            total_cents=total_cents,
            created_at=created_at,
            snapshot=snapshot,
        )
        session.add(order)

        for item in items_out:
            session.add(
                OrderItem(
                    order_id=order_id,
                    product_id=item["product_id"],
                    name=item["name"],
                    quantity=item["quantity"],
                    unit_price_cents=item["unit_price_cents"],
                )
            )
        await session.flush()
        # Evento order.created: se guarda en la outbox DENTRO de la misma
        # transacción que el pedido y el inventario.
        event_payload = build_order_created_event(
            order_id=order_id,
            customer_id=(
                str(payload.customer_id)
                if hasattr(payload, "customer_id")
                else "customer-demo"
            ),
            items=items_out,
            total_cents=total_cents,
            created_at=created_at,
        )

        session.add(
            Outbox(
                event_id=uuid.UUID(str(event_payload["id"])),
                dataset_id=dataset_id,
                order_id=order_id,
                payload=event_payload,
                status="pending",
            )
        )

        # Semana 11: tarea de facturación pendiente, con snapshot inmutable del
        # pedido. Se guarda en la MISMA transacción; la llamada HTTP al servicio
        # de facturación la hace el worker después, fuera de esta transacción.
        session.add(
            BillingInvoice(
                order_id=order_id,
                dataset_id=dataset_id,
                status="pending",
                attempts=0,
                next_attempt_at=created_at,
                created_at=created_at,
                updated_at=created_at,
                request_body={
                    "order_id": str(order_id),
                    "currency": "PEN",
                    "items": [
                        {
                            "product_id": item["product_id"],
                            "name": item["name"],
                            "quantity": item["quantity"],
                            "unit_price_cents": item["unit_price_cents"],
                        }
                        for item in items_out
                    ],
                    "total_cents": total_cents,
                },
            )
        )

    return snapshot


@router.get("/api/v1/products")
async def list_products(
    request: Request,
    session: AsyncSession = Depends(get_session),
    context: DatasetContext = Depends(dataset_context),
) -> dict[str, Any]:
    products = (
        await session.execute(
            select(Product)
            .where(Product.dataset_id == context.dataset_id)
            .order_by(Product.sort_order, Product.id)
        )
    ).scalars().all()

    if not products:
        raise ApiError(404, "NOT_FOUND", "Catalog not found")

    return {
        "items": [
            {
                "id": product.id,
                "name": product.name,
                "description": product.description,
                "category": product.category,
                "price_cents": product.price_cents,
                "original_price_cents": product.original_price_cents,
                "stock": product.stock,
                "image": product.image,
            }
            for product in products
        ],
        "campaign": dict(CAMPAIGN),
    }


@router.post("/api/v1/orders")
async def create_order(
    payload: OrderCreate,
    request: Request,
    session: AsyncSession = Depends(get_session),
    context: DatasetContext = Depends(dataset_context),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
) -> JSONResponse:
    key = validate_idempotency_key(idempotency_key)
    request_hash = _canonical_request_hash(payload)
    snapshot = await _create_or_replay(
        session,
        context.dataset_id,
        key,
        request_hash,
        payload,
    )
    # Tarea C: ya no se espera a la notificación. El pedido se confirma de
    # inmediato (notification_status = "pending") y el worker la procesa después.
    return JSONResponse(
        status_code=201,
        content=snapshot,
        headers={"Location": f"/api/v1/orders/{snapshot['id']}"},
    )


@router.get("/api/v1/orders/{order_id}")
async def get_order(
    order_id: str,
    request: Request,
    session: AsyncSession = Depends(get_session),
    context: DatasetContext = Depends(dataset_context),
) -> JSONResponse:
    try:
        identifier = uuid.UUID(order_id)
    except (ValueError, AttributeError, TypeError):
        raise ApiError(404, "NOT_FOUND", "Order not found") from None

    order = await session.get(Order, identifier)
    if order is None or order.dataset_id != context.dataset_id:
        raise ApiError(404, "NOT_FOUND", "Order not found")

    snapshot = dict(order.snapshot)
    snapshot["notification_status"] = order.notification_status
    return JSONResponse(content=snapshot)