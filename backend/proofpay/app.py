"""Litestar assembly point: routers, dependency container, errors, OpenAPI."""

import asyncio
import sys
from typing import TYPE_CHECKING, Any

import structlog
from dishka import FromDishka
from dishka.integrations.litestar import inject, setup_dishka
from litestar import Litestar, Request, Response, Router, get
from litestar.exceptions import HTTPException
from litestar.openapi import OpenAPIConfig
from litestar.openapi.plugins import ScalarRenderPlugin
from litestar.status_codes import HTTP_503_SERVICE_UNAVAILABLE
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from proofpay.di import build_container
from proofpay.modules.registry import all_routers
from proofpay.settings import Settings
from proofpay.shared.errors import DomainError, problem_detail
from proofpay.shared.logging import setup_logging

if TYPE_CHECKING:
    from dishka import AsyncContainer

# Content type of an error response per RFC 9457.
PROBLEM_MEDIA_TYPE = "application/problem+json"


@get(
    "/healthz",
    tags=["Service"],
    summary="Process liveness",
    description=(
        "Answers as long as the application process is alive. Does not check "
        "external dependencies - use /readyz for that."
    ),
)
async def healthz() -> dict[str, str]:
    return {"status": "ok"}


@get(
    "/readyz",
    tags=["Service"],
    summary="Readiness to accept requests",
    description=(
        "Checks PostgreSQL, the only service request handling cannot do "
        "without. Answers 503 when it is unavailable; the body carries the "
        "state of the service."
    ),
)
@inject
async def readyz(db: FromDishka[AsyncSession]) -> Response[dict[str, Any]]:
    """Readiness of the database."""
    checks = {"postgres": await _probe_postgres(db)}
    ready = all(state == "ok" for state in checks.values())
    return Response(
        content={"status": "ok" if ready else "unavailable", "checks": checks},
        status_code=200 if ready else HTTP_503_SERVICE_UNAVAILABLE,
    )


async def _probe_postgres(db: AsyncSession) -> str:
    """Runs a trivial query, turning a failure into a state.

    The reason goes to the log: from outside /readyz only reports the state,
    and without a log entry diagnosis would come down to guessing.
    """
    try:
        await db.execute(text("SELECT 1"))
    except Exception as exc:
        structlog.get_logger(__name__).warning(
            "readyz.service_unavailable",
            service="postgres",
            error=str(exc),
        )
        return "unavailable"
    return "ok"


def domain_error_handler(
    request: Request[Any, Any, Any],
    exc: DomainError,
) -> Response[dict[str, Any]]:
    """Domain exception to an RFC 9457 problem+json response."""
    return Response(
        content=problem_detail(exc, instance=request.url.path),
        status_code=exc.status,
        media_type=PROBLEM_MEDIA_TYPE,
    )


def http_exception_handler(
    request: Request[Any, Any, Any],
    exc: HTTPException,
) -> Response[dict[str, Any]]:
    """Litestar's own error responses in the same problem+json format."""
    return Response(
        content={
            "type": "about:blank",
            "title": exc.detail,
            "status": exc.status_code,
            "instance": request.url.path,
            "code": type(exc).__name__,
            # Litestar's `extra` is either a dict of substitutions or a list
            # of validation messages; both are passed through to the client.
            **({"params": exc.extra} if isinstance(exc.extra, dict) else {}),
            **({"errors": exc.extra} if isinstance(exc.extra, list) else {}),
        },
        status_code=exc.status_code,
        media_type=PROBLEM_MEDIA_TYPE,
    )


def create_app(
    settings: Settings | None = None,
    container: AsyncContainer | None = None,
) -> Litestar:
    """Builds the application.

    Tests pass settings and container; in normal operation settings come
    from the environment and the container builds itself.
    """
    if settings is None:
        settings = Settings()

    setup_logging(json=not settings.debug)
    dishka_container = container if container is not None else build_container()

    app = Litestar(
        route_handlers=[healthz, readyz, *all_routers()],
        exception_handlers={
            DomainError: domain_error_handler,
            HTTPException: http_exception_handler,
        },
        openapi_config=OpenAPIConfig(
            title="ProofPay API",
            version="0.1.0",
            summary="Escrowed bounties for GitHub issues",
            path="/api/docs",
            render_plugins=[ScalarRenderPlugin()],
            use_handler_docstrings=True,
            # include_in_schema=False is required: a custom router overrides
            # the default, and the documentation pages would otherwise land
            # in the schema itself, where the client generator turns them
            # into API calls. There is no login, so the router has no guard.
            openapi_router=Router(
                path="/api/docs",
                route_handlers=[],
                include_in_schema=False,
            ),
        ),
        debug=settings.debug,
    )
    setup_dishka(container=dishka_container, app=app)
    return app


def main() -> None:
    """Runs the application server.

    The event loop is created here rather than by uvicorn: on Windows uvicorn
    picks the Proactor loop by default, which is incompatible with psycopg in
    async mode - the app starts but cannot see the database. Production runs
    on Linux, where the loop stays the default one.

    For auto-reload during development use uvicorn directly:
    ``uv run uvicorn proofpay.app:create_app --factory --reload``.
    """
    import uvicorn  # noqa: PLC0415

    settings = Settings()
    config = uvicorn.Config(
        "proofpay.app:create_app",
        factory=True,
        host="0.0.0.0",  # noqa: S104
        port=8000,
        log_level="debug" if settings.debug else "info",
    )
    loop_factory = asyncio.SelectorEventLoop if sys.platform == "win32" else None
    with asyncio.Runner(loop_factory=loop_factory) as runner:
        runner.run(uvicorn.Server(config).serve())
