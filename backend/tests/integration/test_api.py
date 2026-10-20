"""Write routes of the bounties API and the PayPal return pages, through HTTP.

Real PostgreSQL and the real routing, validation and error handling; PayPal,
GitHub, the model and the job queue are the fakes of `tests/fakes.py`. Jobs
(`review`, `poll_payout`) are not routes: tests run them the way the worker
does, from a container scope.
"""

from typing import Any
from uuid import UUID

import pytest
from httpx import Response
from litestar import Litestar
from litestar.testing import AsyncTestClient

from proofpay.modules.bounties.domain.answers import JudgeAnswer
from tests.fakes import (
    ISSUE_URL,
    PR_URL,
    SOLVER_EMAIL,
    FakeServices,
    Flow,
    confirming_judge,
    drafted_criteria,
)

pytestmark = pytest.mark.integration

Client = AsyncTestClient[Litestar]

CRITERIA = [
    {"id": "c1", "text": "divide returns None on zero"},
    {"id": "c2", "text": "a test covers dividing by zero"},
]
CLAIM = {
    "solver_name": "agent-7",
    "solver_kind": "agent",
    "paypal_email": SOLVER_EMAIL,
}


def _key(key: str) -> dict[str, str]:
    return {"X-Funder-Key": key}


def _assert_problem(response: Response, status: int, code: str) -> dict[str, Any]:
    assert response.status_code == status, response.text
    assert response.headers["content-type"].startswith("application/problem+json")
    body: dict[str, Any] = response.json()
    assert body["code"] == code
    assert body["status"] == status
    return body


async def _create(
    client: Client, services: FakeServices, amount: Any = 25
) -> tuple[str, str]:
    """Creates a draft over HTTP; returns the bounty id and the funder key."""
    services.model.queue(drafted_criteria())
    response = await client.post(
        "/api/v1/bounties",
        json={
            "issue_url": ISSUE_URL,
            "amount_usd": amount,
            "done_when": "divide(a, 0) returns None and a test covers it",
        },
    )
    assert response.status_code == 201, response.text
    body = response.json()
    return body["bounty"]["id"], body["funder_key"]


async def _fund(client: Client, bounty_id: str, key: str) -> Response:
    return await client.post(
        f"/api/v1/bounties/{bounty_id}/fund",
        headers=_key(key),
        json={"criteria": CRITERIA},
    )


async def _approve(client: Client, bounty_id: str) -> Response:
    """The browser comes back from PayPal after the funder approved."""
    return await client.get(
        f"/paypal/return?token=ORDER-{bounty_id}&PayerID=PAYER",
        follow_redirects=False,
    )


async def _funded(
    client: Client, services: FakeServices, amount: Any = 25
) -> tuple[str, str]:
    bounty_id, key = await _create(client, services, amount)
    assert (await _fund(client, bounty_id, key)).status_code == 200
    assert (await _approve(client, bounty_id)).status_code == 302
    return bounty_id, key


async def _status(client: Client, bounty_id: str) -> str:
    response = await client.get(f"/api/v1/bounties/{bounty_id}")
    assert response.status_code == 200
    status: str = response.json()["status"]
    return status


# -- creating -------------------------------------------------------------------


@pytest.mark.parametrize(
    ("sent", "stored"),
    [(25, "25.00"), ("25.50", "25.50"), (12.5, "12.50"), ("1", "1.00")],
    ids=["int", "numeric-string", "float", "string-int"],
)
async def test_create_returns_the_draft_with_ai_criteria_and_the_funder_key(
    client: Client, services: FakeServices, sent: Any, stored: str
) -> None:
    services.model.queue(drafted_criteria())

    response = await client.post(
        "/api/v1/bounties",
        json={
            "issue_url": ISSUE_URL,
            "amount_usd": sent,
            "done_when": "divide(a, 0) returns None and a test covers it",
        },
    )

    assert response.status_code == 201
    body = response.json()
    assert len(body["funder_key"]) >= 20
    page = body["bounty"]
    assert page["status"] == "draft"
    assert page["amount_usd"] == stored
    assert page["title"] == "divide() raises ZeroDivisionError"
    assert page["issue_url"] == ISSUE_URL
    assert page["criteria"] == [
        {"id": "c1", "text": "divide returns None when the divisor is zero"},
        {"id": "c2", "text": "a test covers dividing by zero"},
    ]
    assert page["claims"] == []
    assert page["verdict"] is None
    assert page["events"][0]["kind"] == "created"
    # The key is shown once: the page of the same bounty must not repeat it.
    again = await client.get(f"/api/v1/bounties/{page['id']}")
    assert body["funder_key"] not in again.text


