from __future__ import annotations

import asyncio
import logging

from redis.asyncio import Redis

from .config import Settings, get_settings
from .db import Database
from .events import (
    create_redis,
    ensure_consumer_group,
    handle_stream_message,
    publish_outbox_batch,
    purge_expired_runs,
)

logger = logging.getLogger(__name__)


def _read_messages(response: object) -> list[tuple[str, dict[str, object]]]:
    messages: list[tuple[str, dict[str, object]]] = []
    if not response:
        return messages
    for _stream_name, entries in response:
        for message_id, fields in entries:
            messages.append((message_id, fields))
    return messages


async def relay_loop(database: Database, client: Redis, settings: Settings) -> None:
    while True:
        try:
            await publish_outbox_batch(database.session_factory, client, settings)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.warning("relay error type=%s", type(exc).__name__)
            await asyncio.sleep(min(max(settings.outbox_poll_seconds * 5, 0.5), 5.0))
            continue
        await asyncio.sleep(settings.outbox_poll_seconds)


async def consumer_loop(database: Database, client: Redis, settings: Settings) -> None:
    consumer_name = f"worker-{settings.instance_id}"[:120]
    while True:
        try:
            pending = await client.xreadgroup(
                settings.consumer_group,
                consumer_name,
                {settings.stream_name: "0"},
                count=20,
            )
            for message_id, fields in _read_messages(pending):
                handled = await handle_stream_message(
                    message_id,
                    fields,
                    database.session_factory,
                    client,
                    settings,
                )
                if not handled:
                    await asyncio.sleep(1.0)

            response = await client.xreadgroup(
                settings.consumer_group,
                consumer_name,
                {settings.stream_name: ">"},
                count=20,
                block=1000,
            )
            for message_id, fields in _read_messages(response):
                handled = await handle_stream_message(
                    message_id,
                    fields,
                    database.session_factory,
                    client,
                    settings,
                )
                if not handled:
                    await asyncio.sleep(1.0)

            claimed = await client.xautoclaim(
                settings.stream_name,
                settings.consumer_group,
                consumer_name,
                settings.notification_claim_idle_ms,
                start_id="0-0",
                count=20,
            )
            if isinstance(claimed, tuple) and len(claimed) >= 2:
                for message_id, fields in _read_messages([("claimed", claimed[1])]):
                    handled = await handle_stream_message(
                        message_id,
                        fields,
                        database.session_factory,
                        client,
                        settings,
                    )
                    if not handled:
                        await asyncio.sleep(1.0)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.warning("consumer error type=%s", type(exc).__name__)
            await asyncio.sleep(1.0)


async def cleanup_loop(database: Database, settings: Settings) -> None:
    while True:
        try:
            await purge_expired_runs(database.session_factory, settings)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.warning("cleanup error type=%s", type(exc).__name__)
        await asyncio.sleep(30.0)


async def run_worker() -> None:
    settings = get_settings()
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    database = Database(settings)
    client = create_redis(settings)
    try:
        await database.initialize()
        last_error: Exception | None = None
        for attempt in range(1, settings.startup_max_attempts + 1):
            try:
                await client.ping()
                await ensure_consumer_group(client, settings)
                last_error = None
                break
            except Exception as exc:
                last_error = exc
                logger.warning(
                    "redis not ready attempt=%s/%s error=%s",
                    attempt,
                    settings.startup_max_attempts,
                    type(exc).__name__,
                )
                if attempt < settings.startup_max_attempts:
                    await asyncio.sleep(settings.startup_retry_seconds)
        if last_error is not None:
            raise RuntimeError("redis unavailable") from last_error

        await asyncio.gather(
            relay_loop(database, client, settings),
            consumer_loop(database, client, settings),
            cleanup_loop(database, settings),
        )
    finally:
        await client.aclose()
        await database.close()


def main() -> None:
    try:
        asyncio.run(run_worker())
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
