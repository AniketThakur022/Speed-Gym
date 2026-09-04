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


@pytest.mark.parametrize(
    "answer_key",
    [
        "$x + 3y - 11 = 0$",                     # equation of a line IS the answer
        "31x - 39y - 23 = 0",
        "$2x' - 3y' = 0$",
        "y + 2 = \\frac{3}{4}(x + 1) \\quad \\text{or} \\quad 3x - 4y - 5 = 0",
        "(a) $ x - 3y - 33 = 0 $; (b) $ y = 3x + 13 $",   # multi-part
    ],
)
def test_equation_answers_are_never_read_as_the_number_zero(answer_key):
    """These keys are equations, not values. Taking the right-hand side yields
    0, which is the worst failure available: a learner who answers correctly is
    marked wrong, and one who types "0" is marked right. 18 servable problems
    were affected."""
    assert extract_numeric_answer(answer_key) is None


def test_arithmetic_equations_still_yield_their_value():
    """The split must still work when the left side is pure arithmetic."""
    assert extract_numeric_answer("$735 + 167 = 902$") == 902.0
    assert extract_numeric_answer("27 - 74 + 81 - 19 = 15") == 15.0
    # LaTeX command letters must not be mistaken for variables.
    assert extract_numeric_answer("$\\frac{9}{2} = 4\\frac{1}{2}$") == 4.5


# ── Tier-1 trust ladder integration ─────────────────────────────────────────
from app.routers.session import _feeds_mastery, _tier1_trust  # noqa: E402


def test_unreviewed_tier1_content_defaults_to_static_verified():
    """Book content with no ladder row has never been reviewed; its warrant is
    answer verification only."""
    assert _tier1_trust("Bird_Engineering_Math_sa_1", {}) == "static_verified"
    assert _feeds_mastery("Bird_Engineering_Math_sa_1", {}) is True


def test_stage7_promotion_overrides_the_default_label():
    """Without this, a review pipeline would have no observable effect on what
    gets served."""
    assert _tier1_trust("x", {"x": "TRUSTED"}) == "trusted"
    assert _tier1_trust("x", {"x": "LIVE"}) == "trusted"
    assert _feeds_mastery("x", {"x": "TRUSTED"}) is True


def test_sandbox_content_is_labelled_and_never_feeds_mastery():
    """SANDBOX is playable but excluded from mastery and mocks — the rule the
    whole ladder exists to enforce."""
    assert _tier1_trust("x", {"x": "SANDBOX"}) == "sandbox"
    assert _feeds_mastery("x", {"x": "SANDBOX"}) is False
