"""Shared ProofPay test fixtures.

Tests run against a real PostgreSQL: constraints, row locks and sequences are
not verified by mocks. The database address comes from the environment so the
same setup works on a workstation and in CI:

- ``PROOFPAY_TEST_DATABASE_URL`` - the test database (created on first run and
  brought up to date by migrations).
"""

import asyncio
import os
import sys
from asyncio import AbstractEventLoop
from collections.abc import AsyncIterator, Callable, Iterator
from pathlib import Path
from typing import TYPE_CHECKING

import psycopg
import pytest
from alembic import command
from alembic.config import Config
from dishka import make_async_container
from dishka.integrations.litestar import LitestarProvider
from litestar.testing import AsyncTestClient
from psycopg import sql
from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from proofpay.app import create_app
from proofpay.integrations.providers import IntegrationsProvider
from proofpay.modules.registry import MODULES, all_providers
from proofpay.settings import Settings
from proofpay.shared.di import InfraProvider, SessionProvider
from tests.fakes import FakeServices, FakeServicesProvider, Flow

if TYPE_CHECKING:
    from dishka import AsyncContainer
    from litestar import Litestar

BACKEND_ROOT = Path(__file__).resolve().parents[1]

DEFAULT_TEST_DB_URL = (
    "postgresql+psycopg://proofpay:proofpay@localhost:5433/proofpay_test"
)

# Schemas whose data is wiped between tests: those owned by registered modules.
TRUNCATED_SCHEMAS = tuple(MODULES.values())


def pytest_configure(config: pytest.Config) -> None:
    """Marker registration (duplicated from pyproject.toml)."""
    config.addinivalue_line("markers", "boundary: module boundary tests")
    config.addinivalue_line(
        "markers", "integration: integration tests that need a database"
    )


def pytest_asyncio_loop_factories() -> dict[str, Callable[[], AbstractEventLoop]]:
    """Event loop for async tests.

    On Windows the default loop (Proactor) is incompatible with psycopg in
    async mode, so the Selector loop is used. Production runs on Linux, where
    the default loop stays.
    """
    if sys.platform == "win32":
        return {"selector": asyncio.SelectorEventLoop}
    return {"default": asyncio.new_event_loop}


def _create_database_if_missing(database_url: str) -> None:
    """Creates the test database through the ``postgres`` maintenance database."""
    url = make_url(database_url)
    database = url.database
    if database is None:
        message = "test database URL has no database name"
        raise ValueError(message)
    maintenance = url.set(drivername="postgresql", database="postgres")
    dsn = maintenance.render_as_string(hide_password=False)
    with psycopg.connect(dsn, autocommit=True) as connection:
        exists = connection.execute(
            "SELECT 1 FROM pg_database WHERE datname = %s", (database,)
        ).fetchone()
        if exists is None:
            connection.execute(
                sql.SQL("CREATE DATABASE {}").format(sql.Identifier(database))
            )


@pytest.fixture(scope="session")
def test_database_url() -> str:
    """Address of the test database."""
    return os.environ.get("PROOFPAY_TEST_DATABASE_URL", DEFAULT_TEST_DB_URL)


@pytest.fixture(scope="session", autouse=True)
def environment(test_database_url: str) -> Iterator[None]:
    """Application environment variables for the duration of the run.

    The application reads settings from the environment, so tests set them
    the same way the real environment does instead of patching a settings
    object.
    """
    previous = {
        key: os.environ.get(key) for key in ("PROOFPAY_DATABASE_URL", "PROOFPAY_DEBUG")
    }
    os.environ["PROOFPAY_DATABASE_URL"] = test_database_url
    os.environ["PROOFPAY_DEBUG"] = "true"
    yield
    for key, value in previous.items():
        if value is None:
            os.environ.pop(key, None)
        else:
            os.environ[key] = value


@pytest.fixture
def settings(environment: None) -> Settings:
    """Application settings from the test environment."""
    return Settings()


@pytest.fixture(scope="session")
def migrated_database(environment: None, test_database_url: str) -> str:
    """Prepares the test database: creates it and applies migrations."""
    _create_database_if_missing(test_database_url)
    config = Config(str(BACKEND_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(BACKEND_ROOT / "migrations"))
    command.upgrade(config, "head")
    return test_database_url


@pytest.fixture
async def engine(migrated_database: str) -> AsyncIterator[AsyncEngine]:
    """A separate engine for preparing and inspecting data in tests."""
    created = create_async_engine(migrated_database)
    yield created
    await created.dispose()


async def _truncate_all(engine: AsyncEngine) -> None:
    """Empties every table of the module schemas; no-op with no modules."""
    if not TRUNCATED_SCHEMAS:
        return
    async with engine.begin() as connection:
        result = await connection.execute(
            text(
                "SELECT format('%I.%I', schemaname, tablename) "
                "FROM pg_tables WHERE schemaname = ANY(:schemas)"
            ),
            {"schemas": list(TRUNCATED_SCHEMAS)},
        )
        tables = [row[0] for row in result]
        if tables:
            await connection.execute(
                text(f"TRUNCATE {', '.join(tables)} RESTART IDENTITY CASCADE")
            )


@pytest.fixture
async def clean_database(engine: AsyncEngine) -> AsyncIterator[None]:
    """Cleans application data before and after a test."""
    await _truncate_all(engine)
    yield
    await _truncate_all(engine)


@pytest.fixture
def services() -> FakeServices:
    """The fake external services of one test."""
    return FakeServices()


@pytest.fixture
async def container(
    clean_database: None, services: FakeServices
) -> AsyncIterator[AsyncContainer]:
    """Application container: the production provider set, fakes last.

    The container takes the last registered implementation of a port, so the
    external services are fakes while everything else stays real.
    """
    built = make_async_container(
        InfraProvider(),
        SessionProvider(),
        IntegrationsProvider(),
        LitestarProvider(),
        *all_providers(),
        FakeServicesProvider(services),
    )
    yield built
    await built.close()


@pytest.fixture
def flow(container: AsyncContainer, services: FakeServices) -> Flow:
    """Scenario driver over the test container."""
    return Flow(container, services)


@pytest.fixture
async def app(container: AsyncContainer) -> Litestar:
    """Application with the test container."""
    return create_app(container=container)


@pytest.fixture
async def client(app: Litestar) -> AsyncIterator[AsyncTestClient[Litestar]]:
    """Application client; starts and stops the lifecycle."""
    # The client runs the application lifecycle in its own event loop; on
    # Windows it must be a Selector loop too, or psycopg refuses to work in
    # async mode.
    options = (
        {"loop_factory": asyncio.SelectorEventLoop} if sys.platform == "win32" else {}
    )
    async with AsyncTestClient(app=app, backend_options=options) as test_client:
        yield test_client
