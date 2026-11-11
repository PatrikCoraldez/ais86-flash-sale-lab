from __future__ import annotations

import os
import socket
import uuid
from functools import lru_cache

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(extra="ignore", case_sensitive=False)

    database_url: str
    redis_url: str
    lab_key: SecretStr

    instance_id: str = Field(
        default_factory=lambda: f"{socket.gethostname()}-{os.getpid()}-{uuid.uuid4().hex[:8]}"
    )
    frontend_dist: str = "/app/frontend/dist"
    enable_docs: bool = False

    body_limit_bytes: int = Field(default=16384, ge=1024, le=1048576)
    rate_limit_api_per_minute: int = Field(default=600, ge=1, le=100000)
    rate_limit_orders_per_minute: int = Field(default=240, ge=1, le=100000)

    stream_name: str = "flash:orders"
    consumer_group: str = "notifications-v1"
    stream_maxlen: int = Field(default=10000, ge=1000, le=1000000)
    outbox_batch_size: int = Field(default=100, ge=1, le=1000)
    outbox_poll_seconds: float = Field(default=0.2, ge=0.05, le=10.0)
    notification_claim_idle_ms: int = Field(default=30000, ge=1000, le=3600000)
    run_ttl_seconds: int = Field(default=1800, ge=60, le=86400)
    max_active_runs: int = Field(default=20, ge=1, le=1000)

    startup_max_attempts: int = Field(default=60, ge=1, le=600)
    startup_retry_seconds: float = Field(default=1.0, ge=0.05, le=30.0)
    db_connect_timeout_seconds: int = Field(default=5, ge=1, le=60)
    db_pool_size: int = Field(default=10, ge=1, le=100)
    db_max_overflow: int = Field(default=20, ge=0, le=200)

    @field_validator("database_url")
    @classmethod
    def normalize_database_url(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("DATABASE_URL is required")
        if value.startswith("postgres://"):
            value = "postgresql://" + value[len("postgres://") :]
        if value.startswith("postgresql://"):
            value = "postgresql+psycopg://" + value[len("postgresql://") :]
        if not value.startswith("postgresql+psycopg://"):
            raise ValueError("DATABASE_URL must be a PostgreSQL URL")
        return value

    @field_validator("redis_url")
    @classmethod
    def validate_redis_url(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("REDIS_URL is required")
        if not (value.startswith("redis://") or value.startswith("rediss://")):
            raise ValueError("REDIS_URL must be a redis URL")
        return value

    @field_validator("lab_key")
    @classmethod
    def validate_lab_key(cls, value: SecretStr) -> SecretStr:
        if len(value.get_secret_value().encode("utf-8")) < 32:
            raise ValueError("LAB_KEY must be at least 32 bytes")
        return value

    @field_validator("instance_id")
    @classmethod
    def validate_instance_id(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("INSTANCE_ID must not be empty")
        return value

    def lab_key_value(self) -> str:
        return self.lab_key.get_secret_value()


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
