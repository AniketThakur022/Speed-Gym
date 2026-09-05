"""Offline entitlement token (SUB-10 / PAY-05).

Server signs `HMAC-SHA256(user_id:expires_at)` on every sync and on checkout
success (PAY-04). The client stores it and verifies locally, applying
`grace_days` past `expires_at` before downgrading to free and re-enabling ads.

UX only. The server re-validates tier on every online action; a forged token
buys a broken client and nothing else. The secret never leaves the server.

`expires_at` is the REAL entitlement horizon — the subscription's current
period end (trial end while trialing) — not "now + 3 days", so a paid learner
who is offline for a week does not lose Pro on day 4.
"""

from __future__ import annotations

import hashlib
import hmac
from datetime import datetime, timedelta, timezone
from typing import Optional

from ..config import get_settings
from .state import TIER_GRANTING_STATUSES


def sign_entitlement(user_id: str, tier: str, expires_at: datetime) -> dict:
    settings = get_settings()
    exp = int(expires_at.timestamp())
    payload = f"{user_id}:{exp}"
    signature = hmac.new(
        settings.offline_token_secret.encode(), payload.encode(), hashlib.sha256
    ).hexdigest()
    return {
        "tier": tier,
        "expires_at": exp,
        "grace_days": settings.billing_grace_days,
        "signature": signature,
    }


def verify_entitlement(user_id: str, expires_at: int, signature: str) -> bool:
    settings = get_settings()
    expected = hmac.new(
        settings.offline_token_secret.encode(), f"{user_id}:{expires_at}".encode(), hashlib.sha256
    ).hexdigest()
    return hmac.compare_digest(expected, signature)


async def _live_subscription(conn, user_id: str):
    return await (
        await conn.execute(
            """SELECT tier, status, current_period_end, trial_ends_at
               FROM subscriptions
               WHERE user_id = %s::uuid AND status IN ('active', 'trialing', 'past_due')
               ORDER BY updated_at DESC LIMIT 1""",
            (user_id,),
        )
    ).fetchone()


async def entitlement_for(conn, user_id: str, user_tier: str) -> dict:
    """Compute and sign the entitlement for a learner (or a child via parent)."""
    settings = get_settings()
    now = datetime.now(timezone.utc)

    row = await (
        await conn.execute(
            "SELECT account_type, parent_user_id FROM users WHERE id = %s::uuid", (user_id,)
        )
    ).fetchone()
    account_type, parent_id = (row[0], row[1]) if row else ("standard", None)

    anchor = str(parent_id) if account_type == "child" and parent_id else user_id
    sub = await _live_subscription(conn, anchor)

    if user_tier == "free":
        return sign_entitlement(user_id, "free", now)

    if sub is None:
        # Paid tier with no provider subscription (admin grant, referral reward,
        # or a lifetime ad-free unlock): re-signed each sync for one grace window.
        return sign_entitlement(user_id, user_tier, now + timedelta(days=settings.billing_grace_days))

    _tier, status, period_end, trial_end = sub
    horizon: Optional[datetime] = period_end or trial_end
    if status not in TIER_GRANTING_STATUSES or horizon is None:
        horizon = now + timedelta(days=settings.billing_grace_days)
    return sign_entitlement(user_id, user_tier, horizon)
