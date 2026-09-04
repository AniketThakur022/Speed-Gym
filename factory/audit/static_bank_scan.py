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

# Every class ships the invariant that fires AND the exception that would clear it.
# A judge shown only a flag drifts toward confirming it; a judge shown the exception
# can clear content confidently. The sa_325 near-miss is why this is mandatory: the
# same invariant that proves a defect where a root is CLAIMED becomes a false accuser
# where a shift is merely described.
CLASS_DOC = {
    "false_root_claim": {
        "invariant": "For a root transformation y = x - r, the constant term of the "
                     "transformed polynomial EQUALS f(r). A non-zero constant term is "
                     "therefore proof that r is not a root.",
        "exception": "Applies ONLY where a step explicitly CLAIMS r is a root. A shift "
                     "problem ('find the equation whose roots are k less than these') "
                     "legitimately has a non-zero constant term and is CORRECT — "
                     "Schaums_College_Math_sa_325 is exactly that case and is not a "
                     "defect. If no root is claimed, this flag does not apply.",
        "confidence": "exact — no false positives once a root claim is present",
    },
    "orphan_continuation": {
        "invariant": "The FIRST step of an example describes continuing a process "
                     "('second pass', 'continue', 'repeat until') that has no antecedent "
                     "within that example.",
        "exception": "Legitimate when the antecedent exists in an EARLIER EXAMPLE of the "
                     "same template and the examples are a deliberate sequence — e.g. "
                     "Bird_Engineering_Math_sa_256 ex1 'Again recall the volume formula, "
                     "as this is a new problem with different values'. Check the previous "
                     "example before failing.",
        "confidence": "heuristic — legitimate exceptions exist, adjudication required",
    },
    "duplicate_step_prose": {
        "invariant": "An identical step-description sequence is shared across templates "
                     "carrying DIFFERENT technique/sub_category labels.",
        "exception": "Sharing within a single technique is normal template reuse and is "
                     "not flagged. Note: the population scan found ZERO cross-technique "
                     "cases, so a hit here would be genuinely unusual.",
        "confidence": "heuristic",
    },
}

ROOT_CLAIM = re.compile(r"(-?\d+)\s+is a root|since\s+(-?\d+)\s+is\s+a\s+root", re.I)
# Only BACKWARD references count. "carry 1 to the next step" is forward-looking and
# perfectly normal in a first step — including "next" here made the scan flag
# Vedic_Secrets_sa_26, whose opening step is fine. The defect is a step that resumes
# work with no antecedent, not one that anticipates work to come.
CONTINUATION = re.compile(
    r"^\s*(continue|continuing|repeat|again|then|second|third|final(ly)?|remaining)\b"
    r"|\b(second|third|final)\s+(pass|iteration|division|round)\b", re.I)
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
    ap.add_argument("--packets", default="data/factory/static_bank_candidates.jsonl",
                    help="self-contained adjudication packets: each candidate with the "
                         "invariant that fired, the exception that would clear it, and "
                         "the content needed to judge without a lookup")
    args = ap.parse_args()

    findings, examples = scan(Path(args.bank))

    # Attach the class documentation and the surrounding content to each finding.
    bank = {}
    for line in Path(args.bank).read_text().splitlines():
        if line.strip():
            t = json.loads(line)
            bank[t["id"]] = t
    packets = []
    for f in findings:
        doc = CLASS_DOC.get(f["class"], {})
        t = bank.get(f["template_id"], {})
        ex = None
        if f["example"] is not None and t.get("examples"):
            e = t["examples"][f["example"]]
            ex = {"problem_statement": e.get("problem_statement"),
                  "answer": e.get("answer"),
                  "steps": [{"step_num": s.get("step_num"),
                             "operation": s.get("operation"),
                             "description": s.get("description"),
                             "result": s.get("result")} for s in (e.get("solution") or [])]}
        prior = None
        if f["class"] == "orphan_continuation" and f["example"]:
            # The exception hinges on whether a previous example set up the process,
            # so ship it rather than making the judge go looking.
            pe = t["examples"][f["example"] - 1]
            prior = {"problem_statement": pe.get("problem_statement"),
                     "last_steps": [s.get("description") for s in (pe.get("solution") or [])][-3:]}
        packets.append({**f, **doc, "concept": t.get("concept"),
                        "example_content": ex, "previous_example": prior,
                        "instruction": "The flag is a reason to LOOK, never a reason to fail. "
                                       "Check the exception first; clear the item if it "
                                       "applies."})
    with Path(args.packets).open("w") as fh:
        for p in packets:
            fh.write(json.dumps(p, ensure_ascii=False) + "\n")
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
