"""Content serving rules — answer extraction and the trust ladder.

Two things live here because both the session builder and the admin surfaces
need them, and getting either wrong is a correctness problem rather than a
formatting one:

* `extract_numeric_answer` decides whether an item can be checked ON DEVICE.
  The practice loop is offline-first, so an item is only fully playable without
  a network if the client can compare answers locally.
* `servable_trust` enforces the trust ladder. QUARANTINED content is never
  served; SANDBOX content is served but must never feed mastery or mocks.
"""

from __future__ import annotations

import re
from typing import Optional

# A fraction optionally preceded by a whole part, i.e. a mixed number: the
# "4" in "4\frac{1}{2}" is worth 4, so ignoring it would turn 4.5 into 0.5.
FRACTION = re.compile(
    r"^(?P<whole>-?\d+)?\s*\\d?frac\{(?P<num>-?[\d.]+)\}\{(?P<den>-?[\d.]+)\}$"
)
PLAIN_NUMBER = re.compile(r"^-?\d+(?:\.\d+)?$")
LATEX_NOISE = ("\\,", "\\;", "\\!", "\\ ", "\\left", "\\right", "\\$")
LATEX_COMMAND = re.compile(r"\\[a-zA-Z]+")


def _strip_latex_commands(text: str) -> str:
    """Drop \\frac, \\times etc. so their letters are not mistaken for variables."""
    return LATEX_COMMAND.sub(" ", text)


def extract_numeric_answer(answer_key: Optional[str]) -> Optional[float]:
    """Return the answer as a number, or None when it needs a server check.

    Corpus answer keys are written as full equations far more often than as
    bare values ("$735 + 167 = 902$"), so the answer is the right-hand side.
    Anything with prose, symbols or multiple values falls through to None —
    a conservative miss costs a network round-trip, a false hit would mark a
    correct learner wrong.
    """
    if not answer_key:
        return None

    text = answer_key.strip().strip("$")

    # An answer key is often "expression = value" ("$735 + 167 = 902$"), so the
    # value is the right-hand side. But the key is just as often an EQUATION that
    # IS the answer ("$x + 3y - 11 = 0$" — find the line), and blindly taking the
    # RHS turns those into the number 0. That is the worst possible failure:
    # a learner who answers correctly is marked wrong, and one who types "0" is
    # marked right. So only split when the left side is pure arithmetic.
    if "=" in text:
        parts = text.split("=")
        # More than one "=" means an equation chain or a multi-part answer
        # ("(a) ... = 0; (b) ... = 0"); never a single numeric value.
        if len(parts) != 2:
            return None
        lhs = _strip_latex_commands(parts[0])
        if re.search(r"[a-zA-Z]", lhs):
            return None  # the left side names variables, so this is an equation
        text = parts[1]

    for noise in LATEX_NOISE:
        text = text.replace(noise, "")
    text = text.strip()

    fraction = FRACTION.match(text)
    if fraction:
        denominator = float(fraction.group("den"))
        if denominator == 0:
            return None
        value = float(fraction.group("num")) / denominator
        whole = fraction.group("whole")
        if whole is not None:
            # Mixed number: the fractional part carries the whole part's sign.
            magnitude = abs(float(whole)) + abs(value)
            return -magnitude if whole.startswith("-") else magnitude
        return value

    cleaned = text.replace(",", "").replace("\\%", "").replace("%", "").replace("$", "")
    cleaned = re.sub(r"^\\text\{.*?\}", "", cleaned).strip()
    return float(cleaned) if PLAIN_NUMBER.match(cleaned) else None


# ── Trust ladder ────────────────────────────────────────────────────────────
# The factory emits its own vocabulary ("quarantined_pending_consensus",
# "trusted_candidate"); the canonical enum is the 5-value one in
# problem_health_scores. Both are mapped here so a new factory label can never
# be silently treated as servable.

TRUSTED_LABELS = {"LIVE", "TRUSTED", "trusted", "live"}
SANDBOX_LABELS = {"SANDBOX", "sandbox", "sandbox_candidate", "trusted_candidate"}

# Ids the content factory rejected, loaded once per process from
# problem_health_scores (populated by scripts/import_content_trust.py).
# Cached because every serving path needs it and the set is tiny; a factory
# re-import is a deploy-time event, not a per-request one.
_quarantined: Optional[set[str]] = None
_trust_levels: Optional[dict[str, str]] = None


async def trust_levels(pool) -> dict[str, str]:
    """content_id -> trust_level for everything the ladder has an opinion on.

    Stage-7 promotes items into this table, so the serving path must read the
    WHOLE ladder, not just the quarantine rung — otherwise a promotion to
    SANDBOX or TRUSTED has no observable effect and the review work is wasted.

    Fails open to an empty mapping for the same reason as quarantined_ids: a
    trust-metadata outage must not take the practice loop down. The caller
    treats "no opinion" as the default rung, which is what applied before this
    table was populated at all.
    """
    global _trust_levels
    if _trust_levels is not None:
        return _trust_levels
    try:
        async with pool.connection() as conn:
            rows = await (
                await conn.execute("SELECT content_id, trust_level FROM problem_health_scores")
            ).fetchall()
        _trust_levels = {row[0]: row[1] for row in rows}
    except Exception:  # noqa: BLE001
        return {}
    return _trust_levels


async def quarantined_ids(pool) -> set[str]:
    """Content ids that must never be served, from the canonical trust table.

    Returns an empty set if the table cannot be read: failing open on a
    *serving* path is wrong, but failing closed here would take the whole
    practice loop down over a trust-metadata outage. Callers still apply the
    graph-level filters, so the worst case is the pre-existing behaviour.
    """
    global _quarantined
    if _quarantined is not None:
        return _quarantined
    try:
        async with pool.connection() as conn:
            rows = await (
                await conn.execute(
                    "SELECT content_id FROM problem_health_scores "
                    "WHERE trust_level IN ('QUARANTINED_SOFT', 'QUARANTINED_HARD')"
                )
            ).fetchall()
        _quarantined = {row[0] for row in rows}
    except Exception:  # noqa: BLE001
        return set()
    return _quarantined


def reset_quarantine_cache() -> None:
    """Drop the caches — for tests, and after a factory import or a stage-7
    promotion writes new rows."""
    global _quarantined, _trust_levels
    _quarantined = None
    _trust_levels = None


class TrustDecision:
    __slots__ = ("servable", "tier", "feeds_mastery", "reason")

    def __init__(self, servable: bool, tier: str, feeds_mastery: bool, reason: str):
        self.servable = servable
        self.tier = tier
        self.feeds_mastery = feeds_mastery
        self.reason = reason


def servable_trust(label: Optional[str]) -> TrustDecision:
    """Decide whether content may be served, and whether it may drive mastery.

    Unknown labels are refused rather than assumed safe: a typo in a factory
    label must not become a path for unreviewed content to reach a learner.
    `trusted_candidate` is deliberately treated as SANDBOX — a candidate has
    not passed the stage-7 jester review that promotes it.
    """
    if not label:
        return TrustDecision(False, "unknown", False, "missing trust label")
    if label in TRUSTED_LABELS:
        return TrustDecision(True, "trusted", True, "trusted")
    if label in SANDBOX_LABELS:
        # Exposure-capped upstream; never feeds BKT or mock exams.
        return TrustDecision(True, "sandbox", False, "sandbox: excluded from mastery")
    if label.lower().startswith("quarantin"):
        return TrustDecision(False, "quarantined", False, f"quarantined ({label})")
    return TrustDecision(False, "unknown", False, f"unrecognised trust label ({label})")