async def test_create_with_a_bad_issue_url_is_422_with_its_code(
    client: Client, services: FakeServices
) -> None:
    response = await client.post(
        "/api/v1/bounties",
        json={
            "issue_url": "https://example.com/not-an-issue",
            "amount_usd": 25,
            "done_when": "divide(a, 0) returns None",
        },
    )

    _assert_problem(response, 422, "ISSUE_URL_INVALID")
    assert services.code.calls == []


@pytest.mark.parametrize("amount", [501, "500.01", "0.50"])
async def test_create_with_an_amount_outside_the_range_is_422_with_its_code(
    client: Client, services: FakeServices, amount: Any
) -> None:
    response = await client.post(
        "/api/v1/bounties",
        json={
            "issue_url": ISSUE_URL,
            "amount_usd": amount,
            "done_when": "divide(a, 0) returns None",
        },
    )

    _assert_problem(response, 422, "AMOUNT_OUT_OF_RANGE")
    assert services.model.asked == []


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("amount_usd", 0),
        ("amount_usd", -5),
        ("amount_usd", "12.345"),
        ("amount_usd", "ten"),
        ("amount_usd", "NaN"),
        ("amount_usd", None),
        ("done_when", "too short"),
        ("done_when", "x" * 2001),
        ("issue_url", None),
    ],
)
async def test_create_with_a_malformed_body_is_422_problem_json_and_asks_nobody(
    client: Client, services: FakeServices, field: str, value: Any
) -> None:
    body = {
        "issue_url": ISSUE_URL,
        "amount_usd": 25,
        "done_when": "divide(a, 0) returns None",
        field: value,
    }

    response = await client.post("/api/v1/bounties", json=body)

    problem = _assert_problem(response, 422, "VALIDATION_ERROR")
    assert problem["errors"]
    assert services.code.calls == []
    assert services.model.asked == []


# -- funding and the PayPal pages -------------------------------------------------


async def test_fund_with_a_wrong_key_is_403_and_opens_no_order(
    client: Client, services: FakeServices
) -> None:
    bounty_id, _ = await _create(client, services)

    response = await _fund(client, bounty_id, "not-the-key")

    _assert_problem(response, 403, "FUNDER_KEY_INVALID")
    assert services.gateway.calls_of("create_order") == []
    assert await _status(client, bounty_id) == "draft"


async def test_fund_without_the_key_header_is_refused_and_opens_no_order(
    client: Client, services: FakeServices
) -> None:
    bounty_id, _ = await _create(client, services)

    response = await client.post(
        f"/api/v1/bounties/{bounty_id}/fund", json={"criteria": CRITERIA}
    )

    _assert_problem(response, 422, "VALIDATION_ERROR")
    assert services.gateway.calls_of("create_order") == []


async def test_fund_with_the_key_returns_the_paypal_approve_url_and_the_edited_criteria(
    client: Client, services: FakeServices
) -> None:
    bounty_id, key = await _create(client, services)

    response = await client.post(
        f"/api/v1/bounties/{bounty_id}/fund",
        headers=_key(key),
        json={"criteria": [{"id": "c1", "text": "only this one counts"}]},
    )

    assert response.status_code == 200
    assert response.json() == {
        "approve_url": f"https://paypal.test/approve/{bounty_id}"
    }
    page = (await client.get(f"/api/v1/bounties/{bounty_id}")).json()
    assert page["status"] == "awaiting_payment"
    assert page["criteria"] == [{"id": "c1", "text": "only this one counts"}]
    (order,) = services.gateway.calls_of("create_order")
    assert order.args["return_url"].endswith("/paypal/return")


