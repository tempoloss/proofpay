"""Pure business rules of bounties: transitions, diff parsing, quote checks, CI.

Nothing here does I/O. The AI judge only proposes quotes; this module decides
whether each quote really appears in the added lines of the diff.
"""

import hashlib
import re
from collections.abc import Iterable, Sequence
from dataclasses import replace
from typing import Protocol

from proofpay.modules.bounties.domain.answers import JudgeAnswer, JudgeItem
from proofpay.modules.bounties.domain.entities import (
    Bounty,
    BountyStatus,
    CiState,
    Criterion,
    Outcome,
    VerdictItem,
)
from proofpay.shared.errors import ConflictError

# A diff larger than this is not sent to the judge: it goes to a human.
MAX_DIFF_CHARS = 200_000

# A quote shorter than this proves nothing, so it cannot confirm a criterion.
MIN_QUOTE_CHARS = 8

MISSING_CRITERION_REASON = "criterion missing from judge answer"
QUOTE_NOT_FOUND_REASON = "quote not found in added lines"

ALLOWED: dict[BountyStatus, frozenset[BountyStatus]] = {
    BountyStatus.DRAFT: frozenset(
        {BountyStatus.AWAITING_PAYMENT, BountyStatus.CANCELLED}
    ),
    BountyStatus.AWAITING_PAYMENT: frozenset(
        {BountyStatus.FUNDED, BountyStatus.CANCELLED, BountyStatus.DRAFT}
    ),
    BountyStatus.FUNDED: frozenset(
        {BountyStatus.IN_REVIEW, BountyStatus.CANCELLED, BountyStatus.EXPIRED}
    ),
    BountyStatus.IN_REVIEW: frozenset(
        {
            BountyStatus.FUNDED,
            BountyStatus.RELEASED,
            BountyStatus.NEEDS_HUMAN,
            BountyStatus.EXPIRED,
        }
    ),
    BountyStatus.NEEDS_HUMAN: frozenset(
        {BountyStatus.RELEASED, BountyStatus.FUNDED, BountyStatus.CANCELLED}
    ),
    BountyStatus.RELEASED: frozenset({BountyStatus.PAID, BountyStatus.NEEDS_HUMAN}),
    BountyStatus.PAID: frozenset(),
    BountyStatus.CANCELLED: frozenset(),
    BountyStatus.EXPIRED: frozenset(),
}

_HUNK_HEADER = re.compile(r"^@@ -\d+(?:,(\d+))? \+\d+(?:,(\d+))? @@")
_PASSING_CONCLUSIONS = frozenset({"success", "skipped", "neutral"})


def transition(bounty: Bounty, new: BountyStatus) -> Bounty:
    """Return the bounty moved to `new`; reject transitions not in `ALLOWED`."""
    if new not in ALLOWED[bounty.status]:
        raise ConflictError(
            code="INVALID_TRANSITION",
            detail=f"bounty cannot move from {bounty.status} to {new}",
            params={"from": bounty.status.value, "to": new.value},
        )
    return replace(bounty, status=new)


def added_lines(diff: str) -> dict[str, list[str]]:
    """Map each file of a git unified diff to its added lines, without the `+`.

    Header lines are recognised only outside hunks. The remaining old and new
    line counts of the current hunk tell hunk lines apart from headers, so an
    added line whose content starts with `++` (diff line `+++x`) is kept.
    Deleted files (`+++ /dev/null`) contribute nothing.
    """
    added: dict[str, list[str]] = {}
    path: str | None = None
    old_left = 0  # lines still expected in the current hunk, old side
    new_left = 0  # lines still expected in the current hunk, new side
    for line in diff.replace("\r\n", "\n").split("\n"):
        if old_left or new_left:
            marker = line[:1]
            if marker == "+" and new_left:
                new_left -= 1
                if path is not None:
                    added.setdefault(path, []).append(line[1:])
                continue
            if marker == "-" and old_left:
                old_left -= 1
                continue
            if marker in {" ", ""} and old_left and new_left:
                old_left -= 1
                new_left -= 1
                continue
            if marker == "\\":  # "\ No newline at end of file"
                continue
            # Not a hunk line: the hunk ended early or the diff is malformed.
            old_left = 0
            new_left = 0
        if match := _HUNK_HEADER.match(line):
            old_left = int(match.group(1) or 1)
            new_left = int(match.group(2) or 1)
        elif line.startswith("+++ "):
            target = line[4:]
            path = None if target == "/dev/null" else target.removeprefix("b/")
    return added


