"""Background tasks of the bounties module.

An entry point like presentation: a task opens a scope of the worker container
and calls the application service. The names and the queue are the contract
with `jobs.py`, which defers by name.
"""

from uuid import UUID

from proofpay.modules.bounties.application.service import BountyService
from proofpay.modules.bounties.infrastructure.jobs import (
    MONEY_QUEUE,
    POLL_PAYOUT_TASK,
    REVIEW_TASK,
)
from proofpay.worker import app, container

EXPIRE_DUE_TASK = "bounties.expire_due"


@app.task(name=REVIEW_TASK, queue=MONEY_QUEUE)
async def review_claim(claim_id: str) -> None:
    """Judges the pull request of a claim and moves its money."""
    async with container() as scope:
        service = await scope.get(BountyService)
        await service.review(UUID(claim_id))


@app.task(name=POLL_PAYOUT_TASK, queue=MONEY_QUEUE)
async def poll_payout(claim_id: str) -> None:
    """Checks whether the payout of a claim has been delivered."""
    async with container() as scope:
        service = await scope.get(BountyService)
        await service.poll_payout(UUID(claim_id))


@app.periodic(cron="*/10 * * * *")
@app.task(
    name=EXPIRE_DUE_TASK,
    queue=MONEY_QUEUE,
    # queueing_lock: not queued twice; lock: not run by two workers at once.
    queueing_lock=EXPIRE_DUE_TASK,
    lock=EXPIRE_DUE_TASK,
)
async def expire_due(timestamp: int) -> None:
    """Voids authorizations that are about to run out."""
    async with container() as scope:
        service = await scope.get(BountyService)
        await service.expire_due()
