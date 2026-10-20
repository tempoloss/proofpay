"""Router of the bounties module."""

from litestar import Router

from proofpay.modules.bounties.presentation.routes import get_bounty, list_bounties

router = Router(path="/api/v1", route_handlers=[list_bounties, get_bounty])
