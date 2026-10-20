"""PayPal client against a mocked transport: no network, no credentials."""

import base64
import json
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import httpx
import pytest
from pydantic import SecretStr

from proofpay.integrations.paypal.client import PayPalClient
from proofpay.settings import Settings
from proofpay.shared.errors import UpstreamError

NOW = datetime(2026, 10, 20, 12, 0, tzinfo=UTC)
TOKEN_BODY = {"access_token": "tok-1", "token_type": "Bearer", "expires_in": 3600}


class FakeClock:
    def __init__(self) -> None:
        self.current = NOW

    def now(self) -> datetime:
        return self.current


class PayPalStub:
    """Records requests and answers by path; unknown paths fail the test."""

    def __init__(self, routes: dict[str, httpx.Response] | None = None) -> None:
        self.routes = routes or {}
        self.requests: list[httpx.Request] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if request.url.path == "/v1/oauth2/token":
            return httpx.Response(200, json=TOKEN_BODY)
        return self.routes[request.url.path]

    def api_requests(self) -> list[httpx.Request]:
        return [r for r in self.requests if r.url.path != "/v1/oauth2/token"]

    def token_requests(self) -> list[httpx.Request]:
        return [r for r in self.requests if r.url.path == "/v1/oauth2/token"]


def make_settings(**overrides: object) -> Settings:
    values: dict[str, object] = {
        "paypal_client_id": "client-id",
        "paypal_client_secret": SecretStr("client-secret"),
        "paypal_env": "sandbox",
        "allow_live": False,
    }
    values.update(overrides)
    return Settings(_env_file=None, **values)  # type: ignore[arg-type]


def make_client(
    stub: Callable[[httpx.Request], httpx.Response],
    *,
    settings: Settings | None = None,
    clock: FakeClock | None = None,
) -> PayPalClient:
    http = httpx.AsyncClient(transport=httpx.MockTransport(stub))
    return PayPalClient(http, settings or make_settings(), clock or FakeClock())


ORDER_CREATED = {
    "id": "ORDER1",
    "status": "PAYER_ACTION_REQUIRED",
    "links": [
        {
            "href": "https://api.sandbox.paypal.com/v2/checkout/orders/ORDER1",
            "rel": "self",
        },
        {
            "href": "https://www.sandbox.paypal.com/checkoutnow?token=ORDER1",
            "rel": "payer-action",
        },
    ],
}
AUTHORIZED = {
    "id": "ORDER1",
    "status": "COMPLETED",
    "purchase_units": [
        {
            "payments": {
                "authorizations": [
                    {
                        "id": "AUTH1",
                        "status": "CREATED",
                        "expiration_time": "2026-11-18T09:00:00Z",
                    }
                ]
            }
        }
    ],
}
PAYOUT_CREATED = {
    "batch_header": {"payout_batch_id": "BATCH1", "batch_status": "PENDING"},
}

Call = Callable[[PayPalClient], Awaitable[object]]


