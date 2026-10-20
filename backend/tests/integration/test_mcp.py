"""The MCP server as an agent sees it: tools over the SDK's in-memory client.

Real PostgreSQL and the real server; PayPal, GitHub, the model and the job
queue are the fakes of `tests/fakes.py`. The review and payout jobs are not
tools: the tests run them the way the worker does, through `BountyService`.
"""

import json
from typing import Any
from uuid import UUID, uuid4

import httpx
import pytest
from dishka import AsyncContainer
from mcp import Client
from mcp.server.mcpserver import MCPServer
from mcp_types import CallToolResult, ListToolsResult

from proofpay.mcp_server import build_app, build_server
from proofpay.settings import Settings
from tests.fakes import (
    PR_URL,
    SOLVER_EMAIL,
    SOURCE_QUOTE,
    TEST_QUOTE,
    FakeServices,
    Flow,
    Opened,
    confirming_judge,
)

pytestmark = pytest.mark.integration


class Agent:
    """An agent's connection: one in-memory session per call.

    The real endpoint is stateless, so a call never depends on an earlier one;
    a session per call also keeps the SDK's task groups inside one task.
    """

    def __init__(self, server: MCPServer) -> None:
        self._server = server

    async def call_tool(self, name: str, arguments: dict[str, Any]) -> CallToolResult:
        async with Client(self._server) as client:
            return await client.call_tool(name, arguments)

    async def list_tools(self) -> ListToolsResult:
        async with Client(self._server) as client:
            return await client.list_tools()


@pytest.fixture
def agent(container: AsyncContainer) -> Agent:
    return Agent(build_server(container))


async def _call(agent: Agent, tool: str, **arguments: Any) -> CallToolResult:
    return await agent.call_tool(tool, arguments)


def _ok(result: CallToolResult) -> dict[str, Any]:
    assert not result.is_error, result.content
    assert result.structured_content is not None
    return result.structured_content


def _error(result: CallToolResult) -> str:
    assert result.is_error
    assert len(result.content) == 1
    block = result.content[0]
    assert block.type == "text"
    return block.text


async def _claim(agent: Agent, bounty_id: UUID) -> str:
    claimed = _ok(
        await _call(
            agent,
            "claim_bounty",
            bounty_id=str(bounty_id),
            agent_name="agent-7",
            paypal_email=SOLVER_EMAIL,
        )
    )
    return str(claimed["claim_id"])


async def _settle(flow: Flow, services: FakeServices, claim_id: UUID) -> None:
    """Runs the jobs a submit queues: review, then the payout poll."""
    services.model.queue(confirming_judge())
    async with flow.service() as service:
        await service.review(claim_id)
    async with flow.service() as service:
        await service.poll_payout(claim_id)


async def test_the_agent_sees_the_tools_of_the_contract(agent: Agent) -> None:
    listed = await agent.list_tools()

    assert sorted(tool.name for tool in listed.tools) == [
        "claim_bounty",
        "claim_status",
        "list_bounties",
        "submit_proof",
    ]


async def test_list_bounties_offers_only_funded_ones(agent: Agent, flow: Flow) -> None:
    await flow.draft()
    await flow.awaiting_payment()
    reviewed = await flow.funded("10.00")
    await flow.submitted(reviewed)  # in review: nobody else may take it
    open_bounty = await flow.funded("40.50")

    result = _ok(await _call(agent, "list_bounties"))

    assert [item["id"] for item in result["result"]] == [str(open_bounty.bounty.id)]
    [item] = result["result"]
    assert item["amount_usd"] == "40.50"
    assert item["issue_url"] == "https://github.com/acme/tinycalc/issues/1"
    assert item["title"] == "divide() raises ZeroDivisionError"
    assert [c["id"] for c in item["criteria"]] == ["c1", "c2"]
    assert item["criteria"][1]["text"] == "a test covers dividing by zero"


async def test_claim_bounty_records_an_agent_claim_and_hides_the_email(
    agent: Agent, flow: Flow
) -> None:
    opened = await flow.funded()

    result = await _call(
        agent,
        "claim_bounty",
        bounty_id=str(opened.bounty.id),
        agent_name="agent-7",
        paypal_email=SOLVER_EMAIL,
    )

    claim_id = _ok(result)["claim_id"]
    assert SOLVER_EMAIL not in json.dumps(result.model_dump(mode="json"))
    [claim] = (await flow.page(opened.bounty.id)).claims
    assert str(claim.id) == claim_id
    assert claim.solver_kind == "agent"
    assert claim.solver_name == "agent-7"
    assert claim.status == "open"


async def test_claim_bounty_rejects_a_malformed_email_and_creates_no_claim(
    agent: Agent, flow: Flow
) -> None:
    opened = await flow.funded()

    result = await _call(
        agent,
        "claim_bounty",
        bounty_id=str(opened.bounty.id),
        agent_name="agent-7",
        paypal_email="not-an-email",
    )

    assert result.is_error
    assert (await flow.page(opened.bounty.id)).claims == ()


async def test_a_domain_error_reaches_the_agent_as_code_and_detail(
    agent: Agent, flow: Flow
) -> None:
    draft = await flow.draft()

    not_open = await _call(
        agent,
        "claim_bounty",
        bounty_id=str(draft.bounty.id),
        agent_name="agent-7",
        paypal_email=SOLVER_EMAIL,
    )
    missing = await _call(
        agent,
        "claim_bounty",
        bounty_id=str(uuid4()),
        agent_name="agent-7",
        paypal_email=SOLVER_EMAIL,
    )

    assert _error(not_open) == "BOUNTY_NOT_OPEN: The bounty is not open for claims"
    assert _error(missing).startswith("BOUNTY_NOT_FOUND")


