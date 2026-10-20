"""Response models of the bounties HTTP API.

Money is a string with two decimals, so no client rounds it as a float.
"""

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field

from proofpay.modules.bounties.application.queries import (
    BountyCard,
    BountyView,
    ClaimView,
    CriterionView,
    EventView,
    VerdictView,
)


class CriterionOut(BaseModel):
    id: str = Field(description="Criterion id: c1, c2, ...")
    text: str = Field(description="What the added lines must show")

    @classmethod
    def from_view(cls, view: CriterionView) -> CriterionOut:
        return cls(id=view.id, text=view.text)


class VerdictItemOut(BaseModel):
    criterion_id: str = Field(description="Id of the judged criterion")
    state: str = Field(description="met, not_met or unverified")
    quote: str = Field(description="Verbatim quote from the added lines of the diff")
    file: str = Field(description="Path of the file the quote comes from")
    reason: str = Field(description="One-sentence explanation")


class VerdictOut(BaseModel):
    outcome: str = Field(description="pass, fail or needs_human")
    ci: str = Field(description="green, red or pending")
    items: list[VerdictItemOut] = Field(description="One entry per criterion")

    @classmethod
    def from_view(cls, view: VerdictView) -> VerdictOut:
        return cls(
            outcome=view.outcome,
            ci=view.ci,
            items=[
                VerdictItemOut(
                    criterion_id=item.criterion_id,
                    state=item.state,
                    quote=item.quote,
                    file=item.file,
                    reason=item.reason,
                )
                for item in view.items
            ],
        )


class EventOut(BaseModel):
    at: datetime = Field(description="When it happened")
    kind: str = Field(description="Kind of event, e.g. funded, verdict, paid")
    detail: dict[str, Any] = Field(description="Event data; never contains secrets")

    @classmethod
    def from_view(cls, view: EventView) -> EventOut:
        return cls(at=view.at, kind=view.kind, detail=dict(view.detail))


class ClaimOut(BaseModel):
    id: UUID = Field(description="Claim id")
    solver_name: str = Field(description="Display name of the solver")
    solver_kind: str = Field(description="human or agent")
    pr_url: str | None = Field(description="Submitted pull request, if any")
    status: str = Field(
        description="open, submitted, rejected, needs_human or accepted"
    )
    verdict: VerdictOut | None = Field(description="Review result, once reviewed")
    created_at: datetime = Field(description="When the claim was made")

    @classmethod
    def from_view(cls, view: ClaimView) -> ClaimOut:
        return cls(
            id=view.id,
            solver_name=view.solver_name,
            solver_kind=view.solver_kind,
            pr_url=view.pr_url,
            status=view.status,
            verdict=None
            if view.verdict is None
            else VerdictOut.from_view(view.verdict),
            created_at=view.created_at,
        )


class BountyCardOut(BaseModel):
    id: UUID = Field(description="Bounty id")
    issue_url: str = Field(description="GitHub issue the bounty is on")
    repo_owner: str = Field(description="Owner of the GitHub repository")
    repo_name: str = Field(description="Name of the GitHub repository")
    issue_number: int = Field(description="Issue number in the repository")
    title: str = Field(description="Issue title")
    amount_usd: str = Field(description="Reward in USD with two decimals")
    done_when: str = Field(description="The funder's 'done when' statement")
    status: str = Field(description="Lifecycle status of the bounty")
    criteria: list[CriterionOut] = Field(description="Acceptance criteria")
    created_at: datetime = Field(description="When the bounty was created")

    @classmethod
    def from_view(cls, view: BountyCard) -> BountyCardOut:
        return cls(
            id=view.id,
            issue_url=view.issue_url,
            repo_owner=view.repo_owner,
            repo_name=view.repo_name,
            issue_number=view.issue_number,
            title=view.title,
            amount_usd=f"{view.amount_usd:.2f}",
            done_when=view.done_when,
            status=view.status,
            criteria=[CriterionOut.from_view(item) for item in view.criteria],
            created_at=view.created_at,
        )


class BountyViewOut(BountyCardOut):
    claims: list[ClaimOut] = Field(description="Claims, oldest first")
    verdict: VerdictOut | None = Field(
        description="Verdict of the newest claim that has one"
    )
    events: list[EventOut] = Field(description="Audit log, oldest first")

    @classmethod
    def from_page(cls, view: BountyView) -> BountyViewOut:
        return cls(
            id=view.id,
            issue_url=view.issue_url,
            repo_owner=view.repo_owner,
            repo_name=view.repo_name,
            issue_number=view.issue_number,
            title=view.title,
            amount_usd=f"{view.amount_usd:.2f}",
            done_when=view.done_when,
            status=view.status,
            criteria=[CriterionOut.from_view(item) for item in view.criteria],
            created_at=view.created_at,
            claims=[ClaimOut.from_view(claim) for claim in view.claims],
            verdict=None
            if view.verdict is None
            else VerdictOut.from_view(view.verdict),
            events=[EventOut.from_view(event) for event in view.events],
        )
