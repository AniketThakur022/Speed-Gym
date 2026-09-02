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
    text = text.split("=")[-1]
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
