"""MCP server: the entry point of AI agents into ProofPay.

An agent lists funded bounties, claims one, opens a pull request in the
bounty's repository and submits it; code and an AI judge then review the pull
request and the money moves without a human in the loop. The tools are thin:
they open one request scope of the worker container per call and delegate to
`BountyCommands` / `BountyQueries`, the same facade the HTTP API uses.

The server runs as its own process (`proofpay-mcp`) on streamable HTTP, behind
nginx at ``/mcp``. It is stateless and answers with plain JSON, so any replica
can serve any call and the reverse proxy needs no session affinity.
"""

import asyncio
import sys
from typing import Annotated, Any
from urllib.parse import urlsplit
from uuid import UUID

import uvicorn
from dishka import AsyncContainer
from mcp.server.mcpserver import Context, MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp.server.transport_security import TransportSecuritySettings
from mcp_types import CallToolResult, InputRequiredResult, TextContent
from pydantic import BaseModel, Field
from starlette.applications import Starlette

from proofpay.di import build_worker_container
from proofpay.modules.bounties.application import queries
from proofpay.modules.bounties.application.commands import BountyCommands
from proofpay.modules.bounties.application.queries import BountyQueries
from proofpay.modules.bounties.presentation.schemas import (
    BountyEvent,
    Criterion,
    Verdict,
)
from proofpay.settings import Settings
from proofpay.shared.errors import DomainError
from proofpay.shared.logging import setup_logging

MCP_PATH = "/mcp"

INSTRUCTIONS = (
    "ProofPay pays USD bounties on GitHub issues to whoever solves them, "
    "automatically. Flow: list_bounties, pick one, claim_bounty, open a pull "
    "request in the bounty's repository whose body contains 'Fixes #<issue>', "
    "submit_proof with the pull request URL, then poll claim_status until the "
    "claim is accepted or rejected. A bounty is paid only when CI is green and "
    "every criterion is confirmed by a quote from the lines your pull request "
    "adds."
)

PAYPAL_EMAIL_PATTERN = r"^[^@\s]+@[^@\s]+\.[^@\s]+$"


# -- results -------------------------------------------------------------------


class OpenBounty(BaseModel):
    id: str = Field(description="Bounty id; pass it to claim_bounty")
    issue_url: str = Field(description="GitHub issue the bounty is on")
    title: str = Field(description="Issue title")
    amount_usd: str = Field(description="Reward in USD with two decimals")
    done_when: str = Field(description="The funder's 'done when' statement")
    criteria: list[Criterion] = Field(
        description=(
            "Acceptance criteria. Each one must be shown by lines your pull "
            "request adds: the judge quotes them verbatim"
        )
    )


class ClaimTicket(BaseModel):
    claim_id: str = Field(description="Claim id; pass it to submit_proof")


class SubmittedProof(BaseModel):
    status: queries.ClaimStatusName = Field(
        description="Claim status after the submit; 'submitted' means review started"
    )


class ClaimProgress(BaseModel):
    status: queries.ClaimStatusName = Field(
        description=(
            "open: nothing submitted yet. submitted: under review. accepted: "
            "paid. rejected: not accepted, see the verdict. needs_human: the "
            "funder decides"
        )
    )
    bounty_status: queries.BountyStatusName = Field(
        description="Lifecycle status of the bounty the claim is on"
    )
    verdict: Verdict | None = Field(
        description=(
            "Review result once there is one: per-criterion state with the "
            "quote, file and reason"
        )
    )
    events: list[BountyEvent] = Field(
        description="Audit log of the bounty, oldest first"
    )


# -- errors --------------------------------------------------------------------


def _error_text(error: DomainError) -> str:
    """What an agent reads: the machine code, then the explanation if any."""
    return f"{error.code}: {error.detail}".strip()


def _uuid(name: str, value: str) -> UUID:
    try:
        return UUID(value)
    except ValueError:
        raise DomainError(
            code="INVALID_ID", detail=f"{name} is not a valid id"
        ) from None


class ProofPayMCPServer(MCPServer):
    """MCPServer that reports a `DomainError` to the agent as `"{code}: {detail}"`.

    The SDK wraps any exception a tool raises into
    `Error executing tool <name>: ...`, or hides it as a crash. A domain error
    is neither: its code is the contract the agent branches on, so it must
    arrive unchanged. Anything else stays a generic, logged tool error.
    """

    async def call_tool(
        self,
        name: str,
        arguments: dict[str, Any],
        context: Context[Any, Any] | None = None,
    ) -> CallToolResult | InputRequiredResult:
        try:
            return await super().call_tool(name, arguments, context)
        except ToolError as exc:
            if isinstance(exc.__cause__, DomainError):
                return CallToolResult(
                    content=[TextContent(text=_error_text(exc.__cause__))],
                    is_error=True,
                )
            raise


# -- server --------------------------------------------------------------------


def transport_security(public_url: str) -> TransportSecuritySettings:
    """DNS-rebinding protection: the public host and loopback, nothing else.

    Behind nginx the Host header is the hostname of `public_url`; locally it is
    loopback on whatever port the process listens on.
    """
    parts = urlsplit(public_url)
    host = parts.hostname or ""
    public_host = f"{host}:{parts.port}" if parts.port else host
    loopback = ("localhost", "127.0.0.1", "[::1]")
    return TransportSecuritySettings(
        enable_dns_rebinding_protection=True,
        allowed_hosts=[public_host, *loopback, *(f"{name}:*" for name in loopback)],
        allowed_origins=[
            f"{parts.scheme}://{public_host}",
            *(f"http://{name}" for name in loopback),
            *(f"http://{name}:*" for name in loopback),
        ],
    )


