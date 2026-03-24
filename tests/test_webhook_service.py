from unittest.mock import patch, AsyncMock

import pytest
import respx
from httpx import Response

from app.services.webhook_service import send_webhook

WEBHOOK_URL = "https://example.com/webhook"
PAYLOAD = {"payment_id": "abc", "status": "succeeded", "processed_at": "2026-03-24T12:00:00Z"}


@respx.mock
async def test_webhook_delivered_on_first_attempt():
    """Successful response on first try — no retries, no sleep."""
    respx.post(WEBHOOK_URL).mock(return_value=Response(200))

    with patch("app.services.webhook_service.asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
        await send_webhook(WEBHOOK_URL, PAYLOAD)

    assert respx.calls.call_count == 1
    mock_sleep.assert_not_called()


@respx.mock
async def test_webhook_retries_on_failure_then_gives_up():
    """After 3 failed attempts the function returns without raising — logs error only."""
    respx.post(WEBHOOK_URL).mock(return_value=Response(500))

    with patch("app.services.webhook_service.asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
        await send_webhook(WEBHOOK_URL, PAYLOAD)  # must not raise

    assert respx.calls.call_count == 3
    # Exponential backoff: sleep before attempt 2 (1s) and before attempt 3 (2s)
    assert mock_sleep.call_count == 2
    sleep_args = [c.args[0] for c in mock_sleep.call_args_list]
    assert sleep_args == [1, 2]
