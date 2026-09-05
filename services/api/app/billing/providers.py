"""Payment providers — Razorpay PRIMARY, Stripe secondary.

Two layers, deliberately separated:

* **Pure functions** for signature verification and webhook normalisation.
  No I/O, fully unit-testable, and the only place a provider's wire format is
  interpreted.
* **Adapters** that make the REST calls (plans, subscriptions, checkout
  sessions, cancel/resume/reprice) over httpx. Injectable via
  `set_provider_override` so the API tests never touch the network.

Nothing here reads a secret from anywhere but settings. If a secret is empty
the adapter reports `configured() == False`, checkout answers 503 and webhooks
are rejected — an unsigned webhook is never trusted.
"""

from __future__ import annotations

import hashlib
import hmac
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Optional

import httpx

from ..config import get_settings
from .pricing import Quote

PROVIDERS = ("razorpay", "stripe")


class ProviderError(Exception):
    status_code = 502


class ProviderNotConfigured(ProviderError):
    status_code = 503


class ProviderUnsupported(ProviderError):
    status_code = 409


# ── normalised shapes ────────────────────────────────────────────────────────

# Provider statuses collapse onto the subscriptions.status enum. `past_due`
# keeps the tier for the grace window; `unpaid`/`cancelled` drop it.
NORMALIZED_STATUSES = ("trialing", "active", "past_due", "unpaid", "cancelled")


@dataclass
class SubscriptionEvent:
    provider: str
    event_id: str
    event_type: str
    subscription_ref: Optional[str] = None
    customer_ref: Optional[str] = None
    status: Optional[str] = None            # one of NORMALIZED_STATUSES or None
    period_start: Optional[datetime] = None
    period_end: Optional[datetime] = None
    trial_end: Optional[datetime] = None
    cancel_at_period_end: Optional[bool] = None
    user_id: Optional[str] = None
    intent_id: Optional[str] = None
    amount_minor: Optional[int] = None
    currency: Optional[str] = None
    relevant: bool = True                    # False = acknowledged, not a subscription signal


@dataclass
class CheckoutPayload:
    provider: str
    provider_ref: str                        # subscription id / checkout session id
    plan_ref: Optional[str]
    client: dict                             # what the PWA hands to the provider SDK


def _hmac_hex(secret: str, message: bytes) -> str:
    return hmac.new(secret.encode(), message, hashlib.sha256).hexdigest()


def _ts(value: Any) -> Optional[datetime]:
    if value in (None, "", 0):
        return None
    try:
        return datetime.fromtimestamp(int(value), tz=timezone.utc)
    except (TypeError, ValueError, OSError):
        return None


# ── Razorpay: pure helpers ───────────────────────────────────────────────────

RAZORPAY_STATUS: dict[str, Optional[str]] = {
    "created": None,
    "authenticated": "trialing",     # mandate authorised, first charge at start_at
    "active": "active",
    "pending": "past_due",           # a charge failed, Razorpay is retrying
    "halted": "unpaid",              # retries exhausted
    "paused": "past_due",
    "cancelled": "cancelled",
    "completed": "cancelled",
    "expired": "cancelled",
}

RAZORPAY_SUBSCRIPTION_EVENTS = {
    "subscription.authenticated",
    "subscription.activated",
    "subscription.charged",
    "subscription.pending",
    "subscription.halted",
    "subscription.paused",
    "subscription.resumed",
    "subscription.cancelled",
    "subscription.completed",
    "subscription.updated",
}


def verify_razorpay_webhook(raw_body: bytes, signature: str, webhook_secret: str) -> bool:
    if not webhook_secret or not signature:
        return False
    return hmac.compare_digest(_hmac_hex(webhook_secret, raw_body), signature.strip())


def verify_razorpay_checkout(
    payment_id: str, subscription_id: str, signature: str, key_secret: str
) -> bool:
    """Razorpay Checkout returns (payment_id, subscription_id, signature) where
    signature = HMAC-SHA256(payment_id + "|" + subscription_id, key_secret)."""
    if not key_secret or not signature:
        return False
    expected = _hmac_hex(key_secret, f"{payment_id}|{subscription_id}".encode())
    return hmac.compare_digest(expected, signature.strip())


