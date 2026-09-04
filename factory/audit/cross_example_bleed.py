#!/usr/bin/env python3
"""Detect cross-example content bleed in multi-example templates.

Confirmed by hand on Tirthaji_Vedic_Math_sa_172: example 1's step-3 `result` is
example 0's ANSWER, and example 2's step results are verbatim copies of example
0's step-1 expression, while the `operation` fields of those same steps are
correct and consistent with their own answers.

Why this one is worth building when the semantic detectors were not: the defect
is literal copying, so it is decided by string equality rather than meaning. Every
previous rule-based attempt here failed because it proxied a semantic property
(does this prose describe this method?). This proxies nothing — a step in example
1 whose result is character-identical to distinct content in example 0, on a
different problem, is copied by construction.

Reports per-template evidence, not a verdict: a short or trivially shared string
can repeat legitimately, so only substantial content counts and pairs are shown.
"""

import argparse
import json
import re
from collections import Counter
from pathlib import Path

MIN_LEN = 12          # ignore trivial fragments like "= 0" or a bare number
STRIP = re.compile(r"\s+")


def norm(s) -> str:
    return STRIP.sub(" ", s or "").strip()


def scan(path: Path):
    findings = []
    multi = 0
    for line in path.read_text().splitlines():
        if not line.strip():
            continue
        t = json.loads(line)
        exs = t.get("examples") or []
        if len(exs) < 2:
            continue
        multi += 1
        # content owned by each example: its answer and its step results
        owned = []
        for ex in exs:
            vals = {norm(ex.get("answer"))}
            for s in ex.get("solution") or []:
                vals.add(norm(s.get("result")))
            owned.append({v for v in vals if len(v) >= MIN_LEN})

        for i, ex in enumerate(exs):
            others = set().union(*[owned[j] for j in range(len(exs)) if j != i]) if len(exs) > 1 else set()
            mine = owned[i]
            for s in ex.get("solution") or []:
                r = norm(s.get("result"))
                if len(r) < MIN_LEN:
                    continue
                # bleed = this result belongs to a sibling example and is not
                # otherwise part of this example's own answer
                if r in others and r != norm(ex.get("answer")):
                    src = next(j for j in range(len(exs))
                               if j != i and r in owned[j])
                    findings.append({
                        "template_id": t["id"], "example": i, "step_num": s.get("step_num"),
                        "bled_from_example": src,
                        "is_sibling_answer": r == norm(exs[src].get("answer")),
                        "operation": (s.get("operation") or "")[:70],
                        "result": r[:70],
                    })
    return findings, multi


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--bank", default="data/factory/solvealong_bank_v1_4.jsonl")
    ap.add_argument("--out", default="data/factory/cross_example_bleed.json")
    args = ap.parse_args()

    findings, multi = scan(Path(args.bank))
    tpl = {f["template_id"] for f in findings}
    report = {
        "bank": args.bank,
        "multi_example_templates": multi,
        "templates_with_bleed": len(tpl),
        "bleeding_steps": len(findings),
        "steps_carrying_a_sibling_ANSWER": sum(1 for f in findings if f["is_sibling_answer"]),
        "share_of_multi_example_templates": round(len(tpl) / multi, 4) if multi else 0,
        "method": "exact string equality of a step's `result` against content owned by a "
                  "DIFFERENT example in the same template; substantial strings only",
        "interpretation": (
            "Counts steps whose result duplicates substantial content from a sibling "
            "example. Since each example is a different problem, such sharing is "
            "suspicious by construction — verified by hand on Bird_Engineering_Math_"
            "sa_103, whose example 1 step 1 displays example 0's equation. But the check "
            "flags BOTH copies of a shared string and cannot say which example is the "
            "victim, so the step count over-states and per-template adjudication is "
            "still required. The unambiguous sub-case is a step result equal to a "
            "sibling's ANSWER (`steps_carrying_a_sibling_ANSWER`), which has no innocent "
            "reading."),
        "findings": findings,
    }
    Path(args.out).write_text(json.dumps(report, indent=1, ensure_ascii=False))
    print(json.dumps({k: v for k, v in report.items() if k != "findings"}, indent=1))
    for f in findings[:6]:
        print(f"  {f['template_id']} ex{f['example']} step{f['step_num']} "
              f"<- ex{f['bled_from_example']}"
              f"{' (its ANSWER)' if f['is_sibling_answer'] else ''}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
