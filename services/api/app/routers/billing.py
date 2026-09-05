"""Billing — `/api/v1/billing/*` (client-facing; the recovered APK had no
billing routes, so this surface is the rebuilt contract — see memory
`billing-contract-v1`).

Flow (Razorpay, primary):
  1. POST /checkout        → intent + provider subscription; client opens Razorpay Checkout
  2. POST /checkout/verify → HMAC over payment_id|subscription_id; tier granted NOW,
                             entitlement re-signed (PAY-04). The webhook confirms
                             later and is idempotent against this.
Stripe (secondary): POST /checkout returns a hosted session URL; the webhook
alone grants the tier.
"""

from __future__ import annotations

from typing import Literal, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from .. import db
from ..billing import pricing
from ..billing.entitlement import entitlement_for
from ..billing.providers import (
    ProviderError,
    SubscriptionEvent,
    available_providers,
    get_provider,
    verify_razorpay_checkout,
)
from ..billing.state import apply_subscription_event, effective_tier, set_user_tier
from ..config import get_settings
from ..security import get_current_user

router = APIRouter(prefix="/billing", tags=["billing"])

Tier = Literal["pro", "bundle_2", "bundle_3"]
Provider = Literal["razorpay", "stripe"]


class CheckoutRequest(BaseModel):
    tier: Tier
    seats_count: int = Field(default=0, ge=0, le=pricing.MAX_FAMILY_SEATS)
    provider: Optional[Provider] = None
    currency: Optional[Literal["INR", "USD"]] = None


class RazorpayVerifyRequest(BaseModel):
    intent_id: str
    razorpay_payment_id: str = Field(min_length=1, max_length=64)
    razorpay_subscription_id: str = Field(min_length=1, max_length=64)
    razorpay_signature: str = Field(min_length=1, max_length=128)


class ChangeTierRequest(BaseModel):
    tier: Tier


def _provider_or_503(name: str):
    provider = get_provider(name)
    if not provider.configured():
        raise HTTPException(
            status_code=503,
            detail=f"{name} is not configured on this server (owner supplies keys via .env)",
        )
    return provider


def _provider_http_error(exc: ProviderError) -> HTTPException:
    return HTTPException(status_code=getattr(exc, "status_code", 502), detail=str(exc))


async def _live_subscription_row(conn, user_id: str):
    return await (
        await conn.execute(
            """SELECT id, provider, tier, status, seats_count, currency, amount_minor,
                      current_period_start, current_period_end, trial_ends_at,
                      cancel_at_period_end, razorpay_subscription_id, stripe_subscription_id,
                      provider_plan_ref
               FROM subscriptions
               WHERE user_id = %s::uuid AND status IN ('active', 'trialing', 'past_due')
               ORDER BY updated_at DESC LIMIT 1""",
            (user_id,),
        )
    ).fetchone()


def _subscription_public(row) -> Optional[dict]:
    if row is None:
        return None
    (sid, provider, tier, status, seats, currency, amount, ps, pe, te, cape, rz, st, plan) = row
    return {
        "id": str(sid),
        "provider": provider,
        "tier": tier,
        "status": status,
        "effective_tier": effective_tier(tier, status),
        "seats_count": seats,
        "currency": currency,
        "amount_minor": amount,
        "current_period_start": ps.isoformat() if ps else None,
        "current_period_end": pe.isoformat() if pe else None,
        "trial_ends_at": te.isoformat() if te else None,
        "cancel_at_period_end": cape,
    }


def _provider_ref(row) -> str:
    provider = row[1]
    return row[11] if provider == "razorpay" else row[12]


async def _require_standard_account(conn, user_id: str) -> None:
    row = await (
        await conn.execute("SELECT account_type FROM users WHERE id = %s::uuid", (user_id,))
    ).fetchone()
    if row and row[0] == "child":
        raise HTTPException(status_code=403, detail="child accounts are billed through the parent")


@router.get("/plans")
async def plans() -> dict:
    """Public catalogue: tiers in USD and INR at the configured rate."""
    s = get_settings()
    return {
        "default_provider": s.billing_default_provider,
        "default_currency": s.billing_default_currency,
        "providers_available": available_providers(),
        "usd_inr_rate": s.usd_inr_rate,
        "trial_days": s.trial_days,
        "family": {
            "max_seats": pricing.MAX_FAMILY_SEATS,
            "seat_discount_pct": pricing.SEAT_DISCOUNT_PCT,
        },
        "plans": pricing.plan_catalog(s.usd_inr_rate, s.trial_days),
    }


