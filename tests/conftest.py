import uuid
from datetime import datetime, timezone
from decimal import Decimal
from unittest.mock import AsyncMock

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from app.core.database import get_session
from app.main import app

FIXED_ID = uuid.UUID("11111111-1111-1111-1111-111111111111")
FIXED_NOW = datetime(2026, 3, 24, 12, 0, 0, tzinfo=timezone.utc)
API_KEY = "secret-api-key"


@pytest_asyncio.fixture
async def client():
    """HTTP client with mocked DB session and valid API key pre-set."""
    async def override_get_session():
        yield AsyncMock()

    app.dependency_overrides[get_session] = override_get_session
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c
    app.dependency_overrides.clear()


@pytest.fixture
def auth_headers():
    return {"X-API-Key": API_KEY, "Idempotency-Key": "test-idempotency-key-001"}


@pytest.fixture
def payment_payload():
    return {
        "amount": "100.00",
        "currency": "RUB",
        "description": "Test payment",
        "metadata": {"order_id": "42"},
        "webhook_url": "https://example.com/webhook",
    }