def parse_razorpay_event(payload: dict, event_id: str) -> SubscriptionEvent:
    event_type = str(payload.get("event", ""))
    ev = SubscriptionEvent(provider="razorpay", event_id=event_id, event_type=event_type)
    entity = ((payload.get("payload") or {}).get("subscription") or {}).get("entity") or {}
    if event_type not in RAZORPAY_SUBSCRIPTION_EVENTS or not entity:
        ev.relevant = False
        return ev

    notes = entity.get("notes") or {}
    ev.subscription_ref = entity.get("id")
    ev.customer_ref = entity.get("customer_id")
    ev.status = RAZORPAY_STATUS.get(str(entity.get("status", "")), None)
    ev.period_start = _ts(entity.get("current_start"))
    ev.period_end = _ts(entity.get("current_end"))
    start_at = _ts(entity.get("start_at"))
    if ev.status == "trialing":
        ev.trial_end = start_at
        ev.period_end = ev.period_end or start_at
    ev.cancel_at_period_end = (
        True if str(entity.get("status")) == "active" and entity.get("has_scheduled_changes")
        and entity.get("end_at") else None
    )
    ev.user_id = notes.get("user_id") if isinstance(notes, dict) else None
    ev.intent_id = notes.get("intent_id") if isinstance(notes, dict) else None
    payment = ((payload.get("payload") or {}).get("payment") or {}).get("entity") or {}
    if payment.get("amount") is not None:
        ev.amount_minor = int(payment["amount"])
        ev.currency = payment.get("currency")
    return ev


# ── Stripe: pure helpers ─────────────────────────────────────────────────────

STRIPE_STATUS: dict[str, Optional[str]] = {
    "trialing": "trialing",
    "active": "active",
    "past_due": "past_due",
    "unpaid": "unpaid",
    "canceled": "cancelled",
    "incomplete": None,
    "incomplete_expired": "cancelled",
    "paused": "past_due",
}

STRIPE_TOLERANCE_SECONDS = 300


def verify_stripe_webhook(
    raw_body: bytes, signature_header: str, webhook_secret: str, now: Optional[int] = None
) -> bool:
    """`Stripe-Signature: t=<ts>,v1=<hex>[,v1=<hex>...]`; signed payload is
    `<ts>.<raw body>`; reject timestamps outside ±300 s (replay window)."""
    if not webhook_secret or not signature_header:
        return False
    timestamp: Optional[str] = None
    candidates: list[str] = []
    for part in signature_header.split(","):
        key, _, value = part.strip().partition("=")
        if key == "t":
            timestamp = value
        elif key == "v1":
            candidates.append(value)
    if not timestamp or not candidates or not timestamp.isdigit():
        return False
    current = int(time.time()) if now is None else now
    if abs(current - int(timestamp)) > STRIPE_TOLERANCE_SECONDS:
        return False
    expected = _hmac_hex(webhook_secret, f"{timestamp}.".encode() + raw_body)
    return any(hmac.compare_digest(expected, c) for c in candidates)


def parse_stripe_event(payload: dict) -> SubscriptionEvent:
    event_type = str(payload.get("type", ""))
    ev = SubscriptionEvent(
        provider="stripe", event_id=str(payload.get("id", "")), event_type=event_type
    )
    obj = ((payload.get("data") or {}).get("object")) or {}
    meta = obj.get("metadata") or {}

    if event_type == "checkout.session.completed":
        # Links the session to the intent; the subscription events carry status.
        ev.subscription_ref = obj.get("subscription")
        ev.customer_ref = obj.get("customer")
        ev.user_id = obj.get("client_reference_id") or meta.get("user_id")
        ev.intent_id = meta.get("intent_id")
        ev.amount_minor = obj.get("amount_total")
        ev.currency = (obj.get("currency") or "").upper() or None
        return ev

    if event_type.startswith("customer.subscription."):
        ev.subscription_ref = obj.get("id")
        ev.customer_ref = obj.get("customer")
        ev.status = STRIPE_STATUS.get(str(obj.get("status", "")), None)
        ev.period_start = _ts(obj.get("current_period_start"))
        ev.period_end = _ts(obj.get("current_period_end"))
        ev.trial_end = _ts(obj.get("trial_end"))
        ev.cancel_at_period_end = bool(obj.get("cancel_at_period_end", False))
        ev.user_id = meta.get("user_id")
        ev.intent_id = meta.get("intent_id")
        return ev

    if event_type in ("invoice.paid", "invoice.payment_failed"):
        ev.subscription_ref = obj.get("subscription")
        ev.customer_ref = obj.get("customer")
        ev.status = "active" if event_type == "invoice.paid" else "past_due"
        ev.amount_minor = obj.get("amount_paid") if event_type == "invoice.paid" else None
        ev.currency = (obj.get("currency") or "").upper() or None
        lines = ((obj.get("lines") or {}).get("data")) or []
        if lines:
            period = lines[0].get("period") or {}
            ev.period_start = _ts(period.get("start"))
            ev.period_end = _ts(period.get("end"))
        return ev

    ev.relevant = False
    return ev


