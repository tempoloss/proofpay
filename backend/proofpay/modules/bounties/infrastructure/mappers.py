"""Conversion between domain entities and database rows, both directions."""

from typing import Any, Literal, cast

from proofpay.modules.bounties.domain.entities import (
    Bounty,
    BountyStatus,
    CiState,
    Claim,
    ClaimStatus,
    Criterion,
    Event,
    EventKind,
    Outcome,
    SolverKind,
    Verdict,
    VerdictItem,
)
from proofpay.modules.bounties.infrastructure.models import (
    BountyRow,
    ClaimRow,
    EventRow,
)

type ItemState = Literal["met", "not_met", "unverified"]


def criteria_to_json(criteria: tuple[Criterion, ...]) -> list[dict[str, Any]]:
    return [{"id": item.id, "text": item.text} for item in criteria]


def criteria_from_json(data: list[dict[str, Any]]) -> tuple[Criterion, ...]:
    return tuple(Criterion(id=item["id"], text=item["text"]) for item in data)


def verdict_to_json(verdict: Verdict) -> dict[str, Any]:
    return {
        "outcome": verdict.outcome.value,
        "ci": verdict.ci.value,
        "head_sha": verdict.head_sha,
        "items": [
            {
                "criterion_id": item.criterion_id,
                "state": item.state,
                "quote": item.quote,
                "file": item.file,
                "reason": item.reason,
            }
            for item in verdict.items
        ],
    }


def verdict_from_json(data: dict[str, Any]) -> Verdict:
    return Verdict(
        outcome=Outcome(data["outcome"]),
        ci=CiState(data["ci"]),
        head_sha=data.get("head_sha", ""),
        items=tuple(
            VerdictItem(
                criterion_id=item["criterion_id"],
                state=cast("ItemState", item["state"]),
                quote=item["quote"],
                file=item["file"],
                reason=item["reason"],
            )
            for item in data["items"]
        ),
    )


def bounty_from_row(row: BountyRow) -> Bounty:
    return Bounty(
        id=row.id,
        repo_owner=row.repo_owner,
        repo_name=row.repo_name,
        issue_number=row.issue_number,
        title=row.title,
        amount=row.amount,
        done_when=row.done_when,
        criteria=criteria_from_json(row.criteria),
        status=BountyStatus(row.status),
        funder_key_hash=row.funder_key_hash,
        order_id=row.order_id,
        order_attempt=row.order_attempt,
        auth_id=row.auth_id,
        auth_expires_at=row.auth_expires_at,
        capture_id=row.capture_id,
        created_at=row.created_at,
    )


def apply_bounty(row: BountyRow, bounty: Bounty) -> None:
    """Copy every field of the entity onto an existing row."""
    row.repo_owner = bounty.repo_owner
    row.repo_name = bounty.repo_name
    row.issue_number = bounty.issue_number
    row.title = bounty.title
    row.amount = bounty.amount
    row.done_when = bounty.done_when
    row.criteria = criteria_to_json(bounty.criteria)
    row.status = bounty.status.value
    row.funder_key_hash = bounty.funder_key_hash
    row.order_id = bounty.order_id
    row.order_attempt = bounty.order_attempt
    row.auth_id = bounty.auth_id
    row.auth_expires_at = bounty.auth_expires_at
    row.capture_id = bounty.capture_id
    row.created_at = bounty.created_at


def bounty_to_row(bounty: Bounty) -> BountyRow:
    row = BountyRow(id=bounty.id)
    apply_bounty(row, bounty)
    return row


def claim_from_row(row: ClaimRow) -> Claim:
    return Claim(
        id=row.id,
        bounty_id=row.bounty_id,
        solver_name=row.solver_name,
        solver_kind=SolverKind(row.solver_kind),
        paypal_email=row.paypal_email,
        pr_url=row.pr_url,
        status=ClaimStatus(row.status),
        verdict=None if row.verdict is None else verdict_from_json(row.verdict),
        payout_batch_id=row.payout_batch_id,
        created_at=row.created_at,
    )


def apply_claim(row: ClaimRow, claim: Claim) -> None:
    """Copy every field of the entity onto an existing row."""
    row.bounty_id = claim.bounty_id
    row.solver_name = claim.solver_name
    row.solver_kind = claim.solver_kind.value
    row.paypal_email = claim.paypal_email
    row.pr_url = claim.pr_url
    row.status = claim.status.value
    row.verdict = None if claim.verdict is None else verdict_to_json(claim.verdict)
    row.payout_batch_id = claim.payout_batch_id
    row.created_at = claim.created_at


def claim_to_row(claim: Claim) -> ClaimRow:
    row = ClaimRow(id=claim.id)
    apply_claim(row, claim)
    return row


def event_from_row(row: EventRow) -> Event:
    return Event(
        bounty_id=row.bounty_id,
        at=row.at,
        kind=EventKind(row.kind),
        detail=row.detail,
    )


def event_to_row(event: Event) -> EventRow:
    return EventRow(
        bounty_id=event.bounty_id,
        at=event.at,
        kind=event.kind.value,
        detail=dict(event.detail),
    )
