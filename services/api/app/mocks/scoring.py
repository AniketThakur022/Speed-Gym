"""Pool-independent scoring engine. Pure functions over the questions an
attempt was served and the answers it recorded."""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any, Optional

from ..content import extract_numeric_answer
from .blueprints import Blueprint, Section


def _norm(text: Optional[str]) -> str:
    return " ".join(str(text or "").strip().lower().split())


def grade(question: dict[str, Any], answer: Optional[str]) -> Optional[bool]:
    """True/False, or None when unattempted or not auto-gradable (essay)."""
    if question.get("kind") == "essay":
        return None
    if answer is None or _norm(answer) == "":
        return None
    expected = question.get("correct_answer")
    if expected is None:
        return None
    kind = question.get("kind")
    if kind == "mcq":
        a, e = _norm(answer), _norm(expected)
        if a == e:
            return True
        # Accept the option letter or its text.
        options = question.get("options") or []
        for i, opt in enumerate(options):
            letter = chr(ord("a") + i)
            label = _norm(opt.get("id") if isinstance(opt, dict) else letter)
            text = _norm(opt.get("text") if isinstance(opt, dict) else opt)
            if e in (label, text) and a in (label, text):
                return True
        return False
    # tita / numeric: tolerant numeric comparison
    got = extract_numeric_answer(str(answer))
    exp = extract_numeric_answer(str(expected))
    if got is None or exp is None:
        return _norm(answer) == _norm(expected)
    return abs(got - exp) <= 1e-6 * max(1.0, abs(exp))


@dataclass
class SectionResult:
    key: str
    questions: int
    attempted: int = 0
    correct: int = 0
    wrong: int = 0
    unattempted: int = 0
    raw: float = 0.0
    max_raw: float = 0.0
    accuracy: float = 0.0
    scaled: Optional[int] = None
    time_seconds: Optional[int] = None

    def as_dict(self) -> dict:
        return self.__dict__.copy()


def score_section(section: Section, questions: list[dict], answers: dict[str, Optional[str]]) -> SectionResult:
    # Max is over the questions actually served (a short pool must not
    # inflate the denominator).
    res = SectionResult(key=section.key, questions=len(questions),
                        max_raw=len(questions) * section.marks_correct if section.auto_scored else 0.0)
    for q in questions:
        verdict = grade(q, answers.get(q["question_id"]))
        if verdict is None:
            res.unattempted += 1
            continue
        res.attempted += 1
        if verdict:
            res.correct += 1
            res.raw += float(q.get("marks_correct", section.marks_correct))
        else:
            res.wrong += 1
            res.raw += float(q.get("marks_wrong", 0.0))
    res.accuracy = round(res.correct / res.attempted, 4) if res.attempted else 0.0
    if section.scaled_range and section.auto_scored and res.questions:
        lo, hi = section.scaled_range
        pct = res.correct / res.questions
        res.scaled = int(round(lo + (hi - lo) * pct))
    return res


def scale_total(blueprint: Blueprint, results: list[SectionResult]) -> Optional[int]:
    if blueprint.scoring != "scaled":
        return None
    if blueprint.key == "gmat" and blueprint.scaled_total:
        lo, hi, step = blueprint.scaled_total
        pcts = [r.correct / r.questions for r in results if r.questions and r.max_raw]
        if not pcts:
            return lo
        total = lo + (hi - lo) * (sum(pcts) / len(pcts))
        # Steps are relative to the floor (205, 215, … 805): 805 is not a multiple of 10.
        return lo + int(math.floor((total - lo) / step + 0.5)) * step
    # GRE: the two measures are reported separately; total is their sum
    return sum(r.scaled for r in results if r.scaled is not None) or None


@dataclass
class AttemptResult:
    total_raw: float
    max_raw: float
    sections: list[SectionResult]
    scaled_total: Optional[int]
    scaled_approximate: bool
    weak_areas: list[dict] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {
            "total_raw": self.total_raw, "max_raw": self.max_raw,
            "sections": [s.as_dict() for s in self.sections],
            "scaled_total": self.scaled_total, "scaled_approximate": self.scaled_approximate,
            "weak_areas": self.weak_areas,
        }


def weak_areas(questions: list[dict], answers: dict[str, Optional[str]], threshold: float = 0.7) -> list[dict]:
    """Skills answered below `threshold` accuracy (user journey §11.4: <70 %),
    ordered worst first. Unattempted questions count against the skill —
    skipping a whole topic is the signal, not noise."""
    by_skill: dict[str, list[Optional[bool]]] = {}
    for q in questions:
        if q.get("kind") == "essay":
            continue
        skill = q.get("skill") or "unclassified"
        by_skill.setdefault(skill, []).append(grade(q, answers.get(q["question_id"])))
    out = []
    for skill, verdicts in by_skill.items():
        n = len(verdicts)
        correct = sum(1 for v in verdicts if v)
        acc = correct / n if n else 0.0
        if acc < threshold:
            out.append({"skill": skill, "questions": n, "correct": correct, "accuracy": round(acc, 3)})
    out.sort(key=lambda w: (w["accuracy"], -w["questions"]))
    return out


def score_attempt(blueprint: Blueprint, served: dict[str, list[dict]], answers: dict[str, Optional[str]],
                  section_times: Optional[dict[str, int]] = None) -> AttemptResult:
    results: list[SectionResult] = []
    for key, questions in served.items():
        section = blueprint.section(key)
        if section is None:
            continue
        r = score_section(section, questions, answers)
        if section_times and key in section_times:
            r.time_seconds = int(section_times[key])
        results.append(r)
    all_q = [q for qs in served.values() for q in qs]
    return AttemptResult(
        total_raw=round(sum(r.raw for r in results), 2),
        max_raw=sum(r.max_raw for r in results),
        sections=results,
        scaled_total=scale_total(blueprint, results),
        scaled_approximate=blueprint.scoring == "scaled",
        weak_areas=weak_areas(all_q, answers),
    )


def percentile(score: float, others: list[float]) -> int:
    """Percent of other test-takers at or below this score (ties count half).
    0 when nobody else has taken this configuration yet — honest, not 50."""
    if not others:
        return 0
    below = sum(1 for o in others if o < score)
    equal = sum(1 for o in others if o == score)
    return int(round(100 * (below + 0.5 * equal) / len(others)))
