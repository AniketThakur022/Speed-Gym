#!/usr/bin/env python3
"""
Topic Browser Orchestrator — Wires together question generation, auditing,
answer generation, validation loop, and bank exhaustion handling.
"""
import json
import uuid
import random
from pathlib import Path
from typing import Optional, Dict, Any, List

CONFIG_DIR = Path(__file__).resolve().parent.parent / "runtime_config"


def load_config(name: str) -> dict:
    with open(CONFIG_DIR / name) as f:
        return json.load(f)


class TopicBrowserOrchestrator:
    def __init__(self):
        self.question_cfg = load_config("question_generator_config.json")
        self.auditor_cfg = load_config("auditor_system_config.json")
        self.answer_cfg = load_config("answer_generator_config.json")
        self.validation_cfg = load_config("validation_loop_config.json")
        self.exhaustion_cfg = load_config("bank_exhaustion_config.json")
        self.master_cfg = load_config("master_orchestrator_config.json")
        self.seen_hashes: set = set()

    def generate_question(
        self,
        subtopic_id: str,
        difficulty: str,
        user_mastery: Optional[Dict[str, Any]] = None,
    ) -> Optional[Dict[str, Any]]:
        """Smoke-testable entry point: build a single question instance."""
        user_mastery = user_mastery or {}

        valid_difficulties = ["L1", "L2", "L3", "L4", "L5"]
        if difficulty not in valid_difficulties:
            raise ValueError(f"Invalid difficulty: {difficulty!r}. Must be one of {valid_difficulties}")

        # --- Tier 1: static bank stub ---
        # In production this loads from Neo4j/JSONL based on subtopic_id.
        base = random.choice([10, 100, 1000])
        offset_range = self.question_cfg["difficulty_scaling"][difficulty]["base_distance_pct"]
        max_offset = max(2, int(base * offset_range))

        a = base - random.randint(1, max_offset)
        b = base - random.randint(1, max_offset)

        problem = {
            "problem_id": str(uuid.uuid4()),
            "subtopic_id": subtopic_id,
            "difficulty_level": difficulty,
            "problem_text": f"Multiply {a} × {b}",
            "problem_latex": f"{a} \\times {b}",
            "base": base,
            "params": {"a": a, "b": b, "base": base},
        }

        # --- Auditor stub ---
        audit_ok = self._run_audit_stub(problem)
        if not audit_ok:
            return None

        # --- Answer generator stub ---
        problem["answer"] = str(a * b)

        # Dedup
        phash = hash((a, b, base))
        if phash in self.seen_hashes:
            return None
        self.seen_hashes.add(phash)

        return problem

    def _run_audit_stub(self, problem: Dict[str, Any]) -> bool:
        # Stage 1 structural + Stage 3 SymPy
        if not problem["problem_text"]:
            return False
        try:
            a = problem["params"]["a"]
            b = problem["params"]["b"]
            _ = a * b
        except Exception:
            return False
        return True

    def validate_answer(self, problem: Dict[str, Any], user_answer: str) -> Dict[str, Any]:
        """Smoke-testable entry point: validate a user answer."""
        canonical = problem.get("answer", "")
        normalized_user = user_answer.strip().replace(",", "")
        normalized_canonical = canonical.strip().replace(",", "")

        is_correct = normalized_user == normalized_canonical

        result = {
            "is_correct": is_correct,
            "correct_answer": canonical,
            "user_answer": user_answer,
            "trap_detected": None,
            "feedback": self.validation_cfg["feedback"]["on_correct" if is_correct else "on_incorrect"],
        }

        if not is_correct:
            # Stub trap detection
            result["trap_detected"] = {
                "trap_type": "CALCULATION_ERROR",
                "hint": "Double-check your multiplication and carry handling.",
            }

        return result

    def check_exhaustion(self, available_count: int) -> str:
        """Smoke-testable entry point: decide replenishment tier.

        Mirrors the 5-tier strategy in bank_exhaustion_config.json.
        """
        if available_count > 10:
            return "none"
        if available_count > 5:
            return "resample_with_stricter_dedup"
        if available_count > 2:
            return "escalate_difficulty"
        if available_count > 0:
            return "cross_topic_bridge"
        return "explainer_conversion"


if __name__ == "__main__":
    # Smoke test path
    orch = TopicBrowserOrchestrator()
    q = orch.generate_question("nikhilam_sutra", "L2")
    assert q is not None, "Question generation failed"
    assert "answer" in q, "Answer missing"

    val_correct = orch.validate_answer(q, q["answer"])
    assert val_correct["is_correct"] is True, "Correct answer marked wrong"

    val_wrong = orch.validate_answer(q, str(int(q["answer"]) + 1))
    assert val_wrong["is_correct"] is False, "Wrong answer marked correct"

    exhaustion = orch.check_exhaustion(0)
    assert exhaustion == "explainer_conversion", "Exhaustion tier mismatch"

    print("✅ Topic Browser Orchestrator smoke tests passed")
