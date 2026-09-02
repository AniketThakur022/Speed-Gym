"""Answer-extraction and trust-ladder rules — pure logic, no databases."""

import pytest

from app.content import extract_numeric_answer, servable_trust


@pytest.mark.parametrize(
    "answer_key,expected",
    [
        ("$735 + 167 = 902$", 902.0),
        ("27 - 74 + 81 - 19 = 15", 15.0),
        ("764 × 38 = 29032", 29032.0),
        ("6", 6.0),
        ("95550", 95550.0),
        ("$\\frac{9}{2} = 4\\frac{1}{2}$", 4.5),  # mixed number, not the 1/2 alone
        ("$-2\\frac{1}{4}$", -2.25),  # sign applies to the whole quantity
        ("$\\frac{2}{5}$", 0.4),
        ("1,250", 1250.0),
        ("-42", -42.0),
    ],
)
def test_answer_extraction(answer_key, expected):
    assert extract_numeric_answer(answer_key) == expected


@pytest.mark.parametrize(
    "answer_key",
    [None, "", "see the worked solution", "x = 2y + 1", "$\\frac{1}{0}$", "3 and 7"],
)
def test_unextractable_answers_defer_to_the_server(answer_key):
    """A conservative miss costs a round-trip; a false hit marks a correct
    learner wrong, so anything ambiguous must return None."""
    assert extract_numeric_answer(answer_key) is None


def test_trusted_content_is_servable_and_feeds_mastery():
    decision = servable_trust("TRUSTED")
    assert (decision.servable, decision.tier, decision.feeds_mastery) == (True, "trusted", True)


def test_sandbox_content_is_servable_but_never_feeds_mastery():
    decision = servable_trust("sandbox")
    assert decision.servable and decision.tier == "sandbox"
    assert decision.feeds_mastery is False


def test_trusted_candidate_is_treated_as_sandbox_not_trusted():
    """A candidate has not passed stage-7 review; promoting it on the strength
    of its name would serve unreviewed content as trusted."""
    decision = servable_trust("trusted_candidate")
    assert decision.tier == "sandbox"
    assert decision.feeds_mastery is False


@pytest.mark.parametrize(
    "label", ["QUARANTINED_SOFT", "QUARANTINED_HARD", "quarantined_pending_consensus"]
)
def test_quarantined_content_is_never_served(label):
    assert servable_trust(label).servable is False


@pytest.mark.parametrize("label", [None, "", "trusted_ish", "promoted"])
def test_unknown_labels_are_refused_rather_than_assumed_safe(label):
    decision = servable_trust(label)
    assert decision.servable is False and decision.feeds_mastery is False
