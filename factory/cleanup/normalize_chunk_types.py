#!/usr/bin/env python3
"""Chunk type-label cleanup — the 'messy type labels' debt from the RAG factory PDF.

The legacy chunks.jsonl (4,943 rows) encodes three things in chunk_type:
  'explanation'                  -> fine as-is
  'template_<8-char book prefix>' -> type 'template' + redundant truncated book tag
  'enriched_record_<hash>'       -> type 'enriched_record' + per-record ref suffix

We do NOT rewrite the 110MB export. This emits a compact patch keyed by chunk id,
applied at ingest time (station 5 MERGE): normalized chunk_type, plus the recovered
suffix ref, plus a book cross-check (template prefix vs book_id).

Output: data/factory/chunk_type_patch_v1.jsonl {id, chunk_type, ref?, book_check}
        + stats to stdout.
"""

import argparse
import json
from collections import Counter
from pathlib import Path

CANON_TYPES = ("explanation", "template", "enriched_record")


def normalize(raw: str) -> tuple[str, str | None]:
    if raw == "explanation":
        return "explanation", None
    if raw.startswith("template_"):
        return "template", raw[len("template_"):] or None
    if raw.startswith("enriched_record_"):
        return "enriched_record", raw[len("enriched_record_"):] or None
    return "UNKNOWN", raw


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--chunks", default="incoming/topic_browser_full_package/db_exports/chunks.jsonl")
    ap.add_argument("--out", default="data/factory/chunk_type_patch_v1.jsonl")
    args = ap.parse_args()

    stats = Counter()
    book_mismatch = []
    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w") as out, Path(args.chunks).open() as f:
        for line in f:
            c = json.loads(line)
            norm, ref = normalize(c.get("chunk_type") or "")
            stats[norm] += 1
            row = {"id": c["id"], "chunk_type": norm}
            if ref:
                row["ref"] = ref
            if norm == "template":
                book_id = c.get("book_id") or ""
                ok = bool(ref) and book_id.replace(" ", "_").startswith(ref.rstrip("_"))
                row["book_check"] = "ok" if ok else "mismatch"
                if not ok:
                    stats["book_mismatch"] += 1
                    if len(book_mismatch) < 10:
                        book_mismatch.append({"id": c["id"], "prefix": ref, "book_id": book_id})
            out.write(json.dumps(row, ensure_ascii=False) + "\n")

    print("patch:", out_path)
    print("normalized type counts:", dict(stats))
    if book_mismatch:
        print("book mismatch sample:", json.dumps(book_mismatch[:3], indent=1))
    return 1 if stats.get("UNKNOWN") else 0


if __name__ == "__main__":
    raise SystemExit(main())
