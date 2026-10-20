"""PayPal payment port: authorize, capture, void, refund and pay out (USD only)."""

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Protocol


@dataclass(frozen=True, slots=True)
class CreatedOrder:
    order_id: str
    approve_url: str


@dataclass(frozen=True, slots=True)
class Authorization:
    auth_id: str
    expires_at: datetime


@dataclass(frozen=True, slots=True)
class PayoutStatus:
    """Latest state of a payout batch.

    batch_status is the state of the whole batch (PENDING, PROCESSING, SUCCESS,
    DENIED, CANCELED); item_status is the state of its only item (SUCCESS,
    FAILED, PENDING, UNCLAIMED, RETURNED, ONHOLD, BLOCKED, REFUNDED, REVERSED)
    or None while PayPal has not produced the item yet.
    """

    batch_status: str
    item_status: str | None


class PaymentGateway(Protocol):
    """Every POST takes a caller-chosen request_id that PayPal uses to
    deduplicate retries (header PayPal-Request-Id)."""

    async def create_order(
        self,
        amount: Decimal,
        reference_id: str,
        return_url: str,
        cancel_url: str,
        *,
        request_id: str,
    ) -> CreatedOrder: ...

    async def authorize(self, order_id: str, *, request_id: str) -> Authorization: ...

    async def capture(self, auth_id: str, *, request_id: str) -> str:
        """Captures the whole authorization; returns the capture id."""
        ...

    async def void(self, auth_id: str, *, request_id: str) -> None: ...

    async def refund(self, capture_id: str, *, request_id: str) -> str:
        """Refunds the whole capture; returns the refund id."""
        ...

    async def payout(
        self,
        email: str,
        amount: Decimal,
        sender_batch_id: str,
        note: str,
        *,
        request_id: str,
    ) -> str:
        """Sends one payout item to a PayPal account; returns the batch id.

        PayPal rejects a reused sender_batch_id and points at the original
        payout: the implementation returns that batch id instead of failing.
        """
        ...

    async def payout_status(self, batch_id: str) -> PayoutStatus: ...
