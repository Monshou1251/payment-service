"""
Payment Consumer: processes payments from the payments.new queue.

Flow per message:
  1. Parse payment_id from message body
  2. Load Payment from DB
  3. Emulate gateway processing (2-5s, 90% success / 10% failure)
  4. Update payment status + processed_at in DB
  5. Send webhook notification (with internal retry — see webhook_service)
  6. Ack message on success

Retry / DLQ:
  Consumer retries up to MAX_RETRIES times with exponential backoff (1s, 2s).
  After all attempts fail — nack without requeue → DLX → payments.dead (DLQ).
"""
import asyncio
import json
import logging
import random
import uuid
from datetime import datetime, timezone

import aio_pika
from sqlalchemy import select

from app.core.database import AsyncSessionFactory
from app.models.payment import Payment
from app.outbox.rabbit import PAYMENTS_QUEUE, declare_topology, get_rabbit_connection
from app.services.webhook_service import send_webhook

logger = logging.getLogger(__name__)

MAX_RETRIES = 3


async def emulate_gateway() -> bool:
    """Simulate external payment gateway: 2-5s delay, 90% success."""
    await asyncio.sleep(random.uniform(2, 5))
    return random.random() < 0.9


async def process_message(body: bytes) -> None:
    payload = json.loads(body)
    payment_id = uuid.UUID(payload["payment_id"])

    async with AsyncSessionFactory() as session:
        result = await session.execute(select(Payment).where(Payment.id == payment_id))
        payment = result.scalar_one_or_none()

        if payment is None:
            logger.error("Payment %s not found, skipping", payment_id)
            return

        succeeded = await emulate_gateway()
        processed_at = datetime.now(timezone.utc)
        payment.status = "succeeded" if succeeded else "failed"
        payment.processed_at = processed_at

        # Extract values before session closes to avoid detached object access
        webhook_url = payment.webhook_url
        payment_id_str = str(payment.id)
        status = payment.status

        await session.commit()
        logger.info("Payment %s → %s", payment_id, status)

    await send_webhook(
        webhook_url=webhook_url,
        payload={
            "payment_id": payment_id_str,
            "status": status,
            "processed_at": processed_at.isoformat(),
        },
    )


async def handle_message(message: aio_pika.abc.AbstractIncomingMessage) -> None:
    """Consume one message with retry logic. Nack → DLQ after MAX_RETRIES failures."""
    last_exc: Exception | None = None

    for attempt in range(1, MAX_RETRIES + 1):
        try:
            await process_message(message.body)
            await message.ack()
            return
        except Exception as exc:
            last_exc = exc
            logger.warning(
                "Processing attempt %d/%d failed for message %s: %s",
                attempt, MAX_RETRIES, message.message_id, exc,
            )
            if attempt < MAX_RETRIES:
                await asyncio.sleep(2 ** (attempt - 1))  # 1s, 2s before retry

    logger.error(
        "Message %s failed after %d attempts, sending to DLQ: %s",
        message.message_id, MAX_RETRIES, last_exc,
    )
    await message.nack(requeue=False)  # → payments.dlx → payments.dead


async def run() -> None:
    logging.basicConfig(level=logging.INFO)
    logger.info("Payment consumer started")

    connection = await get_rabbit_connection()
    async with connection:
        channel = await connection.channel()
        await channel.set_qos(prefetch_count=10)
        await declare_topology(channel)

        queue = await channel.get_queue(PAYMENTS_QUEUE)
        await queue.consume(handle_message)

        logger.info("Listening on queue '%s'", PAYMENTS_QUEUE)
        await asyncio.Future()  # run forever


if __name__ == "__main__":
    asyncio.run(run())
