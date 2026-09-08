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
    """746 of the served problems have 2-7 skill parents, so one is chosen as the
    mastery key. collect() has no ordering guarantee and this key joins a
    learner's history, so an unstable pick would split mastery across two keys.

    This assertion used to be double-blind: it compiled a regex BYTE-IDENTICAL to
    the one in session.py, so any structural name production missed the test
    missed too — and it inspected only the first 50 items, which happened to
    exclude both problems that were in fact keyed on a chapter/band heading
    ('Chapter 11 on simple equations' and 'Advance Level' each won their pick).
    It passed while the defect it was written to catch was live.

    So: check the WHOLE served pool, and detect structural names by a criterion
    independent of production's — a leading structural word anywhere in the name,
    with an explicit allowlist for the concepts that legitimately start with one.
    """
    import re

    # Deliberately BROADER than session.py's whole-string regex, so this test can
    # fail on something production's demotion misses. 'Unit Circle' and
    # 'Unit Conversion' are real concepts, not structure — hence the allowlist.
    leading_structural = re.compile(
        r"(?i)^\s*(chapter|ch\.|section|sec\.|unit|part|exercise|ex\.|lesson|"
        r"appendix|preface|advance level|basic level|previous)\b"
    )
    LEGITIMATE = {"Unit Circle", "Unit Conversion", "Unit Circle Definitions",
                  "Partial Fractions", "Particle Motion"}
    bare_number = re.compile(r"^\s*[0-9.]+\s*$")

    runs = []
    for _ in range(3):
        res = client.get("/api/v1/practice/session", params={"size": 50})
        runs.append({i["template_id"]: i["skill"] for i in res.json()["items"]})
    assert runs[0] == runs[1] == runs[2], "mastery key must be stable across calls"

    # The page is only 50 items; the defect lived outside it. Assert over every
    # servable problem, and assert the served key IS the pin.
    from neo4j import GraphDatabase

    from app.config import get_settings

    settings = get_settings()

    driver = GraphDatabase.driver(
        settings.neo4j_uri, auth=(settings.neo4j_user, settings.neo4j_password)
    )
    try:
        with driver.session() as neo:
            keys = [
                (r["tid"], r["key"])
                for r in neo.run(
                    "MATCH (p:Problem) WHERE p.mastery_key IS NOT NULL "
                    "RETURN p.template_id AS tid, p.mastery_key AS key"
                )
            ]
            unpinned = neo.run(
                "MATCH (:Skill)-[:PREREQUISITE_OF]->(p:Problem) "
                "WHERE p.mastery_key IS NULL RETURN count(DISTINCT p) AS n"
            ).single()["n"]
            dangling = neo.run(
                "MATCH (p:Problem) WHERE p.mastery_key IS NOT NULL AND NOT EXISTS "
                "{ MATCH (:Skill {name: p.mastery_key}) } RETURN count(p) AS n"
            ).single()["n"]
            dupes = [
                r["names"]
                for r in neo.run(
                    "MATCH (s:Skill) WITH toLower(s.name) AS k, collect(s.name) AS names "
                    "WHERE size(names) > 1 RETURN names"
                )
            ]
    finally:
        driver.close()

    assert keys, "seeded graph should have pinned mastery keys"
    assert unpinned == 0, f"{unpinned} problems have a skill parent but no pinned key"
    assert dangling == 0, f"{dangling} pinned keys name a :Skill that no longer exists"
    assert dupes == [], f"case-duplicate :Skill names are back: {dupes[:5]}"

    for template_id, key in keys:
        assert not bare_number.match(key), f"{template_id} keyed on {key!r}"
        assert key in LEGITIMATE or not leading_structural.match(key), (
            f"{template_id} keyed on structural name {key!r}"
        )

    # The served key must be the pin, not a fresh sort — that is what stops a
    # future rename silently re-attributing a learner's history.
    pinned = dict(keys)
    for template_id, skill in runs[0].items():
        if template_id in pinned:
            assert skill == pinned[template_id], (
                f"{template_id} served {skill!r} but is pinned to {pinned[template_id]!r}"
            )


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
