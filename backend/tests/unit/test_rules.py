"""Unit tests for the pure rules of the bounties domain."""

from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal

import pytest

from proofpay.modules.bounties.domain.answers import JudgeAnswer, JudgeItem
from proofpay.modules.bounties.domain.entities import (
    Bounty,
    BountyStatus,
    CiState,
    Criterion,
    Outcome,
    VerdictItem,
    new_id,
)
from proofpay.modules.bounties.domain.rules import (
    added_lines,
    check_quotes,
    ci_state,
    hash_funder_key,
    outcome,
    transition,
)
from proofpay.shared.errors import ConflictError

CALC = "src/calc.py"
TEST_FILE = "tests/test_calc.py"

# Two files: a modified module with one removed line and one new test file.
DIFF = "\n".join(
    [
        "diff --git a/src/calc.py b/src/calc.py",
        "index 1111111..2222222 100644",
        "--- a/src/calc.py",
        "+++ b/src/calc.py",
        "@@ -1,5 +1,7 @@",
        " def divide(a, b):",
        "-    return a * 0 + legacy_divide(a, b)",
        "+    if b == 0:",
        "+        return None",
        "+    return a / b",
        " ",
        " def add(a, b):",
        "     return a + b",
        "diff --git a/tests/test_calc.py b/tests/test_calc.py",
        "new file mode 100644",
        "index 0000000..3333333",
        "--- /dev/null",
        "+++ b/tests/test_calc.py",
        "@@ -0,0 +1,4 @@",
        "+from src.calc import divide",
        "+",
        "+def test_divide_by_zero():",
        "+    assert divide(1, 0) is None",
        "",
    ]
)

ZERO_CHECK = Criterion(id="c1", text="divide returns None on zero")
COVERAGE = Criterion(id="c2", text="a test covers the zero divisor")


def _bounty(status: BountyStatus) -> Bounty:
    return Bounty(
        id=new_id(),
        repo_owner="acme",
        repo_name="tinycalc",
        issue_number=1,
        title="divide by zero",
        amount=Decimal("25.00"),
        done_when="divide returns None on zero",
        criteria=(ZERO_CHECK,),
        status=status,
        funder_key_hash="0" * 64,
        order_id=None,
        auth_id=None,
        auth_expires_at=None,
        capture_id=None,
        created_at=datetime(2026, 10, 20, 9, 0, tzinfo=UTC),
    )


def _judge(
    criterion_id: str = "c1",
    met: bool = True,
    quote: str = "if b == 0:",
    file: str = CALC,
    reason: str = "judge reason",
) -> JudgeItem:
    return JudgeItem(
        criterion_id=criterion_id,
        met=met,
        quote=quote,
        file=file,
        reason=reason,
    )


def _check_one(quote: str, file: str = CALC, met: bool = True) -> VerdictItem:
    raw = JudgeAnswer(items=[_judge(quote=quote, file=file, met=met)])
    (item,) = check_quotes((ZERO_CHECK,), raw, DIFF)
    return item


@dataclass(frozen=True, slots=True)
class _Run:
    status: str
    conclusion: str | None


# --- transition -------------------------------------------------------------


def test_transition_from_draft_to_paid_is_rejected_with_params() -> None:
    with pytest.raises(ConflictError) as excinfo:
        transition(_bounty(BountyStatus.DRAFT), BountyStatus.PAID)

    assert excinfo.value.code == "INVALID_TRANSITION"
    assert excinfo.value.params == {"from": "draft", "to": "paid"}
    assert excinfo.value.status == 409


def test_transition_out_of_paid_is_rejected() -> None:
    with pytest.raises(ConflictError) as excinfo:
        transition(_bounty(BountyStatus.PAID), BountyStatus.CANCELLED)

    assert excinfo.value.params == {"from": "paid", "to": "cancelled"}


def test_transition_from_funded_to_in_review_returns_new_bounty() -> None:
    original = _bounty(BountyStatus.FUNDED)

    moved = transition(original, BountyStatus.IN_REVIEW)

    assert moved.status is BountyStatus.IN_REVIEW
    assert moved.id == original.id
    assert original.status is BountyStatus.FUNDED


# --- added_lines ------------------------------------------------------------


def test_added_lines_of_two_file_diff_excludes_context_and_removed_lines() -> None:
    assert added_lines(DIFF) == {
        CALC: ["    if b == 0:", "        return None", "    return a / b"],
        TEST_FILE: [
            "from src.calc import divide",
            "",
            "def test_divide_by_zero():",
            "    assert divide(1, 0) is None",
        ],
    }


def test_added_line_whose_content_starts_with_double_plus_is_kept() -> None:
    diff = "\n".join(
        [
            "diff --git a/a.c b/a.c",
            "--- a/a.c",
            "+++ b/a.c",
            "@@ -1,1 +1,2 @@",
            " int x;",
            "+++i;",
            "",
        ]
    )

    assert added_lines(diff) == {"a.c": ["++i;"]}


def test_deleted_file_contributes_no_added_lines() -> None:
    diff = "\n".join(
        [
            "diff --git a/old.py b/old.py",
            "deleted file mode 100644",
            "index 4444444..0000000",
            "--- a/old.py",
            "+++ /dev/null",
            "@@ -1,2 +0,0 @@",
            '-print("a")',
            '-print("b")',
            "",
        ]
    )

    assert added_lines(diff) == {}


def test_no_newline_marker_does_not_count_as_added_line() -> None:
    diff = "\n".join(
        [
            "diff --git a/a.txt b/a.txt",
            "--- a/a.txt",
            "+++ b/a.txt",
            "@@ -1 +1 @@",
            "-old",
            "\\ No newline at end of file",
            "+new",
            "\\ No newline at end of file",
            "",
        ]
    )

    assert added_lines(diff) == {"a.txt": ["new"]}


