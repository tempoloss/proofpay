"""Use cases of the bounties module.

One service holds every scenario of a bounty's life: creating and funding it,
claiming, reviewing a pull request, moving the money and cancelling.

Transactions are explicit: the request-scoped session does not commit by
itself. Rules the methods keep, because they move money:

- every state change and its audit event are written in one transaction;
- a PayPal money call (capture, payout) is committed right after it succeeds,
  so its result is never lost;
- a job is deferred only after the commit it depends on;
- the PayPal request ids are always derived from the bounty or claim id, so a
  repeated call after an ambiguous failure replays instead of paying twice.
"""

import hmac
import re
import secrets
from collections.abc import Sequence
from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Literal
from uuid import UUID

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from proofpay.integrations.github.ports import CodeHost, Issue
from proofpay.integrations.llm.ports import LLMUnavailable, StructuredModel
from proofpay.integrations.paypal.ports import PaymentGateway
from proofpay.modules.bounties.application.prompts import (
    CRITERIA_SYSTEM,
    JUDGE_SYSTEM,
    criteria_prompt,
    judge_prompt,
)
from proofpay.modules.bounties.domain.answers import CriteriaAnswer, JudgeAnswer
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
    new_id,
)
from proofpay.modules.bounties.domain.ports import JobQueue
from proofpay.modules.bounties.domain.repositories import BountyRepository
from proofpay.modules.bounties.domain.rules import (
    MAX_DIFF_CHARS,
    check_quotes,
    ci_state,
    hash_funder_key,
    outcome,
    transition,
)
from proofpay.settings import Settings
from proofpay.shared.clock import Clock
from proofpay.shared.errors import (
    ConflictError,
    DomainError,
    ForbiddenError,
    NotFoundError,
    UnprocessableError,
    UpstreamError,
)

log = structlog.get_logger(__name__)

_ISSUE_URL = re.compile(r"https://github\.com/([^/]+)/([^/]+)/issues/([0-9]{1,9})")
_PR_URL = re.compile(r"https://github\.com/([^/]+)/([^/]+)/pull/([0-9]{1,9})")

MIN_BOUNTY_USD = Decimal(1)
_CENT = Decimal("0.01")
MIN_CRITERIA = 1
MAX_CRITERIA = 6
MAX_CRITERION_CHARS = 500
# How long to wait before looking again at a pending CI run or payout.
RECHECK_DELAY = timedelta(seconds=30)
# An authorization that ends within this window is voided before it lapses.
EXPIRY_WINDOW = timedelta(hours=24)

_FAILED_ITEM_STATES = frozenset(
    {"FAILED", "RETURNED", "UNCLAIMED", "BLOCKED", "REFUNDED", "REVERSED"}
)
_FAILED_BATCH_STATES = frozenset({"DENIED", "CANCELED"})
_ACTIVE_CLAIM_STATES = frozenset({ClaimStatus.SUBMITTED, ClaimStatus.NEEDS_HUMAN})


@dataclass(frozen=True, slots=True)
class CreatedBounty:
    """A new bounty and its funder key. The key is shown once and not stored."""

    bounty: Bounty
    funder_key: str


def _failure_code(exc: Exception) -> str:
    """Short machine-readable reason for an event: a domain code or a type."""
    return exc.code if isinstance(exc, DomainError) else type(exc).__name__


