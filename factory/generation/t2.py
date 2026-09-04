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
import re

# question_generator_config.json difficulty_scaling (recovered, canonical)
SCALING = {
    1: {"digit_complexity": 1, "base_distance_pct": 0.12, "carry_density": "low"},
    2: {"digit_complexity": 2, "base_distance_pct": 0.16, "carry_density": "low"},
    3: {"digit_complexity": 2, "base_distance_pct": 0.20, "carry_density": "medium"},
    4: {"digit_complexity": 3, "base_distance_pct": 0.25, "carry_density": "medium"},
    5: {"digit_complexity": 3, "base_distance_pct": 0.30, "carry_density": "high"},
}
MIN_DEVIATION = 2
# Bump when the fingerprint hashing rule changes: v2 added the step FORMULA and
# multi-instance variant sampling, so v1 hashes are incomparable, not "changed".
FINGERPRINT_VERSION = "fpv2"
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


def _assemble_near_base(cross: int, prod: int, base: int):
    """Resolve the right part against the base's digit width.

    The stage-7 panel caught the walkthroughs asserting the right part "must fill
    exactly N digits" while displaying a product that does not — measured at ~80%
    of L3-L5 instances. The real sutra rule is a carry (or a borrow when the
    deviation product is negative), so it must be computed AND shown, not asserted.
    Returns (left_final, right_str, adjust_note | None).
    """
    width = len(str(base)) - 1
    span = 10 ** width
    if prod >= span:
        carry, right = divmod(prod, span)
        return cross + carry, str(right).zfill(width), {
            "operation": "Carry the overflow into the left part",
            "reasoning": "The right part cannot be wider than the base's zeros, so the "
                         "excess is ADDED to the left part",
            "formula": (
                f"{prod} \\div {span} = {carry} \\text{{ remainder }} {right} "
                f"\\;\\Rightarrow\\; \\text{{carry }} {carry},\\; "
                f"\\text{{left }} {cross} + {carry} = {cross + carry},\\; "
                f"\\text{{right }} {str(right).zfill(width)}")}
    if prod < 0:
        # The trigger here is NEGATIVITY, not width: a negative product must be
        # completed from the base regardless of how few digits it has. Sizing the
        # borrow is ceil(|prod| / span), and every figure is shown rather than
        # asserted — a panel caught an earlier version stating "borrow 31" with the
        # two load-bearing computations happening off-page.
        borrow = -(-abs(prod) // span) if abs(prod) % span else abs(prod) // span
        borrow = max(1, borrow)
        right = borrow * span + prod
        return cross - borrow, str(right).zfill(width), {
            # A dissenting lens caught the previous version describing this case with
            # the CARRY text: it named a width trigger (false — the trigger is the
            # negative sign) and said the excess "moves into" the left part, while the
            # arithmetic SUBTRACTS. A learner following that prose added instead of
            # subtracting and got the wrong answer. All three fields now come from the
            # same branch so the prose cannot drift from the arithmetic again.
            "operation": "Complete the negative right part from the base",
            "reasoning": "The right part came out negative, so it is completed from the "
                         "base and the amount borrowed is SUBTRACTED from the left part",
            "formula": (
                f"\\text{{the product }} {prod} \\text{{ is negative, so complete it from "
                f"the base: }}\\;\\lceil {abs(prod)} \\div {span} \\rceil = {borrow} "
                f"\\;\\Rightarrow\\; \\text{{left }} {cross} - {borrow} = {cross - borrow},"
                f"\\; \\text{{right }} {borrow}\\times{span} {prod:+d} = {right}")}
    return cross, str(prod).zfill(width), None


def _near_base_traps(da: int, db: int, base: int) -> list[str]:
    """Hazards this instance can actually present — not a generic list."""
    width = len(str(base)) - 1
    span = 10 ** width
    prod = da * db
    traps = []
    if da < 0 and db < 0:
        traps.append("treating the product of two negative deviations as negative, when "
                     "two minuses give a positive right part")
    if (da < 0) != (db < 0):
        traps.append("sign error when one deviation is positive and the other negative")
    if prod >= span:
        traps.append("writing the whole product in the right part instead of carrying the "
                     "overflow into the left part")
    elif prod < 0:
        traps.append("forgetting to complete a negative right part from the base, and to "
                     "reduce the left part by the amount borrowed")
    elif len(str(abs(prod))) < width:
        traps.append(f"omitting the leading zero(s) needed to fill the {width}-digit right part")
    return traps or ["misreading the deviation's sign when writing it under the number"]


def _nikhilam_steps(a, b, base):
    da, db = a - base, b - base
    cross = a + db
    prod = da * db
    left_final, right_str, adjust = _assemble_near_base(cross, prod, base)
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
         "reasoning": f"The right part occupies {len(str(base)) - 1} digits — the width of "
                      f"the base's zeros"},
    ]
    if adjust:
        steps.append({"step_num": 5, **adjust})
    steps.append({
        "step_num": len(steps) + 1, "operation": "Assemble the answer",
        "formula": f"{left_final}\\,|\\,{right_str} = {a * b}",
        "reasoning": f"left \\times {base} + right, with the digits placed by width"})
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
    # From L3 up, require an instance that actually EXERCISES the carry/borrow. A
    # panel drew an L3 example (85×98, product 30) whose product happened to fit, so
    # the walkthrough never showed the rule — the same weakness found in urdhva.
    # Internal consistency ("the step appears when arithmetically needed") is not the
    # same property as pedagogical coverage ("the learner is shown the rule").
    span = 10 ** (len(str(base)) - 1)
    for _ in range(60):
        prod = (a - base) * (b - base)
        if level < 3 or prod >= span or prod < 0:
            break
        a, b = base + _deviation(rng, base, level), base + _deviation(rng, base, level)
    return {
        "sub_topic": "Nikhilam Navatashcaramam (All from 9, Last from 10)",
        "technique_name": "multiplication",
        "problem_statement": f"Multiply {a} × {b} using the Nikhilam base method",
        "compute": f"{a}*{b}",
        "final_answer": str(a * b),
        "params": {"a": a, "b": b, "base": base},
        "solution": _nikhilam_steps(a, b, base),
        # Traps must describe hazards THIS instance can actually present. A panel
        # caught a static list naming a mixed-sign error on an instance where both
        # deviations were negative — a mistake the learner could not commit here.
        "traps": _near_base_traps(a - base, b - base, base),
        "visual_scaffold": {"type": "place_value_chart"},
        "prerequisite_chain": ["Arithmetic", "Basic Operations (+, -, ×, ÷)", "Number Bases"],
    }