# ── adapters ─────────────────────────────────────────────────────────────────


class PaymentProvider:
    name: str = ""

    def configured(self) -> bool:
        raise NotImplementedError

    async def create_checkout(
        self, *, user: dict, quote: Quote, intent_id: str, trial_days: int
    ) -> CheckoutPayload:
        raise NotImplementedError

    async def cancel(self, subscription_ref: str, *, at_period_end: bool) -> None:
        raise NotImplementedError

    async def resume(self, subscription_ref: str) -> None:
        raise NotImplementedError

    async def reprice(self, subscription_ref: str, quote: Quote) -> Optional[str]:
        """Change the recurring amount. Returns the new plan/price reference."""
        raise NotImplementedError

    def public_key(self) -> Optional[str]:
        return None


def _raise_for(resp: httpx.Response, what: str) -> dict:
    if resp.status_code >= 400:
        detail = ""
        try:
            detail = str(resp.json().get("error", {}).get("description") or resp.json())[:200]
        except Exception:  # noqa: BLE001
            detail = resp.text[:200]
        raise ProviderError(f"{what} failed ({resp.status_code}): {detail}")
    return resp.json()


class RazorpayProvider(PaymentProvider):
    name = "razorpay"

    def __init__(self, client: Optional[httpx.AsyncClient] = None):
        self._client = client

    def configured(self) -> bool:
        s = get_settings()
        return bool(s.razorpay_key_id and s.razorpay_key_secret)

    def public_key(self) -> Optional[str]:
        return get_settings().razorpay_key_id or None

    def _http(self) -> httpx.AsyncClient:
        if self._client is None:
            s = get_settings()
            self._client = httpx.AsyncClient(
                base_url=s.razorpay_api_base,
                auth=(s.razorpay_key_id, s.razorpay_key_secret),
                timeout=20.0,
            )
        return self._client

    async def _create_plan(self, quote: Quote) -> str:
        body = {
            "period": "monthly",
            "interval": 1,
            "item": {
                "name": f"Exam Arena {quote.tier} (+{quote.seats_count} seats)",
                "amount": quote.total_minor,
                "currency": quote.currency,
            },
            "notes": {"tier": quote.tier, "seats_count": str(quote.seats_count)},
        }
        data = _raise_for(await self._http().post("/plans", json=body), "razorpay plan")
        return str(data["id"])

    async def create_checkout(
        self, *, user: dict, quote: Quote, intent_id: str, trial_days: int
    ) -> CheckoutPayload:
        if not self.configured():
            raise ProviderNotConfigured("razorpay is not configured")
        plan_id = await self._create_plan(quote)
        body: dict[str, Any] = {
            "plan_id": plan_id,
            "total_count": 120,             # 10 years of monthly cycles; cancel ends it
            "quantity": 1,
            "customer_notify": 1,
            "notes": {"user_id": user["id"], "intent_id": intent_id, "tier": quote.tier},
        }
        if trial_days > 0:
            body["start_at"] = int(time.time()) + trial_days * 86_400
        data = _raise_for(await self._http().post("/subscriptions", json=body), "razorpay subscription")
        sub_id = str(data["id"])
        return CheckoutPayload(
            provider="razorpay",
            provider_ref=sub_id,
            plan_ref=plan_id,
            client={
                "key_id": get_settings().razorpay_key_id,
                "subscription_id": sub_id,
                "name": "Exam Arena",
                "description": f"{quote.tier} monthly",
                "prefill": {"email": user.get("email")},
                "notes": {"intent_id": intent_id},
                "short_url": data.get("short_url"),
            },
        )

    async def cancel(self, subscription_ref: str, *, at_period_end: bool) -> None:
        _raise_for(
            await self._http().post(
                f"/subscriptions/{subscription_ref}/cancel",
                json={"cancel_at_cycle_end": 1 if at_period_end else 0},
            ),
            "razorpay cancel",
        )

    async def resume(self, subscription_ref: str) -> None:
        # Razorpay cannot undo a scheduled cancellation; the learner re-subscribes
        # after the period ends. Surfaced as 409 by the router.
        raise ProviderUnsupported("razorpay cannot resume a cancelled subscription")

    async def reprice(self, subscription_ref: str, quote: Quote) -> Optional[str]:
        plan_id = await self._create_plan(quote)
        _raise_for(
            await self._http().patch(
                f"/subscriptions/{subscription_ref}",
                json={"plan_id": plan_id, "schedule_change_at": "now", "customer_notify": 1},
            ),
            "razorpay reprice",
        )
        return plan_id


