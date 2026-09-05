"""XP, levels, streaks and the XP leaderboard.

Awards are idempotent on (user, reason, ref): a replayed sync batch or a
redelivered match result pays once. Streaks are calendar-day based (UTC).
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Optional

XP_RULES: dict[str, int] = {
    "practice_correct": 10,
    "session_complete": 25,
    "streak_day": 20,
    "duel_win": 50,
    "duel_loss": 15,
    "daily_challenge_complete": 50,
    "daily_challenge_correct": 10,
    "ghost_race_win": 30,
    "friend_added": 10,
}
LEVEL_XP = 500


def level_for(xp: int) -> int:
    return max(1, xp // LEVEL_XP + 1)


async def award(cur, user_id: str, reason: str, ref: str, delta: Optional[int] = None) -> int:
    """Returns the XP actually added (0 when this (reason, ref) was seen before)."""
    amount = XP_RULES[reason] if delta is None else int(delta)
    if amount == 0:
        return 0
    await cur.execute(
        """INSERT INTO xp_ledger (user_id, delta, reason, ref) VALUES (%s::uuid, %s, %s, %s)
           ON CONFLICT DO NOTHING""",
        (user_id, amount, reason, ref[:120]),
    )
    if (cur.rowcount or 0) == 0:
        return 0
    await cur.execute(
        """INSERT INTO user_xp (user_id, xp) VALUES (%s::uuid, %s)
           ON CONFLICT (user_id) DO UPDATE SET xp = GREATEST(0, user_xp.xp + EXCLUDED.xp), updated_at = NOW()""",
        (user_id, amount),
    )
    return amount


async def total_xp(cur, user_id: str) -> int:
    await cur.execute("SELECT xp FROM user_xp WHERE user_id = %s::uuid", (user_id,))
    row = await cur.fetchone()
    return int(row[0]) if row else 0


async def record_activity_day(cur, user_id: str, day: date, problems: int = 0) -> dict:
    """Mark `day` active; extend/reset the streak. Returns the streak state and
    whether the day was new (so the caller can award streak XP once)."""
    await cur.execute(
        """INSERT INTO streak_days (user_id, activity_date, problems) VALUES (%s::uuid, %s, %s)
           ON CONFLICT (user_id, activity_date) DO UPDATE
             SET problems = streak_days.problems + EXCLUDED.problems""",
        (user_id, day, problems),
    )
    await cur.execute(
        "SELECT current_streak, longest_streak, last_activity_date FROM streaks WHERE user_id = %s::uuid",
        (user_id,),
    )
    row = await cur.fetchone()
    current, longest, last = (row[0], row[1], row[2]) if row else (0, 0, None)
    new_day = last != day
    if last == day:
        pass
    elif last == day - timedelta(days=1):
        current += 1
    elif last is not None and last > day:
        new_day = False        # a backfilled older day never rewinds the streak
    else:
        current = 1
    longest = max(longest, current)
    if new_day:
        await cur.execute(
            """INSERT INTO streaks (user_id, current_streak, longest_streak, last_activity_date)
               VALUES (%s::uuid, %s, %s, %s)
               ON CONFLICT (user_id) DO UPDATE SET current_streak = EXCLUDED.current_streak,
                 longest_streak = EXCLUDED.longest_streak,
                 last_activity_date = EXCLUDED.last_activity_date, updated_at = NOW()""",
            (user_id, current, longest, day),
        )
    return {"current": current, "longest": longest, "new_day": new_day}


async def streak_state(cur, user_id: str, today: date) -> dict:
    await cur.execute(
        "SELECT current_streak, longest_streak, last_activity_date FROM streaks WHERE user_id = %s::uuid",
        (user_id,),
    )
    row = await cur.fetchone()
    if not row:
        return {"current": 0, "longest": 0, "last_activity_date": None}
    current, longest, last = row
    # A streak that skipped yesterday is over, even before the next activity.
    if last is not None and last < today - timedelta(days=1):
        current = 0
    return {"current": int(current), "longest": int(longest), "last_activity_date": last.isoformat() if last else None}


async def week_days(cur, user_id: str, today: date) -> list[bool]:
    """Mon..Sun of the current ISO week, True where the learner was active."""
    monday = today - timedelta(days=today.weekday())
    await cur.execute(
        """SELECT activity_date FROM streak_days
           WHERE user_id = %s::uuid AND activity_date BETWEEN %s AND %s""",
        (user_id, monday, monday + timedelta(days=6)),
    )
    active = {r[0] for r in await cur.fetchall()}
    return [(monday + timedelta(days=i)) in active for i in range(7)]


async def leaderboard(cur, user_id: str, limit: int = 10) -> tuple[list[dict], Optional[dict], int]:
    """Top N by XP plus the caller's own row and rank. Ties share a rank."""
    await cur.execute(
        """SELECT x.user_id, u.display_name, x.xp, RANK() OVER (ORDER BY x.xp DESC) AS rnk
           FROM user_xp x JOIN users u ON u.id = x.user_id
           ORDER BY x.xp DESC, u.created_at LIMIT %s""",
        (limit,),
    )
    top = [{"user_id": str(r[0]), "name": r[1], "xp": int(r[2]), "rank": int(r[3])} for r in await cur.fetchall()]
    await cur.execute(
        """SELECT rnk, xp, total FROM (
               SELECT user_id, xp, RANK() OVER (ORDER BY xp DESC) AS rnk, COUNT(*) OVER () AS total
               FROM user_xp) t WHERE user_id = %s::uuid""",
        (user_id,),
    )
    row = await cur.fetchone()
    me = {"rank": int(row[0]), "xp": int(row[1])} if row else None
    total = int(row[2]) if row else len(top)
    return top, me, total


def percentile(rank: Optional[int], total: int) -> int:
    """Higher is better: rank 1 of 100 → 99."""
    if not rank or total <= 0:
        return 0
    return max(0, min(99, round(100 * (1 - (rank - 0.5) / total))))
