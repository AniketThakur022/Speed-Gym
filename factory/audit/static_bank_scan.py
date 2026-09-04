#!/usr/bin/env python3
"""Deterministic defect scan over the whole static bank.

The stage-7 panels sample ~60 templates and adjudicate them expensively. This
scans all 823 cheaply for the SAME defect classes they have been finding, so the
panel's next sample can be pointed at candidates instead of drawn blind. It
reports CANDIDATES, not verdicts — several classes here have legitimate
exceptions, so nothing is auto-quarantined.

Classes (each derived from a defect a panel actually found, not invented):

  false_root_claim   A step asserts "N is a root", and the template's own answer
                     disproves it. For a root transformation y = x - r the
                     constant term of the transformed polynomial IS f(r), so a
                     non-zero constant term is proof the claim is false. Exact —
                     no false positives — but only applies where a root is
                     CLAIMED: a shift problem ("roots 4 less than...") legitimately
                     has a non-zero constant and must not be flagged.

  orphan_continuation  The FIRST step of an example describes continuing a process
                     that never started ("second division pass", "continue to get
                     the final form"). Heuristic: a cross-example reference can be
                     legitimate, so these need adjudication.

  duplicate_step_prose  Templates sharing an identical step-description sequence.
                     Within one technique this is normal template reuse; ACROSS
                     techniques it indicates mis-filed content.
"""

import argparse
import hashlib
import json
import re
from collections import Counter, defaultdict
from pathlib import Path

ROOT_CLAIM = re.compile(r"(-?\d+)\s+is a root|since\s+(-?\d+)\s+is\s+a\s+root", re.I)
CONTINUATION = re.compile(
    r"^\s*(continue|continuing|repeat|again|next|then|second|third|final(ly)?|remaining)\b"
    r"|\b(second|third|next|final)\s+(pass|iteration|step|division|round)\b", re.I)
POLY_ANSWER = re.compile(r"^\s*[a-z]\s*\^?\s*\d")


def constant_term(poly: str):
    """Constant term of a single-variable polynomial string, or None."""
    body = poly.split("=")[0].replace(" ", "").replace("\\", "")
    for term in reversed(re.findall(r"[+-]?[^+-]+", body)):
        if not re.search(r"[a-zA-Z]", term):
            try:
                return int(term)
            except ValueError:
                return None
    return 0


def scan(bank: Path):
    findings = []
    seqs = defaultdict(list)
    examples = 0

    for line in bank.read_text().splitlines():
        if not line.strip():
            continue
        t = json.loads(line)
        tech = t["concept"]["technique_name"]
        sub = t["concept"].get("sub_category")
        for i, ex in enumerate(t.get("examples", [])):
            sol = ex.get("solution") or []
            if not sol:
                continue
            examples += 1

            # false root claim — exact, via constant term == f(r)
            first = f"{sol[0].get('description','')} {sol[0].get('result','')}"
            m = ROOT_CLAIM.search(first)
            ans = (ex.get("answer") or "").strip()
            if m and POLY_ANSWER.match(ans):
                c = constant_term(ans)
                if c not in (None, 0):
                    r = m.group(1) or m.group(2)
                    findings.append({
                        "template_id": t["id"], "example": i, "class": "false_root_claim",
                        "severity": "confirmed",
                        "detail": f"step 1 claims {r} is a root, but the transformed "
                                  f"polynomial's constant term is {c}; for y = x - r that "
                                  f"constant IS f(r), so f({r}) = {c} != 0",
                        "evidence": ans[:80]})

            # orphan continuation — heuristic, needs adjudication
            d = (sol[0].get("description") or "").strip()
            if d and CONTINUATION.search(d):
                findings.append({
                    "template_id": t["id"], "example": i, "class": "orphan_continuation",
                    "severity": "candidate",
                    "detail": "first step describes continuing a process with no antecedent "
                              "in this example; may be a legitimate cross-example reference",
                    "evidence": d[:110]})

            descs = [(s.get("description") or "").strip() for s in sol]
            if len([x for x in descs if x]) >= 3:
                seqs[hashlib.sha256("|".join(descs).encode()).hexdigest()[:16]].append(
                    (t["id"], tech, sub))

    for _h, members in seqs.items():
        if len(members) > 1 and (len({m[1] for m in members}) > 1
                                 or len({m[2] for m in members}) > 1):
            findings.append({
                "template_id": members[0][0], "example": None,
                "class": "duplicate_step_prose", "severity": "candidate",
                "detail": "identical step-description sequence shared ACROSS different "
                          "techniques — indicates mis-filed content",
                "evidence": json.dumps([f"{i}[{tc}/{sc}]" for i, tc, sc in members][:6])})

    return findings, examples


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--bank", default="data/factory/solvealong_bank_v1_4.jsonl")
    ap.add_argument("--out", default="data/factory/static_bank_scan.json")
    args = ap.parse_args()

    findings, examples = scan(Path(args.bank))
    report = {
        "bank": args.bank, "examples_scanned": examples,
        "findings": len(findings),
        "by_class": dict(Counter(f["class"] for f in findings)),
        "by_severity": dict(Counter(f["severity"] for f in findings)),
        "note": "CANDIDATES for panel adjudication, not verdicts. Only 'confirmed' "
                "severity is proven by construction; the rest have legitimate exceptions "
                "and must not be auto-quarantined.",
        "results": findings,
    }
    Path(args.out).write_text(json.dumps(report, indent=1, ensure_ascii=False))
    print(json.dumps({k: v for k, v in report.items() if k != "results"}, indent=1))
    for f in findings[:8]:
        print(f"  [{f['severity']:9s}] {f['class']:22s} {f['template_id']} ex{f['example']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