@pytest.mark.parametrize(
    ("path", "response", "call"),
    [
        (
            "/v2/checkout/orders",
            httpx.Response(201, json=ORDER_CREATED),
            lambda c: c.create_order(
                Decimal("25"),
                "bounty-1",
                "https://x/return",
                "https://x/cancel",
                request_id="order-b1",
            ),
        ),
        (
            "/v2/checkout/orders/ORDER1/authorize",
            httpx.Response(201, json=AUTHORIZED),
            lambda c: c.authorize("ORDER1", request_id="auth-b1"),
        ),
        (
            "/v2/payments/authorizations/AUTH1/capture",
            httpx.Response(201, json={"id": "CAP1", "status": "COMPLETED"}),
            lambda c: c.capture("AUTH1", request_id="capture-b1"),
        ),
        (
            "/v2/payments/authorizations/AUTH1/void",
            httpx.Response(204),
            lambda c: c.void("AUTH1", request_id="void-b1"),
        ),
        (
            "/v1/payments/payouts",
            httpx.Response(201, json=PAYOUT_CREATED),
            lambda c: c.payout(
                "solver@example.com",
                Decimal("25"),
                "payout-c1",
                "bounty",
                request_id="payout-c1",
            ),
        ),
        (
            "/v2/payments/captures/CAP1/refund",
            httpx.Response(201, json={"id": "REF1", "status": "COMPLETED"}),
            lambda c: c.refund("CAP1", request_id="refund-b1"),
        ),
    ],
    ids=["create_order", "authorize", "capture", "void", "payout", "refund"],
)
async def test_every_post_carries_its_request_id(
    path: str, response: httpx.Response, call: Call
) -> None:
    stub = PayPalStub({path: response})
    client = make_client(stub)

    await call(client)

    [request] = stub.api_requests()
    assert request.method == "POST"
    expected = {
        "/v2/checkout/orders": "order-b1",
        "/v2/checkout/orders/ORDER1/authorize": "auth-b1",
        "/v2/payments/authorizations/AUTH1/capture": "capture-b1",
        "/v2/payments/authorizations/AUTH1/void": "void-b1",
        "/v1/payments/payouts": "payout-c1",
        "/v2/payments/captures/CAP1/refund": "refund-b1",
    }[path]
    assert request.headers["PayPal-Request-Id"] == expected
    assert request.headers["Authorization"] == "Bearer tok-1"


def test_live_environment_requires_explicit_opt_in() -> None:
    with pytest.raises(RuntimeError, match="live PayPal disabled"):
        make_client(PayPalStub(), settings=make_settings(paypal_env="live"))


async def test_live_environment_uses_the_live_host_when_allowed() -> None:
    stub = PayPalStub({"/v2/payments/authorizations/A/void": httpx.Response(204)})
    client = make_client(
        stub, settings=make_settings(paypal_env="live", allow_live=True)
    )

    await client.void("A", request_id="void-b1")

    assert {r.url.host for r in stub.requests} == {"api-m.paypal.com"}


async def test_sandbox_is_the_default_host() -> None:
    stub = PayPalStub({"/v2/payments/authorizations/A/void": httpx.Response(204)})

    await make_client(stub).void("A", request_id="void-b1")

    assert {r.url.host for r in stub.requests} == {"api-m.sandbox.paypal.com"}


async def test_token_is_fetched_once_for_consecutive_calls() -> None:
    stub = PayPalStub({"/v2/payments/authorizations/A/void": httpx.Response(204)})
    client = make_client(stub)

    await client.void("A", request_id="void-1")
    await client.void("A", request_id="void-2")

    assert len(stub.token_requests()) == 1
    assert len(stub.api_requests()) == 2


async def test_token_is_refreshed_a_minute_before_it_expires() -> None:
    stub = PayPalStub({"/v2/payments/authorizations/A/void": httpx.Response(204)})
    clock = FakeClock()
    client = make_client(stub, clock=clock)

    await client.void("A", request_id="void-1")
    clock.current = NOW + timedelta(seconds=3600 - 61)
    await client.void("A", request_id="void-2")
    assert len(stub.token_requests()) == 1

    clock.current = NOW + timedelta(seconds=3600 - 59)
    await client.void("A", request_id="void-3")
    assert len(stub.token_requests()) == 2


async def test_token_request_uses_client_credentials_with_basic_auth() -> None:
    stub = PayPalStub({"/v2/payments/authorizations/A/void": httpx.Response(204)})

    await make_client(stub).void("A", request_id="void-1")

    [token_request] = stub.token_requests()
    assert token_request.content == b"grant_type=client_credentials"
    expected = base64.b64encode(b"client-id:client-secret").decode()
    assert token_request.headers["Authorization"] == f"Basic {expected}"


async def test_paypal_error_keeps_name_and_debug_id_only() -> None:
    body = {
        "name": "UNPROCESSABLE_ENTITY",
        "message": "secret detail that must not leak",
        "debug_id": "dbg-123",
        "details": [{"issue": "ORDER_NOT_APPROVED"}],
    }
    stub = PayPalStub(
        {"/v2/checkout/orders/ORDER1/authorize": httpx.Response(422, json=body)}
    )

    with pytest.raises(UpstreamError) as raised:
        await make_client(stub).authorize("ORDER1", request_id="auth-b1")

    error = raised.value
    assert error.code == "PAYPAL_ERROR"
    assert error.params == {"name": "UNPROCESSABLE_ENTITY", "debug_id": "dbg-123"}
    assert "secret detail" not in error.detail
    assert error.status == 502


