"""Providers of application-level infrastructure dependencies.

- InfraProvider   - settings, clock, session factory (both entry points).
- SessionProvider - one database session per request or per worker scope.
"""

from collections.abc import AsyncIterator

from dishka import Provider, Scope, provide
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from proofpay.settings import Settings
from proofpay.shared.clock import Clock, SystemClock
from proofpay.shared.db.session import build_engine, open_session


class InfraProvider(Provider):
    """Settings, clock, database session factory."""

    @provide(scope=Scope.APP)
    def settings(self) -> Settings:
        return Settings()

    @provide(scope=Scope.APP)
    def clock(self) -> Clock:
        return SystemClock()

    @provide(scope=Scope.APP)
    async def session_factory(
        self,
        settings: Settings,
    ) -> AsyncIterator[async_sessionmaker[AsyncSession]]:
        engine, factory = build_engine(settings)
        yield factory
        await engine.dispose()


class SessionProvider(Provider):
    """Database session of one request (or one worker task scope)."""

    @provide(scope=Scope.REQUEST)
    async def session(
        self,
        factory: async_sessionmaker[AsyncSession],
    ) -> AsyncIterator[AsyncSession]:
        async with open_session(factory) as session:
            yield session
