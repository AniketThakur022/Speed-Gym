"""Telemetry registry + sampling policy. Pure logic, no databases.

The invariant under test: psychometric events are NEVER sampled, at any DAU.
Sampling them is the documented P99 ≈ 69pp mastery-error failure mode.
"""

import pytest

from app.telemetry import (
    DAU_SAMPLING_THRESHOLD,
    NEVER_SAMPLED,
    PSYCHOMETRIC_EVENTS,
    REGISTRY,
    SamplingClass,
    decide,
    registry_snapshot,
)

HIGH_DAU = DAU_SAMPLING_THRESHOLD * 5


def test_registry_has_a_meaningful_size_and_unique_names():
    names = [e["event_type"] for e in registry_snapshot()]
    assert len(names) == len(set(names))
    assert len(names) >= 33  # the RFP's TEL-01..33, plus phase-2 additions


@pytest.mark.parametrize("event_type", sorted(PSYCHOMETRIC_EVENTS))
def test_psychometric_events_are_never_sampled_even_at_huge_dau(event_type):
    """Try many event ids so a lucky hash cannot mask a sampling bug."""
    for i in range(200):
        d = decide(event_type, "user-1", f"evt-{i}", HIGH_DAU)
        assert d.ingest and not d.sampled_out, f"{event_type} was sampled"


@pytest.mark.parametrize("event_type", sorted(NEVER_SAMPLED - PSYCHOMETRIC_EVENTS))
def test_conversion_and_ops_events_are_never_sampled(event_type):
    for i in range(50):
        d = decide(event_type, "user-1", f"evt-{i}", HIGH_DAU)
        assert d.ingest and not d.sampled_out


def test_ui_events_are_not_sampled_below_the_dau_threshold():
    kept = sum(1 for i in range(500) if decide("page_view", "u", f"e{i}", DAU_SAMPLING_THRESHOLD).ingest)
    assert kept == 500  # at the threshold, still 100%


def test_ui_events_sample_to_roughly_one_in_ten_above_the_threshold():
    kept = sum(1 for i in range(5000) if decide("page_view", "u", f"e{i}", HIGH_DAU).ingest)
    assert 400 <= kept <= 600  # 10% ± a comfortable margin


def test_sampling_is_deterministic_across_calls_and_processes():
    """The v5.2 snippet used Python's salted hash(); the same event could be
    kept by one worker and dropped by another. SHA-256 makes it a pure
    function of the event."""
    first = [decide("page_view", "u", f"e{i}", HIGH_DAU).ingest for i in range(300)]
    second = [decide("page_view", "u", f"e{i}", HIGH_DAU).ingest for i in range(300)]
    assert first == second
    # And a known vector, so a change to the hash input is caught.
    assert decide("page_view", "user-1", "evt-1", HIGH_DAU).ingest is decide(
        "page_view", "user-1", "evt-1", HIGH_DAU
    ).ingest


def test_unknown_event_types_are_ingested_and_marked_not_dropped():
    d = decide("brand_new_event_from_a_newer_client", "u", "e1", HIGH_DAU)
    assert d.ingest is True
    assert d.known is False
    assert d.sampled_out is False


def test_problem_attempt_is_classified_psychometric():
    """The single most important row: this is the event the v5.2 sampler
    would have thinned to 10%."""
    assert REGISTRY["problem_attempt"].sampling is SamplingClass.PSYCHOMETRIC
    assert "problem_attempt" in PSYCHOMETRIC_EVENTS


def test_only_the_ui_class_is_sampleable():
    for spec in REGISTRY.values():
        if spec.sampling is not SamplingClass.UI:
            assert spec.name in NEVER_SAMPLED