def check_quotes(
    criteria: Sequence[Criterion], raw: JudgeAnswer, diff: str
) -> tuple[VerdictItem, ...]:
    """Turn the judge's answer into one verified item per criterion.

    A "met" claim stands only if its quote is a substring of the added lines of
    the file the judge named. Every other claim becomes `unverified` or
    `not_met`, never `met`.
    """
    added = added_lines(diff)
    answers: dict[str, list[JudgeItem]] = {}
    for item in raw.items:
        answers.setdefault(item.criterion_id, []).append(item)
    return tuple(
        _check_criterion(criterion, answers.get(criterion.id, []), added)
        for criterion in criteria
    )


def _check_criterion(
    criterion: Criterion,
    answers: list[JudgeItem],
    added: dict[str, list[str]],
) -> VerdictItem:
    if len(answers) != 1:
        return VerdictItem(
            criterion_id=criterion.id,
            state="unverified",
            quote="",
            file="",
            reason=MISSING_CRITERION_REASON,
        )
    answer = answers[0]
    if not answer.met:
        return VerdictItem(
            criterion_id=criterion.id,
            state="not_met",
            quote=answer.quote,
            file=answer.file,
            reason=answer.reason,
        )
    if _quote_in_added_lines(answer.quote, added.get(answer.file, [])):
        return VerdictItem(
            criterion_id=criterion.id,
            state="met",
            quote=answer.quote,
            file=answer.file,
            reason=answer.reason,
        )
    return VerdictItem(
        criterion_id=criterion.id,
        state="unverified",
        quote=answer.quote,
        file=answer.file,
        reason=QUOTE_NOT_FOUND_REASON,
    )


def _quote_in_added_lines(quote: str, lines: list[str]) -> bool:
    # Joining with "\n" lets a multi-line quote match consecutive added lines.
    # A quote without a line break cannot match across the join, because the
    # join adds one: it matches only inside a single added line.
    stripped = quote.strip()
    return len(stripped) >= MIN_QUOTE_CHARS and stripped in "\n".join(lines)


def outcome(items: Sequence[VerdictItem], ci: CiState) -> Outcome:
    """Decide the result of a review from verified items and CI state."""
    if ci is not CiState.GREEN:
        return Outcome.FAIL
    states = {item.state for item in items}
    if "not_met" in states:
        return Outcome.FAIL
    if "unverified" in states:
        return Outcome.NEEDS_HUMAN
    return Outcome.PASS


class CheckLike(Protocol):
    """A CI check run, as far as the domain needs to see it."""

    @property
    def status(self) -> str: ...

    @property
    def conclusion(self) -> str | None: ...


def ci_state(runs: Iterable[CheckLike]) -> CiState:
    """Aggregate check runs: no runs is RED, any unfinished run is PENDING."""
    checks = list(runs)
    if not checks:
        return CiState.RED
    if any(run.status != "completed" for run in checks):
        return CiState.PENDING
    if all(run.conclusion in _PASSING_CONCLUSIONS for run in checks):
        return CiState.GREEN
    return CiState.RED


def hash_funder_key(key: str) -> str:
    """Return the SHA-256 hex digest that is stored in place of a funder key."""
    return hashlib.sha256(key.encode("utf-8")).hexdigest()
