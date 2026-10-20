"""Procrastinate implementation of the job queue port.

Jobs are deferred by task name: the process that defers (the API) never
imports `tasks.py` or `proofpay.worker`, so it needs no worker setup. The
worker registers the tasks under the same names and queue.
"""

import math
from datetime import timedelta
from uuid import UUID

import procrastinate
import structlog
from procrastinate.exceptions import AlreadyEnqueued

REVIEW_TASK = "bounties.review_claim"
POLL_PAYOUT_TASK = "bounties.poll_payout"
MONEY_QUEUE = "money"

log = structlog.get_logger(__name__)


class ProcrastinateJobQueue:
    """Implements JobQueue on a procrastinate app that is already open."""

    def __init__(self, app: procrastinate.App) -> None:
        self._app = app

    async def review(self, claim_id: UUID, *, delay: timedelta | None = None) -> None:
        await self._defer(REVIEW_TASK, f"review:{claim_id}", claim_id, delay)

    async def poll_payout(
        self, claim_id: UUID, *, delay: timedelta | None = None
    ) -> None:
        await self._defer(POLL_PAYOUT_TASK, f"payout:{claim_id}", claim_id, delay)

    async def _defer(
        self, task: str, lock: str, claim_id: UUID, delay: timedelta | None
    ) -> None:
        # An unknown task gets the default queue unless it is named here, so the
        # queue is passed explicitly instead of being left to the task decorator.
        deferrer = self._app.configure_task(
            task,
            queue=MONEY_QUEUE,
            queueing_lock=lock,
            schedule_in=(
                None if delay is None else {"seconds": math.ceil(delay.total_seconds())}
            ),
        )
        try:
            await deferrer.defer_async(claim_id=str(claim_id))
        except AlreadyEnqueued:
            # A job with this lock is already waiting and will do the work.
            log.info("job_already_enqueued", task=task, claim_id=str(claim_id))
