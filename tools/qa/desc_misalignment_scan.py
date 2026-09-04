#!/usr/bin/env python3
"""Detect within-template description/operation misalignment in a SolveAlong bank.

The defect (found by stage-7 panels, 2026-09-04): a step's `description` narrates a
DIFFERENT example than the one it sits in — carried over from a sibling example or
offset by one — so it contradicts the `operation` it labels.

Three independent signatures, reported separately because they have different
false-positive profiles:

  sibling_carryover  A description's distinctive terms are absent from its own
                     example but present in a sibling example of the same template.
                     Strong: carry-over is the only ordinary way that happens.
  desc_duplicated    The same description text labels steps whose operations differ
                     materially, within one template. Strong, but template authors
                     do legitimately reuse generic descriptions ("Simplify"), so
                     short/common descriptions are excluded.
  no_overlap         A description shares no content word with its own operation or
                     result. Weak on its own (a description may legitimately explain
                     rather than restate) — reported for triage, never as a verdict.

Every finding is a CANDIDATE. The exceptions are real: a description may legitimately
reference a prior example ("as in the previous problem"), and generic descriptions
legitimately repeat. Nothing here should auto-quarantine content.

Usage: python3 tools/qa/desc_misalignment_scan.py [bank.jsonl] [-o report.json]
"""
import json
import re
import sys
from collections import defaultdict
from pathlib import Path

# Words too common in mathematical instruction to be distinctive.
STOP = set("""
about above across after again against all also and any are because been before
being below between both but came can come could did does down each end even
every few first for from further get give given gives had has have here how
into its itself just like made make many more most much must never next not
now number numbers off once only onto other our out over own part parts place
places same see should since some step steps such take than that the their them
then there these they this those through thus too under until use used uses
using very was way well were what when where which while who why will with
within without would you your
answer apply calculate calculation compute continue convert equation equations
expression final find first form formula get gives left multiply next number
obtain operation problem process rectangle result results right rule second
set side solution solve solving step steps substitute subtract sum term terms
third total unknown value values variable write
""".split())

WORD = re.compile(r"[a-z]{4,}")


def content_words(text):
    if not text:
        return set()
    return {w for w in WORD.findall(str(text).lower()) if w not in STOP}


def example_context(ex):
    """Every content word appearing in an example's own problem, operations and results."""
    ctx = content_words(ex.get("problem_statement"))
    for s in ex.get("solution") or []:
        ctx |= content_words(s.get("operation")) | content_words(s.get("result"))
    ctx |= content_words(ex.get("answer"))
    return ctx


def scan_template(t):
    findings = []
    examples = t.get("examples") or []
    if not examples:
        return findings

    own_ctx = [example_context(ex) for ex in examples]
    union_ctx = set().union(*own_ctx) if own_ctx else set()

    # --- signature 1: sibling carry-over -------------------------------------
    for ei, ex in enumerate(examples):
        sib_ctx = set().union(*(c for i, c in enumerate(own_ctx) if i != ei)) if len(examples) > 1 else set()
        for s in ex.get("solution") or []:
            desc = content_words(s.get("description"))
            if not desc:
                continue
            foreign = desc - own_ctx[ei]
            if not foreign:
                continue
            from_sibling = foreign & sib_ctx
            # Distinctive terms that are absent here but present next door, and the
            # description is not merely using vocabulary absent from the whole template.
            if from_sibling and len(from_sibling) >= 2:
                findings.append({
                    "signature": "sibling_carryover",
                    "template_id": t.get("id"),
                    "example_index": ei,
                    "step_num": s.get("step_num"),
                    "operation": (s.get("operation") or "")[:120],
                    "description": (s.get("description") or "")[:200],
                    "terms_from_sibling": sorted(from_sibling)[:8],
                    "exception": "legitimate if the description deliberately references a "
                                 "prior example (e.g. 'as in the previous problem')",
                    "confidence": "heuristic",
                })

    # --- signature 2: duplicated description over divergent operations -------
    by_desc = defaultdict(list)
    for ei, ex in enumerate(examples):
        for s in ex.get("solution") or []:
            d = (s.get("description") or "").strip()
            if len(d) >= 40:  # skip generic one-liners
                by_desc[d].append((ei, s))
    for d, uses in by_desc.items():
        if len(uses) < 2:
            continue
        ops = [content_words(s.get("operation")) for _, s in uses]
        # material divergence: some pair of operations shares no content word
        divergent = any(
            ops[i] and ops[j] and not (ops[i] & ops[j])
            for i in range(len(ops)) for j in range(i + 1, len(ops))
        )
        if divergent:
            findings.append({
                "signature": "desc_duplicated",
                "template_id": t.get("id"),
                "example_index": [ei for ei, _ in uses],
                "step_num": [s.get("step_num") for _, s in uses],
                "operation": [(s.get("operation") or "")[:80] for _, s in uses],
                "description": d[:200],
                "exception": "legitimate when one description genuinely covers steps that "
                             "differ only in notation",
                "confidence": "heuristic",
            })

    # --- signature 3: description shares nothing with its own step -----------
    for ei, ex in enumerate(examples):
        for s in ex.get("solution") or []:
            desc = content_words(s.get("description"))
            step = content_words(s.get("operation")) | content_words(s.get("result"))
            if desc and step and not (desc & step) and not (desc & own_ctx[ei]):
                findings.append({
                    "signature": "no_overlap",
                    "template_id": t.get("id"),
                    "example_index": ei,
                    "step_num": s.get("step_num"),
                    "operation": (s.get("operation") or "")[:120],
                    "description": (s.get("description") or "")[:200],
                    "exception": "legitimate when a description explains WHY rather than "
                                 "restating the operation — triage only, never a verdict",
                    "confidence": "weak",
                })
    return findings


def main():
    argv = [a for a in sys.argv[1:] if not a.startswith("-")]
    bank = Path(argv[0]) if argv else Path("data/factory/solvealong_bank_v1_4.jsonl")
    out = Path(sys.argv[sys.argv.index("-o") + 1]) if "-o" in sys.argv \
        else Path("data/factory/desc_misalignment_scan_v2.json")

    templates = [json.loads(l) for l in bank.read_text().splitlines() if l.strip()]
    findings = []
    for t in templates:
        findings.extend(scan_template(t))

    by_sig = defaultdict(set)
    for f in findings:
        by_sig[f["signature"]].add(f["template_id"])

    report = {
        "bank": str(bank),
        "templates_scanned": len(templates),
        "findings": len(findings),
        "templates_by_signature": {k: len(v) for k, v in by_sig.items()},
        "all_flagged_templates": len(set().union(*by_sig.values())) if by_sig else 0,
        "note": "candidates, not verdicts — every signature has stated exceptions and "
                "no finding should auto-quarantine content",
        "detail": findings,
    }
    out.write_text(json.dumps(report, indent=1))
    print(json.dumps({k: v for k, v in report.items() if k != "detail"}, indent=1))


if __name__ == "__main__":
    main()
