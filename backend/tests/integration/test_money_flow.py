"""Bounty scenarios end to end: real PostgreSQL, fake PayPal/GitHub/model/jobs.

The money rules are what these tests protect: one capture and one payout per
bounty with stable request ids, nothing paid for an unproven claim, and no
bounty left in a state nobody can move out of.
"""

from datetime import timedelta
from decimal import Decimal

import pytest
from litestar import Litestar
from litestar.testing import AsyncTestClient

from proofpay.integrations.github.ports import CheckRun
from proofpay.integrations.paypal.ports import PayoutStatus
from proofpay.modules.bounties.domain.answers import (
    CriteriaAnswer,
    JudgeAnswer,
    JudgeItem,
)
from proofpay.modules.bounties.domain.entities import Criterion, SolverKind
from proofpay.modules.bounties.domain.rules import MAX_DIFF_CHARS
from proofpay.shared.errors import (
    ConflictError,
    ForbiddenError,
    UnprocessableError,
    UpstreamError,
)
from tests.fakes import (
    ISSUE_URL,
    NOW,
    OWNER,
    PR_URL,
    REPO,
    SOLVER_EMAIL,
    SOURCE_FILE,
    TEST_FILE,
    TEST_QUOTE,
    FakeServices,
    Flow,
    confirming_judge,
    drafted_criteria,
)

pytestmark = pytest.mark.integration

PAYPAL_REJECTED = UpstreamError(code="PAYPAL_ERROR", detail="rejected")
HALF_A_MINUTE = timedelta(seconds=30)


async def _review(flow: Flow, claim_id) -> None:
    async with flow.service() as service:
        await service.review(claim_id)


async def _poll(flow: Flow, claim_id) -> None:
    async with flow.service() as service:
        await service.poll_payout(claim_id)


async def _release(flow: Flow, claim_id) -> None:
    async with flow.service() as service:
        await service.release(claim_id)


async def _decide(flow: Flow, opened, decision) -> None:
    async with flow.service() as service:
        await service.decide(opened.bounty.id, opened.key, decision)


async def _reviewed_to_payout(flow: Flow, services: FakeServices):
    """A funded bounty whose claim passed review; the payout is in flight."""
    opened = await flow.funded()
    claim = await flow.submitted(opened)
    services.model.queue(confirming_judge())
    await _review(flow, claim.id)
    return opened, claim


# -- the money path ------------------------------------------------------


