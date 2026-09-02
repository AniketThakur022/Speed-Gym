#!/usr/bin/env python3
"""T2 generation — seeded-random parametric instantiation (no AI).

Patterns implement the recovered question_generator_config contract:
L1-L5 difficulty scaling via digit_complexity / base_distance_pct / carry_density /
min_deviation; enum bases {10, 100, 1000, 10000}; deterministic under a run seed.

Every instance carries a `compute` expression the auditor re-evaluates
INDEPENDENTLY (stage 3) — generation never grades its own homework.
Output records use the factory-side template shape so they flow through the
same auditor + to_solvealong_template() adapter as recovered T1 content.
"""

import hashlib
import random

# question_generator_config.json difficulty_scaling (recovered, canonical)
SCALING = {
    1: {"digit_complexity": 1, "base_distance_pct": 0.12, "carry_density": "low"},
    2: {"digit_complexity": 2, "base_distance_pct": 0.16, "carry_density": "low"},
    3: {"digit_complexity": 2, "base_distance_pct": 0.20, "carry_density": "medium"},
    4: {"digit_complexity": 3, "base_distance_pct": 0.25, "carry_density": "medium"},
    5: {"digit_complexity": 3, "base_distance_pct": 0.30, "carry_density": "high"},
}
MIN_DEVIATION = 2
BASES = {1: 10, 2: 100, 3: 1000}  # digit_complexity -> base


def _deviation(rng: random.Random, base: int, level: int) -> int:
    pct = SCALING[level]["base_distance_pct"]
    lo, hi = MIN_DEVIATION, max(MIN_DEVIATION + 1, int(base * pct))
    dev = rng.randint(lo, hi)
    carry = SCALING[level]["carry_density"]
    # low: both below base (no borrow juggling); medium: mixed sign; high: force mixed
    if carry == "low":
        return -dev
    if carry == "high":
        return dev if rng.random() < 0.5 else -dev
    return dev if rng.random() < 0.3 else -dev


def params_hash(pattern_id: str, params: dict) -> str:
    blob = pattern_id + "|" + "|".join(f"{k}={params[k]}" for k in sorted(params))
    return hashlib.sha256(blob.encode()).hexdigest()


def _nikhilam_steps(a, b, base):
    da, db = a - base, b - base
    cross = a + db
    prod = da * db
    steps = [
        {"step_num": 1, "operation": f"Choose the base {base}",
         "formula": f"a={a},\\; b={b},\\; \\text{{base}}={base}",
         "reasoning": "Both numbers are near this power of 10, so Nikhilam applies"},
        {"step_num": 2, "operation": "Write the deviations from the base",
         "formula": f"{a}\\to{da:+d},\\quad {b}\\to{db:+d}",
         "reasoning": "Deviation = number − base"},
        {"step_num": 3, "operation": "Cross-add for the left part",
         "formula": f"{a}{db:+d} = {cross}",
         "reasoning": "Either cross-sum gives the same left part"},
        {"step_num": 4, "operation": "Multiply the deviations for the right part",
         "formula": f"({da:+d})\\times({db:+d}) = {prod}",
         "reasoning": f"Right part must fill exactly {len(str(base)) - 1} digits (carry/borrow if not)"},
        {"step_num": 5, "operation": "Assemble the answer",
         "formula": f"{cross}\\times{base} {prod:+d} = {a * b}",
         "reasoning": "left·base + deviation product"},
    ]
    return steps


PATTERNS = {}


def pattern(pid):
    def reg(fn):
        PATTERNS[pid] = fn
        return fn
    return reg


@pattern("mult_near_base")
def gen_mult_near_base(rng: random.Random, level: int) -> dict:
    base = BASES[SCALING[level]["digit_complexity"]]
    a, b = base + _deviation(rng, base, level), base + _deviation(rng, base, level)
    return {
        "sub_topic": "Nikhilam Navatashcaramam (All from 9, Last from 10)",
        "technique_name": "multiplication",
        "problem_statement": f"Multiply {a} × {b} using the Nikhilam base method",
        "compute": f"{a}*{b}",
        "final_answer": str(a * b),
        "params": {"a": a, "b": b, "base": base},
        "solution": _nikhilam_steps(a, b, base),
        "traps": ["forgetting the carry when the deviation product overflows the base digits",
                  "sign error when one deviation is positive and one negative"],
        "visual_scaffold": {"type": "place_value_chart"},
        "prerequisite_chain": ["Arithmetic", "Basic Operations (+, -, ×, ÷)", "Number Bases"],
    }


