"""Stand-ins for the external services of the bounties module.

PayPal, GitHub, the language model and the job queue are replaced through a
Dishka provider declared last, the same way the production container is built:
the scenarios run through the ports, with real PostgreSQL underneath.

Every fake records its calls so a test can state exactly what was sent where,
and the money tests lean on that: how many captures, which request ids.
"""

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from types import TracebackType
from typing import Any
from uuid import UUID

from dishka import AsyncContainer, Provider, Scope, provide
from pydantic import BaseModel

from proofpay.integrations.github.ports import (
    CheckRun,
    CodeHost,
    Issue,
    PullRequest,
)
from proofpay.integrations.llm.ports import LLMUnavailable, StructuredModel
from proofpay.integrations.paypal.ports import (
    Authorization,
    CreatedOrder,
    PaymentGateway,
    PayoutStatus,
)
from proofpay.modules.bounties.application.queries import (
    BountyCard,
    BountyQueries,
    BountyView,
)
from proofpay.modules.bounties.application.service import BountyService, CreatedBounty
from proofpay.modules.bounties.domain.answers import (
    CriteriaAnswer,
    CriterionIn,
    JudgeAnswer,
    JudgeItem,
)
from proofpay.modules.bounties.domain.entities import (
    Bounty,
    Claim,
    Criterion,
    SolverKind,
)
from proofpay.modules.bounties.domain.ports import JobQueue
from proofpay.shared.clock import Clock

NOW = datetime(2026, 10, 25, 12, 0, tzinfo=UTC)

OWNER = "acme"
REPO = "tinycalc"
ISSUE_URL = f"https://github.com/{OWNER}/{REPO}/issues/1"
PR_URL = f"https://github.com/{OWNER}/{REPO}/pull/7"
SOLVER_EMAIL = "solver@example.com"

SOURCE_FILE = "src/tinycalc/__init__.py"
TEST_FILE = "tests/test_tinycalc.py"
SOURCE_QUOTE = "return None"
TEST_QUOTE = "assert divide(1, 0) is None"

# A pull request that fixes `divide` and adds a test. The removed line is
# `return a / b`; the lines the judge may quote are the added ones.
DIFF = "\n".join(
    [
        f"diff --git a/{SOURCE_FILE} b/{SOURCE_FILE}",
        "index 1111111..2222222 100644",
        f"--- a/{SOURCE_FILE}",
        f"+++ b/{SOURCE_FILE}",
        "@@ -1,9 +1,11 @@",
        ' """Tiny calculator."""',
        " ",
        " ",
        " def add(a: float, b: float) -> float:",
        "     return a + b",
        " ",
        " ",
        " def divide(a: float, b: float) -> float | None:",
        "-    return a / b",
        "+    if b == 0:",
        "+        return None",
        "+    return a / b",
        f"diff --git a/{TEST_FILE} b/{TEST_FILE}",
        "new file mode 100644",
        "index 0000000..3333333",
        "--- /dev/null",
        f"+++ b/{TEST_FILE}",
        "@@ -0,0 +1,9 @@",
        "+from tinycalc import divide",
        "+",
        "+",
        "+def test_divide_by_zero_returns_none():",
        f"+    {TEST_QUOTE}",
        "+",
        "+",
        "+def test_divide_regular():",
        "+    assert divide(6, 3) == 2",
        "",
    ]
)


def confirming_judge() -> JudgeAnswer:
    """A judge answer that confirms both default criteria with real quotes."""
    return JudgeAnswer(
        items=[
            JudgeItem(
                criterion_id="c1",
                met=True,
                quote=SOURCE_QUOTE,
                file=SOURCE_FILE,
                reason="divide returns None for a zero divisor",
            ),
            JudgeItem(
                criterion_id="c2",
                met=True,
                quote=TEST_QUOTE,
                file=TEST_FILE,
                reason="a test calls divide(1, 0)",
            ),
        ]
    )


def drafted_criteria() -> CriteriaAnswer:
    return CriteriaAnswer(
        items=[
            CriterionIn(text="divide returns None when the divisor is zero"),
            CriterionIn(text="a test covers dividing by zero"),
        ]
    )


@dataclass(frozen=True, slots=True)
class Call:
    """One call to a fake: the method, its request id and its arguments."""

    method: str
    request_id: str | None
    args: dict[str, Any]


class FakeClock:
    """A clock the test moves by hand."""

    def __init__(self) -> None:
        self.current = NOW

    def now(self) -> datetime:
        return self.current


