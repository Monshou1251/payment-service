import uuid
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, call, patch

import pytest
from sqlalchemy.exc import IntegrityError

from app.models.payment import Payment
from app.schemas.payment import Currency, PaymentCreate, PaymentStatus
from app.services.payment_service import PaymentService
from tests.conftest import FIXED_ID, FIXED_NOW


def make_payload(**kwargs) -> PaymentCreate:
    defaults = dict(
        amount=Decimal("100.00"),
        currency=Currency.RUB,
        description="Test",
        metadata=None,
        webhook_url="https://example.com/webhook",
    )
    return PaymentCreate(**(defaults | kwargs))


def make_existing_payment() -> Payment:
    return Payment(
        id=FIXED_ID,
        idempotency_key="existing-key",
        amount=Decimal("100.00"),
        currency="RUB",
        description="Test",
        status="pending",
        webhook_url="https://example.com/webhook",
        created_at=FIXED_NOW,
    )


async def test_create_new_payment():
    """create() saves Payment + OutboxEvent in one commit and returns pending status."""
    mock_session = AsyncMock()
    mock_session.add = MagicMock()  # add() is synchronous in SQLAlchemy
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = None  # no existing payment
    mock_session.execute.return_value = mock_result

    service = PaymentService(mock_session)
    response = await service.create(make_payload(), idempotency_key="new-key-001")

    assert mock_session.add.call_count == 2  # Payment + OutboxEvent
    mock_session.commit.assert_called_once()
    assert response.status == PaymentStatus.PENDING


async def test_create_idempotent_returns_existing():
    """create() returns existing payment without touching DB when idempotency key is known."""
    existing = make_existing_payment()
    mock_session = AsyncMock()
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = existing
    mock_session.execute.return_value = mock_result

    service = PaymentService(mock_session)
    response = await service.create(make_payload(), idempotency_key="existing-key")

    mock_session.add.assert_not_called()
    mock_session.commit.assert_not_called()
    assert response.payment_id == FIXED_ID


async def test_create_race_condition_handled():
    """When concurrent insert causes IntegrityError, rollback and return the winner's payment."""
    existing = make_existing_payment()
    mock_session = AsyncMock()

    result_none = MagicMock()
    result_none.scalar_one_or_none.return_value = None

    result_existing = MagicMock()
    result_existing.scalar_one_or_none.return_value = existing

    # First execute: no payment found; second: payment found after rollback
    mock_session.add = MagicMock()  # add() is synchronous in SQLAlchemy
    mock_session.execute.side_effect = [result_none, result_existing]
    mock_session.commit.side_effect = IntegrityError("unique", {}, None)

    service = PaymentService(mock_session)
    response = await service.create(make_payload(), idempotency_key="race-key")

    mock_session.rollback.assert_called_once()
    assert response.payment_id == FIXED_ID