class StripeProvider(PaymentProvider):
    name = "stripe"

    def __init__(self, client: Optional[httpx.AsyncClient] = None):
        self._client = client

    def configured(self) -> bool:
        return bool(get_settings().stripe_secret_key)

    def public_key(self) -> Optional[str]:
        return get_settings().stripe_publishable_key or None

    def _http(self) -> httpx.AsyncClient:
        if self._client is None:
            s = get_settings()
            self._client = httpx.AsyncClient(
                base_url=s.stripe_api_base,
                headers={"Authorization": f"Bearer {s.stripe_secret_key}"},
                timeout=20.0,
            )
        return self._client

    @staticmethod
    def _price_form(quote: Quote, prefix: str) -> dict[str, str]:
        return {
            f"{prefix}[currency]": quote.currency.lower(),
            f"{prefix}[unit_amount]": str(quote.total_minor),
            f"{prefix}[recurring][interval]": "month",
            f"{prefix}[product_data][name]": f"Exam Arena {quote.tier} (+{quote.seats_count} seats)",
        }

    async def create_checkout(
        self, *, user: dict, quote: Quote, intent_id: str, trial_days: int
    ) -> CheckoutPayload:
        if not self.configured():
            raise ProviderNotConfigured("stripe is not configured")
        s = get_settings()
        form: dict[str, str] = {
            "mode": "subscription",
            "success_url": s.stripe_checkout_success_url,
            "cancel_url": s.stripe_checkout_cancel_url,
            "client_reference_id": user["id"],
            "line_items[0][quantity]": "1",
            "metadata[intent_id]": intent_id,
            "metadata[user_id]": user["id"],
            "subscription_data[metadata][intent_id]": intent_id,
            "subscription_data[metadata][user_id]": user["id"],
            "subscription_data[metadata][tier]": quote.tier,
            **self._price_form(quote, "line_items[0][price_data]"),
        }
        if user.get("email"):
            form["customer_email"] = user["email"]
        if trial_days > 0:
            form["subscription_data[trial_period_days]"] = str(trial_days)
        data = _raise_for(await self._http().post("/checkout/sessions", data=form), "stripe checkout")
        return CheckoutPayload(
            provider="stripe",
            provider_ref=str(data["id"]),
            plan_ref=None,
            client={"url": data.get("url"), "session_id": data["id"]},
        )

    async def cancel(self, subscription_ref: str, *, at_period_end: bool) -> None:
        if at_period_end:
            _raise_for(
                await self._http().post(
                    f"/subscriptions/{subscription_ref}", data={"cancel_at_period_end": "true"}
                ),
                "stripe cancel",
            )
        else:
            _raise_for(await self._http().delete(f"/subscriptions/{subscription_ref}"), "stripe cancel")

    async def resume(self, subscription_ref: str) -> None:
        _raise_for(
            await self._http().post(
                f"/subscriptions/{subscription_ref}", data={"cancel_at_period_end": "false"}
            ),
            "stripe resume",
        )

    async def reprice(self, subscription_ref: str, quote: Quote) -> Optional[str]:
        sub = _raise_for(await self._http().get(f"/subscriptions/{subscription_ref}"), "stripe fetch")
        items = ((sub.get("items") or {}).get("data")) or []
        if not items:
            raise ProviderError("stripe subscription has no items to reprice")
        price = _raise_for(
            await self._http().post(
                "/prices",
                data={
                    "currency": quote.currency.lower(),
                    "unit_amount": str(quote.total_minor),
                    "recurring[interval]": "month",
                    "product_data[name]": f"Exam Arena {quote.tier} (+{quote.seats_count} seats)",
                },
            ),
            "stripe price",
        )
        _raise_for(
            await self._http().post(
                f"/subscriptions/{subscription_ref}",
                data={
                    "items[0][id]": items[0]["id"],
                    "items[0][price]": price["id"],
                    "proration_behavior": "create_prorations",
                },
            ),
            "stripe reprice",
        )
        return str(price["id"])


_overrides: dict[str, PaymentProvider] = {}


def set_provider_override(name: str, provider: Optional[PaymentProvider]) -> None:
    """Tests inject fakes here; production never calls this."""
    if provider is None:
        _overrides.pop(name, None)
    else:
        _overrides[name] = provider


def get_provider(name: str) -> PaymentProvider:
    if name not in PROVIDERS:
        raise ProviderError(f"unknown provider: {name}")
    if name in _overrides:
        return _overrides[name]
    return RazorpayProvider() if name == "razorpay" else StripeProvider()


def available_providers() -> list[str]:
    return [p for p in PROVIDERS if get_provider(p).configured()]
