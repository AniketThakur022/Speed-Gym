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
from ..content import extract_numeric_answer, servable_trust

router = APIRouter(prefix="/practice", tags=["practice"])

ANSWER_VERIFIED = {"verified_L1", "verified_L2"}
TRAY_PREFIX = "factory:tray:"


def _tier1_item(record: dict[str, Any]) -> dict[str, Any]:
    answer = extract_numeric_answer(record.get("answer_key"))
    return {
        "source": "tier1_static",
        "template_id": record.get("template_id"),
        "question_text": record.get("question_text"),
        "difficulty": record.get("difficulty") or 1,
        "technique": record.get("technique"),
        "topic": record.get("topic"),
        "sub_topic": record.get("sub_topic"),
        "trust": "trusted",
        "feeds_mastery": True,
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


async def _load_tier1(topic: Optional[str], technique: Optional[str], limit: int) -> list[dict]:
    filters = [
        "p.question_text IS NOT NULL",
        "p.answer_key IS NOT NULL",
        "p.validation_status IN $verified",
    ]
    params: dict[str, Any] = {"verified": sorted(ANSWER_VERIFIED), "limit": limit}
    if topic:
        filters.append("p.topic = $topic")
        params["topic"] = topic
    if technique:
        filters.append("p.technique = $technique")
        params["technique"] = technique

    query = (
        "MATCH (p:Problem) WHERE "
        + " AND ".join(filters)
        + """ RETURN p.template_id AS template_id, p.question_text AS question_text,
                     p.answer_key AS answer_key, p.difficulty AS difficulty,
                     p.technique AS technique, p.topic AS topic, p.sub_topic AS sub_topic
              ORDER BY p.difficulty LIMIT $limit"""
    )
    driver = db.get_neo4j()
    async with driver.session() as neo:
        result = await neo.run(query, **params)
        return [_tier1_item(dict(record)) async for record in result]


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
        tier1 = await _load_tier1(topic, technique, size)
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
