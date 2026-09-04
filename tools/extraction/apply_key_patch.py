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
    global PATCH
    if len(sys.argv) > 1:
        PATCH = Path(sys.argv[1]).resolve()
    patch = {}  # (set_id, number) -> entry
    for line in PATCH.read_text().splitlines():
        if not line.strip():
            continue
        e = json.loads(line)
        patch[(e["set_id"], str(e["number"]))] = e

    # Match on set_id membership, not a hardcoded book: the same patch format
    # is used for every book's key recovery (Sinha grids, H&K grids, ...).
    patch_sets = {sid for sid, _ in patch}

    out_lines = []
    applied = flagged = 0
    with MASTER.open() as f:
        for line in f:
            r = json.loads(line)
            rec_e = patch.get((r.get("set_id"), "*"))
            if rec_e is not None and rec_e["action"] == "record_tags":
                r.setdefault("extra", {})["tags"] = rec_e["tags"]
                r["extra"]["tags_source"] = rec_e["tags_source"]
                applied += 1
            rec_c = patch.get((r.get("set_id"), "*"))
            if rec_c is not None and rec_c["action"] == "clear_chart_flag":
                ex = r.setdefault("extra", {})
                if ex.get("needs_chart_vision"):
                    ex["needs_chart_vision"] = False
                    ex["chart_vision_resolution"] = rec_c["resolution"]
                    applied += 1
            if r.get("set_id") in patch_sets:
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
                    elif e["action"] == "suspect":
                        q.setdefault("extra", {})["key_suspect"] = e["reason"]
                        flagged += 1
                    elif e["action"] == "correct_key":
                        prev = q.get("answer_key")
                        if prev == e["answer_key"]:
                            continue
                        q["answer_key"] = e["answer_key"]
                        q["key_source"] = e["key_source"]
                        ex = q.setdefault("extra", {})
                        ex["key_superseded"] = {"previous": prev,
                                                "previous_source": e.get("previous_source"),
                                                "why": e["why"]}
                        applied += 1
                    elif e["action"] == "difficulty":
                        if q.get("difficulty") is not None:
                            continue          # never overwrite an existing value
                        q["difficulty"] = e["difficulty"]
                        q.setdefault("extra", {})["difficulty_source"] = e["difficulty_source"]
                        applied += 1
                    elif e["action"] == "format":
                        # only ever fills in "unclassified"; never overwrites a
                        # format the extraction pipeline already determined
                        if q.get("question_format") not in (None, "", "unclassified"):
                            continue
                        q["question_format"] = e["question_format"]
                        q.setdefault("extra", {})["format_source"] = e["format_source"]
                        applied += 1
            out_lines.append(json.dumps(r, ensure_ascii=False))
    MASTER.write_text("\n".join(out_lines) + "\n")
    print(f"applied {applied} keys, flagged {flagged} questions for re-extraction")


if __name__ == "__main__":
    sys.exit(main())