# --- check_quotes -----------------------------------------------------------


def test_quote_from_added_line_is_met_with_judge_reason() -> None:
    item = _check_one("if b == 0:")

    assert item == VerdictItem(
        criterion_id="c1",
        state="met",
        quote="if b == 0:",
        file=CALC,
        reason="judge reason",
    )


def test_quote_spanning_consecutive_added_lines_is_met() -> None:
    item = _check_one("if b == 0:\n        return None")

    assert item.state == "met"


def test_quote_is_stripped_before_matching() -> None:
    item = _check_one("   if b == 0:   ")

    assert item.state == "met"


def test_quote_absent_from_diff_is_unverified() -> None:
    item = _check_one("def multiply(a, b):")

    assert item.state == "unverified"
    assert item.reason == "quote not found in added lines"
    assert item.quote == "def multiply(a, b):"
    assert item.file == CALC


def test_quote_from_removed_line_is_unverified() -> None:
    item = _check_one("legacy_divide(a, b)")

    assert item.state == "unverified"
    assert item.reason == "quote not found in added lines"


def test_quote_from_added_line_of_other_file_is_unverified() -> None:
    item = _check_one("assert divide(1, 0) is None", file=CALC)

    assert item.state == "unverified"
    assert item.reason == "quote not found in added lines"


def test_quote_shorter_than_eight_characters_is_unverified() -> None:
    # "b == 0:" is in the diff, but 7 characters prove too little.
    item = _check_one("b == 0:")

    assert item.state == "unverified"
    assert item.reason == "quote not found in added lines"


def test_quote_of_exactly_eight_characters_is_enough() -> None:
    item = _check_one("return N")

    assert item.state == "met"


def test_met_false_becomes_not_met_and_keeps_judge_fields() -> None:
    item = _check_one("if b == 0:", met=False)

    assert item == VerdictItem(
        criterion_id="c1",
        state="not_met",
        quote="if b == 0:",
        file=CALC,
        reason="judge reason",
    )


def test_criterion_without_judge_item_is_unverified_and_keeps_order() -> None:
    raw = JudgeAnswer(items=[_judge(criterion_id="c1")])

    items = check_quotes((ZERO_CHECK, COVERAGE), raw, DIFF)

    assert [item.criterion_id for item in items] == ["c1", "c2"]
    assert items[1] == VerdictItem(
        criterion_id="c2",
        state="unverified",
        quote="",
        file="",
        reason="criterion missing from judge answer",
    )


def test_two_judge_items_for_one_criterion_are_unverified() -> None:
    raw = JudgeAnswer(items=[_judge(criterion_id="c1"), _judge(criterion_id="c1")])

    (item,) = check_quotes((ZERO_CHECK,), raw, DIFF)

    assert item.state == "unverified"
    assert item.reason == "criterion missing from judge answer"


def test_judge_items_with_unknown_criterion_ids_are_ignored() -> None:
    raw = JudgeAnswer(items=[_judge(criterion_id="c1"), _judge(criterion_id="c9")])

    items = check_quotes((ZERO_CHECK,), raw, DIFF)

    assert len(items) == 1
    assert items[0].state == "met"


# --- outcome ----------------------------------------------------------------


def _met(criterion_id: str = "c1") -> VerdictItem:
    return VerdictItem(
        criterion_id=criterion_id,
        state="met",
        quote="if b == 0:",
        file=CALC,
        reason="ok",
    )


def _unverified(criterion_id: str = "c2") -> VerdictItem:
    return VerdictItem(
        criterion_id=criterion_id,
        state="unverified",
        quote="",
        file="",
        reason="quote not found in added lines",
    )


def _not_met(criterion_id: str = "c2") -> VerdictItem:
    return VerdictItem(
        criterion_id=criterion_id,
        state="not_met",
        quote="",
        file="",
        reason="no test",
    )


@pytest.mark.parametrize("ci", [CiState.RED, CiState.PENDING])
def test_outcome_fails_when_ci_is_not_green_even_if_all_met(ci: CiState) -> None:
    assert outcome([_met("c1"), _met("c2")], ci) is Outcome.FAIL


def test_outcome_needs_human_for_unverified_item_on_green_ci() -> None:
    assert outcome([_met("c1"), _unverified()], CiState.GREEN) is Outcome.NEEDS_HUMAN


def test_outcome_fails_when_any_not_met_even_with_unverified() -> None:
    items = [_not_met(), _unverified()]

    assert outcome(items, CiState.GREEN) is Outcome.FAIL


def test_outcome_passes_when_green_and_all_met() -> None:
    assert outcome([_met("c1"), _met("c2")], CiState.GREEN) is Outcome.PASS


# --- ci_state ---------------------------------------------------------------


def test_ci_state_without_runs_is_red() -> None:
    assert ci_state([]) is CiState.RED


def test_ci_state_with_a_run_in_progress_is_pending() -> None:
    assert ci_state([_Run(status="in_progress", conclusion=None)]) is CiState.PENDING


def test_ci_state_with_success_skipped_and_neutral_is_green() -> None:
    runs = [
        _Run(status="completed", conclusion="success"),
        _Run(status="completed", conclusion="skipped"),
        _Run(status="completed", conclusion="neutral"),
    ]

    assert ci_state(runs) is CiState.GREEN


def test_ci_state_with_one_failure_is_red() -> None:
    runs = [
        _Run(status="completed", conclusion="success"),
        _Run(status="completed", conclusion="failure"),
    ]

    assert ci_state(runs) is CiState.RED


# --- hash_funder_key --------------------------------------------------------


def test_hash_funder_key_is_sha256_hex_digest() -> None:
    assert hash_funder_key("abc") == (
        "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad"
    )
