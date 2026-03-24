"""
Webhook Service: delivers payment result to client's webhook_url.

Retry policy: 3 attempts with exponential backoff (1s → 2s → 4s).
Final failure is logged — it does not affect payment status.
"""
import asyncio
import logging

import httpx

logger = logging.getLogger(__name__)

MAX_ATTEMPTS = 3


async def send_webhook(webhook_url: str, payload: dict) -> None:
    last_error: Exception | None = None

    async with httpx.AsyncClient(timeout=10.0) as client:
        for attempt in range(1, MAX_ATTEMPTS + 1):
            try:
                response = await client.post(webhook_url, json=payload)
                response.raise_for_status()
                logger.info("Webhook delivered to %s (attempt %d)", webhook_url, attempt)
                return
            except Exception as exc:
                last_error = exc
                logger.warning(
                    "Webhook attempt %d/%d failed for %s: %s",
                    attempt, MAX_ATTEMPTS, webhook_url, exc,
                )
                if attempt < MAX_ATTEMPTS:
                    await asyncio.sleep(2 ** (attempt - 1))  # 1s, 2s, 4s

    logger.error(
        "Webhook delivery permanently failed for %s after %d attempts: %s",
        webhook_url, MAX_ATTEMPTS, last_error,
    )
