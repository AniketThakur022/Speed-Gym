#!/usr/bin/env python3
"""Bring the converted tier onto the frozen contract, and make its refusals in-band.

Two corrections to the handed-over `generationMethod: "converted"` tier:

1. `version` was the string "converted_v1"; the frozen SolveAlongTemplateSchema
   requires a positive integer, so all 348 would be rejected at the frontend. The
   pipeline label moves into `provenance`, which the tier already carries.

2. 152 questions were refused with recorded reasons, but the reasons lived only in
   a sidecar — a consumer reading the shards saw a silent absence. That is exactly
   the unlogged-non-write failure this project adopted a rule against, so the
   refusals are emitted as structured decline records alongside the templates.

Refusing to convert a question whose source is truncated, chart-less or
self-contradictory is correct behaviour. It only becomes a defect when it is
invisible.
"""

import json
import re
from collections import Counter
from pathlib import Path

CONV = Path("data/factory/converted")
# Categories inferred from the recorded prose, so declines are filterable rather
# than only readable.
CATEGORIES = [
    ("missing_chart_or_figure", r"chart itself is not|no series values|figure is absent|"
                                r"not in the packet|chart is missing|diagram"),
    ("truncated_or_garbled_source", r"truncat|garbled|OCR|extraction hole|cut off|incomplete formula"),
    ("bare_cross_reference", r"see (Appendix|Chapter|Section|Example|Table)|cross-reference|refers to"),
    ("source_contradiction_or_erratum", r"erratum|disagree|contradict|does not match the printed"),
    ("solution_restates_answer", r"restates the answer|unsourced line|no derivation|single line"),
]


def categorise(reason: str) -> str:
    for name, pat in CATEGORIES:
        if re.search(pat, reason, re.I):
            return name
    return "other_recorded_reason"


def main() -> int:
    # 1. contract fix
    fixed = 0
    for shard in sorted(CONV.glob("packet_*.jsonl")):
        out = []
        for line in shard.read_text().splitlines():
            if not line.strip():
                continue
            rec = json.loads(line)
            d = rec.get("delivery", rec)
            v = d.get("version")
            if not isinstance(v, int):
                prov = d.get("provenance")
                if isinstance(prov, dict):
                    prov.setdefault("pipeline_version", v)
                elif prov is None:
                    d["provenance"] = {"pipeline_version": v}
                d["version"] = 1
                fixed += 1
            out.append(json.dumps(rec, ensure_ascii=False))
        shard.write_text("\n".join(out) + "\n")

    # 2. declines in-band
    skips = json.loads((CONV / "_skips.json").read_text())["skip_reasons"]
    cats = Counter()
    with (CONV / "declines.jsonl").open("w") as fh:
        for reason in skips:
            # Two prose shapes in the recorded reasons: "<id> (Book, p12): ..." and
            # "<id> — ...". Matching only the first left 31 declines unjoinable to
            # their source question, which is half the point of recording them.
            m = re.match(r"^\s*(\S+?)\s*(?:\(|—|--|:\s)", reason)
            qid = m.group(1) if m else None
            cat = categorise(reason)
            cats[cat] += 1
            fh.write(json.dumps({
                "record_type": "decline",
                "question_id": qid,
                "converted": False,
                "reason_category": cat,
                "reason": reason.strip(),
                "note": "Refused rather than fabricated. A decline is a result, not an "
                        "absence — see the unlogged-non-write rule.",
            }, ensure_ascii=False) + "\n")

    print(f"version corrected on {fixed} templates")
    print(f"declines emitted: {len(skips)} -> {CONV/'declines.jsonl'}")
    print("decline categories:", dict(cats.most_common()))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