@router.get("/subscription")
async def subscription(user: dict = Depends(get_current_user)) -> dict:
    pool = await db.get_pg()
    async with pool.connection() as conn:
        row = await _live_subscription_row(conn, user["id"])
        entitlement = await entitlement_for(conn, user["id"], user["tier"])
    return {"tier": user["tier"], "subscription": _subscription_public(row), "entitlement": entitlement}


@router.post("/checkout")
async def checkout(body: CheckoutRequest, user: dict = Depends(get_current_user)) -> dict:
    s = get_settings()
    provider_name = body.provider or s.billing_default_provider
    provider = _provider_or_503(provider_name)
    currency = body.currency or ("INR" if provider_name == "razorpay" else s.billing_default_currency)

    try:
        q = pricing.quote(body.tier, body.seats_count, currency, s.usd_inr_rate)
    except pricing.PricingError as exc:
        raise HTTPException(status_code=422, detail=str(exc))

    pool = await db.get_pg()
    async with pool.connection() as conn:
        await _require_standard_account(conn, user["id"])
        if await _live_subscription_row(conn, user["id"]):
            raise HTTPException(
                status_code=409, detail="a live subscription exists; use /billing/change or /billing/cancel"
            )
        intent_id = (
            await (
                await conn.execute(
                    """INSERT INTO checkout_intents
                           (user_id, provider, tier, seats_count, currency, amount_minor,
                            usd_inr_rate, trial_days)
                       VALUES (%s, %s, %s, %s, %s, %s, %s, %s) RETURNING id""",
                    (
                        user["id"], provider_name, q.tier, q.seats_count, q.currency,
                        q.total_minor, s.usd_inr_rate if currency == "INR" else None, s.trial_days,
                    ),
                )
            ).fetchone()
        )[0]
        await conn.commit()

        try:
            payload = await provider.create_checkout(
                user=user, quote=q, intent_id=str(intent_id), trial_days=s.trial_days
            )
        except ProviderError as exc:
            await conn.execute(
                "UPDATE checkout_intents SET status = 'failed', completed_at = NOW() WHERE id = %s",
                (intent_id,),
            )
            await conn.commit()
            raise _provider_http_error(exc)

        await conn.execute(
            "UPDATE checkout_intents SET provider_ref = %s, provider_plan_ref = %s WHERE id = %s",
            (payload.provider_ref, payload.plan_ref, intent_id),
        )
        await conn.commit()

    return {
        "intent_id": str(intent_id),
        "provider": provider_name,
        "quote": q.as_dict(),
        "trial_days": s.trial_days,
        "checkout": payload.client,
    }


@router.post("/checkout/verify")
async def verify_checkout(body: RazorpayVerifyRequest, user: dict = Depends(get_current_user)) -> dict:
    """Razorpay Checkout handler result. Signature is over payment_id|subscription_id
    with the key secret; a valid one grants the tier immediately (PAY-04)."""
    s = get_settings()
    _provider_or_503("razorpay")
    if not verify_razorpay_checkout(
        body.razorpay_payment_id, body.razorpay_subscription_id, body.razorpay_signature, s.razorpay_key_secret
    ):
        raise HTTPException(status_code=400, detail="invalid razorpay signature")

    pool = await db.get_pg()
    async with pool.connection() as conn:
        row = await (
            await conn.execute(
                """SELECT id, user_id, provider_ref, status, trial_days FROM checkout_intents
                   WHERE id = %s::uuid AND provider = 'razorpay'""",
                (body.intent_id,),
            )
        ).fetchone()
        if row is None or str(row[1]) != user["id"]:
            raise HTTPException(status_code=404, detail="unknown checkout intent")
        if row[2] and row[2] != body.razorpay_subscription_id:
            raise HTTPException(status_code=400, detail="subscription id does not match the intent")

        ev = SubscriptionEvent(
            provider="razorpay",
            event_id=f"checkout-verify:{body.razorpay_payment_id}",
            event_type="checkout.verified",
            subscription_ref=body.razorpay_subscription_id,
            status="trialing" if row[4] > 0 else "active",
            user_id=user["id"],
            intent_id=str(row[0]),
        )
        async with conn.cursor() as cur:
            summary = await apply_subscription_event(cur, ev)
        await conn.commit()
        sub_row = await _live_subscription_row(conn, user["id"])
        entitlement = await entitlement_for(conn, user["id"], summary.get("tier", user["tier"]))

    return {
        "status": "verified",
        "tier": summary.get("tier"),
        "subscription": _subscription_public(sub_row),
        "entitlement": entitlement,
    }


