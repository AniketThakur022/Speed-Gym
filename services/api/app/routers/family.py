"""Family plans — `/api/v1/family/*` (architecture §10: parent anchor + ≤3
child seats, 100/80/60 % curve, active/suspend toggle; FAM-PRC-*).

A child is a real `users` row with `account_type='child'` and a parent anchor.
Its tier is derived from the parent's subscription and the seat's status —
never set directly, never billed separately. Adding or removing a seat
re-prices the parent's subscription with the provider; suspending does not
(the seat is still owned; suspension is a parental control, not a refund).

Seat pricing is by RANK among the family's seats (1st/2nd/3rd → 100/80/60 %),
and the stored `discount_pct` is recomputed whenever seats change, so what the
family screen shows always matches what the provider bills.

Creating a seat with a payment card on file is the verifiable parental consent
(COPPA "credit card" method); `parental_consent_at/by` record it.
"""

from __future__ import annotations

from typing import Literal, Optional

import psycopg
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, EmailStr, Field

from .. import db
from ..billing import pricing
from ..billing.providers import ProviderError, get_provider
from ..billing.state import effective_tier, sync_family_tiers
from ..config import get_settings
from ..security import get_current_user, hash_password

router = APIRouter(prefix="/family", tags=["family"])


class CreateSeatRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)
    display_name: Optional[str] = Field(default=None, max_length=100)
    age: int = Field(ge=8, le=17)


class OverrideSeatRequest(BaseModel):
    child_user_id: str
    status: Literal["active", "suspended"]


class RemoveSeatRequest(BaseModel):
    child_user_id: str


async def _parent_context(conn, user: dict):
    """Parent must be a standard account; returns the live subscription (or None)."""
    row = await (
        await conn.execute("SELECT account_type FROM users WHERE id = %s::uuid", (user["id"],))
    ).fetchone()
    if row and row[0] == "child":
        raise HTTPException(status_code=403, detail="child accounts cannot manage a family")
    return await (
        await conn.execute(
            """SELECT id, provider, tier, status, seats_count, currency,
                      razorpay_subscription_id, stripe_subscription_id, usd_inr_rate
               FROM subscriptions
               WHERE user_id = %s::uuid AND status IN ('active', 'trialing', 'past_due')
               ORDER BY updated_at DESC LIMIT 1""",
            (user["id"],),
        )
    ).fetchone()


async def _family_id(conn, parent_user_id: str, create: bool) -> Optional[str]:
    row = await (
        await conn.execute(
            "SELECT family_id FROM family_accounts WHERE parent_user_id = %s::uuid", (parent_user_id,)
        )
    ).fetchone()
    if row:
        return str(row[0])
    if not create:
        return None
    row = await (
        await conn.execute(
            "INSERT INTO family_accounts (parent_user_id) VALUES (%s::uuid) RETURNING family_id",
            (parent_user_id,),
        )
    ).fetchone()
    return str(row[0])


async def _seats(conn, family_id: str) -> list[dict]:
    rows = await (
        await conn.execute(
            """SELECT fs.seat_number, fs.status, fs.discount_pct, fs.child_user_id,
                      u.email, u.display_name, u.age, u.tier, fs.parental_consent_at
               FROM family_seats fs LEFT JOIN users u ON u.id = fs.child_user_id
               WHERE fs.family_id = %s::uuid ORDER BY fs.seat_number""",
            (family_id,),
        )
    ).fetchall()
    return [
        {
            "seat_number": r[0],
            "status": r[1],
            "discount_pct": r[2],
            "child_user_id": str(r[3]) if r[3] else None,
            "email": r[4],
            "display_name": r[5],
            "age": r[6],
            "effective_tier": r[7],
            "kids_mode": bool(r[6] is not None and r[6] < 13),
            "parental_consent_at": r[8].isoformat() if r[8] else None,
        }
        for r in rows
    ]


