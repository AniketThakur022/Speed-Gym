"""Achievement catalogue (MULTIPLAYER_GAMING_ENGINE.md Appendix A, verbatim
keys) and the pure evaluator. Phase-2 modes are catalogued but tagged so the
client can hide them while their flags are dark."""

from __future__ import annotations

from typing import Any

P1, P2 = "phase_1_build", "phase_2_activation"

ACHIEVEMENTS: dict[str, dict[str, Any]] = {
    # competitive
    "first_win":        {"name": "First Victory", "tier": 1, "category": "competitive", "phase": P1},
    "win_streak_3":     {"name": "Hat Trick", "tier": 1, "category": "streak", "phase": P1},
    "win_streak_5":     {"name": "On Fire", "tier": 2, "category": "streak", "phase": P1},
    "win_streak_10":    {"name": "Unstoppable", "tier": 3, "category": "streak", "phase": P1},
    "win_streak_25":    {"name": "Legendary", "tier": 5, "category": "streak", "phase": P1},
    "speed_demon":      {"name": "Speed Demon", "tier": 2, "category": "competitive", "phase": P1,
                         "desc": "Win a Speed Race in under 60 seconds"},
    "perfect_game":     {"name": "Perfect Game", "tier": 3, "category": "competitive", "phase": P1,
                         "desc": "Win with 100% accuracy"},
    "comeback_king":    {"name": "Comeback King", "tier": 2, "category": "competitive", "phase": P1,
                         "desc": "Win after being in last place at halfway point"},
    # collaborative (phase 2 modes)
    "boss_slayer":      {"name": "Boss Slayer", "tier": 2, "category": "collaborative", "phase": P2, "flag": "boss_battle"},
    "boss_slayer_hard": {"name": "Dragon Slayer", "tier": 4, "category": "collaborative", "phase": P2, "flag": "boss_battle"},
    "team_player":      {"name": "Team Player", "tier": 1, "category": "collaborative", "phase": P2, "flag": "relay_race"},
    "clutch_solver":    {"name": "Clutch Solver", "tier": 3, "category": "collaborative", "phase": P2, "flag": "boss_battle"},
    # milestone
    "games_10":         {"name": "Getting Started", "tier": 1, "category": "milestone", "phase": P1},
    "games_100":        {"name": "Veteran", "tier": 2, "category": "milestone", "phase": P1},
    "games_500":        {"name": "Warrior", "tier": 3, "category": "milestone", "phase": P1},
    "games_1000":       {"name": "Grandmaster", "tier": 4, "category": "milestone", "phase": P1},
    "elo_1500":         {"name": "Contender", "tier": 2, "category": "milestone", "phase": P1},
    "elo_1800":         {"name": "Expert", "tier": 3, "category": "milestone", "phase": P1},
    "elo_2000":         {"name": "Master", "tier": 4, "category": "milestone", "phase": P1},
    "elo_2200":         {"name": "Grandmaster", "tier": 5, "category": "milestone", "phase": P1},
    # social
    "first_friend":     {"name": "Social Butterfly", "tier": 1, "category": "social", "phase": P1},
    "clan_founder":     {"name": "Founder", "tier": 2, "category": "social", "phase": P2, "flag": "virtual_hubs"},
    "clan_war_win":     {"name": "Clan Victor", "tier": 3, "category": "social", "phase": P2, "flag": "virtual_hubs"},
    # special
    "tournament_win":   {"name": "Champion", "tier": 4, "category": "special", "phase": P2, "flag": "tournament"},
    "tournament_top3":  {"name": "Podium Finish", "tier": 3, "category": "special", "phase": P2, "flag": "tournament"},
    "daily_top10":      {"name": "Daily Elite", "tier": 2, "category": "special", "phase": P1,
                         "desc": "Finish in top 10 of Daily Challenge"},
    "daily_top1":       {"name": "Daily Champion", "tier": 3, "category": "special", "phase": P1},
    "all_modes":        {"name": "Jack of All Games", "tier": 3, "category": "special", "phase": P2},
}


def evaluate(stats: dict[str, Any]) -> list[str]:
    """Keys satisfied by `stats`; the caller subtracts what is already unlocked.

    stats: won, mode, win_streak, matches_played, elo, accuracy_pct, duration_ms,
           comeback, friends_count, daily_rank (all optional).
    """
    out: list[str] = []
    won = bool(stats.get("won"))
    streak = int(stats.get("win_streak") or 0)
    played = int(stats.get("matches_played") or 0)
    elo = int(stats.get("elo") or 0)
    if won:
        out.append("first_win")
        if float(stats.get("accuracy_pct") or 0) >= 100:
            out.append("perfect_game")
        if stats.get("mode") == "speed_race" and (stats.get("duration_ms") or 10**9) < 60_000:
            out.append("speed_demon")
        if stats.get("comeback"):
            out.append("comeback_king")
    for n in (3, 5, 10, 25):
        if streak >= n:
            out.append(f"win_streak_{n}")
    for n in (10, 100, 500, 1000):
        if played >= n:
            out.append(f"games_{n}")
    for n in (1500, 1800, 2000, 2200):
        if elo >= n:
            out.append(f"elo_{n}")
    if int(stats.get("friends_count") or 0) >= 1:
        out.append("first_friend")
    rank = stats.get("daily_rank")
    if rank is not None:
        if rank <= 10:
            out.append("daily_top10")
        if rank == 1:
            out.append("daily_top1")
    return out


async def unlock(cur, user_id: str, keys: list[str]) -> list[str]:
    """Insert new unlocks; returns only the keys that were actually new."""
    fresh: list[str] = []
    for key in keys:
        if key not in ACHIEVEMENTS:
            continue
        await cur.execute(
            """INSERT INTO achievements_unlocked (user_id, achievement_key)
               VALUES (%s::uuid, %s) ON CONFLICT DO NOTHING""",
            (user_id, key),
        )
        if (cur.rowcount or 0) == 1:
            fresh.append(key)
    return fresh


async def unlocked_for(cur, user_id: str) -> dict[str, str]:
    await cur.execute(
        "SELECT achievement_key, unlocked_at FROM achievements_unlocked WHERE user_id = %s::uuid",
        (user_id,),
    )
    return {r[0]: r[1].isoformat() for r in await cur.fetchall()}
