"""Read routes of the bounties API, through HTTP."""

import pytest
from litestar import Litestar
from litestar.testing import AsyncTestClient

from proofpay.modules.bounties.domain.rules import hash_funder_key
from tests.fakes import SOLVER_EMAIL, FakeServices, Flow, confirming_judge

pytestmark = pytest.mark.integration


async def test_list_hides_drafts_and_unpaid_bounties(
    flow: Flow, client: AsyncTestClient[Litestar]
) -> None:
    await flow.draft()
    await flow.awaiting_payment()
    funded = await flow.funded("40.00")

    response = await client.get("/api/v1/bounties")

    assert response.status_code == 200
    body = response.json()
    assert [item["id"] for item in body] == [str(funded.bounty.id)]
    assert body[0]["status"] == "funded"
    assert body[0]["amount_usd"] == "40.00"
    assert body[0]["issue_url"] == "https://github.com/acme/tinycalc/issues/1"
    assert [item["id"] for item in body[0]["criteria"]] == ["c1", "c2"]


async def test_list_shows_the_newest_bounty_first(
    flow: Flow, client: AsyncTestClient[Litestar]
) -> None:
    older = await flow.funded("10.00")
    newer = await flow.funded("20.00")

    response = await client.get("/api/v1/bounties")

    assert [item["id"] for item in response.json()] == [
        str(newer.bounty.id),
        str(older.bounty.id),
    ]


async def test_page_shows_claims_verdict_and_events_without_private_data(
    flow: Flow, services: FakeServices, client: AsyncTestClient[Litestar]
) -> None:
    opened = await flow.funded()
    claim = await flow.submitted(opened)
    services.model.queue(confirming_judge())
    async with flow.service() as service:
        await service.review(claim.id)

    response = await client.get(f"/api/v1/bounties/{opened.bounty.id}")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "released"
    assert body["amount_usd"] == "25.00"
    assert [item["solver_name"] for item in body["claims"]] == ["agent-7"]
    assert body["claims"][0]["pr_url"].endswith("/pull/7")
    assert body["verdict"]["outcome"] == "pass"
    assert [item["state"] for item in body["verdict"]["items"]] == ["met", "met"]
    assert body["verdict"]["items"][0]["file"] == "src/tinycalc/__init__.py"
    kinds = [event["kind"] for event in body["events"]]
    assert kinds[:3] == ["created", "funded", "claimed"]
    assert kinds[-2:] == ["captured", "payout_sent"]
    # What must never leave the server: the payee's e-mail, the funder's key
    # and the hash that would let anyone check a guessed key.
    raw = response.text
    assert SOLVER_EMAIL not in raw
    assert opened.key not in raw
    assert hash_funder_key(opened.key) not in raw
    assert "paypal_email" not in raw
    assert "funder_key" not in raw


async def test_page_of_a_draft_is_readable_by_its_id(
    flow: Flow, client: AsyncTestClient[Litestar]
) -> None:
    created = await flow.draft()

    response = await client.get(f"/api/v1/bounties/{created.bounty.id}")

    assert response.status_code == 200
    assert response.json()["status"] == "draft"
    assert response.json()["claims"] == []
    assert response.json()["verdict"] is None


async def test_unknown_bounty_returns_problem_json_with_a_code(
    client: AsyncTestClient[Litestar],
) -> None:
    response = await client.get("/api/v1/bounties/00000000-0000-7000-8000-000000000000")

    assert response.status_code == 404
    assert response.headers["content-type"].startswith("application/problem+json")
    assert response.json()["code"] == "BOUNTY_NOT_FOUND"
