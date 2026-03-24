import uuid
from datetime import datetime
from decimal import Decimal
from enum import Enum

from pydantic import AliasChoices, BaseModel, Field, HttpUrl


class Currency(str, Enum):
    RUB = "RUB"
    USD = "USD"
    EUR = "EUR"


class PaymentStatus(str, Enum):
    PENDING = "pending"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


class PaymentCreate(BaseModel):
    amount: Decimal = Field(gt=0, decimal_places=2)
    currency: Currency
    description: str = Field(min_length=1, max_length=500)
    metadata: dict | None = None
    webhook_url: HttpUrl


class PaymentCreateResponse(BaseModel):
    payment_id: uuid.UUID
    status: PaymentStatus
    created_at: datetime


class PaymentResponse(BaseModel):
    id: uuid.UUID
    amount: Decimal
    currency: Currency
    description: str
    metadata: dict | None = Field(default=None, validation_alias=AliasChoices("metadata_", "metadata"))
    status: PaymentStatus
    webhook_url: str
    created_at: datetime
    processed_at: datetime | None

    model_config = {"from_attributes": True}
