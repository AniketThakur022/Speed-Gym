"""Payment webhooks — `/api/webhooks/razorpay` and `/api/webhooks/stripe`.

Server-to-server, outside the client prefix (api-contract-v1). Both are
signature-verified against the raw body (PAY-01/02) and idempotent on the
provider's event id (PAY-03): a redelivered event is acknowledged and ignored.

Response policy: 400 for a bad signature, 503 when the provider's webhook
secret is not configured (an unsigned webhook is NEVER accepted), and 200 for
every verified event — including ones we do not act on — so the provider
stops retrying. What happened is recorded in `payment_events`.

Sticky routing to the owner node (PAY-03) is a multi-node concern; Phase 1
runs one API node, and the idempotency ledger already makes replays safe.
"""

from __future__ import annotations

import hashlib
import json

from fastapi import APIRouter, HTTPException, Request

from .. import db
from ..billing.providers import (
    parse_razorpay_event,
    parse_stripe_event,
    verify_razorpay_webhook,
    verify_stripe_webhook,
)
from ..billing.state import apply_subscription_event, mark_payment_event, record_payment_event
from ..config import get_settings

router = APIRouter(prefix="/api/webhooks", tags=["webhooks"])


async def _ingest(provider: str, event_id: str, event_type: str, payload: dict, ev) -> dict:
    pool = await db.get_pg()
    async with pool.connection() as conn:
        async with conn.cursor() as cur:
            fresh = await record_payment_event(cur, provider, event_id, event_type, payload)
            if not fresh:
                await conn.commit()
                return {"status": "duplicate", "event_id": event_id}
            summary = await apply_subscription_event(cur, ev)
            await mark_payment_event(
                cur, provider, event_id,
                handled=bool(summary.get("handled")),
                user_id=summary.get("user_id"),
                note=summary.get("reason") or f"{summary.get('status')}→{summary.get('tier')}",
            )
        await conn.commit()
    return {
        "status": "ok",
        "event_id": event_id,
        "handled": bool(summary.get("handled")),
        "reason": summary.get("reason"),
    }


@router.post("/razorpay")
async def razorpay_webhook(request: Request) -> dict:
    s = get_settings()
    if not s.razorpay_webhook_secret:
        raise HTTPException(status_code=503, detail="razorpay webhook secret not configured")
    raw = await request.body()
    if not verify_razorpay_webhook(raw, request.headers.get("X-Razorpay-Signature", ""), s.razorpay_webhook_secret):
        raise HTTPException(status_code=400, detail="invalid razorpay signature")
    try:
        payload = json.loads(raw)
    except ValueError:
        raise HTTPException(status_code=400, detail="malformed json")
    # Razorpay sends x-razorpay-event-id; fall back to a body digest so a
    # missing header can never make the same delivery count twice.
    event_id = request.headers.get("X-Razorpay-Event-Id") or f"body:{hashlib.sha256(raw).hexdigest()}"
    ev = parse_razorpay_event(payload, event_id)
    return await _ingest("razorpay", event_id, ev.event_type or "unknown", payload, ev)


@router.post("/stripe")
async def stripe_webhook(request: Request) -> dict:
    s = get_settings()
    if not s.stripe_webhook_secret:
        raise HTTPException(status_code=503, detail="stripe webhook secret not configured")
    raw = await request.body()
    if not verify_stripe_webhook(raw, request.headers.get("Stripe-Signature", ""), s.stripe_webhook_secret):
        raise HTTPException(status_code=400, detail="invalid stripe signature")
    try:
        payload = json.loads(raw)
    except ValueError:
        raise HTTPException(status_code=400, detail="malformed json")
    ev = parse_stripe_event(payload)
    if not ev.event_id:
        raise HTTPException(status_code=400, detail="event id missing")
    return await _ingest("stripe", ev.event_id, ev.event_type or "unknown", payload, ev)
