"""Practice sessions — serves the composed session the client actually plays.

Content comes from two tiers:
  * Tier-1 static  — verified :Problem nodes in the graph.
  * Tier-2 generated — SolveAlongTemplates the factory RPUSHes into Redis trays
    (`factory:tray:<sub_topic>`, 24h TTL) as `{trust, template}`.

Trust and verification rules are enforced here, not left to the client:
quarantined content is never served, sandbox content is served but flagged
`feeds_mastery: false`, and `solution_verification` stays `unverified` until
the stage-7 jesters run (see memory `content-verification-semantics`).

Items carry `expected_answer` when the answer is locally checkable. That is
deliberate: the practice loop is offline-first, so a solo learner's device must
be able to mark its own work. Online duels are the opposite case — the game
server is authoritative there and never ships answers to a client.
"""

from __future__ import annotations

import json
from typing import Any, Optional

from fastapi import APIRouter, HTTPException, Query

from .. import db
from ..content import extract_numeric_answer, quarantined_ids, servable_trust, trust_levels

router = APIRouter(prefix="/practice", tags=["practice"])

ANSWER_VERIFIED = {"verified_L1", "verified_L2"}
TRAY_PREFIX = "factory:tray:"


def _tier1_trust(template_id: Optional[str], ladder: dict[str, str]) -> str:
    """Trust label for a Tier-1 item, honouring a stage-7 verdict if one exists.

    No ladder row means the item has never been reviewed, which is the default
    for book content: `static_verified` (question + answer only).
    """
    level = ladder.get(template_id or "")
    if level in {"LIVE", "TRUSTED"}:
        return "trusted"
    if level == "SANDBOX":
        return "sandbox"
    return "static_verified"


def _feeds_mastery(template_id: Optional[str], ladder: dict[str, str]) -> bool:
    """SANDBOX content is served but excluded from mastery and mocks."""
    return ladder.get(template_id or "") != "SANDBOX"


def _tier1_item(record: dict[str, Any], ladder: dict[str, str]) -> dict[str, Any]:
    answer = extract_numeric_answer(record.get("answer_key"))
    # `skill` is the mastery key and comes from the graph's existing
    # (:Skill)-[:PREREQUISITE_OF]->(:Problem) edge. The corpus `technique`/
    # `topic` strings are DISPLAY LABELS only: just 14 of 368 of them match a
    # :Skill name, so keying mastery on them would accumulate state against a
    # vocabulary the graph cannot join back to. Labels are passed through
    # verbatim — no canonical id is fabricated — pending taxonomy_v1.
    skill = record.get("skill")
    return {
        "source": "tier1_static",
        "template_id": record.get("template_id"),
        "question_text": record.get("question_text"),
        "difficulty": record.get("difficulty") or 1,
        "skill": skill,
        "technique": record.get("technique"),
        "topic": record.get("topic"),
        "sub_topic": record.get("sub_topic"),
        # NOT "trusted": that word names a rung on the factory's trust ladder,
        # and Tier-1 book content has never been on that ladder. Its warrant is
        # the graph's ANSWER verification plus exclusion of factory-quarantined
        # ids — a different, weaker claim. Saying "trusted" here would repeat
        # the answer/solution conflation this codebase already corrected once.
        #
        # SCOPE OF THIS LABEL — do not let it drift: static_verified certifies
        # the QUESTION and its ANSWER, nothing else. It says nothing about a
        # worked solution. If Tier-1 ever renders static solution STEPS, those
        # steps are unverified until the stage-7 jesters pass on them, and this
        # label must NOT be stretched to cover them — that is exactly the
        # answer-vs-derivation conflation recorded in the shared memory
        # `content-verification-semantics`.
        # (Open question for the owner: the factory rates 776 of the derived
        # templates `trusted_candidate`, which servable_trust maps to sandbox.
        # Those ratings describe the derived walkthrough, not the book's answer,
        # so they are deliberately NOT applied to Tier-1 here.)
        #
        # A stage-7 promotion in problem_health_scores DOES override, in both
        # directions: it is a human/jester review of this exact content, which
        # outranks the default provenance label. Without this the whole review
        # pipeline would have no observable effect on what gets served.
        "trust": _tier1_trust(record.get("template_id"), ladder),
        # Without a resolvable skill there is nothing to attribute mastery to,
        # and guessing from a display label is the bug this replaces.
        # SANDBOX content is playable but must never move mastery.
        "feeds_mastery": skill is not None and _feeds_mastery(record.get("template_id"), ladder),
        "answer_verification": "verified",
        "solution_verification": "unverified",
        "answer_check": "client_extract" if answer is not None else "server_sympy",
        "expected_answer": answer,
        "answer_key_display": record.get("answer_key"),
    }


def _tier2_item(entry: dict[str, Any], decision) -> dict[str, Any]:
    template = entry["template"]
    example = (template.get("examples") or [{}])[0]
    answer = extract_numeric_answer(example.get("answer"))
    return {
        "source": "tier2_generated",
        "template_id": template.get("id"),
        "question_text": example.get("problem_statement"),
        "difficulty": template.get("difficulty") or 1,
        # Generated templates carry no :Skill edge yet, so they have no mastery
        # key; combined with sandbox trust they never move mastery either way.
        "skill": None,
        "technique": (template.get("concept") or {}).get("technique_name"),
        "topic": (template.get("concept") or {}).get("category"),
        "sub_topic": (template.get("concept") or {}).get("sub_category"),
        "trust": decision.tier,
        "feeds_mastery": decision.feeds_mastery,
        "answer_verification": "verified" if answer is not None else "unverified",
        "solution_verification": "unverified",
        "answer_check": "client_extract" if answer is not None else "server_sympy",
        "expected_answer": answer,
        "template": template,
    }


