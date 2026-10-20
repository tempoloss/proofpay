"""Router of the bounties module.

The PayPal return pages live outside `/api/v1`: PayPal sends the browser to
`{public_url}/paypal/...`, the same origin as the web app.
"""

from litestar import Router

from proofpay.modules.bounties.presentation.routes import (
    cancel_bounty,
    claim_bounty,
    create_bounty,
    decide_bounty,
    fund_bounty,
    get_bounty,
    list_bounties,
    paypal_cancel,
    paypal_return,
    submit_claim,
)

api_router = Router(
    path="/api/v1",
    route_handlers=[
        list_bounties,
        get_bounty,
        create_bounty,
        fund_bounty,
        claim_bounty,
        submit_claim,
        decide_bounty,
        cancel_bounty,
    ],
)

paypal_router = Router(path="/paypal", route_handlers=[paypal_return, paypal_cancel])

router = Router(path="/", route_handlers=[api_router, paypal_router])
