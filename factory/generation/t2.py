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
        # Canonical sub_topic strings mirror the recovered bank exactly, so generated
        # items join the same :Skill as the 861 static templates instead of forking one.
        "sub_topic": "Yavadunam Sutra (Deficiency/Surplus Squaring)",
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


@pattern("urdhva_2x2")
def gen_urdhva_2x2(rng: random.Random, level: int) -> dict:
    """Vertically and crosswise — the general multiplication algorithm.

    Parameter space is ~8,100 pairs at 2 digits (vs a handful for the near-base
    patterns at base 10), which is what makes hourly refill viable per-level.
    """
    lo, hi = {1: (11, 39), 2: (11, 69), 3: (21, 99), 4: (21, 99), 5: (31, 99)}[level]
    a_n, b_n = rng.randint(lo, hi), rng.randint(lo, hi)
    a, b = divmod(a_n, 10)[0], a_n % 10
    c, d = divmod(b_n, 10)[0], b_n % 10
    p1 = b * d
    p2 = a * d + b * c + p1 // 10
    p3 = a * c + p2 // 10
    return {
        "sub_topic": "Urdhva Tiryagbhyam (Vertically and Crosswise)",
        "technique_name": "multiplication",
        "problem_statement": f"Multiply {a_n} × {b_n} using Urdhva Tiryagbhyam (vertically and crosswise)",
        "compute": f"{a_n}*{b_n}",
        "final_answer": str(a_n * b_n),
        "params": {"a": a_n, "b": b_n},
        "solution": [
            {"step_num": 1, "operation": "Write the numbers one above the other",
             "formula": f"{a_n} \\times {b_n}",
             "reasoning": "Urdhva works digit-position by digit-position, right to left"},
            {"step_num": 2, "operation": "Vertical product of the units digits",
             "formula": f"{b} \\times {d} = {p1} \\Rightarrow \\text{{write }} {p1 % 10}"
                        + (f", \\text{{carry }} {p1 // 10}" if p1 // 10 else ""),
             "reasoning": "The units digit of the answer comes from the units column alone"},
            {"step_num": 3, "operation": "Crosswise products, added",
             "formula": f"({a} \\times {d}) + ({b} \\times {c})"
                        + (f" + {p1 // 10}" if p1 // 10 else "")
                        + f" = {p2} \\Rightarrow \\text{{write }} {p2 % 10}"
                        + (f", \\text{{carry }} {p2 // 10}" if p2 // 10 else ""),
             "reasoning": "The tens digit collects both crosswise pairs plus any carry"},
            {"step_num": 4, "operation": "Vertical product of the leading digits",
             "formula": f"{a} \\times {c}" + (f" + {p2 // 10}" if p2 // 10 else "") + f" = {p3}",
             "reasoning": "The leading columns finish the number"},
            {"step_num": 5, "operation": "Read the digits off left to right",
             "formula": f"{a_n} \\times {b_n} = {a_n * b_n}",
             "reasoning": "Assembling the column digits with their carries gives the product"},
        ],
        "traps": ["adding only one crosswise product instead of both",
                  "dropping the carry from the units column into the crosswise step"],
        "visual_scaffold": {"type": "arrow_matrix"},
        "prerequisite_chain": ["Arithmetic", "Basic Operations (+, -, ×, ÷)",
                               "Multiplication Tables"],
    }


@pattern("ekadhikena_square_5")
def gen_ekadhikena_square_5(rng: random.Random, level: int) -> dict:
    """Ekadhikena Purvena — squaring a number ending in 5: a(a+1) | 25."""
    hi = {1: 9, 2: 19, 3: 39, 4: 69, 5: 99}[level]
    a = rng.randint(1, hi)
    n = 10 * a + 5
    left = a * (a + 1)
    return {
        "sub_topic": "Ekadhikena Purvena (One More than the Previous)",
        "technique_name": "squaring",
        "problem_statement": f"Square {n} using Ekadhikena Purvena (one more than the previous)",
        "compute": f"{n}*{n}",
        "final_answer": str(n * n),
        "params": {"a": a, "n": n},
        "solution": [
            {"step_num": 1, "operation": "Split off the final 5",
             "formula": f"{n} = {a}\\,|\\,5",
             "reasoning": "The sutra applies to any number whose last digit is 5"},
            {"step_num": 2, "operation": "Take one more than the previous digits",
             "formula": f"{a} + 1 = {a + 1}",
             "reasoning": "'Ekadhikena Purvena' means by one more than the previous one"},
            {"step_num": 3, "operation": "Multiply the previous by that successor",
             "formula": f"{a} \\times {a + 1} = {left}",
             "reasoning": "This product forms the left-hand part of the square"},
            {"step_num": 4, "operation": "Append 25",
             "formula": f"{left}\\,|\\,25 = {n * n}",
             "reasoning": "The square of the final 5 always contributes exactly 25"},
        ],
        "traps": ["multiplying the digits by themselves instead of by the next number",
                  "appending 5 instead of 25 to the left-hand part"],
        "visual_scaffold": {"type": "place_value_chart"},
        "prerequisite_chain": ["Arithmetic", "Basic Operations (+, -, ×, ÷)",
                               "Multiplication Tables"],
    }


@pattern("nikhilam_complement")
def gen_nikhilam_complement(rng: random.Random, level: int) -> dict:
    """All from 9 and the last from 10 — subtraction from a power of ten."""
    # Capped at 4 digits because the recovered question_generator_config enumerates
    # bases [10, 100, 1000, 10000]; L5 gets its difficulty from tighter digits
    # (no 0s or 9s, which make complements trivial) rather than a 5th digit.
    digits = {1: 2, 2: 3, 3: 3, 4: 4, 5: 4}[level]
    base = 10 ** digits

    def ok(x: int) -> bool:
        if x % 10 == 0:  # 'last from 10' needs a nonzero final digit
            return False
        return not (level == 5 and ({"0", "9"} & set(str(x))))

    n = rng.randint(10 ** (digits - 1), base - 1)
    for _ in range(60):
        if ok(n):
            break
        n = rng.randint(10 ** (digits - 1), base - 1)
    ds = [int(c) for c in str(n).zfill(digits)]
    comp = [9 - x for x in ds[:-1]] + [10 - ds[-1]]
    return {
        "sub_topic": "Nikhilam Navatashcaramam (All from 9, Last from 10)",
        "technique_name": "subtraction",
        "problem_statement": f"Subtract {n} from {base} using 'all from 9 and the last from 10'",
        "compute": f"{base}-{n}",
        "final_answer": str(base - n),
        "params": {"n": n, "base": base},
        "solution": [
            {"step_num": 1, "operation": "Line the number up against the base",
             "formula": f"{base} - {n}",
             "reasoning": f"The base is a power of ten with {digits} zeros"},
            {"step_num": 2, "operation": "Subtract every digit but the last from 9",
             "formula": " ,\\quad ".join(f"9 - {d} = {9 - d}" for d in ds[:-1]) or "\\text{(no leading digits)}",
             "reasoning": "'All from 9' applies to every digit except the final one"},
            {"step_num": 3, "operation": "Subtract the last digit from 10",
             "formula": f"10 - {ds[-1]} = {comp[-1]}",
             "reasoning": "'The last from 10' completes the complement"},
            {"step_num": 4, "operation": "Read the complement",
             "formula": f"{base} - {n} = {''.join(str(x) for x in comp)}",
             "reasoning": "No borrowing is needed anywhere in the subtraction"},
        ],
        "traps": ["taking the last digit from 9 as well, giving an answer one too small",
                  "borrowing out of habit instead of applying the complement"],
        "visual_scaffold": {"type": "place_value_chart"},
        "prerequisite_chain": ["Arithmetic", "Basic Operations (+, -, ×, ÷)", "Number Bases"],
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