@pattern("square_near_base")
def gen_square_near_base(rng: random.Random, level: int) -> dict:
    base = BASES[SCALING[level]["digit_complexity"]]
    d = _deviation(rng, base, level)
    a = base + d
    left, right = a + d, d * d
    return {
        "sub_topic": "Yavadunam (Deficiency Squaring)",
        "technique_name": "squaring",
        "problem_statement": f"Square {a} using the Yavadunam method (base {base})",
        "compute": f"{a}*{a}",
        "final_answer": str(a * a),
        "params": {"a": a, "base": base},
        "solution": [
            {"step_num": 1, "operation": "Deviation from the base",
             "formula": f"{a} - {base} = {d:+d}", "reasoning": "Yavadunam works on the deficiency/surplus"},
            {"step_num": 2, "operation": "Left part: add the deviation again",
             "formula": f"{a}{d:+d} = {left}", "reasoning": "Whatever the deficiency, lessen it further"},
            {"step_num": 3, "operation": "Right part: square the deviation",
             "formula": f"({d:+d})^2 = {right}", "reasoning": f"Must fill {len(str(base)) - 1} digits"},
            {"step_num": 4, "operation": "Assemble",
             "formula": f"{left}\\times{base} + {right} = {a * a}", "reasoning": "left·base + deviation²"},
        ],
        "traps": ["squaring the deviation but dropping its sign context",
                  "right part written with too few digits (missing leading zeros)"],
        "visual_scaffold": {"type": "place_value_chart"},
        "prerequisite_chain": ["Arithmetic", "Basic Operations (+, -, ×, ÷)", "Number Bases"],
    }


@pattern("mult_by_11")
def gen_mult_by_11(rng: random.Random, level: int) -> dict:
    digits = {1: (10, 99), 2: (100, 999), 3: (1000, 9999), 4: (1000, 9999), 5: (10000, 99999)}
    lo, hi = digits[level]
    a = rng.randint(lo, hi)
    return {
        "sub_topic": "Multiplication by 11 (neighbour sums)",
        "technique_name": "multiplication",
        "problem_statement": f"Multiply {a} × 11 using the neighbour-sum shortcut",
        "compute": f"{a}*11",
        "final_answer": str(a * 11),
        "params": {"a": a, "b": 11},
        "solution": [
            {"step_num": 1, "operation": "Split into digit neighbours",
             "formula": f"{a} \\times 11 = {a} \\times (10+1)", "reasoning": "11 = 10 + 1"},
            {"step_num": 2, "operation": "Add each digit to its right neighbour",
             "formula": f"{a}0 + {a} = {a * 11}", "reasoning": "Shift-and-add is the neighbour-sum rule"},
        ],
        "traps": ["forgetting to carry when neighbour sums exceed 9"],
        "visual_scaffold": {"type": "arrow_matrix"},
        "prerequisite_chain": ["Arithmetic", "Basic Operations (+, -, ×, ÷)"],
    }


def generate(pattern_id: str, level: int, count: int, run_seed: str,
             variance_boost: int = 0) -> list[dict]:
    """Deterministic batch. variance_boost widens sampling for hourly T1 resample."""
    out, seen = [], set()
    attempts = 0
    while len(out) < count and attempts < count * 50:
        attempts += 1
        rng = random.Random(f"{run_seed}:{pattern_id}:L{level}:{attempts}:{variance_boost}")
        rec = PATTERNS[pattern_id](rng, level)
        h = params_hash(pattern_id, rec["params"])
        if h in seen:
            continue
        seen.add(h)
        rec.update({
            "template_type": "generated_t2",
            "template_id": f"t2_{pattern_id}_L{level}_{h[:12]}",
            "pattern_id": pattern_id,
            "params_hash": h,
            "difficulty": level,
            "cognitive_load_score": min(5, 1 + level),
            "topic": "VedicMath",
            "generation": {"tier": "T2", "run_seed": run_seed, "attempt": attempts,
                           "variance_boost": variance_boost},
        })
        out.append(rec)
    return out
