"""Exam blueprints — AUTHORED from the specs, because the live graph export has
zero :MockExam / :ExamBlueprint / :Section nodes (verified 2026-09-05).

Sources: architecture §10/§13 (CAT MCQ −1/3 of +3 → −1, MOCK-EXM-01; TITA no
negative), frontend_system_deep_mapping §2.3d (VARC 24 q / 40 min, DILR 20 q /
40 min, QA 40 min), the CAT 2023–2025 pattern (66 questions: 24/20/22), GMAT
Focus Edition (21/23/20 in 45 min each, no negative marking, 205–805 scaled),
GRE (Sept-2023 shorter test: Verbal 12+15 q, Quant 12+15 q, AWA one task, 130–170
per measure, no negative marking).

Scaled scores for GMAT/GRE are LINEAR APPROXIMATIONS — the official
concordance tables are not in the specs and are not public. They are labelled
`approximate` in every response so the client never presents them as official.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

# Pool tags decouple sections from sources. The same tag can be bound to the
# Vedic graph today and the 25-book corpus tomorrow without touching scoring.
POOL_QUANT = "quant"


@dataclass(frozen=True)
class Section:
    key: str
    name: str
    questions: int
    minutes: int
    pool: str
    kinds: tuple[str, ...] = ("mcq", "tita")
    marks_correct: float = 3.0
    marks_wrong_mcq: float = -1.0          # CAT: −1/3 of +3 (MOCK-EXM-01)
    marks_wrong_tita: float = 0.0
    scaled_range: Optional[tuple[int, int]] = None
    auto_scored: bool = True
    notes: str = ""

    @property
    def max_raw(self) -> float:
        return self.questions * self.marks_correct if self.auto_scored else 0.0


@dataclass(frozen=True)
class Blueprint:
    key: str
    name: str
    sections: tuple[Section, ...]
    scoring: str                                  # "raw" | "scaled"
    negative_marking: bool
    scaled_total: Optional[tuple[int, int, int]] = None   # (lo, hi, step)
    notes: str = ""
    extra: dict = field(default_factory=dict)

    @property
    def total_minutes(self) -> int:
        return sum(s.minutes for s in self.sections)

    @property
    def max_raw(self) -> float:
        return sum(s.max_raw for s in self.sections)

    def section(self, key: str) -> Optional[Section]:
        return next((s for s in self.sections if s.key == key), None)


BLUEPRINTS: dict[str, Blueprint] = {
    "cat": Blueprint(
        key="cat", name="CAT", scoring="raw", negative_marking=True,
        notes="CAT 2023–2025 pattern: 66 questions, 120 min, +3 correct, −1 wrong MCQ, TITA no negative.",
        sections=(
            Section("varc", "Verbal Ability & Reading Comprehension", 24, 40, "cat_varc"),
            Section("dilr", "Data Interpretation & Logical Reasoning", 20, 40, "cat_dilr"),
            Section("qa", "Quantitative Ability", 22, 40, POOL_QUANT, kinds=("mcq", "tita", "numeric")),
        ),
    ),
    "gmat": Blueprint(
        key="gmat", name="GMAT Focus Edition", scoring="scaled", negative_marking=False,
        scaled_total=(205, 805, 10),
        notes="Three 45-minute sections, no negative marking; section scale 60–90, total 205–805 (approximate linear scaling).",
        sections=(
            Section("quant", "Quantitative Reasoning", 21, 45, POOL_QUANT, kinds=("mcq", "numeric"),
                    marks_correct=1.0, marks_wrong_mcq=0.0, scaled_range=(60, 90)),
            Section("verbal", "Verbal Reasoning", 23, 45, "gmat_verbal", kinds=("mcq",),
                    marks_correct=1.0, marks_wrong_mcq=0.0, scaled_range=(60, 90)),
            Section("di", "Data Insights", 20, 45, "gmat_di", kinds=("mcq", "numeric"),
                    marks_correct=1.0, marks_wrong_mcq=0.0, scaled_range=(60, 90)),
        ),
    ),
    "gre": Blueprint(
        key="gre", name="GRE General Test", scoring="scaled", negative_marking=False,
        notes="Shorter GRE (Sept 2023+): Verbal 12+15 q / 41 min, Quant 12+15 q / 47 min, AWA one 30-min task (recorded, not auto-scored); 130–170 per measure (approximate linear scaling).",
        sections=(
            Section("verbal", "Verbal Reasoning", 27, 41, "gre_verbal", kinds=("mcq",),
                    marks_correct=1.0, marks_wrong_mcq=0.0, scaled_range=(130, 170)),
            Section("quant", "Quantitative Reasoning", 27, 47, POOL_QUANT, kinds=("mcq", "numeric"),
                    marks_correct=1.0, marks_wrong_mcq=0.0, scaled_range=(130, 170)),
            Section("awa", "Analytical Writing", 1, 30, "gre_awa", kinds=("essay",),
                    marks_correct=0.0, marks_wrong_mcq=0.0, auto_scored=False,
                    notes="Essay is stored for review; no automatic score."),
        ),
    ),
}

assert sum(len(b.sections) for b in BLUEPRINTS.values()) == 9, "architecture: 3 blueprints, 9 sections"


def catalogue() -> list[dict]:
    return [
        {
            "key": b.key, "name": b.name, "scoring": b.scoring, "negative_marking": b.negative_marking,
            "total_minutes": b.total_minutes, "max_raw": b.max_raw,
            "scaled_total": list(b.scaled_total) if b.scaled_total else None, "notes": b.notes,
            "sections": [
                {
                    "key": s.key, "name": s.name, "questions": s.questions, "minutes": s.minutes,
                    "pool": s.pool, "kinds": list(s.kinds), "marks_correct": s.marks_correct,
                    "marks_wrong_mcq": s.marks_wrong_mcq, "marks_wrong_tita": s.marks_wrong_tita,
                    "scaled_range": list(s.scaled_range) if s.scaled_range else None,
                    "auto_scored": s.auto_scored, "notes": s.notes,
                }
                for s in b.sections
            ],
        }
        for b in BLUEPRINTS.values()
    ]
