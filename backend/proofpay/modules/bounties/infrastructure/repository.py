"""PostgreSQL implementation of the bounties storage port."""

from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import Select, select
from sqlalchemy.ext.asyncio import AsyncSession

from proofpay.modules.bounties.domain.entities import (
    Bounty,
    BountyStatus,
    Claim,
    Event,
)
from proofpay.modules.bounties.infrastructure.mappers import (
    apply_bounty,
    apply_claim,
    bounty_from_row,
    bounty_to_row,
    claim_from_row,
    claim_to_row,
    event_from_row,
    event_to_row,
)
from proofpay.modules.bounties.infrastructure.models import (
    BountyRow,
    ClaimRow,
    EventRow,
)
from proofpay.shared.errors import NotFoundError

_HIDDEN_FROM_PUBLIC = (BountyStatus.DRAFT.value, BountyStatus.AWAITING_PAYMENT.value)
_EXPIRABLE = (BountyStatus.FUNDED.value, BountyStatus.IN_REVIEW.value)


def _bounty_not_found() -> NotFoundError:
    return NotFoundError(code="BOUNTY_NOT_FOUND", detail="Bounty not found")


def _fresh[Q: Select[Any]](query: Q) -> Q:
    # Rows loaded earlier in the same session must not shadow what the
    # database holds now: a lock is only useful if it is followed by a re-read.
    return query.execution_options(populate_existing=True)


class SqlBountyRepository:
    """Implements BountyRepository. Never commits."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get(self, bounty_id: UUID) -> Bounty:
        row = await self._session.scalar(
            _fresh(select(BountyRow).where(BountyRow.id == bounty_id))
        )
        if row is None:
            raise _bounty_not_found()
        return bounty_from_row(row)

    async def get_for_update(self, bounty_id: UUID) -> Bounty:
        row = await self._session.scalar(
            _fresh(select(BountyRow).where(BountyRow.id == bounty_id).with_for_update())
        )
        if row is None:
            raise _bounty_not_found()
        return bounty_from_row(row)

    async def get_by_order_for_update(self, order_id: str) -> Bounty:
        row = await self._session.scalar(
            _fresh(
                select(BountyRow)
                .where(BountyRow.order_id == order_id)
                .with_for_update()
            )
        )
        if row is None:
            raise _bounty_not_found()
        return bounty_from_row(row)

    async def add(self, bounty: Bounty) -> None:
        self._session.add(bounty_to_row(bounty))
        await self._session.flush()

    async def save(self, bounty: Bounty) -> None:
        row = await self._session.get(BountyRow, bounty.id)
        if row is None:
            raise _bounty_not_found()
        apply_bounty(row, bounty)
        await self._session.flush()

    async def list_public(self) -> list[Bounty]:
        rows = await self._session.scalars(
            select(BountyRow)
            .where(BountyRow.status.not_in(_HIDDEN_FROM_PUBLIC))
            .order_by(BountyRow.created_at.desc(), BountyRow.id.desc())
        )
        return [bounty_from_row(row) for row in rows]

    async def list_expiring(self, before: datetime) -> list[Bounty]:
        rows = await self._session.scalars(
            select(BountyRow)
            .where(
                BountyRow.status.in_(_EXPIRABLE),
                BountyRow.auth_expires_at < before,
            )
            .order_by(BountyRow.auth_expires_at, BountyRow.id)
        )
        return [bounty_from_row(row) for row in rows]

    async def claims_of(self, bounty_id: UUID) -> list[Claim]:
        rows = await self._session.scalars(
            select(ClaimRow)
            .where(ClaimRow.bounty_id == bounty_id)
            .order_by(ClaimRow.created_at, ClaimRow.id)
        )
        return [claim_from_row(row) for row in rows]

    async def get_claim(self, claim_id: UUID) -> Claim:
        row = await self._session.scalar(
            select(ClaimRow)
            .where(ClaimRow.id == claim_id)
            .execution_options(populate_existing=True)
        )
        if row is None:
            raise NotFoundError(code="CLAIM_NOT_FOUND", detail="Claim not found")
        return claim_from_row(row)

    async def add_claim(self, claim: Claim) -> None:
        self._session.add(claim_to_row(claim))
        await self._session.flush()

    async def save_claim(self, claim: Claim) -> None:
        row = await self._session.get(ClaimRow, claim.id)
        if row is None:
            raise NotFoundError(code="CLAIM_NOT_FOUND", detail="Claim not found")
        apply_claim(row, claim)
        await self._session.flush()

    async def add_event(self, event: Event) -> None:
        self._session.add(event_to_row(event))
        await self._session.flush()

    async def events_of(self, bounty_id: UUID) -> list[Event]:
        rows = await self._session.scalars(
            select(EventRow)
            .where(EventRow.bounty_id == bounty_id)
            .order_by(EventRow.id)
        )
        return [event_from_row(row) for row in rows]
