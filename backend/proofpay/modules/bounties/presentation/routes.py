"""Routes of the bounties API: reads, writes and the PayPal return pages."""

from typing import Annotated
from uuid import UUID

from dishka import FromDishka
from dishka.integrations.litestar import inject
from litestar import get, post
from litestar.params import HeaderParameter, JSONBody, Parameter, QueryParameter
from litestar.response import Redirect

from proofpay.modules.bounties.application.commands import BountyCommands
from proofpay.modules.bounties.application.queries import BountyQueries
from proofpay.modules.bounties.presentation.schemas import (
    ApproveLink,
    BountyCard,
    BountyPage,
    ClaimRequest,
    ClaimView,
    CreateBountyRequest,
    CreatedBounty,
    DecideRequest,
    FundRequest,
    SubmitRequest,
)

FunderKey = Annotated[
    str,
    HeaderParameter(
        name="X-Funder-Key",
        min_length=1,
        description=(
            "The funder key returned when the bounty was created. "
            "A wrong key is answered with 403 FUNDER_KEY_INVALID."
        ),
    ),
]
BountyId = Annotated[UUID, Parameter(description="Bounty id")]
OrderToken = Annotated[
    str,
    QueryParameter(
        min_length=1,
        description="PayPal order id; PayPal sends it as `token`",
    ),
]


# -- reads -----------------------------------------------------------------


@get(
    "/bounties",
    operation_id="listBounties",
    tags=["bounties"],
    summary="List bounties",
    description=(
        "Bounties that are past the draft and payment stages, newest first. "
        "Includes finished ones (paid, cancelled, expired)."
    ),
)
@inject
async def list_bounties(
    queries: FromDishka[BountyQueries],
) -> list[BountyCard]:
    return [BountyCard.from_view(card) for card in await queries.list_bounties()]


@get(
    "/bounties/{bounty_id:uuid}",
    operation_id="getBounty",
    tags=["bounties"],
    summary="Get a bounty page",
    description=(
        "A bounty with its acceptance criteria, claims, the verdict of the "
        "newest reviewed claim and the audit log."
    ),
)
@inject
async def get_bounty(
    bounty_id: BountyId,
    queries: FromDishka[BountyQueries],
) -> BountyPage:
    return BountyPage.from_page(await queries.bounty_page(bounty_id))


# -- funder -----------------------------------------------------------------


@post(
    "/bounties",
    operation_id="createBounty",
    tags=["bounties"],
    summary="Create a draft bounty",
    description=(
        "Reads the GitHub issue and drafts acceptance criteria with the AI "
        "model. Returns the draft page and the funder key, which is shown "
        "only once: keep it, every later funder action needs it."
    ),
)
@inject
async def create_bounty(
    data: JSONBody[CreateBountyRequest],
    commands: FromDishka[BountyCommands],
) -> CreatedBounty:
    created = await commands.create(data.issue_url, data.amount_usd, data.done_when)
    return CreatedBounty.from_view(created)


@post(
    "/bounties/{bounty_id:uuid}/fund",
    operation_id="fundBounty",
    status_code=200,
    tags=["bounties"],
    summary="Fix the criteria and open PayPal checkout",
    description=(
        "Stores the final criteria and creates a PayPal order that only "
        "authorizes the amount. Send the funder to `approve_url`; the money "
        "is held, not taken, until the work is verified."
    ),
)
@inject
async def fund_bounty(
    bounty_id: BountyId,
    funder_key: FunderKey,
    data: JSONBody[FundRequest],
    commands: FromDishka[BountyCommands],
) -> ApproveLink:
    url = await commands.fund(bounty_id, funder_key, data.to_inputs())
    return ApproveLink(approve_url=url)


@post(
    "/bounties/{bounty_id:uuid}/decide",
    operation_id="decideBounty",
    status_code=200,
    tags=["bounties"],
    summary="Settle a bounty the judge could not decide",
    description=(
        "Only for a bounty in `needs_human`: `release` pays the solver, "
        "`reject` turns the claim down and reopens the bounty."
    ),
)
@inject
async def decide_bounty(
    bounty_id: BountyId,
    funder_key: FunderKey,
    data: JSONBody[DecideRequest],
    commands: FromDishka[BountyCommands],
) -> BountyPage:
    page = await commands.decide(bounty_id, funder_key, data.decision)
    return BountyPage.from_page(page)


@post(
    "/bounties/{bounty_id:uuid}/cancel",
    operation_id="cancelBounty",
    status_code=200,
    tags=["bounties"],
    summary="Cancel a bounty",
    description=(
        "Withdraws a bounty that is not in review. A held authorization is "
        "voided, so the funder is not charged."
    ),
)
@inject
async def cancel_bounty(
    bounty_id: BountyId,
    funder_key: FunderKey,
    commands: FromDishka[BountyCommands],
) -> BountyPage:
    return BountyPage.from_page(await commands.cancel(bounty_id, funder_key))


# -- solver -----------------------------------------------------------------


@post(
    "/bounties/{bounty_id:uuid}/claims",
    operation_id="claimBounty",
    tags=["claims"],
    summary="Claim a funded bounty",
    description=(
        "A person or an AI agent announces work on a funded bounty. The PayPal "
        "e-mail is kept private and used only for the payout."
    ),
)
@inject
async def claim_bounty(
    bounty_id: BountyId,
    data: JSONBody[ClaimRequest],
    commands: FromDishka[BountyCommands],
) -> ClaimView:
    claim = await commands.claim(
        bounty_id, data.solver_name, data.solver_kind, data.paypal_email
    )
    return ClaimView.from_view(claim)


@post(
    "/claims/{claim_id:uuid}/submit",
    operation_id="submitClaim",
    status_code=200,
    tags=["claims"],
    summary="Submit a pull request for review",
    description=(
        "The pull request must be in the bounty's repository and mention the "
        "issue (`#<number>`). Review starts at once: CI first, then the AI "
        "judge; the verdict appears on the bounty page."
    ),
)
@inject
async def submit_claim(
    claim_id: Annotated[UUID, Parameter(description="Claim id")],
    data: JSONBody[SubmitRequest],
    commands: FromDishka[BountyCommands],
) -> ClaimView:
    return ClaimView.from_view(await commands.submit(claim_id, data.pr_url))


# -- PayPal return pages -------------------------------------------------------


@get(
    "/return",
    operation_id="paypalReturn",
    status_code=302,
    tags=["paypal"],
    summary="PayPal approval return",
    description=(
        "PayPal sends the funder's browser here after approval. Authorizes "
        "the order, which opens the bounty, and redirects to its page. "
        "Repeating the request is harmless."
    ),
)
@inject
async def paypal_return(
    token: OrderToken,
    commands: FromDishka[BountyCommands],
) -> Redirect:
    bounty_id = await commands.confirm_payment(token)
    return Redirect(path=f"/b/{bounty_id}")


@get(
    "/cancel",
    operation_id="paypalCancel",
    status_code=302,
    tags=["paypal"],
    summary="PayPal approval cancelled",
    description=(
        "PayPal sends the funder's browser here when they leave checkout. "
        "The bounty goes back to draft and the browser to its page."
    ),
)
@inject
async def paypal_cancel(
    token: OrderToken,
    commands: FromDishka[BountyCommands],
) -> Redirect:
    bounty_id = await commands.cancel_payment(token)
    return Redirect(path=f"/b/{bounty_id}")
