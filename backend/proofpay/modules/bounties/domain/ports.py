"""Ports of the bounties module towards background work."""

from datetime import timedelta
from typing import Protocol
from uuid import UUID


class JobQueue(Protocol):
    """Schedules the background steps of a claim.

    Callers commit before scheduling: a job must never see uncommitted state.
    A step that is already waiting in the queue for the same claim is not
    scheduled twice.
    """

    async def review(self, claim_id: UUID, *, delay: timedelta | None = None) -> None:
        """Review the pull request of a claim, after `delay` if given."""
        ...

    async def poll_payout(
        self, claim_id: UUID, *, delay: timedelta | None = None
    ) -> None:
        """Check the payout of a claim, after `delay` if given."""
        ...
