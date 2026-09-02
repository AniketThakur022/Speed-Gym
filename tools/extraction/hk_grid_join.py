#!/usr/bin/env python3
"""Join workflow-transcribed Hall & Knight answer grids to MASTER questions.

Input: JSON produced by the hk-answer-grid-recovery workflow (dual-read +
arbitrated transcription of ANSWERS pages 553-585), saved to a file.

Join logic (two independent keys, both must agree):
  grid block heading "IV. a.  Pages 31, 32"
    -> chapter 4, examples index 1 (a=1, b=2, ...)   -> set_id hall_knight_ch04_examples_1
    -> question print pages 31,32 -> pdf pages 59,60 (constant +28 offset)
       must intersect that record's pdf_pages
Continuation blocks (exercise=null) attach to the previous page's last block.

Output: data/corpus/patches/<date>_hk_grid_keys.patch.jsonl (action=key rows,
answer expressions as answer_key, key_source citing grid pdf page + method)
plus a join report. Does NOT modify MASTER — apply with apply_sinha_grid_keys.py.
"""

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
MASTER = ROOT / "data/corpus/MASTER_corpus.jsonl"
OFFSET = 28  # print page + 28 = pdf page (verified on labels at pdf 60/100/200/300)

ROMAN = {"I": 1, "II": 2, "III": 3, "IV": 4, "V": 5, "VI": 6, "VII": 7, "VIII": 8,
         "IX": 9, "X": 10, "XI": 11, "XII": 12, "XIII": 13, "XIV": 14, "XV": 15,
         "XVI": 16, "XVII": 17, "XVIII": 18, "XIX": 19, "XX": 20, "XXI": 21,
         "XXII": 22, "XXIII": 23, "XXIV": 24, "XXV": 25, "XXVI": 26, "XXVII": 27,
         "XXVIII": 28, "XXIX": 29, "XXX": 30, "XXXI": 31, "XXXII": 32,
         "XXXIII": 33, "XXXIV": 34, "XXXV": 35}


def parse_heading(exercise):
    """'IV. a.' -> (4, 1); 'XXI. b' -> (21, 2); returns None for misc/unparseable."""
    if not exercise:
        return None
    m = re.match(r"\s*([IVXL]+)\s*\.?\s*([a-h])\b", exercise.strip(), re.I)
    if not m:
        return None
    rom = m.group(1).upper()
    if rom not in ROMAN:
        return None
    return ROMAN[rom], ord(m.group(2).lower()) - ord("a") + 1


def parse_qpages(question_pages):
    if not question_pages:
        return set()
    return {int(x) for x in re.findall(r"\d+", question_pages)}


def main(grid_json, patch_out):
    data = json.loads(Path(grid_json).read_text())

    # flatten blocks; attach continuations to the previous real block
    blocks = []
    for page in sorted(data["pages"], key=lambda p: p["page"]):
        for b in page["blocks"]:
            b = dict(b, grid_pdf_page=page["page"])
            if b.get("exercise") is None and blocks:
                prev = blocks[-1]
                merged_ans = dict(b.get("answers") or {})
                overlap = sorted(set(merged_ans) & set(prev["answers"]))
                for n, v in merged_ans.items():
                    prev["answers"].setdefault(n, v)
                prev.setdefault("extra_grid_pages", []).append(page["page"])
                if overlap:
                    prev.setdefault("overlap_warn", []).extend(overlap)
            else:
                b["answers"] = dict(b.get("answers") or {})
                blocks.append(b)

    hk = []
    with MASTER.open() as f:
        for line in f:
            r = json.loads(line)
            if r["book"] == "Hall & Knight" and r["content_type"] == "question_set":
                hk.append(r)
    by_key = {}
    for r in hk:
        m = re.match(r"hall_knight_ch(\d+)_examples_(\d+)$", r["set_id"])
        if m:
            by_key[(int(m.group(1)), int(m.group(2)))] = r

    entries, report = [], {"joined": 0, "keyed": 0, "page_mismatch": [], "no_record": [],
                           "unparsed_heading": [], "already_keyed": 0, "no_grid_number": 0}
    for b in blocks:
        key = parse_heading(b.get("exercise"))
        if not key:
            report["unparsed_heading"].append({"exercise": b.get("exercise"),
                                               "grid_page": b["grid_pdf_page"],
                                               "n_answers": len(b["answers"])})
            continue
        rec = by_key.get(key)
        if not rec:
            report["no_record"].append({"exercise": b.get("exercise"), "key": key})
            continue
        qp = {p + OFFSET for p in parse_qpages(b.get("question_pages"))}
        rec_pp = set(rec.get("pdf_pages") or [])
        if qp and rec_pp and not (qp & rec_pp):
            report["page_mismatch"].append({"exercise": b.get("exercise"), "key": key,
                                            "grid_cites_pdf": sorted(qp),
                                            "record_pdf": sorted(rec_pp)})
            continue
        report["joined"] += 1
        ks = ("answer_grid @p%d (H&K ANSWERS section; dual-read + arbitrated workflow "
              "wf_b9d8eea6, exercise %s verified by page cite, 2026-09-02)"
              % (b["grid_pdf_page"], (b.get("exercise") or "").strip()))
        for q in rec["questions"]:
            n = str(q.get("number")).strip()
            if q.get("answer_key"):
                report["already_keyed"] += 1
                continue
            val = b["answers"].get(n)
            if val is None or str(val).strip() == "":
                report["no_grid_number"] += 1
                continue
            e = {"set_id": rec["set_id"], "number": n, "action": "key",
                 "answer_key": str(val).strip(), "key_source": ks}
            if len(q.get("options") or []) < 2 and (q.get("extra") or {}).get("needs_vision"):
                e["needs_vision"] = (q.get("extra") or {}).get("needs_vision")
            entries.append(e)
            report["keyed"] += 1

    with open(patch_out, "w") as f:
        for e in entries:
            f.write(json.dumps(e, ensure_ascii=False) + "\n")
    print(json.dumps({k: (v if not isinstance(v, list) else v[:8]) for k, v in report.items()},
                     indent=1, ensure_ascii=False))
    print("patch ->", patch_out, "(%d key rows)" % len(entries))


if __name__ == "__main__":
    if len(sys.argv) != 3:
        raise SystemExit(__doc__)
    main(sys.argv[1], sys.argv[2])