async def _recompute_seat_discounts(conn, family_id: str) -> int:
    """discount_pct follows the seat's RANK (by seat_number), matching the
    count-based quote. Returns the number of seats."""
    await conn.execute(
        """UPDATE family_seats fs
           SET discount_pct = CASE r.rn WHEN 1 THEN 100 WHEN 2 THEN 80 ELSE 60 END,
               updated_at = NOW()
           FROM (SELECT id, ROW_NUMBER() OVER (ORDER BY seat_number) AS rn
                 FROM family_seats WHERE family_id = %s::uuid) r
           WHERE fs.id = r.id""",
        (family_id,),
    )
    row = await (
        await conn.execute("SELECT COUNT(*) FROM family_seats WHERE family_id = %s::uuid", (family_id,))
    ).fetchone()
    return int(row[0])


async def _reprice(conn, sub_row, seats_count: int) -> dict:
    """Re-price the parent's subscription for the new seat count.

    Never silent: if the provider cannot be told, the seat change is refused,
    because a seat that is granted but not billed is a revenue leak that no
    later webhook will notice.
    """
    (sub_id, provider_name, tier, _status, _seats, currency, rz, st, rate) = sub_row
    s = get_settings()
    rate = float(rate) if rate else s.usd_inr_rate
    q = pricing.quote(tier, seats_count, currency, rate)
    provider = get_provider(provider_name)
    ref = rz if provider_name == "razorpay" else st
    if not provider.configured():
        raise HTTPException(
            status_code=503, detail=f"{provider_name} is not configured; seat change refused"
        )
    if not ref:
        raise HTTPException(
            status_code=409, detail="subscription has no provider reference; seat change refused"
        )
    try:
        plan_ref = await provider.reprice(ref, q)
    except ProviderError as exc:
        raise HTTPException(status_code=getattr(exc, "status_code", 502), detail=str(exc))
    await conn.execute(
        """UPDATE subscriptions SET seats_count = %s, amount_minor = %s,
               monthly_recurring_revenue_cents = %s,
               provider_plan_ref = COALESCE(%s, provider_plan_ref), updated_at = NOW()
           WHERE id = %s""",
        (seats_count, q.total_minor, pricing.to_usd_cents(q.total_minor, currency, rate), plan_ref, sub_id),
    )
    return q.as_dict()


@router.get("")
async def family(user: dict = Depends(get_current_user)) -> dict:
    pool = await db.get_pg()
    async with pool.connection() as conn:
        fid = await _family_id(conn, user["id"], create=False)
        seats = await _seats(conn, fid) if fid else []
    return {
        "family_id": fid,
        "parent_user_id": user["id"],
        "parent_tier": user["tier"],
        "max_seats": pricing.MAX_FAMILY_SEATS,
        "seats": seats,
    }


@router.post("/sub-account/create")
async def create_sub_account(body: CreateSeatRequest, user: dict = Depends(get_current_user)) -> dict:
    pool = await db.get_pg()
    async with pool.connection() as conn:
        sub = await _parent_context(conn, user)
        if sub is None or effective_tier(sub[2], sub[3]) == "free":
            raise HTTPException(status_code=402, detail="family seats need a live paid subscription")
        parent_tier = effective_tier(sub[2], sub[3])

        fid = await _family_id(conn, user["id"], create=True)
        taken = {
            r[0]
            for r in await (
                await conn.execute(
                    "SELECT seat_number FROM family_seats WHERE family_id = %s::uuid", (fid,)
                )
            ).fetchall()
        }
        if len(taken) >= pricing.MAX_FAMILY_SEATS:
            raise HTTPException(status_code=409, detail=f"family already has {pricing.MAX_FAMILY_SEATS} seats")
        seat_number = next(n for n in range(1, pricing.MAX_FAMILY_SEATS + 1) if n not in taken)

        # Re-seating: a child of THIS parent whose seat was removed keeps their
        # account and history; anyone else's email is refused as taken.
        existing = await (
            await conn.execute(
                """SELECT id, account_type, parent_user_id FROM users WHERE email = %s""",
                (body.email.lower(),),
            )
        ).fetchone()
        if existing is not None:
            if existing[1] != "child" or str(existing[2]) != user["id"]:
                raise HTTPException(status_code=409, detail="email already registered")
            seated = await (
                await conn.execute(
                    "SELECT 1 FROM family_seats WHERE child_user_id = %s::uuid", (existing[0],)
                )
            ).fetchone()
            if seated:
                raise HTTPException(status_code=409, detail="that child already has a seat")
            child_id = str(existing[0])
            await conn.execute(
                "UPDATE users SET age = %s, display_name = COALESCE(%s, display_name), updated_at = NOW() WHERE id = %s::uuid",
                (body.age, body.display_name, child_id),
            )
        else:
            try:
                child = await (
                    await conn.execute(
                        """INSERT INTO users (email, password_hash, display_name, age, tier,
                                              account_type, parent_user_id)
                           VALUES (%s, %s, %s, %s, %s, 'child', %s::uuid)
                           RETURNING id""",
                        (
                            body.email.lower(), hash_password(body.password), body.display_name,
                            body.age, parent_tier, user["id"],
                        ),
                    )
                ).fetchone()
            except psycopg.errors.UniqueViolation:
                await conn.rollback()
                raise HTTPException(status_code=409, detail="email already registered")
            child_id = str(child[0])

        await conn.execute(
            """INSERT INTO family_seats
                   (family_id, child_user_id, seat_number, status, discount_pct,
                    parental_consent_at, parental_consent_by)
               VALUES (%s::uuid, %s::uuid, %s, 'active', 100, NOW(), %s::uuid)""",
            (fid, child_id, seat_number, user["id"]),
        )
        seats_count = await _recompute_seat_discounts(conn, fid)
        quote_dict = await _reprice(conn, sub, seats_count)
        async with conn.cursor() as cur:
            await sync_family_tiers(cur, user["id"], parent_tier)
        await conn.commit()
        seats = await _seats(conn, fid)

    return {
        "family_id": fid,
        "seat": next(s for s in seats if s["child_user_id"] == child_id),
        "seats": seats,
        "quote": quote_dict,
    }


