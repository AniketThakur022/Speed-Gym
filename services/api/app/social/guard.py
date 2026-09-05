"""Leaderboard anxiety guard (MULTIPLAYER_GAMING_ENGINE.md §5.4).

Rules the server can actually decide with what it holds:
* post-match cooldown — hidden for 60 s after the last match result;
* cognitive state from the latest BKT snapshot — mostly FRACTURED → hidden,
  mostly FRAGILE → percentile only;
* kids mode → percentile only (COPPA: no names, no ranks of others).
"In an active match" is game-server memory, not persisted; that rule lives in
the game server, which hides the leaderboard affordance during a match.
"""

from __future__ import annotations

from typing import Optional

POST_MATCH_COOLDOWN_SECONDS = 60


def cognitive_mode(states: Optional[dict]) -> str:
    """'hidden' | 'percentile_only' | 'full' from a technique_states map."""
    if not states:
        return "full"
    labels = [str((v or {}).get("state", "")).lower() for v in states.values() if isinstance(v, dict)]
    if not labels:
        return "full"
    fractured = sum(1 for s in labels if s == "fractured") / len(labels)
    fragile = sum(1 for s in labels if s == "fragile") / len(labels)
    if fractured >= 0.5:
        return "hidden"
    if fragile >= 0.5:
        return "percentile_only"
    return "full"


async def leaderboard_mode(conn, user_id: str, kid: bool) -> tuple[str, str]:
    row = await (
        await conn.execute(
            """SELECT EXTRACT(EPOCH FROM (NOW() - MAX(created_at)))
               FROM player_match_results WHERE user_id = %s::uuid""",
            (user_id,),
        )
    ).fetchone()
    since = row[0] if row and row[0] is not None else None
    if since is not None and float(since) < POST_MATCH_COOLDOWN_SECONDS:
        return "hidden", f"available in {int(POST_MATCH_COOLDOWN_SECONDS - float(since))}s"
    snap = await (
        await conn.execute(
            """SELECT technique_states FROM bkt_state_snapshots
               WHERE user_id = %s::uuid ORDER BY created_at DESC LIMIT 1""",
            (user_id,),
        )
    ).fetchone()
    mode = cognitive_mode(snap[0] if snap else None)
    if mode == "hidden":
        return "hidden", "unavailable in recovery mode"
    if kid or mode == "percentile_only":
        return "percentile_only", "kids_mode" if kid else "fragile"
    return "full", "ok"
