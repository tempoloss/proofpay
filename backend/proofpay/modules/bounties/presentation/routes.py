"""Read routes of the bounties API."""

from typing import Annotated
from uuid import UUID

from dishka import FromDishka
from dishka.integrations.litestar import inject
from litestar import get
from litestar.params import Parameter

from proofpay.modules.bounties.application.queries import BountyQueries
from proofpay.modules.bounties.presentation.schemas import (
    BountyCardOut,
    BountyViewOut,
)


@get(
    "/bounties",
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
) -> list[BountyCardOut]:
    return [BountyCardOut.from_view(card) for card in await queries.list_bounties()]


@get(
    "/bounties/{bounty_id:uuid}",
    tags=["bounties"],
    summary="Get a bounty page",
    description=(
        "A bounty with its acceptance criteria, claims, the verdict of the "
        "newest reviewed claim and the audit log."
    ),
)
@inject
async def get_bounty(
    bounty_id: Annotated[UUID, Parameter(description="Bounty id")],
    queries: FromDishka[BountyQueries],
) -> BountyViewOut:
    return BountyViewOut.from_page(await queries.bounty_page(bounty_id))
