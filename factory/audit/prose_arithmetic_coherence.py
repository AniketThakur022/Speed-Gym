#!/usr/bin/env python3
"""Does a step's PROSE agree with the direction of its own arithmetic?

This exists because the same defect was found twice, one field deeper each time:

  round 1  the walkthrough asserted a digit-width rule its shown value violated
           -> fixed the `result` field
  round 2  `result` was right, but `operation`/`reasoning` still carried the text
           written for the opposite sign ("the excess moves into the left part"
           beside arithmetic that subtracts) -> a learner following the prose adds
  round 3  same shape again at an earlier step: "whatever the deficiency, lessen
           it further" on a SURPLUS instance whose line computes 1208 + 208

Each time the metric in force was satisfied by one field alone. So this checks the
relationship BETWEEN fields: extract the direction the arithmetic actually moves,
and compare it with the direction the prose claims. Any generator whose prose is a
frozen string will fail here as soon as it meets the opposite sign.

  python3 -m factory.audit.prose_arithmetic_coherence [--n 40]
"""

import argparse
import re

from factory.generation import t2

UP = re.compile(r"\b(increase|increased|increasing|add|adds|added|adding|carry|carried|"
                r"carries|surplus|more than|raise|raised)\b", re.I)
DOWN = re.compile(r"\b(lessen|lessened|reduce|reduced|reducing|subtract|subtracted|"
                  r"subtracting|borrow|borrowed|deficiency|deduct|less than|lower)\b", re.I)
# "a op b = c" over plain integers, after stripping LaTeX decoration.
ARITH = re.compile(r"(-?\d+)\s*([+-])\s*(-?\d+)\s*=\s*(-?\d+)")


def strip_tex(s) -> str:
    if not isinstance(s, str):   # bank steps may omit `result` entirely
        return ""
    s = re.sub(r"\\text\{[^}]*\}", " ", s)
    s = re.sub(r"\\[a-zA-Z]+", " ", s)
    return s.replace("{", " ").replace("}", " ").replace("\\", " ")


def step_direction(formula: str):
    """+1 if the arithmetic increases the first operand, -1 if it decreases, else None.

    Only trusted on a SINGLE simple equation. On free-form bank formulas the regex
    happily matches across terms — "4x + 1 - 1 = 9 - 1" yields a bogus "1 - 1 = 9" —
    so anything with several '=' signs or trailing structure is declined rather than
    guessed. Measured on the legacy bank, guessing produced 31 findings of which the
    ones I checked were all false; a repair-QA gate that cries wolf makes people
    "fix" correct content.
    """
    text = strip_tex(formula)
    if text.count("=") != 1:
        return None
    m = ARITH.fullmatch(text.strip().rstrip(".;,"))
    if not m:
        return None
    first, _op, _second, result = (int(m.group(1)), m.group(2), int(m.group(3)), int(m.group(4)))
    if result == first:
        return None
    return 1 if result > first else -1


def bank_records(path):
    """Yield walkthroughs from a delivery-shaped JSONL (bank, converted, repaired).

    Offered as a gate for re-narration passes: a rewritten description that says
    "add" over an operation that subtracts is precisely the "reads fluently but
    misstates its operation" failure, and it is one of the few slices of that class
    a deterministic check can actually catch — because direction is arithmetic, not
    meaning.
    """
    import json
    from pathlib import Path
    for line in Path(path).read_text().splitlines():
        if not line.strip():
            continue
        rec = json.loads(line)
        d = rec.get("delivery", rec)
        for ex in d.get("examples", []):
            yield {"problem_statement": ex.get("problem_statement", d.get("id", "")),
                   "solution": [{"step_num": s.get("step_num"),
                                 "operation": s.get("operation"),
                                 # bank shape calls it description; generated calls it reasoning
                                 "reasoning": s.get("description") or s.get("reasoning"),
                                 "formula": s.get("result") or s.get("formula")}
                                for s in ex.get("solution", [])]}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--n", type=int, default=40, help="instances per (pattern, level)")
    ap.add_argument("--bank", default=None,
                    help="check a delivery-shaped JSONL instead of the generators")
    args = ap.parse_args()

    checked = 0
    mismatches = []
    if args.bank:
        sources = [("bank", 0, list(bank_records(args.bank)))]
    else:
        sources = [(pid, lvl, t2.generate(pid, lvl, args.n, f"coherence:{pid}:{lvl}"))
                   for pid in t2.PATTERNS for lvl in (1, 2, 3, 4, 5)]
    for pid, level, recs in sources:
            for rec in recs:
                for s in rec["solution"]:
                    direction = step_direction(s.get("formula", ""))
                    if direction is None:
                        continue
                    prose = f"{s.get('operation','')} {s.get('reasoning','')}"
                    up, down = bool(UP.search(prose)), bool(DOWN.search(prose))
                    if up == down:          # says both or neither — no claim to contradict
                        continue
                    checked += 1
                    claimed = 1 if up else -1
                    if claimed != direction:
                        mismatches.append({
                            "pattern": pid, "level": level, "step": s.get("step_num"),
                            "problem": rec["problem_statement"][:60],
                            "arithmetic_moves": "up" if direction > 0 else "down",
                            "prose_claims": "up" if claimed > 0 else "down",
                            "operation": s.get("operation"),
                            "reasoning": (s.get("reasoning") or "")[:100],
                            "formula": (s.get("formula") or "")[:100]})

    print(f"steps with both a directional claim and directional arithmetic: {checked}")
    print(f"PROSE/ARITHMETIC DIRECTION MISMATCHES: {len(mismatches)}")
    seen = set()
    for m in mismatches:
        key = (m["pattern"], m["level"], m["step"])
        if key in seen:
            continue
        seen.add(key)
        print(f"  {m['pattern']}@L{m['level']} step {m['step']}: arithmetic goes "
              f"{m['arithmetic_moves']}, prose claims {m['prose_claims']}")
        print(f"     op: {m['operation']}")
        print(f"     {m['formula']}")
    return 1 if mismatches else 0


if __name__ == "__main__":
    raise SystemExit(main())
