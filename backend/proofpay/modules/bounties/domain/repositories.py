"""Storage port of the bounties module."""

from datetime import datetime
from typing import Protocol
from uuid import UUID

from proofpay.modules.bounties.domain.entities import Bounty, Claim, Event


class BountyRepository(Protocol):
    """Bounties, their claims and their audit log.

    The repository never commits: the caller owns the transaction, so a state
    change and its event always land together.
    """

    async def get(self, bounty_id: UUID) -> Bounty:
        """Raises NotFoundError(code="BOUNTY_NOT_FOUND") for an unknown id."""
        ...

    async def get_for_update(self, bounty_id: UUID) -> Bounty:
        """Like `get`, but locks the row until the transaction ends."""
        ...

    async def get_by_order_for_update(self, order_id: str) -> Bounty:
        """Locks the bounty funded through a PayPal order.

        Raises NotFoundError(code="BOUNTY_NOT_FOUND") for an unknown order.
        """
        ...

    async def add(self, bounty: Bounty) -> None: ...

    async def save(self, bounty: Bounty) -> None: ...

    async def list_public(self) -> list[Bounty]:
        """Bounties past the draft and payment stages, newest first."""
        ...

    async def list_expiring(self, before: datetime) -> list[Bounty]:
        """Funded or in-review bounties whose authorization ends before `before`."""
        ...

    async def claims_of(self, bounty_id: UUID) -> list[Claim]:
        """Claims of a bounty, oldest first."""
        ...

    async def get_claim(self, claim_id: UUID) -> Claim:
        """Raises NotFoundError(code="CLAIM_NOT_FOUND") for an unknown id."""
        ...

    async def add_claim(self, claim: Claim) -> None: ...

    async def save_claim(self, claim: Claim) -> None: ...

    async def add_event(self, event: Event) -> None: ...

    async def events_of(self, bounty_id: UUID) -> list[Event]:
        """Audit log of a bounty, oldest first."""
        ...
