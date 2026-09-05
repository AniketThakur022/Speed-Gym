"""COPPA kids mode (FAM-05 / SEC-08) and the taunt gates (SOC-15 / SOC-16).

Kids mode (age < 13): ads off, tracking minimised, parental consent gated,
timers suppressed, sessions capped (10 min; parent override up to 20), bots
disabled, leaderboard percentile-only, clips off, friends parent-managed.

Taunts: cluster-gated frequency — Sprinter every 3 matches, Perfectionist every
5, Deliberate/Rebuilder never (SOC-15); 3+ consecutive losses disables them;
ads & taunts off for age < 10 (SOC-16). Clusters the spec does not name get a
conservative default (every 4) — an ASSUMPTION, marked as such.
"""

from __future__ import annotations

from typing import Optional

KIDS_AGE_LIMIT = 13
TAUNT_MIN_AGE = 10
ADS_MIN_AGE = 10
KIDS_SESSION_CAP_MINUTES = 10
KIDS_SESSION_CAP_PARENT_MAX = 20

TAUNT_EVERY_N_MATCHES: dict[str, int] = {
    "sprinter": 3,
    "perfectionist": 5,
    "deliberate": 0,
    "rebuilder": 0,
}
TAUNT_DEFAULT_EVERY_N = 4          # assumption for balanced / wanderer / parent / unknown
TAUNT_LOSS_STREAK_OFF = 3


def is_kid(age: Optional[int]) -> bool:
    return age is not None and age < KIDS_AGE_LIMIT


def kids_policy(age: Optional[int], account_type: str = "standard",
                session_cap_minutes: Optional[int] = None) -> dict:
    """The per-user policy the client and the game server both read.

    Age unknown is treated as adult for ads/taunts but NOT for bots: the game
    server refuses bots without a confirmed age, and we report that honestly.
    """
    kid = is_kid(age)
    known = age is not None
    cap = None
    if kid:
        cap = min(int(session_cap_minutes or KIDS_SESSION_CAP_MINUTES), KIDS_SESSION_CAP_PARENT_MAX)
    return {
        "kids_mode": kid,
        "account_type": account_type,
        "age_known": known,
        "ads_enabled": (not kid) and (not known or age >= ADS_MIN_AGE),
        "bots_enabled": known and not kid,
        "taunts_enabled": known and age >= TAUNT_MIN_AGE and not kid,
        "timers_suppressed": kid,
        "session_cap_minutes": cap,
        "tracking_minimized": kid,
        "leaderboard": "percentile_only" if kid else "full",
        "clips_enabled": not kid,
        "friends": "parent_managed" if kid else "open",
        "parental_consent_required": kid,
    }


def taunt_decision(age: Optional[int], cluster: Optional[str], matches_since_last_taunt: int,
                   consecutive_losses: int, opted_in: bool = True) -> tuple[bool, str]:
    if not opted_in:
        return False, "opted_out"
    if age is None or age < TAUNT_MIN_AGE:
        return False, "age_gate"           # SOC-16
    if is_kid(age):
        return False, "kids_mode"
    if consecutive_losses >= TAUNT_LOSS_STREAK_OFF:
        return False, "loss_streak"        # SOC-16
    every = TAUNT_EVERY_N_MATCHES.get((cluster or "").lower(), TAUNT_DEFAULT_EVERY_N)
    if every <= 0:
        return False, "cluster_never"      # SOC-15 deliberate / rebuilder
    if matches_since_last_taunt + 1 < every:
        return False, "frequency"
    return True, "ok"