@router.post("/cancel")
async def cancel(user: dict = Depends(get_current_user)) -> dict:
    """Cancel at period end. Tier stays until the period closes (worker flips it)."""
    pool = await db.get_pg()
    async with pool.connection() as conn:
        row = await _live_subscription_row(conn, user["id"])
        if row is None:
            raise HTTPException(status_code=404, detail="no live subscription")
        provider = _provider_or_503(row[1])
        try:
            await provider.cancel(_provider_ref(row), at_period_end=True)
        except ProviderError as exc:
            raise _provider_http_error(exc)
        await conn.execute(
            """UPDATE subscriptions SET cancel_at_period_end = TRUE, cancelled_at = NOW(),
                   cancellation_reason = 'user_request', updated_at = NOW() WHERE id = %s""",
            (row[0],),
        )
        await conn.commit()
        row = await _live_subscription_row(conn, user["id"])
    return {"status": "cancel_scheduled", "subscription": _subscription_public(row)}


@router.post("/resume")
async def resume(user: dict = Depends(get_current_user)) -> dict:
    pool = await db.get_pg()
    async with pool.connection() as conn:
        row = await _live_subscription_row(conn, user["id"])
        if row is None or not row[10]:
            raise HTTPException(status_code=404, detail="nothing to resume")
        provider = _provider_or_503(row[1])
        try:
            await provider.resume(_provider_ref(row))
        except ProviderError as exc:
            raise _provider_http_error(exc)
        await conn.execute(
            """UPDATE subscriptions SET cancel_at_period_end = FALSE, cancelled_at = NULL,
                   cancellation_reason = NULL, updated_at = NOW() WHERE id = %s""",
            (row[0],),
        )
        await conn.commit()
        row = await _live_subscription_row(conn, user["id"])
    return {"status": "resumed", "subscription": _subscription_public(row)}


@router.post("/change")
async def change_tier(body: ChangeTierRequest, user: dict = Depends(get_current_user)) -> dict:
    """Move a live subscription to another paid tier; seats are kept and re-priced."""
    s = get_settings()
    pool = await db.get_pg()
    async with pool.connection() as conn:
        row = await _live_subscription_row(conn, user["id"])
        if row is None:
            raise HTTPException(status_code=404, detail="no live subscription; use /billing/checkout")
        if row[2] == body.tier:
            raise HTTPException(status_code=409, detail="already on that tier")
        provider = _provider_or_503(row[1])
        rate = float(
            (await (await conn.execute(
                "SELECT usd_inr_rate FROM checkout_intents WHERE user_id = %s::uuid AND status = 'paid' "
                "ORDER BY completed_at DESC LIMIT 1", (user["id"],)
            )).fetchone() or [None])[0] or s.usd_inr_rate
        )
        q = pricing.quote(body.tier, row[4], row[5], rate)
        try:
            plan_ref = await provider.reprice(_provider_ref(row), q)
        except ProviderError as exc:
            raise _provider_http_error(exc)
        async with conn.cursor() as cur:
            await cur.execute(
                """UPDATE subscriptions SET tier = %s, amount_minor = %s,
                       provider_plan_ref = COALESCE(%s, provider_plan_ref), updated_at = NOW()
                   WHERE id = %s""",
                (body.tier, q.total_minor, plan_ref, row[0]),
            )
            await set_user_tier(cur, user["id"], effective_tier(body.tier, row[3]))
        await conn.commit()
        row = await _live_subscription_row(conn, user["id"])
    return {"status": "changed", "quote": q.as_dict(), "subscription": _subscription_public(row)}
