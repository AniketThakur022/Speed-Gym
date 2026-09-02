"""Glicko-2 tests, including the worked example from Glickman's paper."""

import pytest

from app.glicko2 import Rating, seed_rating, update_match, update_rating


def test_glickman_worked_example():
    """The canonical example: r=1500 RD=200 vs three opponents (W, L, L).

    Published result: rating ≈ 1464.06, RD ≈ 151.52, volatility ≈ 0.05999.
    """
    player = Rating(rating=1500, rd=200, volatility=0.06)
    opponents = [
        (Rating(rating=1400, rd=30), 1.0),
        (Rating(rating=1550, rd=100), 0.0),
        (Rating(rating=1700, rd=300), 0.0),
    ]
    result = update_rating(player, opponents)

    assert result.rating == pytest.approx(1464.06, abs=0.1)
    assert result.rd == pytest.approx(151.52, abs=0.1)
    assert result.volatility == pytest.approx(0.05999, abs=1e-4)


def test_winning_raises_rating_and_losing_lowers_it():
    player = Rating(rating=1500, rd=200)
    opponent = Rating(rating=1500, rd=200)
    assert update_rating(player, [(opponent, 1.0)]).rating > 1500
    assert update_rating(player, [(opponent, 0.0)]).rating < 1500


def test_playing_reduces_uncertainty():
    player = Rating(rating=1500, rd=350)
    result = update_rating(player, [(Rating(rating=1500, rd=50), 1.0)])
    assert result.rd < 350


def test_inactivity_increases_uncertainty_rather_than_doing_nothing():
    """A player who did not compete should become less certain, not frozen."""
    player = Rating(rating=1500, rd=100, volatility=0.06)
    result = update_rating(player, [])
    assert result.rating == 1500
    assert result.rd > 100


def test_rd_is_clamped_to_the_documented_bounds():
    tight = Rating(rating=1500, rd=30)
    for _ in range(30):
        tight = update_rating(tight, [(Rating(rating=1500, rd=30), 0.5)])
    assert 30 <= tight.rd <= 350


def test_beating_a_stronger_opponent_gains_more_than_beating_a_weaker_one():
    player = Rating(rating=1500, rd=200)
    over_stronger = update_rating(player, [(Rating(rating=1900, rd=50), 1.0)])
    over_weaker = update_rating(player, [(Rating(rating=1100, rd=50), 1.0)])
    assert over_stronger.rating > over_weaker.rating


def test_seed_rating_uses_ability_and_clamps():
    assert seed_rating(0).rating == 1000
    assert seed_rating(1.5).rating == 1600
    assert seed_rating(-3).rating == 600  # raw -200 clamps up
    assert seed_rating(3).rating == 2200


def test_match_update_is_symmetric_and_order_independent():
    ratings = {"alice": Rating(rating=1500, rd=200), "bob": Rating(rating=1500, rd=200)}
    ranks = {"alice": 1, "bob": 2}

    result = update_match(ratings, ranks)
    assert result["alice"].rating > 1500
    assert result["bob"].rating < 1500

    # Iterating the other way must give the same numbers: updates read only
    # pre-match ratings.
    reversed_input = {"bob": ratings["bob"], "alice": ratings["alice"]}
    reversed_result = update_match(reversed_input, ranks)
    assert reversed_result["alice"].rating == pytest.approx(result["alice"].rating)
    assert reversed_result["bob"].rating == pytest.approx(result["bob"].rating)
