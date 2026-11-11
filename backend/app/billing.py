"""Adaptador HTTP hacia el microservicio de facturación (Semana 11).

Diseño:
- Al confirmar un pedido, orders.py guarda una fila `billing_invoices` en estado
  `pending` EN LA MISMA TRANSACCIÓN que el pedido, con un snapshot inmutable del
  cuerpo a enviar (request_body). Si el pedido existe, la tarea existe.
- El worker toma las filas pendientes y llama a POST {BILLING_BASE_URL}/invoices
  FUERA de cualquier transacción de stock, con timeout finito.
- Idempotency-Key = order_id. Un timeout puede ocurrir después de que el
  proveedor guardó la factura: reenviar el mismo cuerpo con la misma clave
  recupera la misma factura sin duplicarla.
- Un fallo de facturación NUNCA revierte el pedido ni toca notification_status.

Estados locales: pending -> issued | failed.
Reintento manual:  python -m app.billing retry [ORDER_ID]
Consulta:          python -m app.billing status
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import sys
import urllib.error
import urllib.request
import uuid
from datetime import timedelta
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from .db import Database, utcnow
from .models import BillingInvoice

logger = logging.getLogger(__name__)

TIMEOUT_SECONDS = 15          # timeout finito por llamada HTTP
MAX_CALLS_PER_RUN = 2         # reintentos automáticos por ejecución (solo fallos transitorios)
MAX_TOTAL_ATTEMPTS = 4        # ejecuciones antes de pasar a failed
RETRY_BACKOFF_SECONDS = 30    # espera base entre ejecuciones (x número de intento)
LEASE_SECONDS = 60            # reserva de la fila mientras se llama al proveedor
POLL_SECONDS = 3.0
BATCH_SIZE = 10


# --------------------------------------------------------------------------- #
# Configuración
# --------------------------------------------------------------------------- #
def _config() -> tuple[str, str]:
    base = (os.environ.get("BILLING_BASE_URL") or "").strip().rstrip("/")
    token = (os.environ.get("BILLING_TOKEN") or "").strip()
    return base, token


def is_configured() -> bool:
    base, token = _config()
    secure = base.startswith("https://") or base.startswith("http://127.0.0.1")
    return bool(base and token and secure)


# --------------------------------------------------------------------------- #
# Llamada HTTP (stdlib, sin dependencias nuevas)
# --------------------------------------------------------------------------- #
def _parse_json(raw: bytes) -> dict[str, Any]:
    try:
        data = json.loads(raw.decode("utf-8"))
    except (ValueError, UnicodeDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def _post_sync(url: str, token: str, key: str, payload: bytes) -> tuple[int, dict[str, Any]]:
    request = urllib.request.Request(
        url,
        data=payload,
        method="POST",
        headers={
            "Content-Type": "application/json",
            "Accept": "application/json",
            "X-Billing-Token": token,
            "Idempotency-Key": key,
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT_SECONDS) as response:
            return response.status, _parse_json(response.read(1_000_000))
    except urllib.error.HTTPError as error:
        try:
            return error.code, _parse_json(error.read(1_000_000))
        finally:
            error.close()


def _error_code(status: int, data: dict[str, Any]) -> str:
    error = data.get("error")
    if isinstance(error, dict) and isinstance(error.get("code"), str):
        return error["code"][:60]
    return f"HTTP_{status}"


def _valid_invoice(data: dict[str, Any], order_id: uuid.UUID, body: dict[str, Any]) -> bool:
    try:
        uuid.UUID(str(data["id"]))
    except (KeyError, ValueError):
        return False
    return (
        data.get("order_id") == str(order_id)
        and data.get("status") == "issued"
        and data.get("currency") == "PEN"
        and data.get("total_cents") == body.get("total_cents")
        and isinstance(data.get("number"), str)
    )


async def _call_with_retries(order_id: uuid.UUID, body: dict[str, Any]) -> dict[str, Any]:
    """Devuelve {"kind": "issued"|"permanent"|"transient", ...}. Nunca lanza."""
    base, token = _config()
    url = f"{base}/invoices"
    key = str(order_id)  # Idempotency-Key exactamente igual al order_id
    payload = json.dumps(body, separators=(",", ":"), ensure_ascii=False).encode("utf-8")

    outcome: dict[str, Any] = {"kind": "transient", "code": "NO_ATTEMPT"}
    for attempt in range(1, MAX_CALLS_PER_RUN + 1):
        try:
            status, data = await asyncio.to_thread(_post_sync, url, token, key, payload)
        except OSError as exc:  # URLError, timeout, conexión rechazada
            outcome = {"kind": "transient", "code": type(exc).__name__[:60]}
        else:
            if status in (200, 201):
                if _valid_invoice(data, order_id, body):
                    return {"kind": "issued", "data": data, "replay": status == 200}
                return {"kind": "permanent", "code": "INVALID_RESPONSE"}
            code = _error_code(status, data)
            if status == 429 or status >= 500:
                outcome = {"kind": "transient", "code": code}
            else:  # 400/401/404/409/413/415/422: reintentar igual no lo arregla
                return {"kind": "permanent", "code": code}
        if attempt < MAX_CALLS_PER_RUN:
            await asyncio.sleep(1.0)
    return outcome


# --------------------------------------------------------------------------- #
# Persistencia del estado local de facturación
# --------------------------------------------------------------------------- #
async def _claim_due(factory: async_sessionmaker[AsyncSession]) -> list[uuid.UUID]:
    now = utcnow()
    async with factory() as session:
        async with session.begin():
            rows = (
                await session.execute(
                    select(BillingInvoice)
                    .where(
                        BillingInvoice.status == "pending",
                        BillingInvoice.next_attempt_at <= now,
                    )
                    .order_by(BillingInvoice.created_at)
                    .limit(BATCH_SIZE)
                    .with_for_update(skip_locked=True)
                )
            ).scalars().all()
            for row in rows:
                row.next_attempt_at = now + timedelta(seconds=LEASE_SECONDS)
            return [row.order_id for row in rows]


async def deliver(factory: async_sessionmaker[AsyncSession], order_id: uuid.UUID) -> str:
    """Intenta facturar un pedido. Devuelve el estado local resultante."""
    async with factory() as session:  # lectura corta, sin transacción abierta durante la llamada HTTP
        row = await session.get(BillingInvoice, order_id)
        if row is None:
            return "missing"
        if row.status == "issued":
            return "issued"
        body = dict(row.request_body)

    outcome = await _call_with_retries(order_id, body)

    async with factory() as session:
        async with session.begin():
            row = await session.get(BillingInvoice, order_id, with_for_update=True)
            if row is None:
                return "missing"
            now = utcnow()
            row.updated_at = now
            row.attempts += 1
            if outcome["kind"] == "issued":
                data = outcome["data"]
                row.status = "issued"
                row.invoice_id = uuid.UUID(str(data["id"]))
                row.invoice_number = str(data["number"])[:80]
                row.last_error = None
                row.next_attempt_at = None
            elif outcome["kind"] == "permanent":
                row.status = "failed"
                row.last_error = outcome["code"][:200]
                row.next_attempt_at = None
            else:  # transitorio: sigue pending con espera creciente, y luego failed
                row.last_error = outcome["code"][:200]
                if row.attempts >= MAX_TOTAL_ATTEMPTS:
                    row.status = "failed"
                    row.next_attempt_at = None
                else:
                    row.status = "pending"
                    row.next_attempt_at = now + timedelta(
                        seconds=RETRY_BACKOFF_SECONDS * row.attempts
                    )
            return row.status


async def process_due(factory: async_sessionmaker[AsyncSession]) -> int:
    order_ids = await _claim_due(factory)
    for order_id in order_ids:
        status = await deliver(factory, order_id)
        logger.info("billing order=%s status=%s", order_id, status)
    return len(order_ids)


async def billing_loop(database: Database) -> None:
    """Bucle del worker. Independiente del relay y del consumidor de notificaciones."""
    while True:
        try:
            if is_configured():
                await process_due(database.session_factory)
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # nunca registrar tokens ni cuerpos
            logger.warning("billing loop error type=%s", type(exc).__name__)
            await asyncio.sleep(2.0)
        await asyncio.sleep(POLL_SECONDS)


# --------------------------------------------------------------------------- #
# Reintento manual y consulta (línea de comandos dentro del contenedor)
# --------------------------------------------------------------------------- #
async def manual_retry(
    factory: async_sessionmaker[AsyncSession], order_id: uuid.UUID | None = None
) -> list[tuple[uuid.UUID, str]]:
    """Vuelve a enviar con el MISMO cuerpo y la MISMA clave las facturas failed/pending."""
    now = utcnow()
    async with factory() as session:
        async with session.begin():
            query = select(BillingInvoice).where(BillingInvoice.status.in_(("failed", "pending")))
            if order_id is not None:
                query = query.where(BillingInvoice.order_id == order_id)
            rows = (await session.execute(query.with_for_update(skip_locked=True))).scalars().all()
            for row in rows:
                row.status = "pending"
                row.attempts = 0
                row.next_attempt_at = now + timedelta(seconds=LEASE_SECONDS)  # evita carrera con el bucle
            targets = [row.order_id for row in rows]
    results = []
    for target in targets:
        results.append((target, await deliver(factory, target)))
    return results


async def _print_status(factory: async_sessionmaker[AsyncSession]) -> None:
    async with factory() as session:
        counts = (
            await session.execute(
                select(BillingInvoice.status, func.count()).group_by(BillingInvoice.status)
            )
        ).all()
        print("Resumen:", {status: total for status, total in counts} or "sin registros")
        rows = (
            await session.execute(
                select(BillingInvoice).order_by(BillingInvoice.created_at.desc()).limit(10)
            )
        ).scalars().all()
        for row in rows:
            print(
                f"{row.order_id} | {row.status:<7} | intentos={row.attempts} | "
                f"factura={row.invoice_number or '-'} | error={row.last_error or '-'}"
            )


async def _cli(argv: list[str]) -> int:
    from .config import get_settings

    command = argv[0] if argv else "status"
    database = Database(get_settings())
    try:
        await database.wait_until_ready()
        if command == "status":
            await _print_status(database.session_factory)
            return 0
        if command == "retry":
            if not is_configured():
                print("Falta BILLING_BASE_URL (https) o BILLING_TOKEN en el entorno.")
                return 2
            target = uuid.UUID(argv[1]) if len(argv) > 1 else None
            results = await manual_retry(database.session_factory, target)
            for order_id, status in results:
                print(f"{order_id} -> {status}")
            if not results:
                print("No hay facturas pending/failed para reintentar.")
            return 0
        print("Uso: python -m app.billing [status | retry [ORDER_ID]]")
        return 2
    finally:
        await database.close()


if __name__ == "__main__":
    sys.exit(asyncio.run(_cli(sys.argv[1:])))
