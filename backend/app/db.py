from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone

from sqlalchemy import text
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from .config import Settings

logger = logging.getLogger(__name__)

PUBLIC_DATASET = "public"

CAMPAIGN = {
    "name": "Drop AIS86",
    "ends_at": "2030-12-31T23:59:59Z",
    "currency": "PEN",
}

PRODUCT_SEED = [
    {
        "id": "nova-headphones",
        "name": "Nova Headphones",
        "description": "Audífonos inalámbricos con cancelación activa y 32 horas de batería.",
        "category": "Audio",
        "price_cents": 129900,
        "original_price_cents": 179900,
        "stock": 40,
        "image": "/assets/nova-headphones.svg",
        "sort_order": 0,
    },
    {
        "id": "orbit-keyboard",
        "name": "Orbit Keyboard",
        "description": "Teclado mecánico compacto, switches lineales y conexión triple.",
        "category": "Periféricos",
        "price_cents": 89900,
        "original_price_cents": 109900,
        "stock": 35,
        "image": "/assets/orbit-keyboard.svg",
        "sort_order": 1,
    },
    {
        "id": "pulse-speaker",
        "name": "Pulse Speaker",
        "description": "Parlante portátil resistente al agua con sonido estéreo.",
        "category": "Audio",
        "price_cents": 74900,
        "original_price_cents": 99900,
        "stock": 25,
        "image": "/assets/pulse-speaker.svg",
        "sort_order": 2,
    },
    {
        "id": "arc-mouse",
        "name": "Arc Mouse",
        "description": "Mouse ergonómico ultraligero con sensor de alta precisión.",
        "category": "Periféricos",
        "price_cents": 49900,
        "original_price_cents": 69900,
        "stock": 60,
        "image": "/assets/arc-mouse.svg",
        "sort_order": 3,
    },
    {
        "id": "terra-pack",
        "name": "Terra Pack",
        "description": "Mochila urbana para equipo de 16 pulgadas y organizador interno.",
        "category": "Accesorios",
        "price_cents": 159900,
        "original_price_cents": 199900,
        "stock": 20,
        "image": "/assets/terra-pack.svg",
        "sort_order": 4,
    },
    {
        "id": "flux-hub",
        "name": "Flux Hub",
        "description": "Hub USB-C de siete puertos con carga rápida y HDMI 4K.",
        "category": "Accesorios",
        "price_cents": 39900,
        "original_price_cents": 59900,
        "stock": 50,
        "image": "/assets/flux-hub.svg",
        "sort_order": 5,
    },
]


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    pass


class Database:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.engine: AsyncEngine = create_async_engine(
            settings.database_url,
            pool_pre_ping=True,
            pool_size=settings.db_pool_size,
            max_overflow=settings.db_max_overflow,
            pool_timeout=10,
            connect_args={"connect_timeout": settings.db_connect_timeout_seconds},
        )
        self.session_factory: async_sessionmaker[AsyncSession] = async_sessionmaker(
            self.engine,
            expire_on_commit=False,
        )

    async def wait_until_ready(self) -> None:
        last_error: Exception | None = None
        for attempt in range(1, self.settings.startup_max_attempts + 1):
            try:
                async with self.engine.connect() as connection:
                    await connection.execute(text("SELECT 1"))
                return
            except Exception as exc:
                last_error = exc
                logger.warning(
                    "database not ready attempt=%s/%s error=%s",
                    attempt,
                    self.settings.startup_max_attempts,
                    type(exc).__name__,
                )
                if attempt < self.settings.startup_max_attempts:
                    await asyncio.sleep(self.settings.startup_retry_seconds)
        raise RuntimeError("database unavailable") from last_error

    async def create_schema(self) -> None:
        from . import models

        async with self.engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)

    async def seed_public_catalog(self) -> None:
        from .models import Product

        rows = [dict(row, dataset_id=PUBLIC_DATASET) for row in PRODUCT_SEED]
        statement = (
            pg_insert(Product)
            .values(rows)
            .on_conflict_do_nothing(index_elements=["dataset_id", "id"])
        )
        async with self.session_factory() as session:
            async with session.begin():
                await session.execute(statement)

    async def initialize(self) -> None:
        await self.wait_until_ready()
        await self.create_schema()
        await self.seed_public_catalog()

    async def ping(self) -> None:
        async with self.engine.connect() as connection:
            await connection.execute(text("SELECT 1"))

    async def close(self) -> None:
        await self.engine.dispose()