async def _load_tier1(
    topic: Optional[str],
    technique: Optional[str],
    limit: int,
    excluded: set[str],
    ladder: dict[str, str],
) -> list[dict]:
    filters = [
        # trim() guards the empty-string hole: IS NOT NULL happily passes "",
        # and a blank prompt is unanswerable.
        "p.question_text IS NOT NULL AND trim(p.question_text) <> ''",
        "p.answer_key IS NOT NULL",
        "p.validation_status IN $verified",
        # Never serve what the content factory rejected.
        "NOT p.template_id IN $excluded",
    ]
    params: dict[str, Any] = {
        "verified": sorted(ANSWER_VERIFIED),
        "limit": limit,
        "excluded": sorted(excluded),
    }
    if topic:
        filters.append("p.topic = $topic")
        params["topic"] = topic
    if technique:
        filters.append("p.technique = $technique")
        params["technique"] = technique

    # The skill edge is REQUIRED, not optional: a problem with no :Skill cannot
    # move mastery, so serving it spends a learner's attempt on something the
    # engine will discard. That costs only ~1.5% of the verified pool, and it is
    # what fixed the first page arriving full of unattributable items.
    #
    # difficulty is populated on every graph :Problem (spread 10/110/315/260/112),
    # so coalesce() here is only a guard for future rows; template_id breaks ties
    # so a page is stable rather than ordered arbitrarily among equal difficulties.
    # 757 of the served problems have 2-7 skill parents, so ONE of them becomes
    # the mastery key. collect() has no ordering guarantee, and this key joins a
    # learner's history — an unstable choice would silently split mastery across
    # two keys. Ordering before collect() makes the pick deterministic, and the
    # CASE demotes structural names ("Chapter 11" is a real :Skill in this graph)
    # so a chapter number never becomes a mastery key while a concept is
    # available. Cleaning up those names is a separate scheduled migration.
    params["structural_skill"] = (
        r"(?i)^\s*(chapter|ch\.?|section|sec\.?|unit|part|exercise|ex\.?|lesson)\s*[0-9ivxl.]*\s*$|^\s*[0-9.]+\s*$"
    )
    query = (
        "MATCH (s:Skill)-[:PREREQUISITE_OF]->(p:Problem) WHERE "
        + " AND ".join(filters)
        + """ WITH p, s
              ORDER BY (CASE WHEN s.name =~ $structural_skill THEN 1 ELSE 0 END), s.name
              WITH p, head(collect(s.name)) AS skill
              RETURN p.template_id AS template_id, p.question_text AS question_text,
                     p.answer_key AS answer_key, p.difficulty AS difficulty,
                     p.technique AS technique, p.topic AS topic, p.sub_topic AS sub_topic,
                     skill
              ORDER BY coalesce(p.difficulty, 3), p.template_id LIMIT $limit"""
    )
    driver = db.get_neo4j()
    async with driver.session() as neo:
        result = await neo.run(query, **params)
        return [_tier1_item(dict(record), ladder) async for record in result]


async def _load_tier2(sub_topic: Optional[str], limit: int) -> tuple[list[dict], dict[str, int]]:
    redis = db.get_redis()
    keys = (
        [f"{TRAY_PREFIX}{sub_topic}"]
        if sub_topic
        else sorted(await redis.keys(f"{TRAY_PREFIX}*"))
    )

    items: list[dict] = []
    withheld: dict[str, int] = {}
    for key in keys:
        for raw in await redis.lrange(key, 0, limit - 1):
            try:
                entry = json.loads(raw)
            except json.JSONDecodeError:
                withheld["malformed"] = withheld.get("malformed", 0) + 1
                continue
            decision = servable_trust(entry.get("trust"))
            if not decision.servable:
                withheld[decision.reason] = withheld.get(decision.reason, 0) + 1
                continue
            items.append(_tier2_item(entry, decision))
            if len(items) >= limit:
                return items, withheld
    return items, withheld


@router.get("/session")
async def build_session(
    topic: Optional[str] = None,
    technique: Optional[str] = None,
    sub_topic: Optional[str] = None,
    size: int = Query(default=10, ge=1, le=50),
) -> dict:
    """Compose a playable session from both content tiers.

    `withheld` reports what was filtered and why, so an empty session is
    explainable rather than looking like a bug — today every Tier-2 tray item
    is quarantined pending stage-7 review, so Tier-2 legitimately yields none.
    """
    try:
        pool = await db.get_pg()
        excluded = await quarantined_ids(pool)
        ladder = await trust_levels(pool)
        tier1 = await _load_tier1(topic, technique, size, excluded, ladder)
        tier2, withheld = await _load_tier2(sub_topic, max(0, size - len(tier1)))
    except HTTPException:
        raise
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=503, detail=f"content unavailable: {type(exc).__name__}")

    items = (tier1 + tier2)[:size]
    return {
        "items": items,
        "summary": {
            "requested": size,
            "served": len(items),
            "tier1_static": sum(1 for i in items if i["source"] == "tier1_static"),
            "tier2_generated": sum(1 for i in items if i["source"] == "tier2_generated"),
            "client_checkable": sum(1 for i in items if i["answer_check"] == "client_extract"),
            "server_checkable": sum(1 for i in items if i["answer_check"] == "server_sympy"),
            "feeds_mastery": sum(1 for i in items if i["feeds_mastery"]),
            "withheld": withheld,
        },
    }
