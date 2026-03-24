import json
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.consumer.payment_consumer import handle_message, process_message
from tests.conftest import FIXED_ID


def make_message(payment_id: uuid.UUID = FIXED_ID) -> MagicMock:
    msg = MagicMock()
    msg.body = json.dumps({"payment_id": str(payment_id)}).encode()
    msg.message_id = "test-msg-id"
    msg.ack = AsyncMock()
    msg.nack = AsyncMock()
    return msg


async def test_process_message_success():
    """process_message updates payment status and sends webhook."""
    from app.models.payment import Payment
    from decimal import Decimal
    from datetime import datetime, timezone

    payment = Payment(
        id=FIXED_ID,
        idempotency_key="key",
        amount=Decimal("100.00"),
        currency="RUB",
        description="Test",
        status="pending",
        webhook_url="https://example.com/webhook",
        created_at=datetime.now(timezone.utc),
    )

    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = payment
    mock_session = AsyncMock()
    mock_session.execute.return_value = mock_result
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=False)

    with (
        patch("app.consumer.payment_consumer.AsyncSessionFactory", return_value=mock_session),
        patch("app.consumer.payment_consumer.emulate_gateway", return_value=True),
        patch("app.consumer.payment_consumer.send_webhook", new_callable=AsyncMock) as mock_webhook,
    ):
        await process_message(json.dumps({"payment_id": str(FIXED_ID)}).encode())

    assert payment.status == "succeeded"
    mock_session.commit.assert_called_once()
    mock_webhook.assert_called_once()
    webhook_payload = mock_webhook.call_args.kwargs["payload"]
    assert webhook_payload["status"] == "succeeded"


async def test_process_message_payment_not_found_skips():
    """process_message returns early without calling gateway or webhook when payment missing."""
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = None
    mock_session = AsyncMock()
    mock_session.execute.return_value = mock_result
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=False)

    with (
        patch("app.consumer.payment_consumer.AsyncSessionFactory", return_value=mock_session),
        patch("app.consumer.payment_consumer.emulate_gateway", new_callable=AsyncMock) as mock_gw,
        patch("app.consumer.payment_consumer.send_webhook", new_callable=AsyncMock) as mock_wh,
    ):
        await process_message(json.dumps({"payment_id": str(FIXED_ID)}).encode())

    mock_gw.assert_not_called()
    mock_wh.assert_not_called()


async def test_handle_message_exhausts_retries_then_nacks():
    """After MAX_RETRIES failures handle_message nacks without requeue (→ DLQ)."""
    message = make_message()

    with (
        patch("app.consumer.payment_consumer.process_message", side_effect=RuntimeError("fail")),
        patch("app.consumer.payment_consumer.asyncio.sleep", new_callable=AsyncMock),
    ):
        await handle_message(message)

    message.ack.assert_not_called()
    message.nack.assert_called_once_with(requeue=False)