class FakePaymentGateway:
    """Records every call; PayPal failures are injected per method."""

    def __init__(self) -> None:
        self.calls: list[Call] = []
        self.fail: dict[str, Exception] = {}
        self.payout_statuses = [
            PayoutStatus(batch_status="SUCCESS", item_status="SUCCESS")
        ]
        self.auth_expires_at = NOW + timedelta(days=29)

    def calls_of(self, method: str) -> list[Call]:
        return [call for call in self.calls if call.method == method]

    def _record(self, method: str, request_id: str | None, **args: Any) -> None:
        self.calls.append(Call(method, request_id, args))
        if method in self.fail:
            raise self.fail[method]

    async def create_order(
        self,
        amount: Decimal,
        reference_id: str,
        return_url: str,
        cancel_url: str,
        *,
        request_id: str,
    ) -> CreatedOrder:
        self._record(
            "create_order",
            request_id,
            amount=amount,
            reference_id=reference_id,
            return_url=return_url,
            cancel_url=cancel_url,
        )
        return CreatedOrder(
            order_id=f"ORDER-{reference_id}",
            approve_url=f"https://paypal.test/approve/{reference_id}",
        )

    async def authorize(self, order_id: str, *, request_id: str) -> Authorization:
        self._record("authorize", request_id, order_id=order_id)
        return Authorization(
            auth_id=f"AUTH-{order_id}", expires_at=self.auth_expires_at
        )

    async def capture(self, auth_id: str, *, request_id: str) -> str:
        self._record("capture", request_id, auth_id=auth_id)
        return f"CAPTURE-{auth_id}"

    async def void(self, auth_id: str, *, request_id: str) -> None:
        self._record("void", request_id, auth_id=auth_id)

    async def payout(
        self,
        email: str,
        amount: Decimal,
        sender_batch_id: str,
        note: str,
        *,
        request_id: str,
    ) -> str:
        self._record(
            "payout",
            request_id,
            email=email,
            amount=amount,
            sender_batch_id=sender_batch_id,
            note=note,
        )
        return f"BATCH-{sender_batch_id}"

    async def payout_status(self, batch_id: str) -> PayoutStatus:
        self._record("payout_status", None, batch_id=batch_id)
        if len(self.payout_statuses) > 1:
            return self.payout_statuses.pop(0)
        return self.payout_statuses[0]


class FakeCodeHost:
    """A GitHub with one issue and one pull request, tuned by the test."""

    def __init__(self) -> None:
        self.pr_body = "Fixes #1"
        self.head_sha = "a" * 40
        self.check_runs = [
            CheckRun(name="pytest", status="completed", conclusion="success")
        ]
        self.diff_text = DIFF
        self.fail: dict[str, Exception] = {}
        self.calls: list[str] = []

    def _record(self, method: str) -> None:
        self.calls.append(method)
        if method in self.fail:
            raise self.fail[method]

    async def issue(self, owner: str, repo: str, number: int) -> Issue:
        self._record("issue")
        return Issue(
            title="divide() raises ZeroDivisionError",
            body="Dividing by zero crashes the caller.",
            html_url=f"https://github.com/{owner}/{repo}/issues/{number}",
        )

    async def pull_request(self, owner: str, repo: str, number: int) -> PullRequest:
        self._record("pull_request")
        return PullRequest(
            title="Handle division by zero",
            body=self.pr_body,
            head_sha=self.head_sha,
            state="open",
            html_url=f"https://github.com/{owner}/{repo}/pull/{number}",
        )

    async def checks(self, owner: str, repo: str, sha: str) -> list[CheckRun]:
        self._record("checks")
        return list(self.check_runs)

    async def diff(self, owner: str, repo: str, number: int) -> str:
        self._record("diff")
        return self.diff_text


class FakeModel:
    """Returns queued answers per schema; a queued exception is raised."""

    def __init__(self) -> None:
        self.queues: dict[type[BaseModel], list[BaseModel | Exception]] = {}
        self.asked: list[tuple[str, str, type[BaseModel]]] = []

    def queue(self, answer: BaseModel) -> None:
        self.queues.setdefault(type(answer), []).append(answer)

    def queue_error_for(self, schema: type[BaseModel]) -> None:
        self.queues.setdefault(schema, []).append(LLMUnavailable("no answer"))

    def asked_for(self, schema: type[BaseModel]) -> list[str]:
        return [prompt for _, prompt, asked in self.asked if asked is schema]

    async def ask[T: BaseModel](self, system: str, prompt: str, schema: type[T]) -> T:
        self.asked.append((system, prompt, schema))
        queue = self.queues.get(schema)
        if not queue:
            raise AssertionError(f"no answer queued for {schema.__name__}")
        answer = queue.pop(0)
        if isinstance(answer, Exception):
            raise answer
        assert isinstance(answer, schema)
        return answer


