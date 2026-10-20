"""Write scenarios for the HTTP API: plain values in, read models out.

`BountyService` speaks the domain (`Criterion`, `SolverKind`, `Claim`); the
presentation layer must not. This facade converts at the boundary, and answers
every call with the read model a client would fetch next, so a response never
shows more than a page does: no payee e-mail, no funder key hash.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from decimal import Decimal
from typing import Literal
from uuid import UUID

from proofpay.modules.bounties.application.queries import (
    BountyQueries,
    BountyView,
    ClaimView,
)
from proofpay.modules.bounties.application.service import BountyService
from proofpay.modules.bounties.domain.entities import Criterion, SolverKind


@dataclass(frozen=True, slots=True)
class CriterionInput:
    """A criterion as the funder edited it."""

    id: str
    text: str


@dataclass(frozen=True, slots=True)
class CreatedBountyView:
    """A new draft bounty and its funder key, which is shown once."""

    bounty: BountyView
    funder_key: str


class BountyCommands:
    """Every write the HTTP API offers."""

    def __init__(self, service: BountyService, queries: BountyQueries) -> None:
        self._service = service
        self._queries = queries

    async def create(
        self, issue_url: str, amount: Decimal, done_when: str
    ) -> CreatedBountyView:
        created = await self._service.create(issue_url, amount, done_when)
        page = await self._queries.bounty_page(created.bounty.id)
        return CreatedBountyView(bounty=page, funder_key=created.funder_key)

    async def fund(
        self, bounty_id: UUID, key: str, criteria: Sequence[CriterionInput]
    ) -> str:
        """Returns the PayPal approve URL."""
        return await self._service.fund(
            bounty_id,
            key,
            [Criterion(id=item.id, text=item.text) for item in criteria],
        )

    async def confirm_payment(self, order_id: str) -> UUID:
        """Returns the id of the bounty the order belongs to."""
        return await self._service.confirm_payment(order_id)

    async def cancel_payment(self, order_id: str) -> UUID:
        """Returns the id of the bounty the order belongs to."""
        return await self._service.cancel_payment(order_id)

    async def claim(
        self,
        bounty_id: UUID,
        solver_name: str,
        solver_kind: Literal["human", "agent"],
        paypal_email: str,
    ) -> ClaimView:
        claim = await self._service.claim(
            bounty_id, solver_name, SolverKind(solver_kind), paypal_email
        )
        return await self._queries.claim_view(claim.id)

    async def submit(self, claim_id: UUID, pr_url: str) -> ClaimView:
        claim = await self._service.submit(claim_id, pr_url)
        return await self._queries.claim_view(claim.id)

    async def decide(
        self, bounty_id: UUID, key: str, decision: Literal["release", "reject"]
    ) -> BountyView:
        await self._service.decide(bounty_id, key, decision)
        return await self._queries.bounty_page(bounty_id)

    async def cancel(self, bounty_id: UUID, key: str) -> BountyView:
        await self._service.cancel(bounty_id, key)
        return await self._queries.bounty_page(bounty_id)