class BountyService:
    """Every write scenario of a bounty."""

    def __init__(
        self,
        repo: BountyRepository,
        gateway: PaymentGateway,
        code: CodeHost,
        model: StructuredModel,
        jobs: JobQueue,
        clock: Clock,
        settings: Settings,
        session: AsyncSession,
    ) -> None:
        self._repo = repo
        self._gateway = gateway
        self._code = code
        self._model = model
        self._jobs = jobs
        self._clock = clock
        self._settings = settings
        self._session = session

    # -- creating and funding ---------------------------------------------

    async def create(
        self, issue_url: str, amount: Decimal, done_when: str
    ) -> CreatedBounty:
        """Open a draft bounty on a GitHub issue with AI-drafted criteria."""
        match = _ISSUE_URL.fullmatch(issue_url)
        if match is None:
            raise UnprocessableError(
                code="ISSUE_URL_INVALID",
                detail="Expected https://github.com/<owner>/<repo>/issues/<number>",
            )
        self._check_amount(amount)
        owner, repo, number = match[1], match[2], int(match[3])
        issue = await self._code.issue(owner, repo, number)
        criteria = await self.draft_criteria(issue, done_when)

        funder_key = secrets.token_urlsafe(24)
        bounty = Bounty(
            id=new_id(),
            repo_owner=owner,
            repo_name=repo,
            issue_number=number,
            title=issue.title,
            amount=amount.quantize(_CENT),
            done_when=done_when,
            criteria=tuple(criteria),
            status=BountyStatus.DRAFT,
            funder_key_hash=hash_funder_key(funder_key),
            order_id=None,
            auth_id=None,
            auth_expires_at=None,
            capture_id=None,
            created_at=self._clock.now(),
        )
        await self._repo.add(bounty)
        await self._event(
            bounty.id,
            EventKind.CREATED,
            amount_usd=f"{bounty.amount:.2f}",
            issue_url=issue_url,
        )
        await self._session.commit()
        return CreatedBounty(bounty=bounty, funder_key=funder_key)

    async def draft_criteria(self, issue: Issue, done_when: str) -> list[Criterion]:
        """Ask the model for 2-6 acceptance criteria, numbered c1..cN."""
        try:
            answer = await self._model.ask(
                CRITERIA_SYSTEM,
                criteria_prompt(issue.title, issue.body, done_when),
                CriteriaAnswer,
            )
        except LLMUnavailable as exc:
            raise UpstreamError(
                code="LLM_UNAVAILABLE",
                detail="The AI model could not draft criteria",
            ) from exc
        return [
            Criterion(id=f"c{index}", text=item.text.strip())
            for index, item in enumerate(answer.items, start=1)
        ]

    async def fund(
        self, bounty_id: UUID, key: str, criteria: Sequence[Criterion]
    ) -> str:
        """Fix the criteria and open a PayPal checkout; returns its approve URL.

        Calling it again while the bounty awaits payment opens a new checkout.
        """
        bounty = await self._repo.get_for_update(bounty_id)
        self._check_key(bounty, key)
        items = self._check_criteria(criteria)
        if bounty.status is not BountyStatus.AWAITING_PAYMENT:
            bounty = transition(bounty, BountyStatus.AWAITING_PAYMENT)
        order = await self._gateway.create_order(
            bounty.amount,
            reference_id=str(bounty.id),
            return_url=f"{self._settings.public_url}/paypal/return",
            cancel_url=f"{self._settings.public_url}/paypal/cancel",
            request_id=f"order-{bounty.id}",
        )
        await self._repo.save(replace(bounty, criteria=items, order_id=order.order_id))
        await self._session.commit()
        return order.approve_url

    async def confirm_payment(self, order_id: str) -> UUID:
        """The funder approved the order: authorize it and open the bounty.

        A repeated call for a bounty that is no longer awaiting payment does
        nothing.
        """
        bounty = await self._repo.get_by_order_for_update(order_id)
        if bounty.status is not BountyStatus.AWAITING_PAYMENT:
            return bounty.id
        authorization = await self._gateway.authorize(
            order_id, request_id=f"auth-{bounty.id}"
        )
        bounty = transition(bounty, BountyStatus.FUNDED)
        await self._repo.save(
            replace(
                bounty,
                auth_id=authorization.auth_id,
                auth_expires_at=authorization.expires_at,
            )
        )
        await self._event(
            bounty.id,
            EventKind.FUNDED,
            auth_expires_at=authorization.expires_at.isoformat(),
        )
        await self._session.commit()
        return bounty.id

    async def cancel_payment(self, order_id: str) -> UUID:
        """The funder abandoned the checkout: back to draft. Otherwise a no-op."""
        bounty = await self._repo.get_by_order_for_update(order_id)
        if bounty.status is BountyStatus.AWAITING_PAYMENT:
            await self._repo.save(transition(bounty, BountyStatus.DRAFT))
        await self._session.commit()
        return bounty.id

    # -- claiming and submitting ------------------------------------------

    async def claim(
        self,
        bounty_id: UUID,
        solver_name: str,
        solver_kind: SolverKind,
        paypal_email: str,
    ) -> Claim:
        """A solver announces work on a funded bounty."""
        bounty = await self._repo.get_for_update(bounty_id)
        if bounty.status is not BountyStatus.FUNDED:
            raise ConflictError(
                code="BOUNTY_NOT_OPEN",
                detail="The bounty is not open for claims",
                params={"status": bounty.status.value},
            )
        claim = Claim(
            id=new_id(),
            bounty_id=bounty.id,
            solver_name=solver_name,
            solver_kind=solver_kind,
            paypal_email=paypal_email,
            pr_url=None,
            status=ClaimStatus.OPEN,
            verdict=None,
            payout_batch_id=None,
            created_at=self._clock.now(),
        )
        await self._repo.add_claim(claim)
        await self._event(
            bounty.id,
            EventKind.CLAIMED,
            claim_id=str(claim.id),
            solver_name=solver_name,
            solver_kind=solver_kind.value,
        )
        await self._session.commit()
        return claim

    async def submit(self, claim_id: UUID, pr_url: str) -> Claim:
        """A solver submits a pull request; review is queued."""
        match = _PR_URL.fullmatch(pr_url)
        if match is None:
            raise UnprocessableError(
                code="PR_URL_INVALID",
                detail="Expected https://github.com/<owner>/<repo>/pull/<number>",
            )
        owner, repo, number = match[1], match[2], int(match[3])
        claim, bounty = await self._lock(claim_id)
        if (owner.lower(), repo.lower()) != (
            bounty.repo_owner.lower(),
            bounty.repo_name.lower(),
        ):
            raise UnprocessableError(
                code="PR_WRONG_REPO",
                detail="The pull request is not in the bounty's repository",
            )
        if bounty.status is BountyStatus.IN_REVIEW:
            raise ConflictError(
                code="BOUNTY_IN_REVIEW",
                detail="Another pull request is being reviewed",
            )
        if bounty.status is not BountyStatus.FUNDED:
            raise ConflictError(
                code="BOUNTY_NOT_OPEN",
                detail="The bounty is not open for submissions",
                params={"status": bounty.status.value},
            )
        if claim.status not in {ClaimStatus.OPEN, ClaimStatus.REJECTED}:
            raise ConflictError(
                code="CLAIM_NOT_OPEN",
                detail="The claim cannot take a pull request in its state",
                params={"status": claim.status.value},
            )
        pull = await self._code.pull_request(owner, repo, number)
        if not _links_issue(pull.body, bounty.issue_number):
            raise UnprocessableError(
                code="PR_NOT_LINKED",
                detail=(
                    f"The pull request body must reference the issue "
                    f"(#{bounty.issue_number})"
                ),
            )
        claim = replace(claim, status=ClaimStatus.SUBMITTED, pr_url=pr_url)
        await self._repo.save(transition(bounty, BountyStatus.IN_REVIEW))
        await self._repo.save_claim(claim)
        await self._event(
            bounty.id, EventKind.SUBMITTED, claim_id=str(claim.id), pr_url=pr_url
        )
        await self._session.commit()
        await self._jobs.review(claim.id)
        return claim

    # -- review ------------------------------------------------------------

    async def review(self, claim_id: UUID) -> None:
        """Check CI, have the model judge the diff, verify its quotes, act."""
        claim, bounty = await self._lock(claim_id)
        if (
            claim.status is not ClaimStatus.SUBMITTED
            or bounty.status is not BountyStatus.IN_REVIEW
            or claim.pr_url is None
        ):
            await self._session.commit()  # stale job: release the lock
            return
        match = _PR_URL.fullmatch(claim.pr_url)
        if match is None:  # cannot happen: submit validated the URL
            await self._to_needs_human(bounty, claim, "pull request url invalid")
            return
        owner, repo, number = match[1], match[2], int(match[3])

        try:
            pull = await self._code.pull_request(owner, repo, number)
            ci = ci_state(await self._code.checks(owner, repo, pull.head_sha))
            if ci is CiState.PENDING:
                await self._session.commit()
                await self._jobs.review(claim.id, delay=RECHECK_DELAY)
                return
            await self._event(
                bounty.id,
                EventKind.CI,
                claim_id=str(claim.id),
                state=ci.value,
                head_sha=pull.head_sha,
            )
            diff = await self._code.diff(owner, repo, number)
        except (NotFoundError, UpstreamError) as exc:
            await self._to_needs_human(
                bounty, claim, f"github error: {_failure_code(exc)}"
            )
            return

        if len(diff) > MAX_DIFF_CHARS:
            await self._to_needs_human(bounty, claim, "diff too large")
            return
        try:
            answer = await self._model.ask(
                JUDGE_SYSTEM,
                judge_prompt(bounty.title, bounty.done_when, bounty.criteria, diff),
                JudgeAnswer,
            )
        except LLMUnavailable:
            await self._to_needs_human(bounty, claim, "llm unavailable")
            return

        items = check_quotes(bounty.criteria, answer, diff)
        result = outcome(items, ci)
        claim = replace(claim, verdict=Verdict(outcome=result, items=items, ci=ci))
        await self._repo.save_claim(claim)
        states = [item.state for item in items]
        await self._event(
            bounty.id,
            EventKind.VERDICT,
            claim_id=str(claim.id),
            outcome=result.value,
            met=states.count("met"),
            not_met=states.count("not_met"),
            unverified=states.count("unverified"),
        )
        if result is Outcome.PASS:
            await self._session.commit()
            await self.release(claim.id)
        elif result is Outcome.FAIL:
            reason = "ci not green" if ci is not CiState.GREEN else "criteria not met"
            await self._reject(bounty, claim, reason)
        else:
            await self._to_needs_human(bounty, claim, "quotes could not be verified")

    # -- money -------------------------------------------------------------

    async def release(self, claim_id: UUID) -> None:
        """Capture the authorization and send the payout. Safe to repeat.

        A repeated call never captures or pays a second time: each PayPal
        call carries the same request id every time, and a payout already
        sent is left to `poll_payout`.
        """
        claim, bounty = await self._lock(claim_id)
        if bounty.status is BountyStatus.PAID:
            await self._session.commit()
            return
        if bounty.status is BountyStatus.RELEASED and claim.payout_batch_id:
            await self._session.commit()  # payout in flight, poll_payout owns it
            return
        if bounty.status not in {
            BountyStatus.IN_REVIEW,
            BountyStatus.NEEDS_HUMAN,
            BountyStatus.RELEASED,
        }:
            raise ConflictError(
                code="INVALID_TRANSITION",
                detail=f"bounty cannot be released from {bounty.status}",
                params={"from": bounty.status.value, "to": BountyStatus.RELEASED.value},
            )

        if bounty.capture_id is None:
            if bounty.auth_id is None:
                raise ConflictError(
                    code="NOT_AUTHORIZED", detail="The bounty has no authorization"
                )
            try:
                capture_id = await self._gateway.capture(
                    bounty.auth_id, request_id=f"capture-{bounty.id}"
                )
            except Exception as exc:
                log.warning("capture_failed", bounty_id=str(bounty.id), error=repr(exc))
                await self._to_needs_human(
                    bounty, claim, f"capture failed: {_failure_code(exc)}"
                )
                return
            bounty = replace(bounty, capture_id=capture_id)
            if bounty.status is not BountyStatus.RELEASED:
                bounty = transition(bounty, BountyStatus.RELEASED)
            await self._repo.save(bounty)
            await self._event(bounty.id, EventKind.CAPTURED, capture_id=capture_id)
            await self._session.commit()
            claim, bounty = await self._lock(claim_id)
        elif bounty.status is BountyStatus.NEEDS_HUMAN:
            # Captured earlier and the payout went wrong: resume.
            await self._repo.save(transition(bounty, BountyStatus.RELEASED))
            await self._session.commit()
            if claim.payout_batch_id:
                # The payout exists at PayPal: look at it again, never resend.
                await self._jobs.poll_payout(claim.id, delay=RECHECK_DELAY)
                return
            claim, bounty = await self._lock(claim_id)

        if bounty.status is not BountyStatus.RELEASED or claim.payout_batch_id:
            await self._session.commit()  # someone else got here first
            return
        try:
            batch_id = await self._gateway.payout(
                claim.paypal_email,
                bounty.amount,
                sender_batch_id=f"payout-{claim.id}",
                note=(
                    f"ProofPay bounty {bounty.repo_owner}/{bounty.repo_name}"
                    f"#{bounty.issue_number}"
                ),
                request_id=f"payout-{claim.id}",
            )
        except Exception as exc:
            log.warning("payout_failed", claim_id=str(claim.id), error=repr(exc))
            await self._repo.save(transition(bounty, BountyStatus.NEEDS_HUMAN))
            await self._event(
                bounty.id,
                EventKind.PAYOUT_FAILED,
                claim_id=str(claim.id),
                reason=_failure_code(exc),
            )
            await self._session.commit()
            return
        await self._repo.save_claim(replace(claim, payout_batch_id=batch_id))
        await self._event(
            bounty.id,
            EventKind.PAYOUT_SENT,
            claim_id=str(claim.id),
            batch_id=batch_id,
        )
        await self._session.commit()
        await self._jobs.poll_payout(claim.id, delay=RECHECK_DELAY)

    async def poll_payout(self, claim_id: UUID) -> None:
        """Look at the payout once; finish, park for a human, or look again."""
        claim, bounty = await self._lock(claim_id)
        if bounty.status is not BountyStatus.RELEASED or claim.payout_batch_id is None:
            await self._session.commit()
            return
        batch_id = claim.payout_batch_id
        try:
            status = await self._gateway.payout_status(batch_id)
        except UpstreamError as exc:
            # The payout was sent: a failed look is not a failed payout.
            log.warning("payout_status_failed", claim_id=str(claim.id), code=exc.code)
            await self._session.commit()
            await self._jobs.poll_payout(claim.id, delay=RECHECK_DELAY)
            return

        if status.item_status == "SUCCESS":
            await self._repo.save(transition(bounty, BountyStatus.PAID))
            await self._repo.save_claim(replace(claim, status=ClaimStatus.ACCEPTED))
            await self._event(
                bounty.id,
                EventKind.PAID,
                claim_id=str(claim.id),
                batch_id=batch_id,
            )
            await self._session.commit()
        elif (
            status.item_status in _FAILED_ITEM_STATES
            or status.batch_status in _FAILED_BATCH_STATES
        ):
            reason = status.item_status or status.batch_status
            await self._repo.save(transition(bounty, BountyStatus.NEEDS_HUMAN))
            await self._repo.save_claim(replace(claim, status=ClaimStatus.NEEDS_HUMAN))
            await self._event(
                bounty.id,
                EventKind.PAYOUT_FAILED,
                claim_id=str(claim.id),
                reason=reason,
            )
            await self._session.commit()
        else:
            await self._session.commit()
            await self._jobs.poll_payout(claim.id, delay=RECHECK_DELAY)

    # -- funder decisions --------------------------------------------------

    async def decide(
        self, bounty_id: UUID, key: str, decision: Literal["release", "reject"]
    ) -> None:
        """The funder settles a bounty that the judge could not."""
        bounty = await self._repo.get_for_update(bounty_id)
        self._check_key(bounty, key)
        if bounty.status is not BountyStatus.NEEDS_HUMAN:
            raise ConflictError(
                code="NOT_AWAITING_DECISION",
                detail="The bounty is not waiting for a decision",
                params={"status": bounty.status.value},
            )
        claims = await self._repo.claims_of(bounty_id)
        active = next(
            (
                claim
                for claim in reversed(claims)
                if claim.status in _ACTIVE_CLAIM_STATES
            ),
            None,
        )
        if active is None:
            raise ConflictError(
                code="NO_ACTIVE_CLAIM", detail="There is no claim to decide on"
            )
        if decision == "release":
            await self.release(active.id)
            return
        if bounty.capture_id is not None:
            raise ConflictError(
                code="ALREADY_CAPTURED",
                detail="The money was already captured; it cannot be rejected",
            )
        await self._reject(bounty, active, "rejected by funder")

    async def cancel(self, bounty_id: UUID, key: str) -> None:
        """The funder withdraws an unclaimed or parked bounty; money is voided."""
        bounty = await self._repo.get_for_update(bounty_id)
        self._check_key(bounty, key)
        cancelled = transition(bounty, BountyStatus.CANCELLED)
        if bounty.status in {BountyStatus.FUNDED, BountyStatus.NEEDS_HUMAN}:
            if bounty.capture_id is not None:
                raise ConflictError(
                    code="ALREADY_CAPTURED",
                    detail="The money was already captured; it cannot be voided",
                )
            if bounty.auth_id is None:
                raise ConflictError(
                    code="NOT_AUTHORIZED", detail="The bounty has no authorization"
                )
            await self._gateway.void(bounty.auth_id, request_id=f"void-{bounty.id}")
        await self._repo.save(cancelled)
        await self._event(bounty.id, EventKind.CANCELLED)
        await self._session.commit()

    async def expire_due(self) -> None:
        """Void authorizations that end within a day, so the hold never lapses."""
        threshold = self._clock.now() + EXPIRY_WINDOW
        for due in await self._repo.list_expiring(threshold):
            try:
                await self._expire(due.id, threshold)
            except UpstreamError as exc:
                await self._session.rollback()
                log.warning("expire_failed", bounty_id=str(due.id), code=exc.code)

    async def _expire(self, bounty_id: UUID, threshold: datetime) -> None:
        bounty = await self._repo.get_for_update(bounty_id)
        if (
            bounty.status not in {BountyStatus.FUNDED, BountyStatus.IN_REVIEW}
            or bounty.auth_id is None
            or bounty.auth_expires_at is None
            or bounty.auth_expires_at >= threshold
        ):
            await self._session.commit()
            return
        await self._gateway.void(bounty.auth_id, request_id=f"void-{bounty.id}")
        await self._repo.save(transition(bounty, BountyStatus.EXPIRED))
        await self._event(bounty.id, EventKind.EXPIRED)
        await self._session.commit()

    # -- helpers -----------------------------------------------------------

    async def _lock(self, claim_id: UUID) -> tuple[Claim, Bounty]:
        """Lock the bounty of a claim; return both as they are after the lock."""
        claim = await self._repo.get_claim(claim_id)
        bounty = await self._repo.get_for_update(claim.bounty_id)
        return await self._repo.get_claim(claim_id), bounty

    async def _event(
        self, bounty_id: UUID, kind: EventKind, **detail: str | int
    ) -> None:
        await self._repo.add_event(
            Event(bounty_id=bounty_id, at=self._clock.now(), kind=kind, detail=detail)
        )

    async def _to_needs_human(self, bounty: Bounty, claim: Claim, reason: str) -> None:
        """Park the claim and the bounty for the funder to decide; commit."""
        if bounty.status is not BountyStatus.NEEDS_HUMAN:
            bounty = transition(bounty, BountyStatus.NEEDS_HUMAN)
        await self._repo.save(bounty)
        await self._repo.save_claim(replace(claim, status=ClaimStatus.NEEDS_HUMAN))
        await self._event(
            bounty.id, EventKind.NEEDS_HUMAN, claim_id=str(claim.id), reason=reason
        )
        await self._session.commit()

    async def _reject(self, bounty: Bounty, claim: Claim, reason: str) -> None:
        """Turn the claim down and open the bounty for other attempts; commit."""
        await self._repo.save(transition(bounty, BountyStatus.FUNDED))
        await self._repo.save_claim(replace(claim, status=ClaimStatus.REJECTED))
        await self._event(
            bounty.id, EventKind.REJECTED, claim_id=str(claim.id), reason=reason
        )
        await self._session.commit()

    @staticmethod
    def _check_key(bounty: Bounty, key: str) -> None:
        if not hmac.compare_digest(hash_funder_key(key), bounty.funder_key_hash):
            raise ForbiddenError(
                code="FUNDER_KEY_INVALID", detail="The funder key does not match"
            )

    def _check_amount(self, amount: Decimal) -> None:
        in_range = (
            amount.is_finite()
            and MIN_BOUNTY_USD <= amount <= self._settings.max_bounty_usd
            and amount == amount.quantize(_CENT)
        )
        if not in_range:
            raise UnprocessableError(
                code="AMOUNT_OUT_OF_RANGE",
                detail=(
                    f"The amount must be between {MIN_BOUNTY_USD} and "
                    f"{self._settings.max_bounty_usd} USD with at most 2 decimals"
                ),
            )

    @staticmethod
    def _check_criteria(criteria: Sequence[Criterion]) -> tuple[Criterion, ...]:
        items = tuple(
            Criterion(id=item.id.strip(), text=item.text.strip()) for item in criteria
        )
        ids = {item.id for item in items}
        valid = (
            MIN_CRITERIA <= len(items) <= MAX_CRITERIA
            and len(ids) == len(items)
            and all(
                item.id and item.text and len(item.text) <= MAX_CRITERION_CHARS
                for item in items
            )
        )
        if not valid:
            raise UnprocessableError(
                code="CRITERIA_INVALID",
                detail=(
                    f"Give {MIN_CRITERIA}-{MAX_CRITERIA} criteria with unique ids "
                    f"and texts of 1-{MAX_CRITERION_CHARS} characters"
                ),
            )
        return items


def _links_issue(body: str, number: int) -> bool:
    """Whether a pull request body references issue `number`.

    `#12` must not count for issue 1, and `foo#1` is not a reference.
    """
    pattern = rf"(?<!\w)#{number}(?![0-9])|issues/{number}(?![0-9])"
    return re.search(pattern, body) is not None
