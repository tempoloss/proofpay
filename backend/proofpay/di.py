"""Root Dishka containers.

The list of modules lives in proofpay.modules.registry; this file only
assembles. There are two containers because there are two entry points:
the HTTP application and the background worker (which has no request).
"""

from dishka import AsyncContainer, make_async_container
from dishka.integrations.litestar import LitestarProvider

from proofpay.modules.registry import all_providers
from proofpay.shared.di import InfraProvider, SessionProvider


def build_container() -> AsyncContainer:
    """Application container: infrastructure, request integration, modules."""
    return make_async_container(
        InfraProvider(),
        SessionProvider(),
        LitestarProvider(),
        *all_providers(),
    )


def build_worker_container() -> AsyncContainer:
    """Background-task container: no request, no HTTP integration."""
    return make_async_container(
        InfraProvider(),
        SessionProvider(),
        *all_providers(),
    )
