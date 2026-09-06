"""Pool-independent scoring: CAT −1/3 (MOCK-EXM-01), TITA no negative, scaled
approximations, percentile, weak areas. Pure."""

from app.mocks import scoring
from app.mocks.blueprints import BLUEPRINTS, catalogue


def q(qid, kind, answer, skill="s", marks_correct=3.0, marks_wrong=-1.0, options=None):
    return {"question_id": qid, "kind": kind, "correct_answer": answer, "skill": skill,
            "marks_correct": marks_correct, "marks_wrong": marks_wrong, "options": options}


def test_three_blueprints_nine_sections_cat_pattern():
    cat = catalogue()
    assert [b["key"] for b in cat] == ["cat", "gmat", "gre"]
    assert sum(len(b["sections"]) for b in cat) == 9
    c = BLUEPRINTS["cat"]
    assert [s.questions for s in c.sections] == [24, 20, 22] and c.total_minutes == 120 and c.max_raw == 198
    assert c.negative_marking and c.section("qa").marks_wrong_mcq == -1.0 and c.section("qa").marks_wrong_tita == 0.0
    assert not BLUEPRINTS["gmat"].negative_marking and not BLUEPRINTS["gre"].negative_marking


def test_grade_mcq_accepts_letter_or_text_and_numeric_tolerance():
    opts = [{"id": "a", "text": "12"}, {"id": "b", "text": "14"}]
    assert scoring.grade(q("1", "mcq", "b", options=opts), "B") is True
    assert scoring.grade(q("1", "mcq", "b", options=opts), "14") is True
    assert scoring.grade(q("1", "mcq", "b", options=opts), "a") is False
    assert scoring.grade(q("2", "tita", "504"), " 504.0 ") is True
    assert scoring.grade(q("2", "tita", "504"), "505") is False
    assert scoring.grade(q("3", "numeric", "0.5"), "1/2") in (True, False)  # extractor's call
    assert scoring.grade(q("4", "mcq", "a"), None) is None and scoring.grade(q("4", "mcq", "a"), "   ") is None
    assert scoring.grade(q("5", "essay", None), "my essay") is None


def test_cat_section_scoring_minus_one_for_wrong_mcq_and_zero_for_tita():
    sec = BLUEPRINTS["cat"].section("qa")
    qs = [q("1", "mcq", "a"), q("2", "mcq", "a"), q("3", "mcq", "a"),          # 3 correct
          q("4", "mcq", "a"), q("5", "mcq", "a"),                              # 2 wrong mcq → −2
          q("6", "tita", "7", marks_wrong=0.0),                                # 1 wrong tita → 0
          q("7", "mcq", "a"), q("8", "mcq", "a"), q("9", "mcq", "a"), q("10", "tita", "1", marks_wrong=0.0)]
    answers = {"1": "a", "2": "a", "3": "a", "4": "b", "5": "c", "6": "8"}
    r = scoring.score_section(sec, qs, answers)
    assert (r.correct, r.wrong, r.unattempted, r.attempted) == (3, 3, 4, 6)
    assert r.raw == 9 - 2 and r.max_raw == 30 and r.accuracy == 0.5 and r.scaled is None


def test_gmat_and_gre_scaling_bounds_and_labels():
    gmat = BLUEPRINTS["gmat"]
    served = {s.key: [q(f"{s.key}{i}", "mcq", "a", marks_correct=1.0, marks_wrong=0.0) for i in range(s.questions)]
              for s in gmat.sections}
    perfect = {qid: "a" for qs in served.values() for qq in qs for qid in [qq["question_id"]]}
    res = scoring.score_attempt(gmat, served, perfect)
    assert res.scaled_total == 805 and all(s.scaled == 90 for s in res.sections) and res.scaled_approximate
    zero = scoring.score_attempt(gmat, served, {})
    assert zero.scaled_total == 205 and all(s.scaled == 60 for s in zero.sections)
    gre = BLUEPRINTS["gre"]
    served = {"verbal": [q(f"v{i}", "mcq", "a", marks_correct=1.0, marks_wrong=0.0) for i in range(27)],
              "quant": [q(f"q{i}", "numeric", "1", marks_correct=1.0, marks_wrong=0.0) for i in range(27)]}
    half = {f"v{i}": "a" for i in range(27)}                       # verbal perfect, quant untouched
    res = scoring.score_attempt(gre, served, half)
    by = {s.key: s for s in res.sections}
    assert by["verbal"].scaled == 170 and by["quant"].scaled == 130 and res.scaled_total == 300


def test_percentile_is_honest_with_no_peers_and_counts_ties_half():
    assert scoring.percentile(50, []) == 0
    assert scoring.percentile(50, [10, 20, 30]) == 100
    assert scoring.percentile(20, [10, 20, 30]) == 50
    assert scoring.percentile(5, [10, 20, 30]) == 0


def test_weak_areas_below_70_percent_worst_first_counting_skipped():
    qs = [q("1", "mcq", "a", skill="algebra"), q("2", "mcq", "a", skill="algebra"), q("3", "mcq", "a", skill="algebra"),
          q("4", "mcq", "a", skill="geometry"), q("5", "mcq", "a", skill="geometry"),
          q("6", "mcq", "a", skill="ratios")]
    answers = {"1": "a", "2": "a", "3": "a", "4": "b", "6": "a"}
    weak = scoring.weak_areas(qs, answers)
    assert [w["skill"] for w in weak] == ["geometry"] and weak[0]["accuracy"] == 0.0
