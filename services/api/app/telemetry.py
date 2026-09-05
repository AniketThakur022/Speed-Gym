"""Telemetry event registry and the sampling policy.

THE ONE RULE THAT MATTERS: events that drive mastery are NEVER sampled.
The v5.2 telemetry spec (§8.1) sampled `problem_attempt` at 10% once DAU passed
10k. The RFP reconciliation (VMSG_TECHNICAL_ARCHITECTURE §11.3, Risk #4) rejected
that outright — sampling attempts yields a P95 ≈ 33pp / P99 ≈ 69pp mastery
error, i.e. BKT computed on a tenth of the evidence. The decided policy is:

  * PSYCHOMETRIC  — always 100%. Never sampled, never evicted, never merged
                    blindly across devices. problem_attempt, problem_solved,
                    trap_triggered, bkt_state_snapshot, session_start/end,
                    calibration_completed, subscription_*.
  * CONVERSION    — always 100% (funnel signals are worthless if thinned).
  * UI            — 10% sample, and ONLY once DAU > 10,000.
  * OPS           — always 100% (they are rare and they are the alarms).

Numbering: the RFP labels these TEL-01..TEL-33. The RFP itself was never
recovered, so those ids cannot be reconstructed with confidence; the names come
from the v5.2 taxonomy (telemetry_architecture.md §9.2) plus the reconciliation
doc, and the `tel_hint` column is a best-effort ordinal, not a citation.

Determinism: the v5.2 snippet sampled with Python's built-in hash(), which is
salted per process — the same event could be kept by one worker and dropped by
another, and a replayed batch would not reproduce. Sampling here uses SHA-256
over (user_id, event_id) so the decision is a pure function of the event.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from enum import Enum
from typing import Optional


class SamplingClass(str, Enum):
    PSYCHOMETRIC = "psychometric_never_sampled"
    CONVERSION = "conversion_never_sampled"
    UI = "ui_sampleable"
    OPS = "ops_never_sampled"


class Phase(str, Enum):
    BUILD = "phase_1_build"
    ACTIVATION = "phase_2_activation"


@dataclass(frozen=True)
class EventSpec:
    name: str
    sampling: SamplingClass
    priority: int  # SHARED_REFERENCE §1 scale: 10 critical … 0 drop-first
    phase: Phase = Phase.BUILD
    feature_flag: Optional[str] = None


DAU_SAMPLING_THRESHOLD = 10_000
UI_SAMPLE_KEEP_ONE_IN = 10

_P, _C, _U, _O = (
    SamplingClass.PSYCHOMETRIC,
    SamplingClass.CONVERSION,
    SamplingClass.UI,
    SamplingClass.OPS,
)

# Order is stable so `tel_hint` (1-based index) is reproducible across runs.
_EVENTS: list[EventSpec] = [
    # ── psychometric (drive BKT / IRT / DFV) ────────────────────────────
    EventSpec("problem_attempt", _P, 5),
    EventSpec("problem_solved", _P, 5),
    EventSpec("problem_failed", _P, 5),
    EventSpec("trap_triggered", _P, 8),
    EventSpec("bkt_state_snapshot", _P, 10),
    EventSpec("session_start", _P, 9),
    EventSpec("session_end", _P, 10),
    EventSpec("calibration_completed", _P, 9),
    EventSpec("phase_transition", _P, 8),
    EventSpec("skill_level_up", _P, 7),
    EventSpec("fatigue_index_computed", _P, 6),
    EventSpec("clr_mode_activated", _P, 7),
    EventSpec("behavioral_profile_computed", _P, 6),
    # ── conversion / funnel ─────────────────────────────────────────────
    EventSpec("subscription_purchased", _C, 10),
    EventSpec("subscription_cancelled", _C, 10),
    EventSpec("trial_started", _C, 9),
    EventSpec("referral_code_used", _C, 8),
    EventSpec("referral_reward_claimed", _C, 8),
    EventSpec("onboarding_begin", _C, 7),
    EventSpec("goal_set", _C, 4),
    EventSpec("auth_complete", _C, 7),
    EventSpec("topic_browser_session_start", _C, 9),
    EventSpec("topic_browser_session_end", _C, 10),
    # ── UI / engagement (the only class that may be sampled) ────────────
    EventSpec("page_view", _U, 0),
    EventSpec("hint_used", _U, 2),
    EventSpec("hint_requested", _U, 2),
    EventSpec("topic_selected", _U, 5),
    EventSpec("widget_expanded", _U, 0),
    EventSpec("dashboard_loaded", _U, 2),
    EventSpec("problem_loaded", _U, 5),
    EventSpec("profile_viewed", _U, 1),
    EventSpec("help_viewed", _U, 1),
    # ── ops ─────────────────────────────────────────────────────────────
    EventSpec("buffer_overflow", _O, 10),
    EventSpec("sync_failed", _O, 9),
    EventSpec("offline_sync_complete", _O, 3),
    # ── phase-2, dark-launched ──────────────────────────────────────────
    EventSpec("lr_set_completed", _P, 9, Phase.ACTIVATION, "glicko2_live"),
    EventSpec("di_set_completed", _P, 9, Phase.ACTIVATION, "irt_3pl_live"),
    EventSpec("passage_completed", _P, 9, Phase.ACTIVATION, "dina_live"),
]

REGISTRY: dict[str, EventSpec] = {e.name: e for e in _EVENTS}
TEL_HINT: dict[str, int] = {e.name: i + 1 for i, e in enumerate(_EVENTS)}

PSYCHOMETRIC_EVENTS: frozenset[str] = frozenset(
    e.name for e in _EVENTS if e.sampling is SamplingClass.PSYCHOMETRIC
)
NEVER_SAMPLED: frozenset[str] = frozenset(
    e.name for e in _EVENTS if e.sampling is not SamplingClass.UI
)


def _stable_bucket(user_id: str, event_id: str, buckets: int) -> int:
    digest = hashlib.sha256(f"{user_id}:{event_id}".encode()).digest()
    return int.from_bytes(digest[:8], "big") % buckets


@dataclass(frozen=True)
class IngestDecision:
    ingest: bool
    sampled_out: bool
    known: bool
    sampling: Optional[SamplingClass]


def decide(event_type: str, user_id: str, event_id: str, dau: int) -> IngestDecision:
    """Whether to ingest one event under the decided policy.

    Unknown event types are INGESTED at 100% and marked unknown, never dropped:
    a client shipping a new event ahead of the registry must not lose data,
    and the mark makes the registry gap visible in the ledger.
    """
    spec = REGISTRY.get(event_type)
    if spec is None:
        return IngestDecision(ingest=True, sampled_out=False, known=False, sampling=None)

    if spec.sampling is not SamplingClass.UI:
        return IngestDecision(ingest=True, sampled_out=False, known=True, sampling=spec.sampling)

    if dau <= DAU_SAMPLING_THRESHOLD:
        return IngestDecision(ingest=True, sampled_out=False, known=True, sampling=spec.sampling)

    keep = _stable_bucket(user_id, event_id, UI_SAMPLE_KEEP_ONE_IN) == 0
    return IngestDecision(ingest=keep, sampled_out=not keep, known=True, sampling=spec.sampling)


def registry_snapshot() -> list[dict]:
    """For the admin surface / docs: the whole table, in stable order."""
    return [
        {
            "tel_hint": TEL_HINT[e.name],
            "event_type": e.name,
            "sampling": e.sampling.value,
            "priority": e.priority,
            "phase": e.phase.value,
            "feature_flag": e.feature_flag,
        }
        for e in _EVENTS
    ]
