"""Verdict JSON stored in the database: old rows must stay readable."""

from proofpay.modules.bounties.domain.entities import (
    CiState,
    Outcome,
    Verdict,
    VerdictItem,
)
from proofpay.modules.bounties.infrastructure.mappers import (
    verdict_from_json,
    verdict_to_json,
)

ITEM = VerdictItem(
    criterion_id="c1",
    state="met",
    quote="return None",
    file="src/calc.py",
    reason="guard added",
)


def test_verdict_round_trips_with_the_judged_commit() -> None:
    verdict = Verdict(
        outcome=Outcome.PASS, items=(ITEM,), ci=CiState.GREEN, head_sha="f" * 40
    )

    assert verdict_from_json(verdict_to_json(verdict)) == verdict


def test_a_verdict_stored_before_head_sha_existed_reads_with_an_empty_commit() -> None:
    stored = {
        "outcome": "fail",
        "ci": "red",
        "items": [
            {
                "criterion_id": "c1",
                "state": "unverified",
                "quote": "",
                "file": "",
                "reason": "quote not found in added lines",
            }
        ],
    }

    verdict = verdict_from_json(stored)

    assert verdict.head_sha == ""
    assert (verdict.outcome, verdict.ci) == (Outcome.FAIL, CiState.RED)
