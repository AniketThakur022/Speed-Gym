"""Billing enforcement — the safety net behind provider webhooks.

Providers tell us about failed charges and cancellations; this task closes the
windows they leave open:

* `past_due` older than the grace window → `unpaid`, tier dropped (SUB-10).
* `cancel_at_period_end` whose period has closed → `cancelled`, tier dropped.
* `trialing` past trial end with no provider signal for a grace window →
  logged, NOT downgraded (the provider owns the trial-to-paid transition; a
  silent webhook outage must not punish learners).
* `checkout_intents` pending > 24 h → `expired`.

Tier derivation for family children mirrors billing/state.py: the parent's
tier while the seat is active, free otherwise.
"""

from __future__ import annotations

import os

from worker.app import app

GRACE_DAYS = int(os.environ.get("BILLING_GRACE_DAYS", "3"))


def _pg():
    import psycopg

    return psycopg.connect(os.environ.get("DATABASE_URL", "postgresql://vmsg:vmsg@localhost:5432/vmsg"))


_SYNC_FAMILY = """
UPDATE users AS c
SET tier = CASE WHEN fs.status = 'active' THEN p.tier ELSE 'free' END, updated_at = NOW()
FROM family_seats fs
JOIN family_accounts fa ON fa.family_id = fs.family_id
JOIN users p ON p.id = fa.parent_user_id
WHERE fs.child_user_id = c.id AND fa.parent_user_id = ANY(%s::uuid[])
"""


@app.task(name="billing.enforce_grace_and_expiry")
def enforce_grace_and_expiry() -> dict:
    summary = {"past_due_expired": 0, "cancellations_closed": 0, "intents_expired": 0, "trials_overdue": 0}
    with _pg() as conn:
        # 1. dunning grace exhausted
        rows = conn.execute(
            """UPDATE subscriptions
               SET status = 'unpaid', cancelled_at = COALESCE(cancelled_at, NOW()),
                   cancellation_reason = COALESCE(cancellation_reason, 'grace_exhausted'),
                   updated_at = NOW()
               WHERE status = 'past_due'
                 AND COALESCE(current_period_end, updated_at) + make_interval(days => %s) < NOW()
               RETURNING user_id""",
            (GRACE_DAYS,),
        ).fetchall()
        users = [str(r[0]) for r in rows]
        summary["past_due_expired"] = len(users)

        # 2. scheduled cancellations whose period closed
        rows = conn.execute(
            """UPDATE subscriptions
               SET status = 'cancelled', updated_at = NOW()
               WHERE status IN ('active', 'trialing') AND cancel_at_period_end
                 AND current_period_end IS NOT NULL AND current_period_end < NOW()
               RETURNING user_id"""
        ).fetchall()
        closed = [str(r[0]) for r in rows]
        summary["cancellations_closed"] = len(closed)
        users += closed

        if users:
            conn.execute(
                "UPDATE users SET tier = 'free', updated_at = NOW() WHERE id = ANY(%s::uuid[])",
                (users,),
            )
            conn.execute(_SYNC_FAMILY, (users,))

        # 3. trials overdue with no provider signal — observe only
        summary["trials_overdue"] = conn.execute(
            """SELECT COUNT(*) FROM subscriptions
               WHERE status = 'trialing' AND trial_ends_at IS NOT NULL
                 AND trial_ends_at + make_interval(days => %s) < NOW()""",
            (GRACE_DAYS,),
        ).fetchone()[0]

        # 4. abandoned checkouts
        summary["intents_expired"] = conn.execute(
            """UPDATE checkout_intents SET status = 'expired', completed_at = NOW()
               WHERE status = 'pending' AND created_at < NOW() - INTERVAL '24 hours'"""
        ).rowcount
        conn.commit()
    return {"status": "ok", **summary}
