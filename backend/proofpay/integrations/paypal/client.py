"""PayPal REST client (Orders v2, Payments v2, Payouts v1, OAuth 2.0).

Only the sandbox is used unless the operator explicitly enables live mode.
Response bodies and credentials are never logged: an error is reported by its
PayPal ``name`` and ``debug_id`` only.
"""

import asyncio
import re
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

import httpx
import structlog

from proofpay.integrations.paypal.ports import (
    Authorization,
    CreatedOrder,
    PayoutStatus,
)
from proofpay.settings import Settings
from proofpay.shared.clock import Clock
from proofpay.shared.errors import UpstreamError

SANDBOX_URL = "https://api-m.sandbox.paypal.com"
LIVE_URL = "https://api-m.paypal.com"
CURRENCY = "USD"
# A token is refreshed this long before PayPal says it expires.
TOKEN_MARGIN = timedelta(seconds=60)
# Link relations that lead the payer to the approval page. The current Orders
# API returns "payer-action" when payment_source.paypal.experience_context is
# used; the legacy relation is "approve".
APPROVE_RELS = ("payer-action", "approve")
# A refund that ends in one of these did not give the money back.
REFUND_FAILED_STATES = frozenset({"FAILED", "CANCELLED"})
# The original payout named by a "duplicate sender_batch_id" error.
_PAYOUT_HREF = re.compile(r"/v1/payments/payouts/([A-Za-z0-9_-]+)/?$")

log = structlog.get_logger(__name__)


def _money(amount: Decimal) -> str:
    """Two-decimal string for a USD amount; refuses to round silently."""
    cents = amount.quantize(Decimal("0.01"))
    if cents != amount:
        raise ValueError("amount must have at most 2 decimal places")
    if cents <= 0:
        raise ValueError("amount must be positive")
    return f"{cents:.2f}"


def _bad_response() -> UpstreamError:
    return UpstreamError(
        code="PAYPAL_BAD_RESPONSE",
        detail="PayPal returned an unexpected response",
    )


def _original_payout_id(error_body: dict[str, Any]) -> str | None:
    """Batch id from the HATEOAS link of a duplicate-sender_batch_id error."""
    links = error_body.get("links")
    if not isinstance(links, list):
        return None
    for link in links:
        if not isinstance(link, dict):
            continue
        href = link.get("href")
        if link.get("method", "GET") == "GET" and isinstance(href, str):
            match = _PAYOUT_HREF.search(href)
            if match is not None:
                return match[1]
    return None


