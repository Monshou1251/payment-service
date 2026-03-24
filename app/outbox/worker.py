"""
Outbox Worker: polls outbox_events table and publishes unpublished events to RabbitMQ.

Flow:
  1. SELECT unpublished events FOR UPDATE SKIP LOCKED (safe for multiple instances)
  2. Publish each event to RabbitMQ exchange
  3. Mark event as published (set published_at)
  4. Repeat on interval
"""
import asyncio
import json
import logging
from datetime import datetime, timezone

import aio_pika
from sqlalchemy import select

from app.core.config import settings
from app.core.database import AsyncSessionFactory
from app.models.outbox import OutboxEvent
from app.outbox.rabbit import ROUTING_KEY, declare_topology, get_rabbit_connection

logger = logging.getLogger(__name__)


async def publish_pending_events(exchange: aio_pika.abc.AbstractExchange) -> None:
    async with AsyncSessionFactory() as session:
        async with session.begin():
            result = await session.execute(
                select(OutboxEvent)
                .where(OutboxEvent.published_at.is_(None))
                .order_by(OutboxEvent.created_at)
                .with_for_update(skip_locked=True)
                .limit(100)
            )
            events = result.scalars().all()

            for event in events:
                message = aio_pika.Message(
                    body=json.dumps(event.payload).encode(),
                    content_type="application/json",
                    delivery_mode=aio_pika.DeliveryMode.PERSISTENT,
                )
                await exchange.publish(message, routing_key=ROUTING_KEY)
                event.published_at = datetime.now(timezone.utc)
                logger.info("Published outbox event %s (type=%s)", event.id, event.event_type)


async def run() -> None:
    logging.basicConfig(level=logging.INFO)
    logger.info("Outbox worker started, poll interval=%.1fs", settings.outbox_poll_interval)

    connection = await get_rabbit_connection()
    async with connection:
        channel = await connection.channel()
        exchange = await declare_topology(channel)

        while True:
            try:
                await publish_pending_events(exchange)
            except Exception:
                logger.exception("Outbox worker iteration failed")
            await asyncio.sleep(settings.outbox_poll_interval)


if __name__ == "__main__":
    asyncio.run(run())
