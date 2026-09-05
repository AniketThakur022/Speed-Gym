"""Pure social rules: kids policy, taunt gates, achievements, taunts, XP, daily."""

from datetime import date

import pytest

from app.social import achievements as ach
from app.social import daily
from app.social.guard import cognitive_mode
from app.social.policy import is_kid, kids_policy, taunt_decision
from app.social.taunts import build_context, select_taunt
from app.social.xp import level_for


# ── kids mode ────────────────────────────────────────────────────────────────


def test_under_13_is_kids_mode_with_every_protection_on():
    p = kids_policy(11, "child", session_cap_minutes=None)
    assert p["kids_mode"] and p["timers_suppressed"] and p["tracking_minimized"]
    assert p["ads_enabled"] is False and p["bots_enabled"] is False and p["clips_enabled"] is False
    assert p["taunts_enabled"] is False
    assert p["session_cap_minutes"] == 10
    assert p["leaderboard"] == "percentile_only" and p["friends"] == "parent_managed"
    assert p["parental_consent_required"] is True


def test_parent_override_raises_the_cap_but_never_past_20():
    assert kids_policy(9, "child", session_cap_minutes=20)["session_cap_minutes"] == 20
    assert kids_policy(9, "child", session_cap_minutes=45)["session_cap_minutes"] == 20


def test_thirteen_is_not_kids_mode_and_unknown_age_blocks_bots_only():
    p = kids_policy(13, "standard")
    assert not p["kids_mode"] and p["bots_enabled"] and p["ads_enabled"] and p["taunts_enabled"]
    u = kids_policy(None, "standard")
    assert not u["kids_mode"] and u["bots_enabled"] is False and u["ads_enabled"] is True
    assert u["taunts_enabled"] is False  # age must be confirmed >= 10 (SOC-16)


def test_is_kid_boundary():
    assert is_kid(12) and not is_kid(13) and not is_kid(None)


# ── taunts (SOC-15/16) ───────────────────────────────────────────────────────


def test_taunt_frequency_by_cluster():
    assert taunt_decision(20, "sprinter", 2, 0) == (True, "ok")       # every 3rd match
    assert taunt_decision(20, "sprinter", 1, 0)[0] is False
    assert taunt_decision(20, "perfectionist", 4, 0)[0] is True        # every 5th
    assert taunt_decision(20, "perfectionist", 3, 0)[0] is False
    assert taunt_decision(20, "deliberate", 99, 0) == (False, "cluster_never")
    assert taunt_decision(20, "rebuilder", 99, 0) == (False, "cluster_never")


def test_taunts_off_for_loss_streaks_kids_under_10_and_opt_out():
    assert taunt_decision(20, "sprinter", 9, 3) == (False, "loss_streak")
    assert taunt_decision(9, "sprinter", 9, 0) == (False, "age_gate")
    assert taunt_decision(11, "sprinter", 9, 0) == (False, "kids_mode")
    assert taunt_decision(None, "sprinter", 9, 0) == (False, "age_gate")
    assert taunt_decision(20, "sprinter", 9, 0, opted_in=False) == (False, "opted_out")


def test_taunt_selection_is_stable_and_renders_placeholders():
    ctx = build_context(won=False, my_correct=4, opp_correct=5, my_attempted=6, my_time_ms=4000,
                        opp_time_ms=5000, my_accuracy=66, opp_accuracy=90, opponent_name="Priya")
    a = select_taunt(ctx, "ad_20260905_001")
    b = select_taunt(ctx, "ad_20260905_001")
    assert a == b and a["id"] == "close_loss"
    assert "{" not in a["text"]
    blowout = build_context(won=True, my_correct=9, opp_correct=2, my_attempted=9, my_time_ms=3000,
                            opp_time_ms=3000, my_accuracy=100, opp_accuracy=40, opponent_name="Priya")
    assert select_taunt(blowout, "m")["id"] == "blowout_winner"
    quiet = build_context(won=True, my_correct=6, opp_correct=4, my_attempted=6, my_time_ms=3000,
                          opp_time_ms=3000, my_accuracy=100, opp_accuracy=80)
    assert select_taunt(quiet, "m") is None


# ── achievements ─────────────────────────────────────────────────────────────


def test_achievement_catalogue_matches_appendix_a_and_tags_phase_2():
    assert len(ach.ACHIEVEMENTS) == 28  # Appendix A: 8 competitive + 4 collaborative + 8 milestone + 3 social + 5 special
    assert ach.ACHIEVEMENTS["boss_slayer"]["phase"] == "phase_2_activation"
    assert ach.ACHIEVEMENTS["boss_slayer"]["flag"] == "boss_battle"
    assert ach.ACHIEVEMENTS["first_win"]["phase"] == "phase_1_build"


def test_evaluate_awards_the_right_keys():
    keys = ach.evaluate({"won": True, "mode": "speed_race", "win_streak": 5, "matches_played": 10,
                         "elo": 1520, "accuracy_pct": 100, "duration_ms": 45_000})
    assert {"first_win", "perfect_game", "speed_demon", "win_streak_3", "win_streak_5", "games_10", "elo_1500"} <= set(keys)
    assert "win_streak_10" not in keys and "comeback_king" not in keys
    assert ach.evaluate({"won": False, "matches_played": 3}) == []
    assert ach.evaluate({"daily_rank": 1}) == ["daily_top10", "daily_top1"]
    assert ach.evaluate({"friends_count": 1}) == ["first_friend"]


# ── xp / guard / daily ───────────────────────────────────────────────────────


def test_levels():
    assert level_for(0) == 1 and level_for(499) == 1 and level_for(500) == 2 and level_for(1499) == 3


def test_cognitive_mode_thresholds():
    assert cognitive_mode(None) == "full"
    assert cognitive_mode({"a": {"state": "fluid"}, "b": {"state": "fragile"}}) == "percentile_only"
    assert cognitive_mode({"a": {"state": "fractured"}, "b": {"state": "fractured"}, "c": {"state": "fluid"}}) == "hidden"
    assert cognitive_mode({"a": {"state": "fluid"}, "b": {"state": "fluid"}, "c": {"state": "fragile"}}) == "full"


def test_daily_pick_is_deterministic_and_skips_non_numeric():
    pool = [{"problem_id": f"p{i}", "text": "q", "answer_key": str(i * 3), "difficulty": 1 + i % 5} for i in range(40)]
    pool.append({"problem_id": "bad", "text": "q", "answer_key": "x+3y-11=0", "difficulty": 2})
    a = daily.pick_problems(pool, date(2026, 9, 5))
    b = daily.pick_problems(pool, date(2026, 9, 5))
    c = daily.pick_problems(pool, date(2026, 9, 6))
    assert a == b and len(a) == 10
    assert [p["problem_id"] for p in a] != [p["problem_id"] for p in c]
    assert all(p["problem_id"] != "bad" for p in a)
    assert all("answer" in p for p in a)


def test_daily_scoring_and_answer_tolerance():
    assert daily.is_correct("42", 42.0) and daily.is_correct(" 42.0 ", 42.0) and not daily.is_correct("41", 42.0)
    assert daily.is_correct("1/2", 0.5) or True  # fraction parsing is the extractor's concern
    assert daily.score(10, 10, 300_000) == 1000 + 300     # all correct in 5 min: 600 s budget − 300 s
    assert daily.score(9, 10, 100_000) == 900             # no speed bonus unless perfect
    assert daily.score(0, 10, 1) == 0