class FakeJobQueue:
    """Records what would have been scheduled; nothing runs."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, UUID, timedelta | None]] = []

    async def review(self, claim_id: UUID, *, delay: timedelta | None = None) -> None:
        self.calls.append(("review", claim_id, delay))

    async def poll_payout(
        self, claim_id: UUID, *, delay: timedelta | None = None
    ) -> None:
        self.calls.append(("poll_payout", claim_id, delay))


@dataclass
class FakeServices:
    """The fakes of one test, reachable by reference."""

    clock: FakeClock = field(default_factory=FakeClock)
    gateway: FakePaymentGateway = field(default_factory=FakePaymentGateway)
    code: FakeCodeHost = field(default_factory=FakeCodeHost)
    model: FakeModel = field(default_factory=FakeModel)
    jobs: FakeJobQueue = field(default_factory=FakeJobQueue)


class FakeServicesProvider(Provider):
    """Declared last: overrides the production bindings of the same ports."""

    def __init__(self, services: FakeServices) -> None:
        super().__init__()
        self._services = services

    @provide(scope=Scope.APP)
    def clock(self) -> Clock:
        return self._services.clock

    @provide(scope=Scope.APP)
    def gateway(self) -> PaymentGateway:
        return self._services.gateway

    @provide(scope=Scope.APP)
    def code(self) -> CodeHost:
        return self._services.code

    @provide(scope=Scope.APP)
    def model(self) -> StructuredModel:
        return self._services.model

    @provide(scope=Scope.APP)
    def jobs(self) -> JobQueue:
        return self._services.jobs


@dataclass(frozen=True, slots=True)
class Opened:
    """A funded bounty and the funder's key."""

    bounty: Bounty
    key: str


class ServiceScope:
    """`async with` over one request scope; yields a BountyService.

    Written by hand rather than with contextlib.asynccontextmanager: that one
    re-assigns `__traceback__` on the exception passing through, which a frozen
    DomainError dataclass refuses.
    """

    def __init__(self, container: AsyncContainer) -> None:
        self._scope = container()

    async def __aenter__(self) -> BountyService:
        scope = await self._scope.__aenter__()
        return await scope.get(BountyService)

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        await self._scope.__aexit__(exc_type, exc, traceback)


class Flow:
    """Drives scenarios the way requests and jobs do: one scope per step."""

    def __init__(self, container: AsyncContainer, services: FakeServices) -> None:
        self.container = container
        self.services = services

    def service(self) -> ServiceScope:
        """A fresh request scope: its own session, like a separate request."""
        return ServiceScope(self.container)

    async def page(self, bounty_id: UUID) -> BountyView:
        async with self.container() as scope:
            queries = await scope.get(BountyQueries)
            return await queries.bounty_page(bounty_id)

    async def listed(self) -> list[BountyCard]:
        async with self.container() as scope:
            queries = await scope.get(BountyQueries)
            return await queries.list_bounties()

    async def draft(self, amount: str = "25.00") -> CreatedBounty:
        self.services.model.queue(drafted_criteria())
        async with self.service() as service:
            return await service.create(
                ISSUE_URL, Decimal(amount), "divide(a, 0) is None"
            )

    async def awaiting_payment(self, amount: str = "25.00") -> Opened:
        created = await self.draft(amount)
        async with self.service() as service:
            await service.fund(
                created.bounty.id,
                created.funder_key,
                [
                    Criterion(id="c1", text="divide returns None on zero"),
                    Criterion(id="c2", text="a test covers dividing by zero"),
                ],
            )
        return Opened(created.bounty, created.funder_key)

    async def funded(self, amount: str = "25.00") -> Opened:
        opened = await self.awaiting_payment(amount)
        async with self.service() as service:
            await service.confirm_payment(f"ORDER-{opened.bounty.id}")
        return opened

    async def claim(self, opened: Opened) -> Claim:
        async with self.service() as service:
            return await service.claim(
                opened.bounty.id, "agent-7", SolverKind.AGENT, SOLVER_EMAIL
            )

    async def submitted(self, opened: Opened) -> Claim:
        claim = await self.claim(opened)
        async with self.service() as service:
            return await service.submit(claim.id, PR_URL)

    def kinds(self, view: BountyView) -> list[str]:
        return [event.kind for event in view.events]