@pytest.mark.parametrize(
    "criteria",
    [[], [{"id": f"c{n}", "text": "t"} for n in range(1, 8)], [{"id": "c1"}]],
    ids=["none", "seven", "no-text"],
)
async def test_fund_with_a_bad_criteria_list_is_422_and_opens_no_order(
    client: Client, services: FakeServices, criteria: list[dict[str, str]]
) -> None:
    bounty_id, key = await _create(client, services)

    response = await client.post(
        f"/api/v1/bounties/{bounty_id}/fund",
        headers=_key(key),
        json={"criteria": criteria},
    )

    _assert_problem(response, 422, "VALIDATION_ERROR")
    assert services.gateway.calls_of("create_order") == []


async def test_paypal_return_authorizes_once_however_often_the_browser_returns(
    client: Client, services: FakeServices
) -> None:
    bounty_id, key = await _create(client, services)
    await _fund(client, bounty_id, key)

    first = await _approve(client, bounty_id)
    second = await _approve(client, bounty_id)

    for response in (first, second):
        assert response.status_code == 302
        assert response.headers["location"] == f"/b/{bounty_id}"
    assert await _status(client, bounty_id) == "funded"
    assert len(services.gateway.calls_of("authorize")) == 1
    kinds = [
        event["kind"]
        for event in (await client.get(f"/api/v1/bounties/{bounty_id}")).json()[
            "events"
        ]
    ]
    assert kinds.count("funded") == 1


async def test_paypal_return_for_an_unknown_order_is_404_problem_json(
    client: Client, services: FakeServices
) -> None:
    response = await client.get(
        "/paypal/return?token=ORDER-UNKNOWN", follow_redirects=False
    )

    _assert_problem(response, 404, "BOUNTY_NOT_FOUND")
    assert services.gateway.calls_of("authorize") == []


async def test_paypal_return_without_a_token_is_refused(
    client: Client, services: FakeServices
) -> None:
    response = await client.get("/paypal/return", follow_redirects=False)

    _assert_problem(response, 422, "VALIDATION_ERROR")
    assert services.gateway.calls_of("authorize") == []


async def test_paypal_cancel_sends_the_browser_back_and_reopens_the_draft(
    client: Client, services: FakeServices
) -> None:
    bounty_id, key = await _create(client, services)
    await _fund(client, bounty_id, key)

    response = await client.get(
        f"/paypal/cancel?token=ORDER-{bounty_id}", follow_redirects=False
    )

    assert response.status_code == 302
    assert response.headers["location"] == f"/b/{bounty_id}"
    assert await _status(client, bounty_id) == "draft"
    assert services.gateway.calls_of("authorize") == []
    assert (await _fund(client, bounty_id, key)).status_code == 200


async def test_paypal_cancel_after_the_bounty_was_funded_does_not_undo_it(
    client: Client, services: FakeServices
) -> None:
    bounty_id, _ = await _funded(client, services)

    response = await client.get(
        f"/paypal/cancel?token=ORDER-{bounty_id}", follow_redirects=False
    )

    assert response.status_code == 302
    assert await _status(client, bounty_id) == "funded"


# -- claiming ---------------------------------------------------------------------


async def test_claim_on_a_bounty_that_is_not_funded_is_409(
    client: Client, services: FakeServices
) -> None:
    bounty_id, _ = await _create(client, services)

    response = await client.post(f"/api/v1/bounties/{bounty_id}/claims", json=CLAIM)

    problem = _assert_problem(response, 409, "BOUNTY_NOT_OPEN")
    assert problem["params"] == {"status": "draft"}


