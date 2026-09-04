"""Practice-read tests — verification semantics are a contract, not a detail.

Answer-verification (SymPy recomputes the result) and solution-verification
(stage-7 jester review of the walkthrough) must stay separate signals: templates
with correct answers and broken derivations exist in the corpus. Skipped when
the dev graph isn't running.
"""

import socket

import pytest
from fastapi.testclient import TestClient

from app.main import create_app


def _reachable(host: str, port: int) -> bool:
    try:
        with socket.create_connection((host, port), timeout=1):
            return True
    except OSError:
        return False


pytestmark = pytest.mark.skipif(
    not _reachable("localhost", 7687), reason="dev Neo4j not running"
)


@pytest.fixture(scope="module")
def client():
    with TestClient(create_app()) as c:
        yield c


def test_problems_never_expose_a_single_ambiguous_verified_field(client):
    res = client.get("/api/practice/problems", params={"limit": 5})
    assert res.status_code == 200
    problems = res.json()["problems"]
    assert problems, "seeded graph should return problems"

    for p in problems:
        # The raw graph field must not leak: it reads like a solution verdict.
        assert "validation_status" not in p
        assert p["answer_verification"] in {"verified", "flagged", "empty_answer", "unverified"}
        # Solution correctness is only established by the offline jester stage,
        # so nothing served today may claim it.
        assert p["solution_verification"] == "unverified"


def test_seeded_corpus_reports_answer_verification(client):
    res = client.get("/api/practice/problems", params={"limit": 20})
    verdicts = {p["answer_verification"] for p in res.json()["problems"]}
    assert "verified" in verdicts


def test_techniques_route_serves_the_live_skill_graph(client):
    res = client.get("/api/practice/techniques", params={"limit": 3})
    assert res.status_code == 200
    techniques = res.json()["techniques"]
    assert techniques and {"name", "problem_count"} <= set(techniques[0])


def test_mastery_is_keyed_on_a_graph_skill_not_a_corpus_label(client):
    """Only 14 of 368 corpus `technique` labels match a :Skill name, so keying
    mastery on them accumulates state the graph can never join back. Items must
    carry a `skill` from the existing PREREQUISITE_OF edge, and anything without
    one must be excluded from mastery rather than falling back to a label."""
    res = client.get("/api/v1/practice/session", params={"size": 10})
    assert res.status_code == 200
    items = res.json()["items"]
    assert items

    for item in items:
        assert "skill" in item
        if item["skill"] is None:
            assert item["feeds_mastery"] is False
        # Display labels are passed through verbatim, never turned into an id.
        assert "topic" in item and "technique" in item


def test_most_served_problems_resolve_a_skill(client):
    """98.4% of answerable problems reach a :Skill today; if a change dropped
    that to near zero, mastery would silently stop accumulating."""
    res = client.get("/api/v1/practice/session", params={"size": 20})
    items = res.json()["items"]
    tier1 = [i for i in items if i["source"] == "tier1_static"]
    assert tier1
    with_skill = [i for i in tier1 if i["skill"]]
    assert len(with_skill) / len(tier1) >= 0.8


QUARANTINED_SAMPLE = [
    "Tirthaji_Vedic_Math_sa_61",   # empty_problem_statement + no_valid_examples
    "Bird_Engineering_Math_sa_17",  # empty_solution
    "Vedic_Made_Easy_sa_20",
]


def test_factory_quarantined_content_is_never_served(client):
    """The factory rejected these; serving them anyway defeats the trust ladder.
    Fetch a large page and assert none appear."""
    res = client.get("/api/v1/practice/session", params={"size": 50})
    served = {i["template_id"] for i in res.json()["items"]}
    assert not (served & set(QUARANTINED_SAMPLE))


def test_served_questions_are_never_blank(client):
    """IS NOT NULL passes the empty string, which is unanswerable."""
    res = client.get("/api/v1/practice/session", params={"size": 50})
    for item in res.json()["items"]:
        assert (item["question_text"] or "").strip()


def test_tier1_does_not_claim_the_factory_trust_ladder(client):
    """Tier-1 book content has never been on the factory's ladder; calling it
    'trusted' would repeat the answer/solution conflation fixed earlier."""
    res = client.get("/api/v1/practice/session", params={"size": 10})
    for item in res.json()["items"]:
        if item["source"] == "tier1_static":
            assert item["trust"] == "static_verified"


def test_mastery_key_is_deterministic_and_never_a_chapter_number(client):
    """757 of the served problems have 2-7 skill parents, so one is chosen as the
    mastery key. collect() has no ordering guarantee and this key joins a
    learner's history, so an unstable pick would split mastery across two keys.
    The graph also contains structural names ('Chapter 11'), which must never win
    over a real concept."""
    import re

    structural = re.compile(
        r"(?i)^\s*(chapter|ch\.?|section|sec\.?|unit|part|exercise|ex\.?|lesson)\s*[0-9ivxl.]*\s*$"
        r"|^\s*[0-9.]+\s*$"
    )
    runs = []
    for _ in range(3):
        res = client.get("/api/v1/practice/session", params={"size": 50})
        runs.append({i["template_id"]: i["skill"] for i in res.json()["items"]})

    assert runs[0] == runs[1] == runs[2], "mastery key must be stable across calls"
    for template_id, skill in runs[0].items():
        assert not (skill and structural.match(skill)), f"{template_id} keyed on {skill!r}"


STEP_FIELDS = {"solution_steps", "solution", "steps", "worked_solution", "walkthrough"}


def test_no_serving_route_emits_solution_steps(client):
    """Walkthroughs are a measurably less reliable layer than question+answer:
    an adversarial review of a 60-item sample of the static bank failed 53,
    dominated by step descriptions that contradict the operations they label.

    static_verified certifies question+answer ONLY, so steps must not ride along
    under it. 797 :Problem nodes carry non-empty solution_steps, i.e. this is one
    RETURN field away from happening by accident — hence a test, not a comment.
    If walkthroughs are ever served they need their own gate keyed on
    solution_verification.
    """
    payloads = [
        client.get("/api/v1/practice/session", params={"size": 25}).json()["items"],
        client.get("/api/practice/problems", params={"limit": 25}).json()["problems"],
    ]
    for items in payloads:
        for item in items:
            leaked = STEP_FIELDS & set(item)
            assert not leaked, f"step content leaked into a served payload: {leaked}"
            # And the honest signal must still be present and negative.
            if "solution_verification" in item:
                assert item["solution_verification"] == "unverified"
