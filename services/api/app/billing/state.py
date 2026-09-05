"""The subscription state machine and family-tier sync.

One function, `apply_subscription_event`, is the only path by which a provider
signal changes a learner's tier. Both webhooks and the Razorpay checkout-verify
route go through it, so the two processors cannot drift on what "active",
"past_due" or "cancelled" mean for entitlement.

Tier grant rule (SUB-10 / PAY-05): `trialing`, `active` and `past_due` keep the
paid tier — past_due is the dunning/grace window, enforced by the worker after
`billing_grace_days`. `unpaid` and `cancelled` drop to free immediately.

Family (FAM-PRC-*): a child's tier is DERIVED — the parent's tier while the
seat is active, free otherwise. Any change to the parent's subscription or a
seat toggle re-derives every child in one statement; children never hold an
independent entitlement.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any, Optional

from .providers import SubscriptionEvent

TIER_GRANTING_STATUSES = frozenset({"active", "trialing", "past_due"})


def effective_tier(tier: str, status: Optional[str]) -> str:
    return tier if status in TIER_GRANTING_STATUSES else "free"


async def sync_family_tiers(cur, parent_user_id: str, parent_tier: str) -> int:
    """Re-derive every child's tier from the parent's. Returns rows touched."""
    await cur.execute(
        """UPDATE users AS c
           SET tier = CASE WHEN fs.status = 'active' THEN %s ELSE 'free' END,
               updated_at = NOW()
           FROM family_seats fs
           JOIN family_accounts fa ON fa.family_id = fs.family_id
           WHERE fa.parent_user_id = %s::uuid AND fs.child_user_id = c.id""",
        (parent_tier, parent_user_id),
    )
    return cur.rowcount or 0


async def set_user_tier(cur, user_id: str, tier: str) -> None:
    await cur.execute(
        "UPDATE users SET tier = %s, updated_at = NOW() WHERE id = %s::uuid", (tier, user_id)
    )
    await sync_family_tiers(cur, user_id, tier)


async def _find_subscription(cur, provider: str, subscription_ref: Optional[str]):
    if not subscription_ref:
        return None
    column = "razorpay_subscription_id" if provider == "razorpay" else "stripe_subscription_id"
    await cur.execute(
        f"""SELECT id, user_id, tier, status, seats_count, current_period_end, trial_ends_at
            FROM subscriptions WHERE {column} = %s""",
        (subscription_ref,),
    )
    return await cur.fetchone()


async def _find_intent(cur, provider: str, intent_id: Optional[str], user_id: Optional[str]):
    """The pending intent this event settles: by id first, else the user's
    latest pending intent on this provider."""
    if intent_id:
        await cur.execute(
            """SELECT id, user_id, tier, seats_count, currency, amount_minor, trial_days,
                      provider_plan_ref, status
               FROM checkout_intents WHERE id = %s::uuid AND provider = %s""",
            (intent_id, provider),
        )
        row = await cur.fetchone()
        if row:
            return row
    if user_id:
        await cur.execute(
            """SELECT id, user_id, tier, seats_count, currency, amount_minor, trial_days,
                      provider_plan_ref, status
               FROM checkout_intents
               WHERE user_id = %s::uuid AND provider = %s AND status = 'pending'
               ORDER BY created_at DESC LIMIT 1""",
            (user_id, provider),
        )
        return await cur.fetchone()
    return None


async def apply_subscription_event(cur, ev: SubscriptionEvent) -> dict[str, Any]:
    """Apply one normalised provider event inside the caller's transaction.

    Returns a summary; `handled` is False when the event could not be tied to
    a learner (logged, acknowledged, never retried into a wrong account).
    """
    if not ev.relevant:
        return {"handled": False, "reason": "not_a_subscription_event"}

    ref_col = "razorpay_subscription_id" if ev.provider == "razorpay" else "stripe_subscription_id"
    cust_col = "razorpay_customer_id" if ev.provider == "razorpay" else "stripe_customer_id"
    now = datetime.now(timezone.utc)

    sub = await _find_subscription(cur, ev.provider, ev.subscription_ref)
    created = False

    if sub is None:
        intent = await _find_intent(cur, ev.provider, ev.intent_id, ev.user_id)
        if intent is None:
            return {"handled": False, "reason": "unresolved_subscription"}
        intent_id, user_id, tier, seats, currency, amount, trial_days, plan_ref, istatus = intent

        # A cancellation for something we never activated: settle the intent, no tier.
        if ev.status in ("cancelled", "unpaid"):
            await cur.execute(
                "UPDATE checkout_intents SET status = 'failed', completed_at = NOW() WHERE id = %s",
                (intent_id,),
            )
            return {"handled": True, "user_id": str(user_id), "reason": "intent_failed"}

        status = ev.status or ("trialing" if trial_days > 0 else "active")
        # Provider may not yet report a period (Stripe checkout.session.completed);
        # a trial's entitlement runs to trial end, else to whatever the provider said.
        period_end = ev.period_end or ev.trial_end
        await cur.execute(
            f"""INSERT INTO subscriptions
                   (user_id, provider, {ref_col}, {cust_col}, tier, status, provider_plan_ref,
                    seats_count, currency, amount_minor, monthly_recurring_revenue_cents,
                    trial_started_at, trial_ends_at, current_period_start, current_period_end,
                    cancel_at_period_end, last_event_at)
               VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
               RETURNING id""",
            (
                user_id, ev.provider, ev.subscription_ref, ev.customer_ref, tier, status, plan_ref,
                seats, currency, amount, amount if currency == "USD" else 0,
                now if trial_days > 0 else None, ev.trial_end, ev.period_start, period_end,
                bool(ev.cancel_at_period_end), now,
            ),
        )
        sub_id = (await cur.fetchone())[0]
        await cur.execute(
            """UPDATE checkout_intents SET status = 'paid', completed_at = NOW(),
                   provider_ref = COALESCE(provider_ref, %s)
               WHERE id = %s""",
            (ev.subscription_ref, intent_id),
        )
        created = True
        user_id = str(user_id)
    else:
        sub_id, user_id, tier, status, seats, cur_period_end, cur_trial_end = sub
        user_id = str(user_id)
        # The provider ref is authoritative, but an event that ALSO names a
        # different learner is a mis-link (or a forged notes field): apply it
        # to nobody rather than guess.
        if ev.user_id and ev.user_id != user_id:
            return {"handled": False, "reason": "user_mismatch", "user_id": user_id}
        if ev.status is not None:
            status = ev.status
        sets = ["status = %s", "last_event_at = %s", "updated_at = NOW()"]
        params: list[Any] = [status, now]
        if ev.period_start is not None:
            sets.append("current_period_start = %s"); params.append(ev.period_start)
        if ev.period_end is not None:
            sets.append("current_period_end = %s"); params.append(ev.period_end)
        if ev.trial_end is not None:
            sets.append("trial_ends_at = %s"); params.append(ev.trial_end)
        if ev.cancel_at_period_end is not None:
            sets.append("cancel_at_period_end = %s"); params.append(ev.cancel_at_period_end)
        if ev.customer_ref:
            sets.append(f"{cust_col} = COALESCE({cust_col}, %s)"); params.append(ev.customer_ref)
        if status in ("cancelled", "unpaid"):
            sets.append("cancelled_at = COALESCE(cancelled_at, %s)"); params.append(now)
            sets.append("cancellation_reason = COALESCE(cancellation_reason, %s)")
            params.append(ev.event_type)
        if ev.amount_minor and ev.status == "active" and ev.event_type in (
            "subscription.charged", "invoice.paid"
        ):
            sets.append("total_revenue_cents = total_revenue_cents + %s"); params.append(ev.amount_minor)
        params.append(sub_id)
        await cur.execute(f"UPDATE subscriptions SET {', '.join(sets)} WHERE id = %s", params)

    new_tier = effective_tier(tier, status)
    await set_user_tier(cur, user_id, new_tier)
    return {
        "handled": True,
        "created": created,
        "user_id": user_id,
        "subscription_id": str(sub_id),
        "status": status,
        "tier": new_tier,
    }


async def record_payment_event(
    cur, provider: str, event_id: str, event_type: str, payload: dict
) -> bool:
    """Idempotency ledger. Returns False when this event was already seen."""
    await cur.execute(
        """INSERT INTO payment_events (provider, event_id, event_type, payload)
           VALUES (%s, %s, %s, %s) ON CONFLICT DO NOTHING""",
        (provider, event_id, event_type, json.dumps(payload)),
    )
    return (cur.rowcount or 0) == 1


async def mark_payment_event(
    cur, provider: str, event_id: str, *, handled: bool, user_id: Optional[str], note: str
) -> None:
    await cur.execute(
        """UPDATE payment_events SET handled = %s, user_id = %s::uuid, note = %s
           WHERE provider = %s AND event_id = %s""",
        (handled, user_id, note[:200], provider, event_id),
    )