@pattern("square_near_base")
def gen_square_near_base(rng: random.Random, level: int) -> dict:
    base = BASES[SCALING[level]["digit_complexity"]]
    d = _deviation(rng, base, level)
    span = 10 ** (len(str(base)) - 1)
    for _ in range(60):  # L3+ must demonstrate the carry, not merely be consistent
        if level < 3 or d * d >= span:
            break
        d = _deviation(rng, base, level)
    a = base + d
    left_raw, right_raw = a + d, d * d
    left, right_str, adjust = _assemble_near_base(left_raw, right_raw, base)
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
             "formula": f"{a}{d:+d} = {left_raw}",
             "reasoning": "Whatever the deficiency, lessen it further"},
            {"step_num": 3, "operation": "Right part: square the deviation",
             "formula": f"({d:+d})^2 = {right_raw}",
             "reasoning": f"The right part occupies {len(str(base)) - 1} digits — the width "
                          f"of the base's zeros"},
            *([{"step_num": 4, **adjust}] if adjust else []),
            {"step_num": 5 if adjust else 4, "operation": "Assemble",
             "formula": f"{left}\\,|\\,{right_str} = {a * a}",
             "reasoning": f"left \\times {base} + right, with the digits placed by width"},
        ],
        "traps": ["squaring the deviation but dropping its sign context",
                  "right part written with too few digits (missing leading zeros)"],
        "visual_scaffold": {"type": "place_value_chart"},
        "prerequisite_chain": ["Arithmetic", "Basic Operations (+, -, ×, ÷)", "Number Bases"],
    }


