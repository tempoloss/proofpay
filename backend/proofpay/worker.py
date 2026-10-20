"""Entry point of procrastinate background tasks.

The procrastinate app works on a plain PostgreSQL DSN: the SQLAlchemy dialect
(``postgresql+psycopg://``) is unknown to it. The dependency container is the
worker one (``build_worker_container``). A task gets its dependencies by
opening a request scope of the container::

    async with container() as scope:
        service = await scope.get(SomeService)
"""

import asyncio
import sys

import procrastinate

from proofpay.di import build_worker_container
from proofpay.settings import Settings


def _plain_dsn(url: str) -> str:
    """DSN without the SQLAlchemy dialect prefix."""
    return url.replace("postgresql+psycopg://", "postgresql://", 1)


container = build_worker_container()

app = procrastinate.App(
    connector=procrastinate.PsycopgConnector(
        conninfo=_plain_dsn(Settings().database_url)
    ),
    # Task modules register their tasks on `app` as an import side effect.
    import_paths=["proofpay.modules.bounties.infrastructure.tasks"],
)


async def _serve() -> None:
    """Opens the connection and serves the queues until stopped."""
    async with app.open_async():
        await app.run_worker_async()


def main() -> None:
    """Runs the procrastinate worker.

    The connection is async (psycopg), so both opening the app and serving
    the queues run in async mode: the synchronous ``app.open()`` is not
    implemented for an async connector.

    On Windows the default event loop (Proactor) is incompatible with psycopg
    in async mode; production runs on Linux, where the default loop stays.
    """
    loop_factory = asyncio.SelectorEventLoop if sys.platform == "win32" else None
    with asyncio.Runner(loop_factory=loop_factory) as runner:
        runner.run(_serve())