async def test_happy_path_pays_once_with_stable_request_ids(
    flow: Flow, services: FakeServices
) -> None:
    opened = await flow.funded()
    claim = await flow.submitted(opened)
    services.model.queue(confirming_judge())

    await _review(flow, claim.id)
    await _poll(flow, claim.id)

    view = await flow.page(opened.bounty.id)
    assert view.status == "paid"
    assert [item.status for item in view.claims] == ["accepted"]
    assert view.verdict is not None
    assert view.verdict.outcome == "pass"
    assert [item.state for item in view.verdict.items] == ["met", "met"]

    captures = services.gateway.calls_of("capture")
    assert [call.request_id for call in captures] == [f"capture-{opened.bounty.id}"]
    payouts = services.gateway.calls_of("payout")
    assert len(payouts) == 1
    assert payouts[0].request_id == f"payout-{claim.id}"
    assert payouts[0].args["sender_batch_id"] == f"payout-{claim.id}"
    assert payouts[0].args["email"] == SOLVER_EMAIL
    assert payouts[0].args["amount"] == Decimal("25.00")
    assert flow.kinds(view) == [
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
    assert services.jobs.calls == [
        ("review", claim.id, None),
        ("poll_payout", claim.id, HALF_A_MINUTE),
    ]


async def test_release_repeated_adds_no_gateway_call_and_no_event(
    flow: Flow, services: FakeServices
) -> None:
    opened, claim = await _reviewed_to_payout(flow, services)
    calls = list(services.gateway.calls)
    jobs = list(services.jobs.calls)
    kinds = flow.kinds(await flow.page(opened.bounty.id))

    await _release(flow, claim.id)  # payout in flight
    await _poll(flow, claim.id)
    paid_calls = list(services.gateway.calls)
    paid_kinds = flow.kinds(await flow.page(opened.bounty.id))
    await _release(flow, claim.id)  # already paid

    assert services.gateway.calls[: len(calls)] == calls
    assert services.gateway.calls == paid_calls
    assert kinds == paid_kinds[:-1]
    assert flow.kinds(await flow.page(opened.bounty.id)) == paid_kinds
    assert services.jobs.calls == jobs


async def test_poll_pending_looks_again_and_does_not_pay_early(
    flow: Flow, services: FakeServices
) -> None:
    opened, claim = await _reviewed_to_payout(flow, services)
    services.gateway.payout_statuses = [
        PayoutStatus(batch_status="PROCESSING", item_status=None),
        PayoutStatus(batch_status="SUCCESS", item_status="SUCCESS"),
    ]

    scheduled = len(services.jobs.calls)
    await _poll(flow, claim.id)
    assert (await flow.page(opened.bounty.id)).status == "released"
    assert services.jobs.calls[scheduled:] == [("poll_payout", claim.id, HALF_A_MINUTE)]

    await _poll(flow, claim.id)
    assert (await flow.page(opened.bounty.id)).status == "paid"
    assert len(services.gateway.calls_of("payout")) == 1


# -- verdicts that do not pay ---------------------------------------------


async def test_quote_missing_from_diff_goes_to_needs_human_not_to_payment(
    flow: Flow, services: FakeServices
) -> None:
    opened = await flow.funded()
    claim = await flow.submitted(opened)
    answer = confirming_judge()
    answer.items[1] = JudgeItem(
        criterion_id="c2",
        met=True,
        quote="assert divide(1, 0) is None  # invented",
        file=TEST_FILE,
        reason="claims a test exists",
    )
    services.model.queue(answer)

    await _review(flow, claim.id)

    view = await flow.page(opened.bounty.id)
    assert view.status == "needs_human"
    assert [item.status for item in view.claims] == ["needs_human"]
    assert view.verdict is not None
    assert [item.state for item in view.verdict.items] == ["met", "unverified"]
    assert services.gateway.calls_of("capture") == []
    assert services.gateway.calls_of("payout") == []


async def test_funder_release_after_needs_human_captures_and_pays(
    flow: Flow, services: FakeServices
) -> None:
    opened = await flow.funded()
    claim = await flow.submitted(opened)
    services.model.queue(
        JudgeAnswer(
            items=[
                JudgeItem(
                    criterion_id="c1",
                    met=True,
                    quote="this text is not in the diff",
                    file=SOURCE_FILE,
                    reason="r",
                ),
                JudgeItem(
                    criterion_id="c2",
                    met=True,
                    quote=TEST_QUOTE,
                    file=TEST_FILE,
                    reason="r",
                ),
            ]
        )
    )
    await _review(flow, claim.id)

    await _decide(flow, opened, "release")

    view = await flow.page(opened.bounty.id)
    assert view.status == "released"
    assert len(services.gateway.calls_of("capture")) == 1
    payouts = services.gateway.calls_of("payout")
    assert [call.request_id for call in payouts] == [f"payout-{claim.id}"]
    assert services.jobs.calls[-1] == ("poll_payout", claim.id, HALF_A_MINUTE)


async def test_funder_reject_after_needs_human_reopens_the_bounty(
    flow: Flow, services: FakeServices
) -> None:
    opened = await flow.funded()
    claim = await flow.submitted(opened)
    services.model.queue(JudgeAnswer(items=[]))  # answers nothing: unverified
    await _review(flow, claim.id)
    assert (await flow.page(opened.bounty.id)).status == "needs_human"

    await _decide(flow, opened, "reject")

    view = await flow.page(opened.bounty.id)
    assert view.status == "funded"
    assert [item.status for item in view.claims] == ["rejected"]
    assert services.gateway.calls_of("capture") == []


async def test_ci_pending_waits_without_asking_the_judge(
    flow: Flow, services: FakeServices
) -> None:
    opened = await flow.funded()
    claim = await flow.submitted(opened)
    services.code.check_runs = [
        CheckRun(name="pytest", status="in_progress", conclusion=None)
    ]

    await _review(flow, claim.id)

    view = await flow.page(opened.bounty.id)
    assert view.status == "in_review"
    assert services.model.asked_for(JudgeAnswer) == []
    assert services.jobs.calls[-1] == ("review", claim.id, HALF_A_MINUTE)
    assert "ci" not in flow.kinds(view)
    assert services.gateway.calls_of("capture") == []


async def test_ci_still_pending_after_an_hour_parks_the_claim_for_a_human(
    flow: Flow, services: FakeServices
) -> None:
    opened = await flow.funded()
    claim = await flow.submitted(opened)
    services.code.check_runs = [
        CheckRun(name="pytest", status="in_progress", conclusion=None)
    ]

    services.clock.current = NOW + timedelta(minutes=59, seconds=59)
    await _review(flow, claim.id)
    assert (await flow.page(opened.bounty.id)).status == "in_review"

    services.clock.current = NOW + timedelta(minutes=60)
    await _review(flow, claim.id)

    view = await flow.page(opened.bounty.id)
    assert view.status == "needs_human"
    assert [item.status for item in view.claims] == ["needs_human"]
    assert dict(view.events[-1].detail) == {
        "claim_id": str(claim.id),
        "reason": "CI did not finish within 60 minutes",
    }
    assert services.model.asked_for(JudgeAnswer) == []
    assert services.gateway.calls_of("capture") == []


async def test_the_ci_wait_counts_from_the_latest_submission_of_the_claim(
    flow: Flow, services: FakeServices
) -> None:
    opened = await flow.funded()
    claim = await flow.claim(opened)
    async with flow.service() as service:
        await service.submit(claim.id, PR_URL)
    services.code.check_runs = [
        CheckRun(name="pytest", status="completed", conclusion="failure")
    ]
    services.model.queue(confirming_judge())
    await _review(flow, claim.id)  # rejected: bounty funded again
    services.clock.current = NOW + timedelta(hours=3)
    async with flow.service() as service:
        await service.submit(claim.id, PR_URL)  # a fresh submission, a fresh hour
    services.code.check_runs = [
        CheckRun(name="pytest", status="in_progress", conclusion=None)
    ]

    services.clock.current = NOW + timedelta(hours=3, minutes=30)
    await _review(flow, claim.id)

    assert (await flow.page(opened.bounty.id)).status == "in_review"


async def test_a_push_during_review_is_not_judged_and_is_queued_again_without_events(
    flow: Flow, services: FakeServices
) -> None:
    opened = await flow.funded()
    claim = await flow.submitted(opened)
    services.model.queue(confirming_judge())
    # CI is read for the first head; by the time of the second look it moved.
    services.code.head_shas = ["a" * 40, "b" * 40]
    events_before = flow.kinds(await flow.page(opened.bounty.id))

    await _review(flow, claim.id)

    view = await flow.page(opened.bounty.id)
    assert view.status == "in_review"
    assert flow.kinds(view) == events_before
    assert services.model.asked_for(JudgeAnswer) == []
    assert services.jobs.calls[-1] == ("review", claim.id, HALF_A_MINUTE)
    assert services.code.checked_shas == ["a" * 40]

    services.code.head_sha = "b" * 40
    await _review(flow, claim.id)

    view = await flow.page(opened.bounty.id)
    assert view.status == "released"
    assert services.code.checked_shas == ["a" * 40, "b" * 40]
    assert view.verdict is not None
    assert view.verdict.head_sha == "b" * 40
    ci_event = next(event for event in view.events if event.kind == "ci")
    assert ci_event.detail["head_sha"] == "b" * 40


async def test_the_verdict_records_the_commit_that_was_judged(
    flow: Flow, services: FakeServices
) -> None:
    opened = await flow.funded()
    claim = await flow.submitted(opened)
    services.code.head_sha = "c" * 40
    services.model.queue(confirming_judge())

    await _review(flow, claim.id)

    view = await flow.page(opened.bounty.id)
    assert view.verdict is not None
    assert view.verdict.head_sha == "c" * 40


async def test_a_pull_request_closed_without_merge_is_rejected_not_judged(
    flow: Flow, services: FakeServices
) -> None:
    opened = await flow.funded()
    claim = await flow.submitted(opened)
    services.code.pr_state = "closed"
    services.model.queue(confirming_judge())

    await _review(flow, claim.id)

    view = await flow.page(opened.bounty.id)
    assert view.status == "funded"
    assert [item.status for item in view.claims] == ["rejected"]
    assert view.events[-1].kind == "rejected"
    assert dict(view.events[-1].detail) == {
        "claim_id": str(claim.id),
        "reason": "pull request closed",
    }
    assert services.model.asked_for(JudgeAnswer) == []
    assert services.gateway.calls_of("capture") == []


async def test_a_pull_request_closed_while_the_diff_was_fetched_is_rejected(
    flow: Flow, services: FakeServices
) -> None:
    opened = await flow.funded()
    claim = await flow.submitted(opened)
    services.model.queue(confirming_judge())
    pulls = services.code.pull_request

    async def closing_after_the_first_look(owner: str, repo: str, number: int):
        pull = await pulls(owner, repo, number)
        services.code.pr_state = "closed"
        return pull

    services.code.pull_request = closing_after_the_first_look  # type: ignore[method-assign]

    await _review(flow, claim.id)

    view = await flow.page(opened.bounty.id)
    assert view.status == "funded"
    assert view.events[-1].kind == "rejected"
    assert services.gateway.calls_of("capture") == []


async def test_a_merged_pull_request_is_judged_normally(
    flow: Flow, services: FakeServices
) -> None:
    opened = await flow.funded()
    claim = await flow.submitted(opened)
    services.code.pr_state = "closed"
    services.code.pr_merged = True
    services.model.queue(confirming_judge())

    await _review(flow, claim.id)

    assert (await flow.page(opened.bounty.id)).status == "released"


async def test_a_test_criterion_proven_from_source_code_goes_to_a_human(
    flow: Flow, services: FakeServices
) -> None:
    opened = await flow.funded()
    claim = await flow.submitted(opened)
    answer = confirming_judge()
    answer.items[1] = JudgeItem(
        criterion_id="c2",
        met=True,
        quote="return None",
        file=SOURCE_FILE,
        reason="the code handles it",
    )
    services.model.queue(answer)

    await _review(flow, claim.id)

    view = await flow.page(opened.bounty.id)
    assert view.status == "needs_human"
    assert view.verdict is not None
    assert [item.state for item in view.verdict.items] == ["met", "unverified"]
    assert (
        view.verdict.items[1].reason == "test criterion must be proven from a test file"
    )
    assert services.gateway.calls_of("capture") == []


async def test_ci_red_rejects_even_when_the_judge_confirms_everything(
    flow: Flow, services: FakeServices
) -> None:
    opened = await flow.funded()
    claim = await flow.submitted(opened)
    services.code.check_runs = [
        CheckRun(name="pytest", status="completed", conclusion="failure")
    ]
    services.model.queue(confirming_judge())

    await _review(flow, claim.id)

    view = await flow.page(opened.bounty.id)
    assert view.status == "funded"
    assert [item.status for item in view.claims] == ["rejected"]
    assert view.verdict is not None
    assert (view.verdict.outcome, view.verdict.ci) == ("fail", "red")
    assert services.gateway.calls_of("capture") == []


async def test_judge_saying_not_met_rejects_the_claim(
    flow: Flow, services: FakeServices
) -> None:
    opened = await flow.funded()
    claim = await flow.submitted(opened)
    answer = confirming_judge()
    answer.items[1] = JudgeItem(
        criterion_id="c2", met=False, quote="", file="", reason="no test was added"
    )
    services.model.queue(answer)

    await _review(flow, claim.id)

    view = await flow.page(opened.bounty.id)
    assert view.status == "funded"
    assert [item.status for item in view.claims] == ["rejected"]
    assert services.gateway.calls_of("capture") == []


async def test_rejected_claim_can_submit_again_and_be_paid(
    flow: Flow, services: FakeServices
) -> None:
    opened = await flow.funded()
    claim = await flow.submitted(opened)
    services.code.check_runs = [
        CheckRun(name="pytest", status="completed", conclusion="failure")
    ]
    services.model.queue(confirming_judge())
    await _review(flow, claim.id)
    services.code.check_runs = [
        CheckRun(name="pytest", status="completed", conclusion="success")
    ]

    async with flow.service() as service:
        await service.submit(claim.id, PR_URL)
    services.model.queue(confirming_judge())
    await _review(flow, claim.id)

    view = await flow.page(opened.bounty.id)
    assert view.status == "released"
    assert len(services.gateway.calls_of("capture")) == 1


async def test_llm_unavailable_during_review_goes_to_needs_human(
    flow: Flow, services: FakeServices
) -> None:
    opened = await flow.funded()
    claim = await flow.submitted(opened)
    services.model.queue_error_for(JudgeAnswer)

    await _review(flow, claim.id)

    view = await flow.page(opened.bounty.id)
    assert view.status == "needs_human"
    assert [item.status for item in view.claims] == ["needs_human"]
    assert view.events[-1].detail["reason"] == "llm unavailable"


async def test_github_failure_during_review_does_not_strand_the_bounty(
    flow: Flow, services: FakeServices
) -> None:
    opened = await flow.funded()
    claim = await flow.submitted(opened)
    services.code.fail["diff"] = UpstreamError(code="GITHUB_ERROR", detail="boom")

    await _review(flow, claim.id)

    view = await flow.page(opened.bounty.id)
    assert view.status == "needs_human"
    assert view.events[-1].detail["reason"] == "github error: GITHUB_ERROR"


async def test_oversized_diff_skips_the_judge(
    flow: Flow, services: FakeServices
) -> None:
    opened = await flow.funded()
    claim = await flow.submitted(opened)
    services.code.diff_text = "x" * (MAX_DIFF_CHARS + 1)

    await _review(flow, claim.id)

    view = await flow.page(opened.bounty.id)
    assert view.status == "needs_human"
    assert services.model.asked_for(JudgeAnswer) == []
    assert view.events[-1].detail["reason"] == "diff too large"


async def test_stale_review_job_changes_nothing(
    flow: Flow, services: FakeServices
) -> None:
    opened, claim = await _reviewed_to_payout(flow, services)
    calls = list(services.gateway.calls)
    kinds = flow.kinds(await flow.page(opened.bounty.id))

    await _review(flow, claim.id)  # the same job delivered a second time

    assert services.gateway.calls == calls
    assert flow.kinds(await flow.page(opened.bounty.id)) == kinds
    assert len(services.model.asked_for(JudgeAnswer)) == 1


# -- failures in the money calls -------------------------------------------


async def test_capture_failure_parks_the_bounty_and_a_retry_reuses_the_request_id(
    flow: Flow, services: FakeServices
) -> None:
    opened = await flow.funded()
    claim = await flow.submitted(opened)
    services.gateway.fail["capture"] = PAYPAL_REJECTED
    services.model.queue(confirming_judge())

    await _review(flow, claim.id)

    view = await flow.page(opened.bounty.id)
    assert view.status == "needs_human"
    assert services.gateway.calls_of("payout") == []

    del services.gateway.fail["capture"]
    await _decide(flow, opened, "release")

    captures = services.gateway.calls_of("capture")
    assert [call.request_id for call in captures] == [f"capture-{opened.bounty.id}"] * 2
    assert len(services.gateway.calls_of("payout")) == 1
    assert (await flow.page(opened.bounty.id)).status == "released"


async def test_payout_error_keeps_the_capture_and_a_retry_cannot_pay_twice(
    flow: Flow, services: FakeServices
) -> None:
    opened = await flow.funded()
    claim = await flow.submitted(opened)
    services.gateway.fail["payout"] = PAYPAL_REJECTED
    services.model.queue(confirming_judge())

    await _review(flow, claim.id)

    view = await flow.page(opened.bounty.id)
    assert view.status == "needs_human"
    assert flow.kinds(view)[-2:] == ["captured", "payout_failed"]

    del services.gateway.fail["payout"]
    await _decide(flow, opened, "release")

    assert len(services.gateway.calls_of("capture")) == 1
    payouts = services.gateway.calls_of("payout")
    assert [call.request_id for call in payouts] == [f"payout-{claim.id}"] * 2
    assert [call.args["sender_batch_id"] for call in payouts] == [
        f"payout-{claim.id}"
    ] * 2
    view = await flow.page(opened.bounty.id)
    assert view.status == "released"
    assert flow.kinds(view).count("payout_sent") == 1


async def test_payout_reported_failed_parks_the_bounty_and_reject_is_refused(
    flow: Flow, services: FakeServices
) -> None:
    opened, claim = await _reviewed_to_payout(flow, services)
    services.gateway.payout_statuses = [
        PayoutStatus(batch_status="SUCCESS", item_status="FAILED")
    ]

    await _poll(flow, claim.id)

    view = await flow.page(opened.bounty.id)
    assert view.status == "needs_human"
    assert flow.kinds(view)[-1] == "payout_failed"
    with pytest.raises(ConflictError) as refused:
        await _decide(flow, opened, "reject")
    assert refused.value.code == "ALREADY_CAPTURED"
    assert (await flow.page(opened.bounty.id)).status == "needs_human"


async def test_release_after_a_failed_payout_polls_the_existing_batch_not_a_new_one(
    flow: Flow, services: FakeServices
) -> None:
    opened, claim = await _reviewed_to_payout(flow, services)
    services.gateway.payout_statuses = [
        PayoutStatus(batch_status="SUCCESS", item_status="UNCLAIMED"),
        PayoutStatus(batch_status="SUCCESS", item_status="SUCCESS"),
    ]
    await _poll(flow, claim.id)
    scheduled = len(services.jobs.calls)

    await _decide(flow, opened, "release")

    assert len(services.gateway.calls_of("payout")) == 1
    assert (await flow.page(opened.bounty.id)).status == "released"
    assert services.jobs.calls[scheduled:] == [("poll_payout", claim.id, HALF_A_MINUTE)]
    await _poll(flow, claim.id)
    assert (await flow.page(opened.bounty.id)).status == "paid"


async def test_poll_survives_a_paypal_error_and_looks_again(
    flow: Flow, services: FakeServices
) -> None:
    opened, claim = await _reviewed_to_payout(flow, services)
    services.gateway.fail["payout_status"] = PAYPAL_REJECTED

    scheduled = len(services.jobs.calls)
    await _poll(flow, claim.id)

    assert (await flow.page(opened.bounty.id)).status == "released"
    assert services.jobs.calls[scheduled:] == [("poll_payout", claim.id, HALF_A_MINUTE)]


# -- funding -----------------------------------------------------------------


async def test_confirm_payment_twice_authorizes_once(
    flow: Flow, services: FakeServices
) -> None:
    opened = await flow.awaiting_payment()
    order = f"ORDER-{opened.bounty.id}"

    async with flow.service() as service:
        first = await service.confirm_payment(order)
    async with flow.service() as service:
        second = await service.confirm_payment(order)

    assert first == second == opened.bounty.id
    authorizations = services.gateway.calls_of("authorize")
    assert [call.request_id for call in authorizations] == [f"auth-{opened.bounty.id}"]
    view = await flow.page(opened.bounty.id)
    assert view.status == "funded"
    assert flow.kinds(view).count("funded") == 1


async def test_fund_sends_order_with_stable_request_id_and_return_urls(
    flow: Flow, services: FakeServices
) -> None:
    created = await flow.draft("25.00")

    async with flow.service() as service:
        url = await service.fund(
            created.bounty.id,
            created.funder_key,
            [Criterion(id="c1", text="divide returns None on zero")],
        )

    assert url == f"https://paypal.test/approve/{created.bounty.id}"
    (call,) = services.gateway.calls_of("create_order")
    assert call.request_id == f"order-{created.bounty.id}"
    assert call.args["amount"] == Decimal("25.00")
    assert call.args["return_url"].endswith("/paypal/return")
    assert call.args["cancel_url"].endswith("/paypal/cancel")
    view = await flow.page(created.bounty.id)
    assert view.status == "awaiting_payment"
    assert [item.text for item in view.criteria] == ["divide returns None on zero"]


async def test_abandoned_checkout_returns_to_draft_and_can_be_funded_again(
    flow: Flow, services: FakeServices
) -> None:
    opened = await flow.awaiting_payment()

    async with flow.service() as service:
        await service.cancel_payment(f"ORDER-{opened.bounty.id}")
    assert (await flow.page(opened.bounty.id)).status == "draft"

    async with flow.service() as service:
        await service.fund(
            opened.bounty.id,
            opened.key,
            [Criterion(id="c1", text="divide returns None on zero")],
        )
    assert (await flow.page(opened.bounty.id)).status == "awaiting_payment"


async def test_wrong_funder_key_on_fund_is_forbidden_and_changes_nothing(
    flow: Flow, services: FakeServices
) -> None:
    created = await flow.draft()

    with pytest.raises(ForbiddenError) as refused:
        async with flow.service() as service:
            await service.fund(
                created.bounty.id,
                "not-the-key",
                [Criterion(id="c1", text="divide returns None on zero")],
            )

    assert refused.value.code == "FUNDER_KEY_INVALID"
    assert services.gateway.calls_of("create_order") == []
    assert (await flow.page(created.bounty.id)).status == "draft"


@pytest.mark.parametrize(
    "criteria",
    [
        [],
        [Criterion(id=f"c{n}", text="t") for n in range(1, 8)],
        [Criterion(id="c1", text="a"), Criterion(id="c1", text="b")],
        [Criterion(id="c1", text="   ")],
        [Criterion(id="c1", text="x" * 501)],
    ],
    ids=["none", "seven", "duplicate-ids", "blank-text", "too-long"],
)
async def test_fund_rejects_invalid_criteria(
    flow: Flow, services: FakeServices, criteria: list[Criterion]
) -> None:
    created = await flow.draft()

    with pytest.raises(UnprocessableError) as refused:
        async with flow.service() as service:
            await service.fund(created.bounty.id, created.funder_key, criteria)

    assert refused.value.code == "CRITERIA_INVALID"
    assert services.gateway.calls_of("create_order") == []


@pytest.mark.parametrize(
    "amount", ["0.99", "500.01", "10.001", "0", "-5", "NaN", "Infinity"]
)
async def test_create_rejects_amounts_outside_the_range(
    flow: Flow, amount: str
) -> None:
    async with flow.service() as service:
        with pytest.raises(UnprocessableError) as refused:
            await service.create(ISSUE_URL, Decimal(amount), "done when text")

    assert refused.value.code == "AMOUNT_OUT_OF_RANGE"


@pytest.mark.parametrize(
    "url",
    [
        "https://github.com/acme/tinycalc/pull/1",
        "http://github.com/acme/tinycalc/issues/1",
        "https://github.com/acme/tinycalc/issues/1/extra",
        "https://github.com/acme/tinycalc/issues/x",
    ],
)
async def test_create_rejects_urls_that_are_not_issues(flow: Flow, url: str) -> None:
    async with flow.service() as service:
        with pytest.raises(UnprocessableError) as refused:
            await service.create(url, Decimal(25), "done when text")

    assert refused.value.code == "ISSUE_URL_INVALID"


async def test_create_edge_amounts_are_accepted_and_stored_exactly(
    flow: Flow, services: FakeServices
) -> None:
    for amount in ("1", "500", "12.34"):
        services.model.queue(drafted_criteria())
        async with flow.service() as service:
            created = await service.create(ISSUE_URL, Decimal(amount), "done when text")
        assert created.bounty.amount == Decimal(amount).quantize(Decimal("0.01"))
        assert (await flow.page(created.bounty.id)).amount_usd == Decimal(amount)


async def test_create_without_a_model_answer_fails_and_stores_nothing(
    flow: Flow, services: FakeServices
) -> None:
    services.model.queue_error_for(CriteriaAnswer)

    with pytest.raises(UpstreamError) as failed:
        async with flow.service() as service:
            await service.create(ISSUE_URL, Decimal(25), "done when text")

    assert failed.value.code == "LLM_UNAVAILABLE"
    assert await flow.listed() == []


async def test_drafted_criteria_are_numbered_from_c1(
    flow: Flow, services: FakeServices
) -> None:
    created = await flow.draft()

    assert [item.id for item in created.bounty.criteria] == ["c1", "c2"]
    assert created.bounty.title == "divide() raises ZeroDivisionError"
    assert (created.bounty.repo_owner, created.bounty.repo_name) == (OWNER, REPO)


# -- claiming and submitting ------------------------------------------------


@pytest.mark.parametrize(
    "body",
    [
        "Fixes #12",
        "no link at all",
        "Fixes acme/tinycalc#1",
        "see issues/10",
        "foo#1",
    ],
)
async def test_submit_rejects_a_pull_request_that_does_not_reference_the_issue(
    flow: Flow, services: FakeServices, body: str
) -> None:
    opened = await flow.funded()
    claim = await flow.claim(opened)
    services.code.pr_body = body

    with pytest.raises(UnprocessableError) as refused:
        async with flow.service() as service:
            await service.submit(claim.id, PR_URL)

    assert refused.value.code == "PR_NOT_LINKED"
    assert (await flow.page(opened.bounty.id)).status == "funded"
    assert services.jobs.calls == []


@pytest.mark.parametrize(
    "body",
    [
        "Fixes #1",
        "closes #1.",
        "(#1)",
        f"Resolves {ISSUE_URL}",
    ],
)
async def test_submit_accepts_references_to_the_issue(
    flow: Flow, services: FakeServices, body: str
) -> None:
    opened = await flow.funded()
    claim = await flow.claim(opened)
    services.code.pr_body = body

    async with flow.service() as service:
        submitted = await service.submit(claim.id, PR_URL)

    assert submitted.status == "submitted"
    assert (await flow.page(opened.bounty.id)).status == "in_review"
    assert services.jobs.calls == [("review", claim.id, None)]


async def test_submit_from_another_repository_is_refused(
    flow: Flow, services: FakeServices
) -> None:
    opened = await flow.funded()
    claim = await flow.claim(opened)

    with pytest.raises(UnprocessableError) as refused:
        async with flow.service() as service:
            await service.submit(claim.id, "https://github.com/acme/other/pull/7")

    assert refused.value.code == "PR_WRONG_REPO"


async def test_submit_malformed_url_is_refused(flow: Flow) -> None:
    opened = await flow.funded()
    claim = await flow.claim(opened)

    with pytest.raises(UnprocessableError) as refused:
        async with flow.service() as service:
            await service.submit(claim.id, "https://github.com/acme/tinycalc/issues/7")

    assert refused.value.code == "PR_URL_INVALID"


async def test_second_submission_while_one_is_in_review_is_refused(
    flow: Flow, services: FakeServices
) -> None:
    opened = await flow.funded()
    first = await flow.submitted(opened)

    async with flow.service() as service:
        with pytest.raises(ConflictError) as refused:
            await service.submit(first.id, PR_URL)

    assert refused.value.code == "BOUNTY_IN_REVIEW"
    assert services.jobs.calls == [("review", first.id, None)]


async def test_claim_on_a_bounty_that_is_not_funded_is_refused(flow: Flow) -> None:
    created = await flow.draft()

    async with flow.service() as service:
        with pytest.raises(ConflictError) as refused:
            await service.claim(
                created.bounty.id, "solver", SolverKind.HUMAN, SOLVER_EMAIL
            )

    assert refused.value.code == "BOUNTY_NOT_OPEN"


# -- cancelling and expiring ---------------------------------------------------


async def test_cancel_from_funded_voids_once_with_a_stable_request_id(
    flow: Flow, services: FakeServices
) -> None:
    opened = await flow.funded()

    async with flow.service() as service:
        await service.cancel(opened.bounty.id, opened.key)

    voids = services.gateway.calls_of("void")
    assert [call.request_id for call in voids] == [f"void-{opened.bounty.id}"]
    assert voids[0].args["auth_id"] == f"AUTH-ORDER-{opened.bounty.id}"
    view = await flow.page(opened.bounty.id)
    assert view.status == "cancelled"
    assert flow.kinds(view)[-1] == "cancelled"


async def test_cancel_before_payment_never_calls_paypal_void(
    flow: Flow, services: FakeServices
) -> None:
    opened = await flow.awaiting_payment()

    async with flow.service() as service:
        await service.cancel(opened.bounty.id, opened.key)

    assert (await flow.page(opened.bounty.id)).status == "cancelled"
    assert services.gateway.calls_of("void") == []


async def test_cancel_with_a_wrong_key_is_forbidden_and_voids_nothing(
    flow: Flow, services: FakeServices
) -> None:
    opened = await flow.funded()

    with pytest.raises(ForbiddenError):
        async with flow.service() as service:
            await service.cancel(opened.bounty.id, "wrong")

    assert services.gateway.calls_of("void") == []
    assert (await flow.page(opened.bounty.id)).status == "funded"


def _batch(claim_id, attempt: int = 1) -> str:
    """Batch id the fake PayPal returns for the given payout attempt."""
    return f"BATCH-payout-{claim_id}" + (f"-{attempt}" if attempt > 1 else "")


def _failed_payout(services: FakeServices, claim_id, attempt: int = 1) -> None:
    services.gateway.batch_statuses[_batch(claim_id, attempt)] = PayoutStatus(
        batch_status="SUCCESS", item_status="BLOCKED"
    )


async def test_dead_payout_then_release_sends_a_new_payout_and_never_the_first_again(
    flow: Flow, services: FakeServices
) -> None:
    opened, claim = await _reviewed_to_payout(flow, services)
    _failed_payout(services, claim.id)
    await _poll(flow, claim.id)
    assert (await flow.page(opened.bounty.id)).status == "needs_human"

    await _decide(flow, opened, "release")

    payouts = services.gateway.calls_of("payout")
    assert [call.request_id for call in payouts] == [
        f"payout-{claim.id}",
        f"payout-{claim.id}-2",
    ]
    assert [call.args["sender_batch_id"] for call in payouts] == [
        f"payout-{claim.id}",
        f"payout-{claim.id}-2",
    ]
    assert len(services.gateway.calls_of("capture")) == 1
    assert (await flow.page(opened.bounty.id)).status == "released"
    await _poll(flow, claim.id)
    view = await flow.page(opened.bounty.id)
    assert view.status == "paid"
    assert [item.status for item in view.claims] == ["accepted"]
    assert services.gateway.calls_of("payout_status")[-1].args["batch_id"] == _batch(
        claim.id, 2
    )


async def test_dead_payout_event_says_definitive_and_names_the_batch(
    flow: Flow, services: FakeServices
) -> None:
    opened, claim = await _reviewed_to_payout(flow, services)
    _failed_payout(services, claim.id)

    await _poll(flow, claim.id)

    view = await flow.page(opened.bounty.id)
    event = view.events[-1]
    assert event.kind == "payout_failed"
    assert dict(event.detail) == {
        "claim_id": str(claim.id),
        "batch_id": _batch(claim.id),
        "item_status": "BLOCKED",
        "definitive": True,
    }
    assert [item.status for item in view.claims] == ["needs_human"]


@pytest.mark.parametrize(
    "status", ["FAILED", "RETURNED", "BLOCKED", "REFUNDED", "REVERSED"]
)
async def test_every_dead_item_state_frees_the_payout_for_a_new_attempt(
    flow: Flow, services: FakeServices, status: str
) -> None:
    opened, claim = await _reviewed_to_payout(flow, services)
    services.gateway.batch_statuses[_batch(claim.id)] = PayoutStatus(
        batch_status="SUCCESS", item_status=status
    )
    await _poll(flow, claim.id)

    await _decide(flow, opened, "release")

    assert len(services.gateway.calls_of("payout")) == 2


@pytest.mark.parametrize("batch_status", ["DENIED", "CANCELED"])
async def test_a_denied_or_canceled_batch_frees_the_payout_for_a_new_attempt(
    flow: Flow, services: FakeServices, batch_status: str
) -> None:
    opened, claim = await _reviewed_to_payout(flow, services)
    services.gateway.batch_statuses[_batch(claim.id)] = PayoutStatus(
        batch_status=batch_status, item_status=None
    )
    await _poll(flow, claim.id)

    await _decide(flow, opened, "release")

    ids = [call.request_id for call in services.gateway.calls_of("payout")]
    assert ids == [f"payout-{claim.id}", f"payout-{claim.id}-2"]


async def test_attempt_numbers_keep_counting_and_an_error_reuses_its_id(
    flow: Flow, services: FakeServices
) -> None:
    opened, claim = await _reviewed_to_payout(flow, services)
    _failed_payout(services, claim.id, 1)
    await _poll(flow, claim.id)
    services.gateway.fail["payout"] = PAYPAL_REJECTED
    await _decide(flow, opened, "release")  # attempt 2 raises: ambiguous
    del services.gateway.fail["payout"]
    _failed_payout(services, claim.id, 2)
    await _decide(flow, opened, "release")  # attempt 2 again, same id
    await _poll(flow, claim.id)  # attempt 2 turned out dead

    await _decide(flow, opened, "release")

    ids = [call.request_id for call in services.gateway.calls_of("payout")]
    assert ids == [
        f"payout-{claim.id}",
        f"payout-{claim.id}-2",
        f"payout-{claim.id}-2",
        f"payout-{claim.id}-3",
    ]
    assert len(services.gateway.calls_of("capture")) == 1


async def test_unclaimed_payout_keeps_its_batch_and_cancel_is_refused(
    flow: Flow, services: FakeServices
) -> None:
    opened, claim = await _reviewed_to_payout(flow, services)
    services.gateway.batch_statuses[_batch(claim.id)] = PayoutStatus(
        batch_status="SUCCESS", item_status="UNCLAIMED"
    )
    await _poll(flow, claim.id)

    with pytest.raises(ConflictError) as refused:
        async with flow.service() as service:
            await service.cancel(opened.bounty.id, opened.key)

    assert refused.value.code == "PAYOUT_IN_FLIGHT"
    assert services.gateway.calls_of("refund") == []
    view = await flow.page(opened.bounty.id)
    assert view.status == "needs_human"
    assert dict(view.events[-1].detail)["definitive"] is False


async def test_onhold_payout_is_not_dead_either(
    flow: Flow, services: FakeServices
) -> None:
    opened, claim = await _reviewed_to_payout(flow, services)
    services.gateway.batch_statuses[_batch(claim.id)] = PayoutStatus(
        batch_status="PROCESSING", item_status="ONHOLD"
    )
    await _poll(flow, claim.id)

    await _decide(flow, opened, "release")

    assert len(services.gateway.calls_of("payout")) == 1
    assert (await flow.page(opened.bounty.id)).status == "released"


async def test_cancel_while_the_payout_is_pending_is_409_payout_in_flight(
    flow: Flow, services: FakeServices, client: AsyncTestClient[Litestar]
) -> None:
    opened, _claim = await _reviewed_to_payout(flow, services)

    response = await client.post(
        f"/api/v1/bounties/{opened.bounty.id}/cancel",
        headers={"X-Funder-Key": opened.key},
    )

    assert response.status_code == 409
    assert response.json()["code"] == "PAYOUT_IN_FLIGHT"
    assert services.gateway.calls_of("refund") == []
    assert (await flow.page(opened.bounty.id)).status == "released"


async def test_cancel_after_a_dead_payout_refunds_once_and_cancels(
    flow: Flow, services: FakeServices
) -> None:
    opened, claim = await _reviewed_to_payout(flow, services)
    _failed_payout(services, claim.id)
    await _poll(flow, claim.id)

    async with flow.service() as service:
        await service.cancel(opened.bounty.id, opened.key)

    refunds = services.gateway.calls_of("refund")
    assert [call.request_id for call in refunds] == [f"refund-{opened.bounty.id}"]
    assert refunds[0].args["capture_id"] == f"CAPTURE-AUTH-ORDER-{opened.bounty.id}"
    assert services.gateway.calls_of("void") == []
    view = await flow.page(opened.bounty.id)
    assert view.status == "cancelled"
    assert flow.kinds(view)[-3:] == ["payout_failed", "refunded", "cancelled"]
    refunded = view.events[-2]
    assert dict(refunded.detail) == {
        "refund_id": f"REFUND-CAPTURE-AUTH-ORDER-{opened.bounty.id}"
    }

    with pytest.raises(ConflictError) as again:
        async with flow.service() as service:
            await service.cancel(opened.bounty.id, opened.key)
    assert again.value.code == "INVALID_TRANSITION"
    assert len(services.gateway.calls_of("refund")) == 1


async def test_cancel_after_a_payout_that_only_raised_refunds(
    flow: Flow, services: FakeServices
) -> None:
    opened = await flow.funded()
    claim = await flow.submitted(opened)
    services.gateway.fail["payout"] = PAYPAL_REJECTED
    services.model.queue(confirming_judge())
    await _review(flow, claim.id)

    async with flow.service() as service:
        await service.cancel(opened.bounty.id, opened.key)

    assert len(services.gateway.calls_of("refund")) == 1
    assert (await flow.page(opened.bounty.id)).status == "cancelled"


async def test_failed_refund_leaves_the_bounty_parked_and_a_retry_reuses_the_id(
    flow: Flow, services: FakeServices
) -> None:
    opened, claim = await _reviewed_to_payout(flow, services)
    _failed_payout(services, claim.id)
    await _poll(flow, claim.id)
    services.gateway.fail["refund"] = PAYPAL_REJECTED

    with pytest.raises(UpstreamError):
        async with flow.service() as service:
            await service.cancel(opened.bounty.id, opened.key)

    view = await flow.page(opened.bounty.id)
    assert view.status == "needs_human"
    assert "refunded" not in flow.kinds(view)

    del services.gateway.fail["refund"]
    async with flow.service() as service:
        await service.cancel(opened.bounty.id, opened.key)

    ids = [call.request_id for call in services.gateway.calls_of("refund")]
    assert ids == [f"refund-{opened.bounty.id}"] * 2
    assert (await flow.page(opened.bounty.id)).status == "cancelled"


async def test_a_paid_bounty_cannot_be_cancelled_or_refunded(
    flow: Flow, services: FakeServices
) -> None:
    opened, claim = await _reviewed_to_payout(flow, services)
    await _poll(flow, claim.id)

    with pytest.raises(ConflictError) as refused:
        async with flow.service() as service:
            await service.cancel(opened.bounty.id, opened.key)

    assert refused.value.code == "INVALID_TRANSITION"
    assert services.gateway.calls_of("refund") == []
    assert (await flow.page(opened.bounty.id)).status == "paid"


async def test_cancel_while_in_review_is_refused(
    flow: Flow, services: FakeServices
) -> None:
    opened = await flow.funded()
    await flow.submitted(opened)

    with pytest.raises(ConflictError) as refused:
        async with flow.service() as service:
            await service.cancel(opened.bounty.id, opened.key)

    assert refused.value.code == "INVALID_TRANSITION"
    assert services.gateway.calls_of("void") == []


async def test_expire_due_voids_only_authorizations_ending_within_a_day(
    flow: Flow, services: FakeServices
) -> None:
    services.gateway.auth_expires_at = NOW + timedelta(hours=25)
    later = await flow.funded()
    services.gateway.auth_expires_at = NOW + timedelta(hours=23)
    soon = await flow.funded()

    async with flow.service() as service:
        await service.expire_due()

    voids = services.gateway.calls_of("void")
    assert [call.request_id for call in voids] == [f"void-{soon.bounty.id}"]
    soon_view = await flow.page(soon.bounty.id)
    assert soon_view.status == "expired"
    assert flow.kinds(soon_view)[-1] == "expired"
    assert (await flow.page(later.bounty.id)).status == "funded"


async def test_expire_due_is_repeatable_and_survives_a_paypal_error(
    flow: Flow, services: FakeServices
) -> None:
    services.gateway.auth_expires_at = NOW + timedelta(hours=1)
    stuck = await flow.funded()
    ok = await flow.funded()
    services.gateway.fail["void"] = PAYPAL_REJECTED

    async with flow.service() as service:
        await service.expire_due()  # both voids fail; nothing raised
    assert (await flow.page(stuck.bounty.id)).status == "funded"

    del services.gateway.fail["void"]
    async with flow.service() as service:
        await service.expire_due()
    async with flow.service() as service:
        await service.expire_due()  # nothing left to do

    assert (await flow.page(stuck.bounty.id)).status == "expired"
    assert (await flow.page(ok.bounty.id)).status == "expired"
    assert len(services.gateway.calls_of("void")) == 4


async def test_decide_when_nothing_awaits_a_decision_is_refused(
    flow: Flow, services: FakeServices
) -> None:
    opened = await flow.funded()

    with pytest.raises(ConflictError) as refused:
        await _decide(flow, opened, "release")

    assert refused.value.code == "NOT_AWAITING_DECISION"
    assert services.gateway.calls_of("capture") == []


async def test_http_submit_of_a_pull_request_without_the_issue_reference_is_422(
    flow: Flow, services: FakeServices, client: AsyncTestClient[Litestar]
) -> None:
    opened = await flow.funded()
    claim = await flow.claim(opened)
    services.code.pr_body = "Fixes #12"  # #12 is not issue #1

    response = await client.post(
        f"/api/v1/claims/{claim.id}/submit", json={"pr_url": PR_URL}
    )

    assert response.status_code == 422
    assert response.headers["content-type"].startswith("application/problem+json")
    assert response.json()["code"] == "PR_NOT_LINKED"
    assert (await flow.page(opened.bounty.id)).status == "funded"
    assert services.jobs.calls == []
