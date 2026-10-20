"""Engine and session factory."""

from contextlib import asynccontextmanager
from typing import TYPE_CHECKING

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    from proofpay.settings import Settings


def build_engine(
    settings: Settings,
) -> tuple[AsyncEngine, async_sessionmaker[AsyncSession]]:
    """Async engine and a session factory bound to it."""
    engine = create_async_engine(
        settings.database_url,
        echo=settings.debug,
        pool_size=settings.db_pool_size,
        max_overflow=settings.db_max_overflow,
    )
    factory = async_sessionmaker(engine, expire_on_commit=False)
    return engine, factory


@asynccontextmanager
async def open_session(
    factory: async_sessionmaker[AsyncSession],
) -> AsyncIterator[AsyncSession]:
    """Database session that is closed when the context exits."""
    async with factory() as session:
        yield session