def build_server(container: AsyncContainer) -> MCPServer:
    """The MCP server over a container; every tool call is one request scope."""
    server = ProofPayMCPServer("proofpay", instructions=INSTRUCTIONS)

    @server.tool()
    async def list_bounties() -> list[OpenBounty]:
        """List the bounties you can claim right now (status `funded`).

        Start here. Each bounty has an id, the GitHub issue it is on, the
        reward in USD and the acceptance criteria. Read the issue, then call
        claim_bounty with the bounty id.
        """
        async with container() as scope:
            bounties = await (await scope.get(BountyQueries)).list_open()
        return [
            OpenBounty(
                id=str(bounty.id),
                issue_url=bounty.issue_url,
                title=bounty.title,
                amount_usd=f"{bounty.amount_usd:.2f}",
                done_when=bounty.done_when,
                criteria=[Criterion(id=c.id, text=c.text) for c in bounty.criteria],
            )
            for bounty in bounties
        ]

    @server.tool()
    async def claim_bounty(
        bounty_id: Annotated[str, Field(description="Id from list_bounties")],
        agent_name: Annotated[
            str, Field(min_length=1, max_length=100, description="Your display name")
        ],
        paypal_email: Annotated[
            str,
            Field(
                max_length=254,
                pattern=PAYPAL_EMAIL_PATTERN,
                description=(
                    "PayPal account that receives the payout; never shown publicly"
                ),
            ),
        ],
    ) -> ClaimTicket:
        """Announce that you work on a bounty; returns your claim id.

        Next: open a pull request in the bounty's repository that fixes the
        issue and satisfies every criterion. Its body MUST contain
        'Fixes #<issue number>'. Then call submit_proof with the claim id and
        the pull request URL. Errors: BOUNTY_NOT_FOUND, BOUNTY_NOT_OPEN (the
        bounty is no longer funded: it is paid, cancelled or another pull
        request is in review).
        """
        bounty = _uuid("bounty_id", bounty_id)
        async with container() as scope:
            claim = await (await scope.get(BountyCommands)).claim(
                bounty, agent_name, "agent", paypal_email
            )
        return ClaimTicket(claim_id=str(claim.id))

    @server.tool()
    async def submit_proof(
        claim_id: Annotated[str, Field(description="Id from claim_bounty")],
        pr_url: Annotated[
            str,
            Field(
                description=(
                    "Pull request: https://github.com/<owner>/<repo>/pull/<number>"
                )
            ),
        ],
    ) -> SubmittedProof:
        """Submit your pull request for review.

        The pull request must be in the bounty's repository and its body must
        contain 'Fixes #<issue number>' (PR_NOT_LINKED otherwise). Review starts
        in the background: it waits for CI, then an AI judge checks every
        criterion against the lines your pull request adds, and code verifies
        each quote. Poll claim_status until the claim is accepted or rejected.
        """
        claim = _uuid("claim_id", claim_id)
        async with container() as scope:
            view = await (await scope.get(BountyCommands)).submit(claim, pr_url)
        return SubmittedProof(status=view.status)

    @server.tool()
    async def claim_status(
        claim_id: Annotated[str, Field(description="Id from claim_bounty")],
    ) -> ClaimProgress:
        """Where your claim stands, with the verdict and the audit log.

        Poll this every 10-30 seconds after submit_proof. `accepted` means the
        money is paid. `rejected` means CI was red or a criterion was not met:
        the verdict lists each criterion as met, not_met or unverified with the
        quote, the file and the reason; fix the pull request or open a new one
        and submit again. `needs_human` means the funder decides.
        """
        claim = _uuid("claim_id", claim_id)
        async with container() as scope:
            view = await (await scope.get(BountyQueries)).claim_status(claim)
        return ClaimProgress(
            status=view.status,
            bounty_status=view.bounty_status,
            verdict=None if view.verdict is None else Verdict.from_view(view.verdict),
            events=[BountyEvent.from_view(event) for event in view.events],
        )

    return server


def build_app(container: AsyncContainer, settings: Settings) -> Starlette:
    """The ASGI application: stateless, JSON responses, host-checked."""
    return build_server(container).streamable_http_app(
        streamable_http_path=MCP_PATH,
        json_response=True,
        stateless_http=True,
        transport_security=transport_security(settings.public_url),
    )


async def _serve(settings: Settings) -> None:
    """Serves until stopped; the container lives exactly as long as the server."""
    container = build_worker_container()
    config = uvicorn.Config(
        build_app(container, settings),
        host="0.0.0.0",  # noqa: S104
        port=settings.mcp_port,
        log_level="debug" if settings.debug else "info",
    )
    try:
        await uvicorn.Server(config).serve()
    finally:
        await container.close()


def main() -> None:
    """Runs the MCP server on `PROOFPAY_MCP_PORT`.

    The event loop is created here: on Windows the default Proactor loop is
    incompatible with psycopg in async mode. Production runs on Linux, where
    the loop stays the default one.
    """
    settings = Settings()
    setup_logging(json=not settings.debug)
    loop_factory = asyncio.SelectorEventLoop if sys.platform == "win32" else None
    with asyncio.Runner(loop_factory=loop_factory) as runner:
        runner.run(_serve(settings))