async def test_claim_is_created_and_the_response_never_shows_the_email(
    client: Client, services: FakeServices
) -> None:
    bounty_id, _ = await _funded(client, services)

    response = await client.post(f"/api/v1/bounties/{bounty_id}/claims", json=CLAIM)

    assert response.status_code == 201
    body = response.json()
    assert body["status"] == "open"
    assert body["solver_name"] == "agent-7"
    assert body["solver_kind"] == "agent"
    assert body["pr_url"] is None
    assert body["verdict"] is None
    assert body["id"]
    assert body["created_at"]
    assert SOLVER_EMAIL not in response.text
    assert "email" not in response.text
    page = await client.get(f"/api/v1/bounties/{bounty_id}")
    assert SOLVER_EMAIL not in page.text


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("paypal_email", "not-an-email"),
        ("paypal_email", "two words@example.com"),
        ("paypal_email", "a@b"),
        ("paypal_email", "a" * 250 + "@example.com"),
        ("solver_kind", "robot"),
        ("solver_name", ""),
        ("solver_name", "n" * 101),
    ],
)
async def test_claim_with_an_invalid_body_is_422_and_creates_nothing(
    client: Client, services: FakeServices, field: str, value: str
) -> None:
    bounty_id, _ = await _funded(client, services)

    response = await client.post(
        f"/api/v1/bounties/{bounty_id}/claims", json={**CLAIM, field: value}
    )

    _assert_problem(response, 422, "VALIDATION_ERROR")
    page = (await client.get(f"/api/v1/bounties/{bounty_id}")).json()
    assert page["claims"] == []


async def test_submit_for_an_unknown_claim_is_404(
    client: Client, services: FakeServices
) -> None:
    response = await client.post(
        "/api/v1/claims/00000000-0000-7000-8000-000000000000/submit",
        json={"pr_url": PR_URL},
    )

    _assert_problem(response, 404, "CLAIM_NOT_FOUND")


# -- the whole path ---------------------------------------------------------------


