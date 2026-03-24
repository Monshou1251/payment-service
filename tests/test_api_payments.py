import uuid
from decimal import Decimal
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.models.payment import Payment
from app.schemas.payment import PaymentCreateResponse, PaymentStatus
from tests.conftest import FIXED_ID, FIXED_NOW, API_KEY


class TestCreatePayment:
    async def test_returns_202_with_pending_status(self, client, auth_headers, payment_payload):
        mock_response = PaymentCreateResponse(
            payment_id=FIXED_ID,
            status=PaymentStatus.PENDING,
            created_at=FIXED_NOW,
        )
        with patch("app.api.v1.payments.PaymentService") as MockService:
            MockService.return_value.create = AsyncMock(return_value=mock_response)
            response = await client.post("/api/v1/payments", headers=auth_headers, json=payment_payload)

        assert response.status_code == 202
        data = response.json()
        assert data["payment_id"] == str(FIXED_ID)
        assert data["status"] == "pending"
        assert "created_at" in data

    async def test_missing_idempotency_key_returns_422(self, client, payment_payload):
        headers = {"X-API-Key": API_KEY}  # no Idempotency-Key
        response = await client.post("/api/v1/payments", headers=headers, json=payment_payload)
        assert response.status_code == 422

    async def test_invalid_amount_returns_422(self, client, auth_headers, payment_payload):
        payment_payload["amount"] = "-50.00"
        response = await client.post("/api/v1/payments", headers=auth_headers, json=payment_payload)
        assert response.status_code == 422

    async def test_missing_api_key_returns_401(self, client, payment_payload):
        headers = {"Idempotency-Key": "some-key"}  # no X-API-Key
        response = await client.post("/api/v1/payments", headers=headers, json=payment_payload)
        assert response.status_code == 401

    async def test_wrong_api_key_returns_401(self, client, payment_payload):
        headers = {"X-API-Key": "wrong-key", "Idempotency-Key": "some-key"}
        response = await client.post("/api/v1/payments", headers=headers, json=payment_payload)
        assert response.status_code == 401

    async def test_idempotency_returns_existing_payment(self, client, auth_headers, payment_payload):
        """Same Idempotency-Key with different body returns the first payment unchanged."""
        mock_response = PaymentCreateResponse(
            payment_id=FIXED_ID,
            status=PaymentStatus.SUCCEEDED,
            created_at=FIXED_NOW,
        )
        with patch("app.api.v1.payments.PaymentService") as MockService:
            MockService.return_value.create = AsyncMock(return_value=mock_response)

            # First request
            r1 = await client.post("/api/v1/payments", headers=auth_headers, json=payment_payload)
            # Second request with same key, different amount
            payment_payload["amount"] = "999.00"
            r2 = await client.post("/api/v1/payments", headers=auth_headers, json=payment_payload)

        assert r1.status_code == r2.status_code == 202
        assert r1.json()["payment_id"] == r2.json()["payment_id"]


class TestGetPayment:
    async def test_returns_200_with_full_details(self, client, auth_headers):
        payment = Payment(
            id=FIXED_ID,
            idempotency_key="test-key",
            amount=Decimal("100.00"),
            currency="RUB",
            description="Test payment",
            metadata_={"order_id": "42"},
            status="succeeded",
            webhook_url="https://example.com/webhook",
            created_at=FIXED_NOW,
            processed_at=FIXED_NOW,
        )
        with patch("app.api.v1.payments.PaymentService") as MockService:
            MockService.return_value.get_by_id = AsyncMock(return_value=payment)
            response = await client.get(f"/api/v1/payments/{FIXED_ID}", headers=auth_headers)

        assert response.status_code == 200
        data = response.json()
        assert data["id"] == str(FIXED_ID)
        assert data["amount"] == "100.00"
        assert data["status"] == "succeeded"
        assert data["metadata"] == {"order_id": "42"}
        assert data["processed_at"] is not None

    async def test_not_found_returns_404(self, client, auth_headers):
        with patch("app.api.v1.payments.PaymentService") as MockService:
            MockService.return_value.get_by_id = AsyncMock(return_value=None)
            response = await client.get(f"/api/v1/payments/{FIXED_ID}", headers=auth_headers)

        assert response.status_code == 404
        assert response.json()["detail"] == "Payment not found"
