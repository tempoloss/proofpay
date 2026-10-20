"""DI provider of the bounties module.

The procrastinate app used for deferring jobs is separate from the worker's
own app (`proofpay.worker.app`): this one only inserts jobs, the worker serves
them. It opens on first use and closes with the container.
"""

from collections.abc import AsyncIterator

import procrastinate
from dishka import Provider, Scope, provide

from proofpay.modules.bounties.application.queries import BountyQueries
from proofpay.modules.bounties.application.service import BountyService
from proofpay.modules.bounties.domain.ports import JobQueue
from proofpay.modules.bounties.domain.repositories import BountyRepository
from proofpay.modules.bounties.infrastructure.jobs import ProcrastinateJobQueue
from proofpay.modules.bounties.infrastructure.repository import SqlBountyRepository
from proofpay.settings import Settings


class BountyProvider(Provider):
    """Repository, use cases and the job queue of the bounties module."""

    scope = Scope.REQUEST

    repository = provide(SqlBountyRepository, provides=BountyRepository)
    service = provide(BountyService)
    queries = provide(BountyQueries)

    @provide(scope=Scope.APP)
    async def job_app(self, settings: Settings) -> AsyncIterator[procrastinate.App]:
        conninfo = settings.database_url.replace(
            "postgresql+psycopg://", "postgresql://", 1
        )
        app = procrastinate.App(
            connector=procrastinate.PsycopgConnector(conninfo=conninfo)
        )
        async with app.open_async():
            yield app

    @provide(scope=Scope.APP)
    def job_queue(self, app: procrastinate.App) -> JobQueue:
        return ProcrastinateJobQueue(app)


provider = BountyProvider()