async def test_non_json_error_body_still_maps_to_paypal_error() -> None:
    stub = PayPalStub(
        {
            "/v2/payments/authorizations/A/void": httpx.Response(
                503, text="<html>down</html>", headers={"PayPal-Debug-Id": "hdr-1"}
            )
        }
    )

    with pytest.raises(UpstreamError) as raised:
        await make_client(stub).void("A", request_id="void-1")

    assert raised.value.code == "PAYPAL_ERROR"
    assert raised.value.params == {"name": "UNKNOWN", "debug_id": "hdr-1"}


async def test_rejected_credentials_map_to_paypal_error() -> None:
    def stub(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"error": "invalid_client"})

    with pytest.raises(UpstreamError) as raised:
        await make_client(stub).void("A", request_id="void-1")

    assert raised.value.code == "PAYPAL_ERROR"
    assert raised.value.params["name"] == "invalid_client"


async def test_transport_failure_maps_to_paypal_unavailable() -> None:
    def stub(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectTimeout("timed out", request=request)

    with pytest.raises(UpstreamError) as raised:
        await make_client(stub).void("A", request_id="void-1")

    assert raised.value.code == "PAYPAL_UNAVAILABLE"


async def test_create_order_returns_approval_url_and_asks_for_authorization() -> None:
    stub = PayPalStub({"/v2/checkout/orders": httpx.Response(201, json=ORDER_CREATED)})

    created = await make_client(stub).create_order(
        Decimal("25"),
        "bounty-1",
        "https://app.test/paypal/return",
        "https://app.test/paypal/cancel",
        request_id="order-b1",
    )

    assert created.order_id == "ORDER1"
    assert (
        created.approve_url == "https://www.sandbox.paypal.com/checkoutnow?token=ORDER1"
    )
    [request] = stub.api_requests()
    body = json.loads(request.content)
    assert body["intent"] == "AUTHORIZE"
    [unit] = body["purchase_units"]
    assert unit["reference_id"] == "bounty-1"
    assert unit["amount"] == {"currency_code": "USD", "value": "25.00"}
    context = body["payment_source"]["paypal"]["experience_context"]
    assert context["return_url"] == "https://app.test/paypal/return"
    assert context["cancel_url"] == "https://app.test/paypal/cancel"


async def test_create_order_accepts_the_legacy_approve_link() -> None:
    legacy = {
        "id": "ORDER2",
        "links": [{"href": "https://pp.test/approve", "rel": "approve"}],
    }
    stub = PayPalStub({"/v2/checkout/orders": httpx.Response(201, json=legacy)})

    created = await make_client(stub).create_order(
        Decimal("1.50"), "b", "https://x/r", "https://x/c", request_id="order-b"
    )

    assert created.approve_url == "https://pp.test/approve"


async def test_order_without_approval_link_is_a_bad_response() -> None:
    body = {"id": "ORDER3", "links": [{"href": "https://pp.test/self", "rel": "self"}]}
    stub = PayPalStub({"/v2/checkout/orders": httpx.Response(201, json=body)})

    with pytest.raises(UpstreamError) as raised:
        await make_client(stub).create_order(
            Decimal("5"), "b", "https://x/r", "https://x/c", request_id="order-b"
        )

    assert raised.value.code == "PAYPAL_BAD_RESPONSE"


@pytest.mark.parametrize("amount", [Decimal("10.005"), Decimal("0"), Decimal("-3.00")])
async def test_amounts_are_never_rounded_or_non_positive(amount: Decimal) -> None:
    stub = PayPalStub({"/v2/checkout/orders": httpx.Response(201, json=ORDER_CREATED)})

    with pytest.raises(ValueError, match="amount"):
        await make_client(stub).create_order(
            amount, "b", "https://x/r", "https://x/c", request_id="order-b"
        )

    assert stub.api_requests() == []


async def test_authorize_returns_authorization_id_and_expiry() -> None:
    stub = PayPalStub(
        {"/v2/checkout/orders/ORDER1/authorize": httpx.Response(201, json=AUTHORIZED)}
    )

    authorization = await make_client(stub).authorize("ORDER1", request_id="auth-b1")

    assert authorization.auth_id == "AUTH1"
    assert authorization.expires_at == datetime(2026, 11, 18, 9, 0, tzinfo=UTC)


async def test_denied_authorization_is_not_reported_as_held_money() -> None:
    denied = json.loads(json.dumps(AUTHORIZED))
    denied["purchase_units"][0]["payments"]["authorizations"][0]["status"] = "DENIED"
    stub = PayPalStub(
        {"/v2/checkout/orders/ORDER1/authorize": httpx.Response(201, json=denied)}
    )

    with pytest.raises(UpstreamError) as raised:
        await make_client(stub).authorize("ORDER1", request_id="auth-b1")

    assert raised.value.code == "PAYPAL_AUTHORIZATION_DENIED"


async def test_capture_captures_everything_and_returns_the_capture_id() -> None:
    stub = PayPalStub(
        {
            "/v2/payments/authorizations/AUTH1/capture": httpx.Response(
                201, json={"id": "CAP1"}
            )
        }
    )

    capture_id = await make_client(stub).capture("AUTH1", request_id="capture-b1")

    assert capture_id == "CAP1"
    [request] = stub.api_requests()
    assert json.loads(request.content) == {"final_capture": True}


async def test_payout_pays_one_email_item_in_usd() -> None:
    stub = PayPalStub(
        {"/v1/payments/payouts": httpx.Response(201, json=PAYOUT_CREATED)}
    )

    batch_id = await make_client(stub).payout(
        "solver@example.com",
        Decimal("25"),
        "payout-c1",
        "Bounty for #1",
        request_id="payout-c1",
    )

    assert batch_id == "BATCH1"
    [request] = stub.api_requests()
    body = json.loads(request.content)
    assert body["sender_batch_header"]["sender_batch_id"] == "payout-c1"
    [item] = body["items"]
    assert item["recipient_type"] == "EMAIL"
    assert item["receiver"] == "solver@example.com"
    assert item["amount"] == {"currency": "USD", "value": "25.00"}
    assert item["note"] == "Bounty for #1"


async def test_payout_status_reports_batch_and_item_state() -> None:
    body = {
        "batch_header": {"payout_batch_id": "BATCH1", "batch_status": "SUCCESS"},
        "items": [{"transaction_status": "UNCLAIMED"}],
    }
    stub = PayPalStub({"/v1/payments/payouts/BATCH1": httpx.Response(200, json=body)})

    status = await make_client(stub).payout_status("BATCH1")

    assert status.batch_status == "SUCCESS"
    assert status.item_status == "UNCLAIMED"
    [request] = stub.api_requests()
    assert request.method == "GET"
    assert "PayPal-Request-Id" not in request.headers


async def test_payout_status_without_items_yet() -> None:
    body = {"batch_header": {"payout_batch_id": "BATCH1", "batch_status": "PENDING"}}
    stub = PayPalStub({"/v1/payments/payouts/BATCH1": httpx.Response(200, json=body)})

    status = await make_client(stub).payout_status("BATCH1")

    assert (status.batch_status, status.item_status) == ("PENDING", None)


async def test_refund_refunds_the_whole_capture_and_returns_the_refund_id() -> None:
    stub = PayPalStub(
        {
            "/v2/payments/captures/CAP1/refund": httpx.Response(
                201, json={"id": "REF1", "status": "COMPLETED"}
            )
        }
    )

    refund_id = await make_client(stub).refund("CAP1", request_id="refund-b1")

    assert refund_id == "REF1"
    [request] = stub.api_requests()
    assert json.loads(request.content) == {}  # no amount: a full refund


async def test_refund_replayed_by_request_id_answers_200_with_the_same_refund() -> None:
    stub = PayPalStub(
        {
            "/v2/payments/captures/CAP1/refund": httpx.Response(
                200, json={"id": "REF1", "status": "COMPLETED"}
            )
        }
    )

    assert await make_client(stub).refund("CAP1", request_id="refund-b1") == "REF1"


async def test_pending_refund_counts_as_accepted() -> None:
    stub = PayPalStub(
        {
            "/v2/payments/captures/CAP1/refund": httpx.Response(
                201, json={"id": "REF1", "status": "PENDING"}
            )
        }
    )

    assert await make_client(stub).refund("CAP1", request_id="refund-b1") == "REF1"


@pytest.mark.parametrize("status", ["FAILED", "CANCELLED"])
async def test_refund_that_did_not_give_the_money_back_is_an_error(status: str) -> None:
    stub = PayPalStub(
        {
            "/v2/payments/captures/CAP1/refund": httpx.Response(
                201, json={"id": "REF1", "status": status}
            )
        }
    )

    with pytest.raises(UpstreamError) as raised:
        await make_client(stub).refund("CAP1", request_id="refund-b1")

    assert raised.value.code == "PAYPAL_REFUND_FAILED"


async def test_refund_rejected_by_paypal_is_an_upstream_error() -> None:
    stub = PayPalStub(
        {
            "/v2/payments/captures/CAP1/refund": httpx.Response(
                422,
                json={"name": "CAPTURE_FULLY_REFUNDED", "debug_id": "dbg-9"},
            )
        }
    )

    with pytest.raises(UpstreamError) as raised:
        await make_client(stub).refund("CAP1", request_id="refund-b1")

    assert raised.value.code == "PAYPAL_ERROR"
    assert raised.value.params["name"] == "CAPTURE_FULLY_REFUNDED"


DUPLICATE_BATCH = {
    "name": "USER_BUSINESS_ERROR",
    "message": "User business error.",
    "debug_id": "dbg-1",
    "details": [
        {
            "field": "sender_batch_id",
            "issue": "Batch with given sender_batch_id already exists",
        }
    ],
    "links": [
        {
            "href": "https://api-m.sandbox.paypal.com/v1/payments/payouts/BATCH-OLD",
            "rel": "self",
            "method": "GET",
        }
    ],
}


async def _payout_with(response: httpx.Response) -> str:
    stub = PayPalStub({"/v1/payments/payouts": response})
    return await make_client(stub).payout(
        "solver@example.com",
        Decimal("25"),
        "payout-c1",
        "Bounty for #1",
        request_id="payout-c1",
    )


async def test_payout_with_a_reused_sender_batch_id_returns_the_original_batch() -> (
    None
):
    assert await _payout_with(httpx.Response(400, json=DUPLICATE_BATCH)) == "BATCH-OLD"


async def test_payout_error_without_a_link_to_an_original_payout_still_raises() -> None:
    body = {"name": "INSUFFICIENT_FUNDS", "debug_id": "dbg-2", "links": []}

    with pytest.raises(UpstreamError) as raised:
        await _payout_with(httpx.Response(400, json=body))

    assert raised.value.params["name"] == "INSUFFICIENT_FUNDS"


async def test_payout_error_linking_something_else_is_not_mistaken_for_a_duplicate() -> (
    None
):
    body = {
        "name": "VALIDATION_ERROR",
        "debug_id": "dbg-3",
        "links": [
            {
                "href": "https://developer.paypal.com/docs/api/payments.payouts-batch/v1/",
                "rel": "information_link",
            },
            {
                "href": "https://api-m.sandbox.paypal.com/v1/payments/payouts-item/ITEM1",
                "rel": "item",
                "method": "GET",
            },
        ],
    }

    with pytest.raises(UpstreamError):
        await _payout_with(httpx.Response(400, json=body))


async def test_server_error_on_payout_is_still_an_error_for_the_caller_to_retry() -> (
    None
):
    with pytest.raises(UpstreamError):
        await _payout_with(httpx.Response(500, json={"name": "INTERNAL_SERVICE_ERROR"}))
