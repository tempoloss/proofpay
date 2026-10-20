"""Dishka provider binding integration ports to their implementations.

Every client lives for the whole application and is closed on shutdown.
"""

from collections.abc import AsyncIterator

import httpx
from dishka import Provider, Scope, provide

from proofpay.integrations.github.client import GitHubClient
from proofpay.integrations.github.ports import CodeHost
from proofpay.integrations.llm.client import build_structured_model
from proofpay.integrations.llm.ports import StructuredModel
from proofpay.integrations.paypal.client import PayPalClient
from proofpay.integrations.paypal.ports import PaymentGateway
from proofpay.settings import Settings
from proofpay.shared.clock import Clock

HTTP_TIMEOUT = httpx.Timeout(20.0)


class IntegrationsProvider(Provider):
    """PayPal, GitHub and the language model chain."""

    @provide(scope=Scope.APP)
    async def payment_gateway(
        self, settings: Settings, clock: Clock
    ) -> AsyncIterator[PaymentGateway]:
        client = PayPalClient(httpx.AsyncClient(timeout=HTTP_TIMEOUT), settings, clock)
        try:
            yield client
        finally:
            await client.aclose()

    @provide(scope=Scope.APP)
    async def code_host(self, settings: Settings) -> AsyncIterator[CodeHost]:
        client = GitHubClient(httpx.AsyncClient(timeout=HTTP_TIMEOUT), settings)
        try:
            yield client
        finally:
            await client.aclose()

    @provide(scope=Scope.APP)
    async def structured_model(
        self, settings: Settings
    ) -> AsyncIterator[StructuredModel]:
        model = build_structured_model(settings)
        try:
            yield model
        finally:
            await model.aclose()
