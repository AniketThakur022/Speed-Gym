"""Pluggable question sources. A pool tag maps to a source; the scoring engine
never knows which. Default bindings:

* `quant` → the graph (same guards as practice: skill edge, verified question
  AND answer, not quarantined, non-blank) — Vedic/quant items with numeric
  answers, served as `numeric` questions.
* everything else → a static JSON pool under data/mocks/pools/<tag>.json, if
  present. Absent pool = the section cannot be served, and /configure says so
  (503 with the tag) rather than padding the exam with the wrong subject.

The owner's serving-path decision (June graph vs 25-book corpus vs both)
becomes a binding change here, nothing else.
"""

from __future__ import annotations

import hashlib
import json
import random
from pathlib import Path
from typing import Any, Optional, Protocol

from .. import db
from ..content import extract_numeric_answer, format_answer, quarantined_ids, servable_trust, trust_levels
from .blueprints import Section

POOLS_DIR = Path(__file__).resolve().parents[4] / "data" / "mocks" / "pools"


class QuestionSource(Protocol):
    async def fetch(self, section: Section, count: int, seed: str) -> list[dict[str, Any]]: ...
    async def available(self) -> bool: ...


def _ramp(questions: list[dict], count: int, rng: random.Random) -> list[dict]:
    """Difficulty curve: linear ramp 30 % easy → 70 % hard (user journey §11.2),
    ordered ascending so the exam gets harder as it goes."""
    easy = [q for q in questions if float(q.get("difficulty") or 1) <= 2]
    hard = [q for q in questions if float(q.get("difficulty") or 1) > 2]
    rng.shuffle(easy); rng.shuffle(hard)
    n_easy = min(len(easy), int(round(count * 0.3)))
    picked = easy[:n_easy] + hard[: count - n_easy]
    if len(picked) < count:
        rest = [q for q in easy[n_easy:] + hard[count - n_easy:] if q not in picked]
        picked += rest[: count - len(picked)]
    picked.sort(key=lambda q: float(q.get("difficulty") or 1))
    return picked[:count]


class GraphSource:
    """Numeric-answer problems from the live graph, practice-loop guards applied."""

    CYPHER = """
    MATCH (s:Skill)-[:PREREQUISITE_OF]->(p:Problem)
    WHERE p.question_text IS NOT NULL AND trim(p.question_text) <> ''
      AND p.answer_key IS NOT NULL
      AND p.validation_status IN ['verified_L1', 'verified_L2']
      AND NOT p.template_id IN $excluded
    WITH p, head(collect(s.name)) AS skill
    RETURN p.template_id AS problem_id, p.question_text AS text, p.answer_key AS answer_key,
           p.difficulty AS difficulty, skill
    LIMIT 800
    """

    async def available(self) -> bool:
        try:
            await db.get_neo4j().verify_connectivity()
            return True
        except Exception:  # noqa: BLE001
            return False

    async def fetch(self, section: Section, count: int, seed: str) -> list[dict[str, Any]]:
        pool = await db.get_pg()
        excluded = await quarantined_ids(pool)
        # The quarantine rung alone is WEAKER than the practice loop: content.py
        # and session.py both state that SANDBOX content "never feeds BKT or
        # mock exams", so a stage-7 SANDBOX verdict has to exclude an item here
        # too. Reading the whole ladder is what makes the review observable.
        ladder = await trust_levels(pool)
        async with db.get_neo4j().session() as neo:
            result = await neo.run(self.CYPHER, excluded=sorted(excluded))
            rows = [dict(r) async for r in result]
        candidates = []
        for r in rows:
            ans = extract_numeric_answer(r.get("answer_key"))
            if ans is None or not r.get("problem_id"):
                continue
            verdict = ladder.get(r["problem_id"])
            if verdict is not None and not servable_trust(verdict).feeds_mastery:
                continue
            candidates.append({
                "question_id": r["problem_id"], "kind": "numeric", "text": r["text"],
                "options": None, "correct_answer": format_answer(ans), "skill": r.get("skill"),
                "difficulty": float(r.get("difficulty") or 1),
            })
        rng = random.Random(int(hashlib.sha256(seed.encode()).hexdigest(), 16))
        return _ramp(candidates, count, rng)


class StaticPoolSource:
    """A JSON file: [{question_id, kind, text, options?, correct_answer, skill?, difficulty?}]."""

    def __init__(self, tag: str, path: Optional[Path] = None):
        self.tag = tag
        self.path = path or (POOLS_DIR / f"{tag}.json")

    def _load(self) -> list[dict]:
        if not self.path.exists():
            return []
        try:
            data = json.loads(self.path.read_text())
        except ValueError:
            return []
        return [q for q in data if q.get("question_id") and q.get("text") and q.get("kind")]

    async def available(self) -> bool:
        return bool(self._load())

    async def fetch(self, section: Section, count: int, seed: str) -> list[dict[str, Any]]:
        items = [q for q in self._load() if q.get("kind") in section.kinds]
        rng = random.Random(int(hashlib.sha256(seed.encode()).hexdigest(), 16))
        return _ramp(items, count, rng)


class InMemorySource:
    """Tests and fixtures."""

    def __init__(self, items: list[dict]):
        self.items = items

    async def available(self) -> bool:
        return bool(self.items)

    async def fetch(self, section: Section, count: int, seed: str) -> list[dict[str, Any]]:
        rng = random.Random(int(hashlib.sha256(seed.encode()).hexdigest(), 16))
        return _ramp([q for q in self.items if q.get("kind") in section.kinds], count, rng)


_overrides: dict[str, QuestionSource] = {}


def set_source_override(tag: str, source: Optional[QuestionSource]) -> None:
    if source is None:
        _overrides.pop(tag, None)
    else:
        _overrides[tag] = source


def source_for(tag: str) -> QuestionSource:
    if tag in _overrides:
        return _overrides[tag]
    if tag == "quant":
        return GraphSource()
    return StaticPoolSource(tag)