def _neighbour_sum_steps(n: int) -> list[dict]:
    """The actual ×11 method: write the last digit, then add each digit to its right
    neighbour moving left, carrying, then the leading digit plus any carry."""
    ds = [int(c) for c in str(n)]
    digit_row = "\\,|\\,".join(["0", *(str(d) for d in ds), "0"])
    steps = [{"step_num": 1, "operation": "Write the digits with a zero at each end",
              "formula": digit_row,
              "reasoning": "Each output digit is a digit plus its right neighbour; the "
                           "outer zeros make the first and last cases follow the same rule"}]
    out, carry, step = [], 0, 2
    steps.append({"step_num": step, "operation": "Units digit: copy it down",
                  "formula": f"{ds[-1]}", "reasoning": "It has no right neighbour to add"})
    out.append(ds[-1] % 10)
    carry = 0
    step += 1
    for i in range(len(ds) - 1, 0, -1):
        s = ds[i - 1] + ds[i] + carry
        steps.append({
            "step_num": step,
            "operation": f"Add digit {ds[i-1]} to its right neighbour {ds[i]}"
                         + (f" plus carry {carry}" if carry else ""),
            "formula": f"{ds[i-1]} + {ds[i]}" + (f" + {carry}" if carry else "")
                       + f" = {s} \\Rightarrow \\text{{write }} {s % 10}"
                       + (f", \\text{{carry }} {s // 10}" if s // 10 else ""),
            "reasoning": "Neighbour sums run right to left, carrying like ordinary addition"})
        out.append(s % 10)
        carry = s // 10
        step += 1
    lead = ds[0] + carry
    steps.append({"step_num": step,
                  "operation": "Leading digit" + (f" plus carry {carry}" if carry else ""),
                  "formula": f"{ds[0]}" + (f" + {carry} = {lead}" if carry else f" = {lead}"),
                  "reasoning": "The leftmost digit closes the number"})
    out.append(lead)
    steps.append({"step_num": step + 1, "operation": "Read the digits right to left",
                  "formula": f"{n} \\times 11 = {n * 11}",
                  "reasoning": "The collected digits are the product"})
    return steps


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
        "solution": _neighbour_sum_steps(a),
        # An earlier version LABELLED these steps "split into digit neighbours" /
        # "add each digit to its right neighbour" while the formulas actually computed
        # a distributive shift-and-add (n×10 + n). The stage-7 panel caught the labels
        # teaching one method while the arithmetic executed another; the steps now
        # perform the digit-wise neighbour-sum they name.
        "traps": ["forgetting to carry when a neighbour sum exceeds 9",
                  "adding digits left to right instead of right to left"],
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

    def draw():
        return rng.randint(lo, hi), rng.randint(lo, hi)

    a_n, b_n = draw()
    for _ in range(40):
        # a == b would emit a squaring item labelled "multiplication"; a shared digit
        # makes the same token appear as both a crosswise and a vertical product,
        # which is confusing for the one template whose job is that distinction.
        # From L3 up, require the instance to actually EXERCISE a carry. The panel
        # failed this pattern on a carry-free example (41×90); measuring showed only
        # ~1/40 instances are carry-free, so that draw was atypical rather than the
        # rule — but a level that exists to teach carrying should never be able to
        # demonstrate itself without one.
        A, B = divmod(a_n, 10)
        C, D = divmod(b_n, 10)
        p1 = B * D
        carries = (p1 // 10) or ((A * D + B * C + p1 // 10) // 10)
        if (a_n != b_n and not (set(str(a_n)) & set(str(b_n)))
                and len(set(str(a_n))) == 2 and (level < 3 or carries)):
            break
        a_n, b_n = draw()
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
             "reasoning": "Crosswise means tens of the top number times units of the bottom, "
                          "plus units of the top times tens of the bottom; the tens column "
                          "collects both pairs plus any carry"},
            {"step_num": 4, "operation": "Vertical product of the leading digits"
                                        + (", plus the carry" if p2 // 10 else ""),
             "formula": f"{a} \\times {c}" + (f" + {p2 // 10}" if p2 // 10 else "")
                        + f" = {p3} \\Rightarrow \\text{{write }} {p3}"
                        + (" \\text{ (all of it — this is the leftmost column)}"
                           if p3 > 9 else ""),
             "reasoning": "This is the leftmost column, so its whole value is written down "
                          "rather than carried further"},
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
    # L1-L2 keep "the previous" a single digit; L3+ guarantee it is multi-digit so
    # the ladder actually introduces the general case (a verifier caught that every
    # level was the same four steps with only the leading digit changing).
    lo, hi = {1: (1, 9), 2: (1, 9), 3: (10, 29), 4: (10, 69), 5: (30, 99)}[level]
    a = rng.randint(lo, hi)
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
    # bases [10, 100, 1000, 10000]. The ladder is STRUCTURAL, not just bigger
    # numbers: L1-L2 are the plain case, L3-L4 introduce short numbers needing
    # leading-zero padding, L5 introduces trailing zeros (where 'last from 10'
    # applies to the last NON-ZERO digit). Two verifiers independently flagged an
    # earlier version whose levels were the same four steps on larger numbers.
    digits = {1: 2, 2: 3, 3: 3, 4: 4, 5: 4}[level]
    base = 10 ** digits
    case = "plain"
    if level in (3, 4) and rng.random() < 0.5:
        case = "padded"      # fewer digits than the base has zeros
    elif level == 5:
        case = "trailing_zero" if rng.random() < 0.6 else "padded"

    if case == "padded":
        n = rng.randint(10 ** (digits - 2), 10 ** (digits - 1) - 1)
        while n % 10 == 0:
            n = rng.randint(10 ** (digits - 2), 10 ** (digits - 1) - 1)
    elif case == "trailing_zero":
        n = rng.randint(10 ** (digits - 2), 10 ** (digits - 1) - 1) * 10
    else:
        n = rng.randint(10 ** (digits - 1), base - 1)
        while n % 10 == 0:
            n = rng.randint(10 ** (digits - 1), base - 1)

    padded = str(n).zfill(digits)
    ds = [int(c) for c in padded]
    # Trailing zeros stay zero; the last NON-ZERO digit goes from 10; the rest from 9.
    last_nz = max(i for i, d in enumerate(ds) if d != 0)
    comp = [(0 if i > last_nz else (10 - d if i == last_nz else 9 - d))
            for i, d in enumerate(ds)]
    return {
        "sub_topic": "Nikhilam Navatashcaramam (All from 9, Last from 10)",
        "technique_name": "subtraction",
        "problem_statement": f"Subtract {n} from {base} using 'all from 9 and the last from 10'",
        "compute": f"{base}-{n}",
        "final_answer": str(base - n),
        "params": {"n": n, "base": base},
        "solution": [
            {"step_num": 1, "operation": f"Pad the number to the base's {digits} digits",
             "formula": f"{base} - {n} \\Rightarrow {base} - {padded}",
             "reasoning": f"The base has {digits} zeros, so the number is written with "
                          f"{digits} digits, adding leading zeros if it is shorter — the "
                          f"complement is taken column by column"},
            {"step_num": 2, "operation": "Every digit before the last non-zero one: from 9",
             "formula": (" ,\\quad ".join(f"9 - {d} = {9 - d}" for d in ds[:last_nz])
                         or "\\text{(none — the first digit is already the last non-zero one)}"),
             "reasoning": "'All from 9' applies to each digit up to but excluding the last "
                          "non-zero digit"},
            {"step_num": 3, "operation": "The last non-zero digit: from 10"
                                        + ("; trailing zeros stay 0" if last_nz < digits - 1 else ""),
             "formula": (f"10 - {ds[last_nz]} = {comp[last_nz]}"
                         + (f" ,\\quad \\text{{then }} {digits - 1 - last_nz}"
                            f" \\text{{ trailing zero(s) stay }} 0" if last_nz < digits - 1 else "")),
             "reasoning": "'The last from 10' applies to the last NON-ZERO digit; any zeros "
                          "after it are already complete and stay 0 (taking 10 from a 0 "
                          "would produce a two-digit column)"},
            {"step_num": 4, "operation": "Write the column results in order",
             "formula": " \\,|\\, ".join(str(x) for x in comp) + f" = {''.join(str(x) for x in comp)}",
             "reasoning": "Each column already holds a single digit, so they are read off "
                          "left to right with no borrowing anywhere"},
        ],
        "traps": ["taking the last digit from 9 as well, giving an answer one too small",
                  "forgetting to pad a short number with leading zeros before complementing",
                  "applying 'from 10' to a trailing zero instead of the last non-zero digit"],
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


def skeleton_fingerprint(pattern_id: str, level: int) -> str:
    """Hash of a pattern's WALKTHROUGH SKELETON at one level.

    A stage-7 verdict judges the skeleton (the sequence of operations and their
    reasoning), not the particular numbers. Digits are stripped so instance
    variation does not change the hash, while any edit to what a step SAYS does.
    This is what makes a verdict falsifiable: change the teaching and the verdict
    that blessed it stops matching.
    """
    # Sample MANY instances, not one. Near-base patterns emit two different skeletons
    # depending on whether the deviation product overflows, so a single-instance
    # fingerprint silently represents only whichever variant that seed produced —
    # and a single-instance spot-check judges only that variant too.
    recs = generate(pattern_id, level, 24, f"fingerprint:{pattern_id}:{level}")
    if not recs:
        return "empty"
    # Include the FORMULA, not just operation/reasoning. An earlier version hashed
    # only the prose, so rewriting a step's arithmetic — exactly the fix panels ask
    # for ("show the computation instead of asserting it") — left the fingerprint
    # unchanged and a stale verdict would have carried over silently.
    variants = sorted({
        "|".join(re.sub(r"\d+", "#",
                        f"{s.get('operation','')}~{s.get('reasoning','')}~{s.get('formula','')}")
                 for s in r["solution"])
        for r in recs})
    # Version-stamped: changing the hashing rule invalidates every stored fingerprint,
    # and a version mismatch means "incomparable", NOT "the content changed". Without
    # the stamp an algorithm change looks identical to a content change, which would
    # either strand valid verdicts or silently bless stale ones.
    return f"{FINGERPRINT_VERSION}:{hashlib.sha256('||'.join(variants).encode()).hexdigest()[:16]}"


def skeleton_variants(pattern_id: str, level: int, n: int = 24) -> int:
    """How many distinct walkthrough skeletons this (pattern, level) can emit.

    >1 means a spot-check of one instance cannot characterise the level.
    """
    recs = generate(pattern_id, level, n, f"variants:{pattern_id}:{level}")
    return len({tuple(s.get("operation", "") for s in r["solution"]) for r in recs})
