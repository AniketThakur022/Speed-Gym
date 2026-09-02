#!/usr/bin/env python3
"""
Bank Exhaustion Handler — Replenishment strategy for Topic Browser.

Implements 5-tier replenishment:
  1. resample_with_stricter_dedup
  2. escalate_difficulty
  3. cross_topic_bridge
  4. llm_regenerate
  5. explainer_conversion

Plus graceful degradation and spaced-repetition reinsertion.
"""
import json
import uuid
import random
from pathlib import Path
from typing import List, Dict, Any, Optional

CONFIG_DIR = Path(__file__).resolve().parent.parent / "runtime_config"


def load_config(name: str) -> dict:
    with open(CONFIG_DIR / name) as f:
        return json.load(f)


class BankExhaustionHandler:
    def __init__(self):
        self.cfg = load_config("bank_exhaustion_config.json")
        self.tiers = {t["tier"]: t for t in self.cfg["replenishment_tiers"]}
        # Topic -> [subtopic_id] registry (validated before any operation)
        # MUST stay in sync with files in content_data/subtopic_explainer/*.json
        self.topic_registry: Dict[str, List[str]] = {
            "Vedic Math": [
                "nikhilam_sutra",
                "urdhva_tiryak",
                "yavadunam",
                "ekanyunena_purvena",
                "puranapuranabhyam",
                "chalana_kalanabhyam",
                "sopantyadvayam",
                "vyasti_samasti",
                "gunaka_samuccayah",
                "gunita_samuccayah",
                "seshanyakena_caramena",
            ],
            "Maths": [
                "addition_tricks",
                "subtraction_tricks",
                "multiplication_tricks",
                "division_tricks",
                "fractions",
                "ratios_proportions",
                "percentages",
                "linear_equations",
                "quadratic_equations",
                "polynomials",
                "number_theory",
                "geometry_basics",
                "mensuration",
                "school_foundation",
            ],
            "Exam Prep": [
                "arithmetic_gre",
                "problem_solving_gmat",
                "quantitative_aptitude_cat",
            ],
        }

    def _validate_topic_subtopic(self, topic: str, subtopic_id: str) -> bool:
        """Topic -> subtopic existence check."""
        if topic not in self.topic_registry:
            raise ValueError(f"Unknown topic: {topic}")
        allowed = self.topic_registry[topic]
        if subtopic_id not in allowed:
            raise ValueError(f"Subtopic {subtopic_id!r} is not under topic {topic!r}. Allowed: {allowed}")
        return True

    def detect_exhaustion(
        self,
        subtopic_id: str,
        available_count: int,
        cache_miss_rate: float,
        mastery_pct: float,
        topic: Optional[str] = None,
    ) -> Optional[str]:
        """Return replenishment tier name or None if not exhausted."""
        if topic:
            self._validate_topic_subtopic(topic, subtopic_id)

        if available_count == 0:
            return "explainer_conversion"
        if cache_miss_rate > 0.95:
            return "llm_regenerate"
        if mastery_pct >= 0.85 and available_count <= 3:
            return "cross_topic_bridge"
        if available_count <= 5:
            return "escalate_difficulty"
        if available_count <= 10:
            return "resample_with_stricter_dedup"
        return None

    def replenish(
        self,
        tier_name: str,
        subtopic_id: str,
        current_difficulty: str,
        available_problems: List[Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        """Produce new problem candidates based on tier strategy."""
        tier = next((t for t in self.cfg["replenishment_tiers"] if t["name"] == tier_name), None)
        if not tier:
            raise ValueError(f"Unknown tier: {tier_name}")

        new_problems: List[Dict[str, Any]] = []

        if tier_name == "resample_with_stricter_dedup":
            # Increase variance on existing patterns
            for _ in range(min(5, len(available_problems) or 5)):
                base = random.choice([10, 100, 1000])
                a = base - random.randint(1, int(base * 0.25))
                b = base - random.randint(1, int(base * 0.25))
                new_problems.append(self._build_problem(subtopic_id, current_difficulty, a, b, base))

        elif tier_name == "escalate_difficulty":
            next_diff = self._next_difficulty(current_difficulty)
            for _ in range(3):
                base = random.choice([100, 1000])
                a = base - random.randint(1, int(base * 0.3))
                b = base - random.randint(1, int(base * 0.3))
                new_problems.append(self._build_problem(subtopic_id, next_diff, a, b, base))

        elif tier_name == "cross_topic_bridge":
            topic_for_subtopic = next(
                (t for t, subs in self.topic_registry.items() if subtopic_id in subs), None
            )
            if not topic_for_subtopic:
                raise ValueError(f"Unknown subtopic: {subtopic_id}")
            siblings = [s for s in self.topic_registry[topic_for_subtopic] if s != subtopic_id]
            if not siblings:
                return []
            for sibling in random.sample(siblings, k=min(2, len(siblings))):
                base = random.choice([10, 100])
                a = base - random.randint(1, int(base * 0.2))
                b = base - random.randint(1, int(base * 0.2))
                new_problems.append(self._build_problem(sibling, current_difficulty, a, b, base))

        elif tier_name == "llm_regenerate":
            # Stub: LLM generation would happen here; for smoke test produce variants
            for _ in range(3):
                base = random.choice([100, 1000, 10000])
                a = base - random.randint(1, int(base * 0.35))
                b = base - random.randint(1, int(base * 0.35))
                new_problems.append(self._build_problem(subtopic_id, current_difficulty, a, b, base, source="llm"))

        elif tier_name == "explainer_conversion":
            # Stub: convert explainer examples into practice
            for _ in range(3):
                base = random.choice([100, 1000])
                a = base - random.randint(1, int(base * 0.15))
                b = base - random.randint(1, int(base * 0.15))
                new_problems.append(self._build_problem(subtopic_id, current_difficulty, a, b, base, source="explainer"))

        return new_problems

    def _build_problem(
        self,
        subtopic_id: str,
        difficulty: str,
        a: int,
        b: int,
        base: int,
        source: str = "replenishment",
    ) -> Dict[str, Any]:
        return {
            "problem_id": str(uuid.uuid4()),
            "subtopic_id": subtopic_id,
            "difficulty_level": difficulty,
            "problem_text": f"Multiply {a} × {b}",
            "problem_latex": f"{a} \\times {b}",
            "answer": str(a * b),
            "base": base,
            "params": {"a": a, "b": b, "base": base},
            "source": source,
        }

    def _next_difficulty(self, difficulty: str) -> str:
        mapping = {"L1": "L2", "L2": "L3", "L3": "L4", "L4": "L5", "L5": "L5"}
        return mapping.get(difficulty, "L5")

    def spaced_repetition_reinsert(
        self,
        mastered_problems: List[Dict[str, Any]],
        days_since_last_seen: List[int],
        mastery_levels: Optional[List[int]] = None,
    ) -> List[Dict[str, Any]]:
        """Return mastered problems that should be reviewed now.

        Uses graduated intervals based on mastery level:
          mastery 0-2 -> 1 day
          mastery 3-4 -> 3 days
          mastery 5-6 -> 7 days
          mastery 7+  -> 14+ days
        """
        intervals = self.cfg["spaced_repetition"]["intervals_days"]
        mastery_levels = mastery_levels or [0] * len(mastered_problems)
        to_review: List[Dict[str, Any]] = []
        for prob, days, mastery in zip(mastered_problems, days_since_last_seen, mastery_levels):
            idx = min(mastery // 2, len(intervals) - 1)
            threshold = intervals[idx]
            if days >= threshold:
                to_review.append(prob)
        return to_review


if __name__ == "__main__":
    handler = BankExhaustionHandler()

    # Smoke tests
    assert handler.detect_exhaustion("nikhilam_sutra", 20, 0.1, 0.3, topic="Vedic Math") is None
    assert handler.detect_exhaustion("nikhilam_sutra", 8, 0.2, 0.5, topic="Vedic Math") == "resample_with_stricter_dedup"
    assert handler.detect_exhaustion("nikhilam_sutra", 3, 0.2, 0.6, topic="Vedic Math") == "escalate_difficulty"
    assert handler.detect_exhaustion("nikhilam_sutra", 2, 0.2, 0.9, topic="Vedic Math") == "cross_topic_bridge"
    assert handler.detect_exhaustion("nikhilam_sutra", 0, 0.96, 0.95, topic="Vedic Math") == "explainer_conversion"

    # Topic -> subtopic validation test
    try:
        handler.detect_exhaustion("linear_equations", 0, 0.0, 0.0, topic="Vedic Math")
        raise AssertionError("Expected topic->subtopic validation to fail")
    except ValueError as e:
        assert "not under topic" in str(e)

    new = handler.replenish("explainer_conversion", "nikhilam_sutra", "L2", [])
    assert len(new) == 3
    assert all(p["answer"] == str(int(p["params"]["a"]) * int(p["params"]["b"])) for p in new)

    review = handler.spaced_repetition_reinsert([{"id": 1}], [3], [3])
    assert len(review) == 1, "Expected 1 problem due for review (mastery 3 → 3-day threshold)"

    not_due = handler.spaced_repetition_reinsert([{"id": 2}], [1], [5])
    assert len(not_due) == 0, "Expected 0 problems not yet due (mastery 5 → 7-day threshold)"

    print("✅ Bank Exhaustion Handler smoke tests passed")
