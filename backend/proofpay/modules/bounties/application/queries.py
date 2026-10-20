"""Read side of the bounties module: read models and the queries that build them.

Read models are frozen dataclasses with plain values (statuses as strings), so
presentation depends on them and not on the domain. They never carry the
solver's PayPal e-mail or anything derived from the funder's key.
"""

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Any, Literal
from uuid import UUID

from proofpay.modules.bounties.domain.entities import (
    Bounty,
    BountyStatus,
    Claim,
    Event,
    Verdict,
)
from proofpay.modules.bounties.domain.repositories import BountyRepository

# The values of the domain enums as string literals: the HTTP schema and the
# generated client are typed with them. mypy checks that they match the enums.
type BountyStatusName = Literal[
    "draft",
    "awaiting_payment",
    "funded",
    "in_review",
    "needs_human",
    "released",
    "paid",
    "cancelled",
    "expired",
]
type ClaimStatusName = Literal[
    "open", "submitted", "rejected", "needs_human", "accepted"
]
type SolverKindName = Literal["human", "agent"]
type OutcomeName = Literal["pass", "fail", "needs_human"]
type CiName = Literal["green", "red", "pending"]


@dataclass(frozen=True, slots=True)
class CriterionView:
    id: str
    text: str


@dataclass(frozen=True, slots=True)
class VerdictItemView:
    criterion_id: str
    state: Literal["met", "not_met", "unverified"]
    quote: str
    file: str
    reason: str


@dataclass(frozen=True, slots=True)
class VerdictView:
    outcome: OutcomeName
    ci: CiName
    items: tuple[VerdictItemView, ...]


@dataclass(frozen=True, slots=True)
class EventView:
    at: datetime
    kind: str
    detail: Mapping[str, Any]


@dataclass(frozen=True, slots=True)
class ClaimView:
    id: UUID
    solver_name: str
    solver_kind: SolverKindName
    pr_url: str | None
    status: ClaimStatusName
    verdict: VerdictView | None
    created_at: datetime


@dataclass(frozen=True, slots=True)
class BountyCard:
    id: UUID
    issue_url: str
    repo_owner: str
    repo_name: str
    issue_number: int
    title: str
    amount_usd: Decimal
    done_when: str
    status: BountyStatusName
    criteria: tuple[CriterionView, ...]
    created_at: datetime


@dataclass(frozen=True, slots=True)
class BountyView:
    id: UUID
    issue_url: str
    repo_owner: str
    repo_name: str
    issue_number: int
    title: str
    amount_usd: Decimal
    done_when: str
    status: BountyStatusName
    criteria: tuple[CriterionView, ...]
    created_at: datetime
    claims: tuple[ClaimView, ...]
    verdict: VerdictView | None
    events: tuple[EventView, ...]


@dataclass(frozen=True, slots=True)
class ClaimStatusView:
    claim_id: UUID
    bounty_id: UUID
    status: ClaimStatusName
    bounty_status: BountyStatusName
    verdict: VerdictView | None
    events: tuple[EventView, ...]


def _verdict_view(verdict: Verdict | None) -> VerdictView | None:
    if verdict is None:
        return None
    return VerdictView(
        outcome=verdict.outcome.value,
        ci=verdict.ci.value,
        items=tuple(
            VerdictItemView(
                criterion_id=item.criterion_id,
                state=item.state,
                quote=item.quote,
                file=item.file,
                reason=item.reason,
            )
            for item in verdict.items
        ),
    )


def _card(bounty: Bounty) -> BountyCard:
    return BountyCard(
        id=bounty.id,
        issue_url=(
            f"https://github.com/{bounty.repo_owner}/{bounty.repo_name}"
            f"/issues/{bounty.issue_number}"
        ),
        repo_owner=bounty.repo_owner,
        repo_name=bounty.repo_name,
        issue_number=bounty.issue_number,
        title=bounty.title,
        amount_usd=bounty.amount,
        done_when=bounty.done_when,
        status=bounty.status.value,
        criteria=tuple(CriterionView(id=c.id, text=c.text) for c in bounty.criteria),
        created_at=bounty.created_at,
    )


def _claim_view(claim: Claim) -> ClaimView:
    return ClaimView(
        id=claim.id,
        solver_name=claim.solver_name,
        solver_kind=claim.solver_kind.value,
        pr_url=claim.pr_url,
        status=claim.status.value,
        verdict=_verdict_view(claim.verdict),
        created_at=claim.created_at,
    )


def _event_view(event: Event) -> EventView:
    return EventView(at=event.at, kind=event.kind.value, detail=event.detail)


class BountyQueries:
    """Read-only access to bounties; never changes state."""

    def __init__(self, repo: BountyRepository) -> None:
        self._repo = repo

    async def list_bounties(self) -> list[BountyCard]:
        """Every bounty that is past the draft and payment stages."""
        return [_card(bounty) for bounty in await self._repo.list_public()]

    async def list_open(self) -> list[BountyCard]:
        """Bounties a solver can claim right now (status `funded`)."""
        return [
            _card(bounty)
            for bounty in await self._repo.list_public()
            if bounty.status is BountyStatus.FUNDED
        ]

    async def bounty_page(self, bounty_id: UUID) -> BountyView:
        """A bounty with its claims, latest verdict and audit log."""
        bounty = await self._repo.get(bounty_id)
        claims = await self._repo.claims_of(bounty_id)
        events = await self._repo.events_of(bounty_id)
        verdict = next(
            (claim.verdict for claim in reversed(claims) if claim.verdict is not None),
            None,
        )
        card = _card(bounty)
        return BountyView(
            id=card.id,
            issue_url=card.issue_url,
            repo_owner=card.repo_owner,
            repo_name=card.repo_name,
            issue_number=card.issue_number,
            title=card.title,
            amount_usd=card.amount_usd,
            done_when=card.done_when,
            status=card.status,
            criteria=card.criteria,
            created_at=card.created_at,
            claims=tuple(_claim_view(claim) for claim in claims),
            verdict=_verdict_view(verdict),
            events=tuple(_event_view(event) for event in events),
        )

    async def claim_view(self, claim_id: UUID) -> ClaimView:
        """One claim as the solver sees it: never with the payee's e-mail."""
        return _claim_view(await self._repo.get_claim(claim_id))

    async def claim_status(self, claim_id: UUID) -> ClaimStatusView:
        """State of one claim, with the status and audit log of its bounty."""
        claim = await self._repo.get_claim(claim_id)
        bounty = await self._repo.get(claim.bounty_id)
        events = await self._repo.events_of(claim.bounty_id)
        return ClaimStatusView(
            claim_id=claim.id,
            bounty_id=claim.bounty_id,
            status=claim.status.value,
            bounty_status=bounty.status.value,
            verdict=_verdict_view(claim.verdict),
            events=tuple(_event_view(event) for event in events),
        )
