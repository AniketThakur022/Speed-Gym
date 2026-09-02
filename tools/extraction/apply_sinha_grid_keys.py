#!/usr/bin/env python3
"""Apply grid-recovered answer keys to Sinha questions in MASTER_corpus.jsonl.

2026-09-02 recovery pass (Speed Gym data extraction chat). Sources:
- Printed "Answer Keys" grids parsed from the page OCR of the recovered Sinha
  PDF (tools/extraction rendered pages 306-396; tesseract pages 1-305 from the
  July-12 package). Grid segments were assigned to question sets by print
  structure (first Answer-Keys-headed grid at/after the set's question page)
  and validated against the 1,238 already-keyed Sinha questions that share
  those grids: 1,141 agreements / 85 clashes pool-wide; only segments with
  clash-rate <= 10% (AUTO_HIGH, >=3 agreements) or <= 20% (AUTO_MED, >=1)
  contribute keys. Three grids vision-verified against page images (p92,
  p120, p173) with exact matches.

Policy applied per unkeyed question in an AUTO-tier set:
- Question text passes a sanity gate (genuine question, not a table row /
  hint prose / glossary fragment) -> answer_key written, key_source cites the
  grid page + validation evidence. If the question has no captured options,
  extra.needs_vision is set so it stays out of playable pools until the
  vision pass recovers the options.
- Gate-failed -> NO key; extra.needs_reextraction records the reason (these
  are misextractions; the vision re-pass re-reads their cited pages).
- REVIEW / NO_SEGMENT sets are untouched this round.

Inputs (produced by the session's matching pipeline, checked into the patch):
  data/corpus/patches/2026-09-02_sinha_grid_keys.patch.jsonl
Running this script re-applies that patch idempotently.
"""

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
MASTER = ROOT / "data/corpus/MASTER_corpus.jsonl"
PATCH = ROOT / "data/corpus/patches/2026-09-02_sinha_grid_keys.patch.jsonl"


def main():
    patch = {}  # (set_id, number) -> entry
    for line in PATCH.read_text().splitlines():
        if not line.strip():
            continue
        e = json.loads(line)
        patch[(e["set_id"], str(e["number"]))] = e

    out_lines = []
    applied = flagged = 0
    with MASTER.open() as f:
        for line in f:
            r = json.loads(line)
            if r.get("book") == "Sinha":
                for q in r.get("questions") or []:
                    e = patch.get((r["set_id"], str(q.get("number"))))
                    if not e:
                        continue
                    if e["action"] == "key":
                        if q.get("answer_key"):  # never overwrite
                            continue
                        q["answer_key"] = e["answer_key"]
                        q["key_source"] = e["key_source"]
                        if e.get("needs_vision"):
                            q.setdefault("extra", {})["needs_vision"] = e["needs_vision"]
                        applied += 1
                    elif e["action"] == "flag":
                        q.setdefault("extra", {})["needs_reextraction"] = e["reason"]
                        flagged += 1
            out_lines.append(json.dumps(r, ensure_ascii=False))
    MASTER.write_text("\n".join(out_lines) + "\n")
    print(f"applied {applied} keys, flagged {flagged} questions for re-extraction")


if __name__ == "__main__":
    sys.exit(main())