async def test_a_malformed_id_is_an_invalid_id_error(agent: Agent) -> None:
    result = await _call(agent, "claim_status", claim_id="12345")

    assert _error(result).startswith("INVALID_ID: ")


async def test_submit_proof_without_the_issue_reference_is_pr_not_linked(
    agent: Agent, flow: Flow, services: FakeServices
) -> None:
    opened = await flow.funded()
    claim_id = await _claim(agent, opened.bounty.id)
    services.code.pr_body = "Handles division by zero, no reference."

    result = await _call(agent, "submit_proof", claim_id=claim_id, pr_url=PR_URL)

    assert _error(result).startswith("PR_NOT_LINKED: ")
    assert (await flow.page(opened.bounty.id)).status == "funded"
    assert services.jobs.calls == []


async def test_an_unexpected_failure_leaks_no_internals(
    agent: Agent, flow: Flow, services: FakeServices
) -> None:
    opened = await flow.funded()
    claim_id = await _claim(agent, opened.bounty.id)
    services.code.fail["pull_request"] = RuntimeError("secret internal detail")

    result = await _call(agent, "submit_proof", claim_id=claim_id, pr_url=PR_URL)

    text = _error(result)
    assert "secret" not in text
    assert text == "Error executing tool submit_proof"


async def _funded_and_submitted(agent: Agent, flow: Flow) -> tuple[Opened, str]:
    opened = await flow.funded()
    claim_id = await _claim(agent, opened.bounty.id)
    submitted = _ok(
        await _call(agent, "submit_proof", claim_id=claim_id, pr_url=PR_URL)
    )
    assert submitted == {"status": "submitted"}
    return opened, claim_id


async def test_claim_status_follows_the_claim_to_accepted_with_quotes(
    agent: Agent, flow: Flow, services: FakeServices
) -> None:
    _opened, claim_id = await _funded_and_submitted(agent, flow)

    waiting = _ok(await _call(agent, "claim_status", claim_id=claim_id))
    assert waiting["status"] == "submitted"
    assert waiting["bounty_status"] == "in_review"
    assert waiting["verdict"] is None

    await _settle(flow, services, UUID(claim_id))

    done = await _call(agent, "claim_status", claim_id=claim_id)
    status = _ok(done)
    assert status["status"] == "accepted"
    assert status["bounty_status"] == "paid"
    assert status["verdict"]["outcome"] == "pass"
    assert status["verdict"]["ci"] == "green"
    items = {item["criterion_id"]: item for item in status["verdict"]["items"]}
    assert items["c1"]["state"] == "met"
    assert items["c1"]["quote"] == SOURCE_QUOTE
    assert items["c1"]["file"] == "src/tinycalc/__init__.py"
    assert items["c1"]["reason"]
    assert items["c2"]["quote"] == TEST_QUOTE
    kinds = [event["kind"] for event in status["events"]]
    assert kinds == [
        "created",
        "funded",
        "claimed",
        "submitted",
        "ci",
        "verdict",
        "captured",
        "payout_sent",
        "paid",
    ]
    assert all(event["at"] for event in status["events"])
    assert SOLVER_EMAIL not in json.dumps(done.model_dump(mode="json"))
    # The payout went to the address the agent gave, once.
    [payout] = services.gateway.calls_of("payout")
    assert payout.args["email"] == SOLVER_EMAIL


async def test_a_rejected_claim_reports_the_failed_criterion(
    agent: Agent, flow: Flow, services: FakeServices
) -> None:
    _opened, claim_id = await _funded_and_submitted(agent, flow)
    judge = confirming_judge()
    judge.items[1].met = False
    judge.items[1].quote = ""
    judge.items[1].reason = "no test for the zero divisor"
    services.model.queue(judge)

    async with flow.service() as service:
        await service.review(UUID(claim_id))

    status = _ok(await _call(agent, "claim_status", claim_id=claim_id))
    assert status["status"] == "rejected"
    assert status["bounty_status"] == "funded"
    states = {
        item["criterion_id"]: item["state"] for item in status["verdict"]["items"]
    }
    assert states == {"c1": "met", "c2": "not_met"}
    assert services.gateway.calls_of("capture") == []


INITIALIZE = {
    "jsonrpc": "2.0",
    "id": 1,
    "method": "initialize",
    "params": {
        "protocolVersion": "2025-06-18",
        "capabilities": {},
        "clientInfo": {"name": "probe", "version": "0"},
    },
}


@pytest.mark.parametrize(
    ("host", "status"),
    [
        ("proof.an8kk.dev", 200),
        ("localhost:8001", 200),
        ("127.0.0.1:8001", 200),
        ("evil.example", 421),
        ("proof.an8kk.dev.evil.example", 421),
    ],
)
async def test_the_http_endpoint_serves_only_the_public_host_and_loopback(
    container: AsyncContainer, host: str, status: int
) -> None:
    app = build_app(container, Settings(public_url="https://proof.an8kk.dev"))

    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(
            transport=transport, base_url="http://test"
        ) as http:
            response = await http.post(
                "/mcp",
                headers={
                    "Host": host,
                    "Accept": "application/json, text/event-stream",
                },
                json=INITIALIZE,
            )

    assert response.status_code == status
    if status == 200:
        assert response.headers["content-type"].startswith("application/json")
        assert response.json()["result"]["serverInfo"]["name"] == "proofpay"