@router.post("/sub-account/override")
async def override_seat(body: OverrideSeatRequest, user: dict = Depends(get_current_user)) -> dict:
    """Parental active/suspend toggle. Billing is unchanged; the child's tier
    re-derives immediately (suspended → free)."""
    pool = await db.get_pg()
    async with pool.connection() as conn:
        sub = await _parent_context(conn, user)
        fid = await _family_id(conn, user["id"], create=False)
        if fid is None:
            raise HTTPException(status_code=404, detail="no family")
        updated = await conn.execute(
            """UPDATE family_seats SET status = %s, updated_at = NOW()
               WHERE family_id = %s::uuid AND child_user_id = %s::uuid""",
            (body.status, fid, body.child_user_id),
        )
        if (updated.rowcount or 0) == 0:
            # Decided by THIS seat's row, never by how many other children synced.
            raise HTTPException(status_code=404, detail="no such seat in this family")
        parent_tier = effective_tier(sub[2], sub[3]) if sub else "free"
        async with conn.cursor() as cur:
            await sync_family_tiers(cur, user["id"], parent_tier)
        await conn.commit()
        seats = await _seats(conn, fid)
    return {"family_id": fid, "seats": seats}


@router.post("/sub-account/remove")
async def remove_seat(body: RemoveSeatRequest, user: dict = Depends(get_current_user)) -> dict:
    """Free the seat and re-price down. The child account stays (free tier)
    and can be re-seated later by the same parent."""
    pool = await db.get_pg()
    async with pool.connection() as conn:
        sub = await _parent_context(conn, user)
        fid = await _family_id(conn, user["id"], create=False)
        if fid is None:
            raise HTTPException(status_code=404, detail="no family")
        deleted = await conn.execute(
            "DELETE FROM family_seats WHERE family_id = %s::uuid AND child_user_id = %s::uuid",
            (fid, body.child_user_id),
        )
        if (deleted.rowcount or 0) == 0:
            raise HTTPException(status_code=404, detail="no such seat in this family")
        await conn.execute(
            "UPDATE users SET tier = 'free', updated_at = NOW() WHERE id = %s::uuid AND parent_user_id = %s::uuid",
            (body.child_user_id, user["id"]),
        )
        remaining = await _recompute_seat_discounts(conn, fid)
        quote_dict = await _reprice(conn, sub, remaining) if sub else None
        await conn.commit()
        seats = await _seats(conn, fid)
    return {"family_id": fid, "seats": seats, "quote": quote_dict}
