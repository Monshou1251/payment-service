"""
RabbitMQ topology declaration.
Shared between outbox worker (publisher) and payment consumer.

Topology:
  payments.exchange  (direct) ──► payments.new (queue)
                                       │ on reject after 3 attempts
                                       ▼
  payments.dlx       (fanout) ──► payments.dead (DLQ)
"""
import aio_pika

from app.core.config import settings

PAYMENTS_EXCHANGE = "payments.exchange"
PAYMENTS_QUEUE = "payments.new"
DLX_EXCHANGE = "payments.dlx"
DLQ_QUEUE = "payments.dead"
ROUTING_KEY = "payments.new"


async def get_rabbit_connection() -> aio_pika.abc.AbstractRobustConnection:
    return await aio_pika.connect_robust(settings.rabbitmq_url)


async def declare_topology(channel: aio_pika.abc.AbstractChannel) -> aio_pika.abc.AbstractExchange:
    """Declare all exchanges and queues. Idempotent — safe to call on every startup."""

    # Dead-letter exchange (fanout — routes everything to DLQ)
    dlx = await channel.declare_exchange(DLX_EXCHANGE, aio_pika.ExchangeType.FANOUT, durable=True)

    # Dead-letter queue
    await channel.declare_queue(DLQ_QUEUE, durable=True, arguments={"x-queue-type": "classic"})
    dlq = await channel.get_queue(DLQ_QUEUE)
    await dlq.bind(dlx)

    # Main exchange
    exchange = await channel.declare_exchange(
        PAYMENTS_EXCHANGE, aio_pika.ExchangeType.DIRECT, durable=True
    )

    # Main queue — dead-letters go to DLX after x-delivery-count >= 3 (handled in consumer)
    queue = await channel.declare_queue(
        PAYMENTS_QUEUE,
        durable=True,
        arguments={
            "x-dead-letter-exchange": DLX_EXCHANGE,
            "x-queue-type": "classic",
        },
    )
    await queue.bind(exchange, routing_key=ROUTING_KEY)

    return exchange
