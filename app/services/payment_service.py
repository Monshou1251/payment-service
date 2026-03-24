import uuid
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.outbox import OutboxEvent
from app.models.payment import Payment
from app.schemas.payment import PaymentCreate, PaymentCreateResponse, PaymentStatus


class PaymentService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create(self, data: PaymentCreate, idempotency_key: str) -> PaymentCreateResponse:
        # Idempotency: return existing payment if key already used
        existing = await self._get_by_idempotency_key(idempotency_key)
        if existing:
            return PaymentCreateResponse(
                payment_id=existing.id,
                status=PaymentStatus(existing.status),
                created_at=existing.created_at,
            )

        payment = Payment(
            id=uuid.uuid4(),
            idempotency_key=idempotency_key,
            amount=data.amount,
            currency=data.currency.value,
            description=data.description,
            metadata_=data.metadata,
            status=PaymentStatus.PENDING.value,
            webhook_url=str(data.webhook_url),
            created_at=datetime.now(timezone.utc),
        )

        outbox_event = OutboxEvent(
            id=uuid.uuid4(),
            event_type="payment.created",
            payload={"payment_id": str(payment.id)},
        )

        # Atomic: both payment and outbox event in one transaction
        self.session.add(payment)
        self.session.add(outbox_event)
        try:
            await self.session.commit()
        except IntegrityError:
            # Race condition: another request with same idempotency_key committed first
            await self.session.rollback()
            existing = await self._get_by_idempotency_key(idempotency_key)
            return PaymentCreateResponse(
                payment_id=existing.id,
                status=PaymentStatus(existing.status),
                created_at=existing.created_at,
            )

        return PaymentCreateResponse(
            payment_id=payment.id,
            status=PaymentStatus(payment.status),
            created_at=payment.created_at,
        )

    async def get_by_id(self, payment_id: uuid.UUID) -> Payment | None:
        result = await self.session.execute(
            select(Payment).where(Payment.id == payment_id)
        )
        return result.scalar_one_or_none()

    async def _get_by_idempotency_key(self, key: str) -> Payment | None:
        result = await self.session.execute(
            select(Payment).where(Payment.idempotency_key == key)
        )
        return result.scalar_one_or_none()
