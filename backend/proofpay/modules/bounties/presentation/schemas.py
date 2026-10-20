"""Request and response models of the bounties HTTP API.

Class names are part of the contract: the generated TypeScript client takes its
type names from them, so they carry no `Out`/`Schema` suffix. Money is a string
with two decimals in responses, so no client rounds it as a float.
"""

from datetime import datetime
from decimal import Decimal
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, Field

from proofpay.modules.bounties.application import queries
from proofpay.modules.bounties.application.commands import (
    CreatedBountyView,
    CriterionInput,
)

# -- requests ------------------------------------------------------------------


class Criterion(BaseModel):
    """One acceptance criterion, in a response and in the funder's edit."""

    id: str = Field(description="Criterion id: c1, c2, ...")
    text: str = Field(description="What the added lines must show")


class CreateBountyRequest(BaseModel):
    issue_url: str = Field(
        description="GitHub issue: https://github.com/<owner>/<repo>/issues/<number>"
    )
    amount_usd: Decimal = Field(
        gt=0,
        decimal_places=2,
        description="Reward in USD, a number or a numeric string, 2 decimals at most",
    )
    done_when: str = Field(
        min_length=10,
        max_length=2000,
        description="What must be true for the work to count as done",
    )


class FundRequest(BaseModel):
    criteria: list[Criterion] = Field(
        min_length=1,
        max_length=6,
        description="The final acceptance criteria, as the funder edited them",
    )

    def to_inputs(self) -> list[CriterionInput]:
        return [CriterionInput(id=item.id, text=item.text) for item in self.criteria]


class ClaimRequest(BaseModel):
    solver_name: str = Field(
        min_length=1, max_length=100, description="Display name of the solver"
    )
    solver_kind: Literal["human", "agent"] = Field(
        description="Whether a person or an AI agent does the work"
    )
    paypal_email: str = Field(
        max_length=254,
        pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$",
        description="PayPal account that receives the payout; never shown publicly",
    )


class SubmitRequest(BaseModel):
    pr_url: str = Field(
        description="Pull request: https://github.com/<owner>/<repo>/pull/<number>"
    )


class DecideRequest(BaseModel):
    decision: Literal["release", "reject"] = Field(
        description="Pay the solver, or turn the claim down and reopen the bounty"
    )


# -- responses -----------------------------------------------------------------


class VerdictItem(BaseModel):
    criterion_id: str = Field(description="Id of the judged criterion")
    state: Literal["met", "not_met", "unverified"] = Field(
        description="met, not_met or unverified"
    )
    quote: str = Field(description="Verbatim quote from the added lines of the diff")
    file: str = Field(description="Path of the file the quote comes from")
    reason: str = Field(description="One-sentence explanation")


class Verdict(BaseModel):
    outcome: queries.OutcomeName = Field(description="pass, fail or needs_human")
    ci: queries.CiName = Field(description="green, red or pending")
    head_sha: str = Field(
        description="Commit whose CI result and diff were judged; empty on old verdicts"
    )
    items: list[VerdictItem] = Field(description="One entry per criterion")

    @classmethod
    def from_view(cls, view: queries.VerdictView) -> Verdict:
        return cls(
            outcome=view.outcome,
            ci=view.ci,
            head_sha=view.head_sha,
            items=[
                VerdictItem(
                    criterion_id=item.criterion_id,
                    state=item.state,
                    quote=item.quote,
                    file=item.file,
                    reason=item.reason,
                )
                for item in view.items
            ],
        )


class BountyEvent(BaseModel):
    at: datetime = Field(description="When it happened")
    kind: str = Field(description="Kind of event, e.g. funded, verdict, paid")
    detail: dict[str, Any] = Field(description="Event data; never contains secrets")

    @classmethod
    def from_view(cls, view: queries.EventView) -> BountyEvent:
        return cls(at=view.at, kind=view.kind, detail=dict(view.detail))


class ClaimView(BaseModel):
    id: UUID = Field(description="Claim id")
    solver_name: str = Field(description="Display name of the solver")
    solver_kind: queries.SolverKindName = Field(description="human or agent")
    pr_url: str | None = Field(description="Submitted pull request, if any")
    status: queries.ClaimStatusName = Field(
        description="open, submitted, rejected, needs_human or accepted"
    )
    verdict: Verdict | None = Field(description="Review result, once reviewed")
    created_at: datetime = Field(description="When the claim was made")

    @classmethod
    def from_view(cls, view: queries.ClaimView) -> ClaimView:
        return cls(
            id=view.id,
            solver_name=view.solver_name,
            solver_kind=view.solver_kind,
            pr_url=view.pr_url,
            status=view.status,
            verdict=None if view.verdict is None else Verdict.from_view(view.verdict),
            created_at=view.created_at,
        )


class BountyCard(BaseModel):
    id: UUID = Field(description="Bounty id")
    issue_url: str = Field(description="GitHub issue the bounty is on")
    repo_owner: str = Field(description="Owner of the GitHub repository")
    repo_name: str = Field(description="Name of the GitHub repository")
    issue_number: int = Field(description="Issue number in the repository")
    title: str = Field(description="Issue title")
    amount_usd: str = Field(description="Reward in USD with two decimals")
    done_when: str = Field(description="The funder's 'done when' statement")
    status: queries.BountyStatusName = Field(
        description="Lifecycle status of the bounty"
    )
    criteria: list[Criterion] = Field(description="Acceptance criteria")
    created_at: datetime = Field(description="When the bounty was created")

    @classmethod
    def from_view(cls, view: queries.BountyCard) -> BountyCard:
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
            criteria=[Criterion(id=c.id, text=c.text) for c in view.criteria],
            created_at=view.created_at,
        )


class BountyPage(BountyCard):
    claims: list[ClaimView] = Field(description="Claims, oldest first")
    verdict: Verdict | None = Field(
        description="Verdict of the newest claim that has one"
    )
    events: list[BountyEvent] = Field(description="Audit log, oldest first")

    @classmethod
    def from_page(cls, view: queries.BountyView) -> BountyPage:
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
            criteria=[Criterion(id=c.id, text=c.text) for c in view.criteria],
            created_at=view.created_at,
            claims=[ClaimView.from_view(claim) for claim in view.claims],
            verdict=None if view.verdict is None else Verdict.from_view(view.verdict),
            events=[BountyEvent.from_view(event) for event in view.events],
        )


class CreatedBounty(BaseModel):
    bounty: BountyPage = Field(description="The new draft bounty")
    funder_key: str = Field(
        description=(
            "Secret that authorises fund, decide and cancel. Shown only in "
            "this response: it cannot be recovered."
        )
    )

    @classmethod
    def from_view(cls, view: CreatedBountyView) -> CreatedBounty:
        return cls(bounty=BountyPage.from_page(view.bounty), funder_key=view.funder_key)


class ApproveLink(BaseModel):
    approve_url: str = Field(description="PayPal page where the funder approves")
