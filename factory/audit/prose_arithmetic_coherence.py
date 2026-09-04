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


def strip_tex(s: str) -> str:
    s = re.sub(r"\\text\{[^}]*\}", " ", s)
    s = re.sub(r"\\[a-zA-Z]+", " ", s)
    return s.replace("{", " ").replace("}", " ").replace("\\", " ")


def step_direction(formula: str):
    """+1 if the arithmetic increases the first operand, -1 if it decreases, else None."""
    m = ARITH.search(strip_tex(formula))
    if not m:
        return None
    first, _op, _second, result = (int(m.group(1)), m.group(2), int(m.group(3)), int(m.group(4)))
    if result == first:
        return None
    return 1 if result > first else -1


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--n", type=int, default=40, help="instances per (pattern, level)")
    args = ap.parse_args()

    checked = 0
    mismatches = []
    for pid in t2.PATTERNS:
        for level in (1, 2, 3, 4, 5):
            for rec in t2.generate(pid, level, args.n, f"coherence:{pid}:{level}"):
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
