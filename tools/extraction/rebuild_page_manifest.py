#!/usr/bin/env python3
"""Rebuild a book's page_manifest.json from its pages/*_meta.json files.

page_ocr_pipeline.py overwrites the manifest with only the pages of the
CURRENT run, so a partial run (e.g. --pages 1-1) clobbers the manifest for
the whole book while the per-page artifacts survive. This tool restores the
manifest from those artifacts. (That is exactly what happened to
CAT_DI_LR_Nishit_K_Sinha in the recovered July-12 package: manifest said
1 page, pages/ held 305.)

Usage:
    python3 rebuild_page_manifest.py <book_dir>
    # e.g. python3 tools/extraction/rebuild_page_manifest.py \
    #        "incoming/topic_browser_full_package/cat_data/CAT_DI_LR_Nishit_K_Sinha"
"""

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

SUBJECTS = {
    "CAT_DI_LR_Nishit_K_Sinha": "DI",
    "CAT_DI_LR_Arun_Sharma": "DI",
    "CAT_LR_LSAT_Logic_Games": "LR",
    "CAT_VARC_Part1": "Verbal",
    "CAT_VARC_Part2": "Verbal",
    "CAT_Quant_Arun_Sharma": "Quant",
    "CAT_Quant_Higher_Algebra": "Quant",
}


def rebuild(book_dir: Path) -> Path:
    metas = []
    for p in sorted((book_dir / "pages").glob("*_meta.json")):
        metas.append(json.loads(p.read_text()))
    if not metas:
        raise SystemExit(f"no pages/*_meta.json under {book_dir}")
    metas.sort(key=lambda m: m["page_num"])

    manifest = {
        "book_id": book_dir.name,
        "subject": SUBJECTS.get(book_dir.name, "Unknown"),
        "total_pages": len(metas),
        "processed_at": datetime.now(timezone.utc).isoformat(),
        "pages": metas,
        "stats": {
            "by_type": {},
            "by_confidence": {"high": 0, "medium": 0, "low": 0},
            "total_words": sum(p["word_count"] for p in metas),
            "has_images": sum(1 for p in metas if p["has_images"]),
            "has_tables": sum(1 for p in metas if p["has_table"]),
        },
    }
    for p in metas:
        t = p["page_type"]
        manifest["stats"]["by_type"][t] = manifest["stats"]["by_type"].get(t, 0) + 1
        c = p["ocr_confidence"]
        band = "high" if c > 0.8 else "medium" if c > 0.5 else "low"
        manifest["stats"]["by_confidence"][band] += 1

    out = book_dir / "page_manifest.json"
    if out.exists():
        out.rename(book_dir / "page_manifest.json.pre_rebuild.bak")
    out.write_text(json.dumps(manifest, indent=2, ensure_ascii=False))
    print(f"rebuilt {out}: {len(metas)} pages, stats {manifest['stats']['by_type']}")
    return out


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit(__doc__)
    rebuild(Path(sys.argv[1]))