class PayPalClient:
    """Implements PaymentGateway over one long-lived httpx client."""

    def __init__(
        self, http: httpx.AsyncClient, settings: Settings, clock: Clock
    ) -> None:
        if settings.paypal_env == "live" and not settings.allow_live:
            raise RuntimeError("live PayPal disabled")
        self._http = http
        self._clock = clock
        self._base_url = LIVE_URL if settings.paypal_env == "live" else SANDBOX_URL
        self._client_id = settings.paypal_client_id
        self._client_secret = settings.paypal_client_secret.get_secret_value()
        self._token: str | None = None
        self._token_expires_at = datetime.min.replace(tzinfo=UTC)
        self._token_lock = asyncio.Lock()

    async def aclose(self) -> None:
        await self._http.aclose()

    # -- PaymentGateway --------------------------------------------------

    async def create_order(
        self,
        amount: Decimal,
        reference_id: str,
        return_url: str,
        cancel_url: str,
        *,
        request_id: str,
    ) -> CreatedOrder:
        body = {
            "intent": "AUTHORIZE",
            "purchase_units": [
                {
                    "reference_id": reference_id,
                    "amount": {"currency_code": CURRENCY, "value": _money(amount)},
                }
            ],
            "payment_source": {
                "paypal": {
                    "experience_context": {
                        "return_url": return_url,
                        "cancel_url": cancel_url,
                        "shipping_preference": "NO_SHIPPING",
                        "user_action": "PAY_NOW",
                    }
                }
            },
        }
        data = await self._request(
            "POST", "/v2/checkout/orders", json=body, request_id=request_id
        )
        try:
            order_id = str(data["id"])
            links = {link["rel"]: link["href"] for link in data["links"]}
            approve_url = next(links[rel] for rel in APPROVE_RELS if rel in links)
        except (KeyError, TypeError, StopIteration) as exc:
            raise _bad_response() from exc
        return CreatedOrder(order_id=order_id, approve_url=str(approve_url))

    async def authorize(self, order_id: str, *, request_id: str) -> Authorization:
        data = await self._request(
            "POST",
            f"/v2/checkout/orders/{order_id}/authorize",
            json={},
            request_id=request_id,
        )
        try:
            auth = data["purchase_units"][0]["payments"]["authorizations"][0]
            auth_id = str(auth["id"])
            expires_at = datetime.fromisoformat(auth["expiration_time"])
            status = auth.get("status")
        except (KeyError, IndexError, TypeError, ValueError) as exc:
            raise _bad_response() from exc
        if status == "DENIED":
            raise UpstreamError(
                code="PAYPAL_AUTHORIZATION_DENIED",
                detail="PayPal denied the authorization",
            )
        if expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=UTC)
        return Authorization(auth_id=auth_id, expires_at=expires_at)

    async def capture(self, auth_id: str, *, request_id: str) -> str:
        data = await self._request(
            "POST",
            f"/v2/payments/authorizations/{auth_id}/capture",
            json={"final_capture": True},
            request_id=request_id,
        )
        try:
            return str(data["id"])
        except KeyError as exc:
            raise _bad_response() from exc

    async def void(self, auth_id: str, *, request_id: str) -> None:
        await self._request(
            "POST",
            f"/v2/payments/authorizations/{auth_id}/void",
            request_id=request_id,
        )

    async def refund(self, capture_id: str, *, request_id: str) -> str:
        # An empty body refunds the whole capture.
        data = await self._request(
            "POST",
            f"/v2/payments/captures/{capture_id}/refund",
            json={},
            request_id=request_id,
        )
        try:
            refund_id = str(data["id"])
        except KeyError as exc:
            raise _bad_response() from exc
        if data.get("status") in REFUND_FAILED_STATES:
            raise UpstreamError(
                code="PAYPAL_REFUND_FAILED",
                detail="PayPal did not refund the capture",
                params={"status": data["status"]},
            )
        return refund_id

    async def payout(
        self,
        email: str,
        amount: Decimal,
        sender_batch_id: str,
        note: str,
        *,
        request_id: str,
    ) -> str:
        body = {
            "sender_batch_header": {
                "sender_batch_id": sender_batch_id,
                "recipient_type": "EMAIL",
                "email_subject": "ProofPay bounty payout",
            },
            "items": [
                {
                    "recipient_type": "EMAIL",
                    "receiver": email,
                    "amount": {"currency": CURRENCY, "value": _money(amount)},
                    "note": note,
                }
            ],
        }
        try:
            data = await self._request(
                "POST", "/v1/payments/payouts", json=body, request_id=request_id
            )
        except UpstreamError as exc:
            # A reused sender_batch_id is rejected with a link to the original
            # payout. That payout is ours: hand its id back instead of failing,
            # so the caller watches it and never pays again.
            existing = exc.params.get("existing_batch_id")
            if existing is None:
                raise
            log.info("paypal_payout_already_exists", batch_id=existing)
            return str(existing)
        try:
            return str(data["batch_header"]["payout_batch_id"])
        except (KeyError, TypeError) as exc:
            raise _bad_response() from exc

    async def payout_status(self, batch_id: str) -> PayoutStatus:
        data = await self._request("GET", f"/v1/payments/payouts/{batch_id}")
        try:
            batch_status = str(data["batch_header"]["batch_status"])
            items = data.get("items") or []
            item_status = str(items[0]["transaction_status"]) if items else None
        except (KeyError, IndexError, TypeError) as exc:
            raise _bad_response() from exc
        return PayoutStatus(batch_status=batch_status, item_status=item_status)

    # -- transport -------------------------------------------------------

    async def _access_token(self) -> str:
        async with self._token_lock:
            now = self._clock.now()
            if self._token is not None and now < self._token_expires_at:
                return self._token
            data = await self._send(
                "POST",
                "/v1/oauth2/token",
                data={"grant_type": "client_credentials"},
                auth=(self._client_id, self._client_secret),
            )
            try:
                token = str(data["access_token"])
                lifetime = timedelta(seconds=int(data["expires_in"]))
            except (KeyError, TypeError, ValueError) as exc:
                raise _bad_response() from exc
            self._token = token
            self._token_expires_at = now + lifetime - TOKEN_MARGIN
            return token

    async def _request(
        self,
        method: str,
        path: str,
        *,
        json: dict[str, Any] | None = None,
        request_id: str | None = None,
    ) -> dict[str, Any]:
        headers = {"Authorization": f"Bearer {await self._access_token()}"}
        if request_id is not None:
            headers["PayPal-Request-Id"] = request_id
        return await self._send(method, path, headers=headers, json=json)

    async def _send(
        self,
        method: str,
        path: str,
        *,
        headers: dict[str, str] | None = None,
        json: dict[str, Any] | None = None,
        data: dict[str, str] | None = None,
        auth: tuple[str, str] | None = None,
    ) -> dict[str, Any]:
        try:
            response = await self._http.request(
                method,
                f"{self._base_url}{path}",
                headers=headers,
                json=json,
                data=data,
                auth=auth,
            )
        except httpx.TransportError as exc:
            log.warning("paypal_unavailable", error=type(exc).__name__)
            raise UpstreamError(
                code="PAYPAL_UNAVAILABLE", detail="PayPal is unreachable"
            ) from exc
        if response.status_code >= httpx.codes.BAD_REQUEST:
            if response.status_code == httpx.codes.UNAUTHORIZED:
                self._token = None
            raise self._error(response)
        if not response.content:
            return {}
        try:
            body = response.json()
        except ValueError as exc:
            raise _bad_response() from exc
        if not isinstance(body, dict):
            raise _bad_response()
        return body

    @staticmethod
    def _error(response: httpx.Response) -> UpstreamError:
        """Maps a failed response to UpstreamError, keeping only name and debug_id."""
        try:
            body = response.json()
        except ValueError:
            body = None
        if not isinstance(body, dict):
            body = {}
        # OAuth errors carry "error" instead of "name".
        name = body.get("name") or body.get("error") or "UNKNOWN"
        debug_id = body.get("debug_id") or response.headers.get("PayPal-Debug-Id")
        log.warning("paypal_error", name=name, debug_id=debug_id)
        params: dict[str, Any] = {"name": name, "debug_id": debug_id}
        existing = _original_payout_id(body)
        if existing is not None:
            params["existing_batch_id"] = existing
        return UpstreamError(
            code="PAYPAL_ERROR",
            detail=f"PayPal rejected the request ({name})",
            params=params,
        )