async def test_http_path_from_creation_to_paid_with_a_verified_verdict(
    client: Client, flow: Flow, services: FakeServices
) -> None:
    bounty_id, key = await _funded(client, services)
    claim = (
        await client.post(f"/api/v1/bounties/{bounty_id}/claims", json=CLAIM)
    ).json()

    submitted = await client.post(
        f"/api/v1/claims/{claim['id']}/submit", json={"pr_url": PR_URL}
    )

    assert submitted.status_code == 200
    assert submitted.json()["status"] == "submitted"
    assert submitted.json()["pr_url"] == PR_URL
    assert await _status(client, bounty_id) == "in_review"
    # The jobs a worker would run, one scope each.
    services.model.queue(confirming_judge())
    async with flow.service() as service:
        await service.review(UUID(claim["id"]))
    async with flow.service() as service:
        await service.poll_payout(UUID(claim["id"]))

    page = (await client.get(f"/api/v1/bounties/{bounty_id}")).json()
    assert page["status"] == "paid"
    assert page["verdict"]["outcome"] == "pass"
    assert page["verdict"]["ci"] == "green"
    assert page["verdict"]["head_sha"] == "a" * 40
    assert [
        (item["criterion_id"], item["state"]) for item in page["verdict"]["items"]
    ] == [
        ("c1", "met"),
        ("c2", "met"),
    ]
    assert page["verdict"]["items"][1]["quote"] == "assert divide(1, 0) is None"
    assert page["verdict"]["items"][1]["file"] == "tests/test_tinycalc.py"
    assert [claim_view["status"] for claim_view in page["claims"]] == ["accepted"]
    assert [event["kind"] for event in page["events"]] == [
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
    assert len(services.gateway.calls_of("capture")) == 1
    assert len(services.gateway.calls_of("payout")) == 1
    listed = (await client.get("/api/v1/bounties")).json()
    assert [(item["id"], item["status"]) for item in listed] == [(bounty_id, "paid")]
    assert key not in str(listed)


# -- decide and cancel --------------------------------------------------------------


async def _parked(
    client: Client, flow: Flow, services: FakeServices
) -> tuple[str, str]:
    """A bounty in needs_human: the judge answered nothing verifiable."""
    bounty_id, key = await _funded(client, services)
    claim = (
        await client.post(f"/api/v1/bounties/{bounty_id}/claims", json=CLAIM)
    ).json()
    await client.post(f"/api/v1/claims/{claim['id']}/submit", json={"pr_url": PR_URL})
    services.model.queue(JudgeAnswer(items=[]))
    async with flow.service() as service:
        await service.review(UUID(claim["id"]))
    assert await _status(client, bounty_id) == "needs_human"
    return bounty_id, key


async def test_decide_with_a_wrong_or_missing_key_changes_nothing(
    client: Client, flow: Flow, services: FakeServices
) -> None:
    bounty_id, _ = await _parked(client, flow, services)

    wrong = await client.post(
        f"/api/v1/bounties/{bounty_id}/decide",
        headers=_key("not-the-key"),
        json={"decision": "release"},
    )
    missing = await client.post(
        f"/api/v1/bounties/{bounty_id}/decide", json={"decision": "release"}
    )

    _assert_problem(wrong, 403, "FUNDER_KEY_INVALID")
    _assert_problem(missing, 422, "VALIDATION_ERROR")
    assert await _status(client, bounty_id) == "needs_human"
    assert services.gateway.calls_of("capture") == []


async def test_decide_with_an_unknown_decision_is_422(
    client: Client, flow: Flow, services: FakeServices
) -> None:
    bounty_id, key = await _parked(client, flow, services)

    response = await client.post(
        f"/api/v1/bounties/{bounty_id}/decide",
        headers=_key(key),
        json={"decision": "refund"},
    )

    _assert_problem(response, 422, "VALIDATION_ERROR")
    assert await _status(client, bounty_id) == "needs_human"


async def test_decide_reject_with_the_key_reopens_the_bounty_and_returns_the_page(
    client: Client, flow: Flow, services: FakeServices
) -> None:
    bounty_id, key = await _parked(client, flow, services)

    response = await client.post(
        f"/api/v1/bounties/{bounty_id}/decide",
        headers=_key(key),
        json={"decision": "reject"},
    )

    assert response.status_code == 200
    page = response.json()
    assert page["id"] == bounty_id
    assert page["status"] == "funded"
    assert [item["status"] for item in page["claims"]] == ["rejected"]
    assert services.gateway.calls_of("capture") == []


async def test_decide_release_with_the_key_captures_and_returns_the_page(
    client: Client, flow: Flow, services: FakeServices
) -> None:
    bounty_id, key = await _parked(client, flow, services)

    response = await client.post(
        f"/api/v1/bounties/{bounty_id}/decide",
        headers=_key(key),
        json={"decision": "release"},
    )

    assert response.status_code == 200
    assert response.json()["status"] == "released"
    assert len(services.gateway.calls_of("capture")) == 1
    assert len(services.gateway.calls_of("payout")) == 1


async def test_decide_when_nothing_awaits_a_decision_is_409(
    client: Client, services: FakeServices
) -> None:
    bounty_id, key = await _funded(client, services)

    response = await client.post(
        f"/api/v1/bounties/{bounty_id}/decide",
        headers=_key(key),
        json={"decision": "release"},
    )

    _assert_problem(response, 409, "NOT_AWAITING_DECISION")


async def test_cancel_with_a_wrong_or_missing_key_voids_nothing(
    client: Client, services: FakeServices
) -> None:
    bounty_id, _ = await _funded(client, services)

    wrong = await client.post(
        f"/api/v1/bounties/{bounty_id}/cancel", headers=_key("not-the-key")
    )
    missing = await client.post(f"/api/v1/bounties/{bounty_id}/cancel")

    _assert_problem(wrong, 403, "FUNDER_KEY_INVALID")
    _assert_problem(missing, 422, "VALIDATION_ERROR")
    assert services.gateway.calls_of("void") == []
    assert await _status(client, bounty_id) == "funded"


async def test_cancel_of_a_funded_bounty_voids_once_and_returns_the_cancelled_page(
    client: Client, services: FakeServices
) -> None:
    bounty_id, key = await _funded(client, services)

    response = await client.post(
        f"/api/v1/bounties/{bounty_id}/cancel", headers=_key(key)
    )

    assert response.status_code == 200
    page = response.json()
    assert page["id"] == bounty_id
    assert page["status"] == "cancelled"
    assert page["events"][-1]["kind"] == "cancelled"
    voids = services.gateway.calls_of("void")
    assert [call.request_id for call in voids] == [f"void-{bounty_id}"]
    assert (await client.get("/api/v1/bounties")).json()[0]["status"] == "cancelled"


async def test_cancel_of_an_unpaid_draft_never_touches_paypal(
    client: Client, services: FakeServices
) -> None:
    bounty_id, key = await _create(client, services)

    response = await client.post(
        f"/api/v1/bounties/{bounty_id}/cancel", headers=_key(key)
    )

    assert response.status_code == 200
    assert response.json()["status"] == "cancelled"
    assert services.gateway.calls_of("void") == []
