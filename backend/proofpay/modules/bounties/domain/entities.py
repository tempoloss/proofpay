"""Domain entities of the bounties module.

Plain frozen dataclasses: no SQLAlchemy and no pydantic, so the rules can be
tested without a database and without any framework.
"""

import uuid
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from enum import StrEnum
from typing import Any, Literal


class BountyStatus(StrEnum):
    """Lifecycle of a bounty. Transitions are defined in `rules.ALLOWED`."""

    DRAFT = "draft"
    AWAITING_PAYMENT = "awaiting_payment"
    FUNDED = "funded"
    IN_REVIEW = "in_review"
    RELEASED = "released"
    PAID = "paid"
    CANCELLED = "cancelled"
    EXPIRED = "expired"
    NEEDS_HUMAN = "needs_human"


class ClaimStatus(StrEnum):
    """Lifecycle of a solver's claim on a bounty."""

    OPEN = "open"
    SUBMITTED = "submitted"
    REJECTED = "rejected"
    NEEDS_HUMAN = "needs_human"
    ACCEPTED = "accepted"


class SolverKind(StrEnum):
    """Who solves the task."""

    HUMAN = "human"
    AGENT = "agent"


class Outcome(StrEnum):
    """Result of reviewing a pull request."""

    PASS = "pass"  # noqa: S105  (an outcome name, not a password)
    FAIL = "fail"
    NEEDS_HUMAN = "needs_human"


class CiState(StrEnum):
    """Aggregated state of the CI check runs of a pull request."""

    GREEN = "green"
    RED = "red"
    PENDING = "pending"


class EventKind(StrEnum):
    """Kinds of entries in the bounty audit log."""

    CREATED = "created"
    FUNDED = "funded"
    CLAIMED = "claimed"
    SUBMITTED = "submitted"
    CI = "ci"
    VERDICT = "verdict"
    CAPTURED = "captured"
    PAYOUT_SENT = "payout_sent"
    PAYOUT_FAILED = "payout_failed"
    PAID = "paid"
    REJECTED = "rejected"
    NEEDS_HUMAN = "needs_human"
    CANCELLED = "cancelled"
    EXPIRED = "expired"


@dataclass(frozen=True, slots=True)
class Criterion:
    """One "done when" item of a bounty. `id` is `c1`, `c2`, ..."""

    id: str
    text: str


@dataclass(frozen=True, slots=True)
class VerdictItem:
    """Judgement of one criterion, after the quote has been checked by code."""

    criterion_id: str
    state: Literal["met", "not_met", "unverified"]
    quote: str
    file: str
    reason: str


@dataclass(frozen=True, slots=True)
class Verdict:
    """Full review result stored on a claim."""

    outcome: Outcome
    items: tuple[VerdictItem, ...]
    ci: CiState


@dataclass(frozen=True, slots=True)
class Bounty:
    """A bounty on a GitHub issue, funded through a PayPal authorization."""

    id: uuid.UUID
    repo_owner: str
    repo_name: str
    issue_number: int
    title: str
    amount: Decimal
    done_when: str
    criteria: tuple[Criterion, ...]
    status: BountyStatus
    funder_key_hash: str
    order_id: str | None
    auth_id: str | None
    auth_expires_at: datetime | None
    capture_id: str | None
    created_at: datetime


@dataclass(frozen=True, slots=True)
class Claim:
    """A solver's attempt on a bounty, from claim to payout."""

    id: uuid.UUID
    bounty_id: uuid.UUID
    solver_name: str
    solver_kind: SolverKind
    paypal_email: str
    pr_url: str | None
    status: ClaimStatus
    verdict: Verdict | None
    payout_batch_id: str | None
    created_at: datetime


@dataclass(frozen=True, slots=True)
class Event:
    """One entry of the audit log of a bounty."""

    bounty_id: uuid.UUID
    at: datetime
    kind: EventKind
    detail: Mapping[str, Any]


def new_id() -> uuid.UUID:
    """Return a time-ordered UUID (version 7)."""
    return uuid.uuid7()
