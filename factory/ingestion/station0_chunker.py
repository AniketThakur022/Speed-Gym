#!/usr/bin/env python3
"""Station 0 — teaching-unit chunker over the shared verbatim page store.

Cross-chat contract (2026-09-02): extraction owns digitizing (page_ocr_pipeline
artifacts: NNNN.png / NNNN_ocr.md / NNNN_meta.json); RAG owns teaching-unit
segmentation + content_hash, consuming those artifacts. This replaces the July
summary-chunks (the 4,943-chunk store) with VERBATIM book text — the input
Station 3 grounding and T4 retrieval actually need.

Page gate (two meta variants):
  new sweep  : meta["verbatim"] is true          (Hall & Knight etc.)
  old store  : no "verbatim" key -> accept when ocr_confidence >= 0.5
               and word_count >= 40               (Sinha tesseract store)
Skipped pages are counted with reasons — they are extraction's vision queue.

Teaching units (factory PDF: one explanation / worked example / problem per
chunk): line-anchored boundary markers (Example N, EXAMPLES/Exercise blocks,
chapter/section headings, markdown headers), then enumerator splitting inside
problem blocks when >= 3 clean `N.`/`N)` markers, size guardrails (merge < 200
chars, split > 4500 at blank lines). Every chunk carries page provenance and a
content_hash (sha256 over whitespace-folded NFKC text) for dedup.

Output: data/factory/chunks/<book_slug>_chunks_v1.jsonl + a sweep report.
No DB writes here — station 2 (embeddings, key-gated) and station 5 (MERGE)
consume these files later.
"""

import argparse
import hashlib
import json
import re
import unicodedata
from collections import Counter
from pathlib import Path

MIN_CHARS = 200
MAX_CHARS = 4500
HEADER_RE = re.compile(r"^<!--.*?-->\s*$", re.M)
WORKED_RE = re.compile(r"^\s*#{0,3}\s*Example[s]?\s+\d", re.I)
PROBLEMS_RE = re.compile(r"^\s*#{0,3}\s*(EXAMPLES?|EXERCISES?|Exercise|PRACTICE\s+(EXERCISES?|PROBLEMS?)|PROBLEMS?\s+FOR\s+PRACTICE|Previous\s+Years?)\b[. ]*", re.I)
SECTION_RE = re.compile(r"^\s*(#{1,3}\s+\S|CHAPTER\b|[A-Z][A-Z0-9 ,.&'()-]{10,}$)")
ENUM_RE = re.compile(r"^\s*(\d{1,3})[.)]\s+\S")


def nfkc(s: str) -> str:
    return unicodedata.normalize("NFKC", s)


def content_hash(s: str) -> str:
    folded = re.sub(r"\s+", " ", nfkc(s)).strip().casefold()
    return hashlib.sha256(folded.encode()).hexdigest()


def page_ok(meta: dict) -> tuple[bool, str]:
    if "verbatim" in meta:
        return (True, "verbatim") if meta["verbatim"] else (False, "needs_render")
    conf = meta.get("ocr_confidence") or 0
    wc = meta.get("word_count") or 0
    if conf >= 0.5 and wc >= 40:
        return True, "confidence"
    return False, f"low_conf_{conf:.2f}" if conf < 0.5 else "too_few_words"


def classify_boundary(line: str) -> str | None:
    if WORKED_RE.match(line):
        return "worked_example"
    if PROBLEMS_RE.match(line):
        return "problem_set"
    if SECTION_RE.match(line):
        return "explanation"
    return None


def split_oversize(text: str) -> list[str]:
    """Pack pieces up to MAX_CHARS: paragraph boundaries first, then single
    lines (PyMuPDF text often has no blank lines at all), hard-cut last."""
    if len(text) <= MAX_CHARS:
        return [text]
    for sep in ("\n\n", "\n"):
        pieces = text.split(sep)
        if len(pieces) < 2:
            continue
        parts, cur, size = [], [], 0
        for piece in pieces:
            if cur and size + len(piece) > MAX_CHARS:
                parts.append(sep.join(cur))
                cur, size = [], 0
            cur.append(piece)
            size += len(piece) + len(sep)
        if cur:
            parts.append(sep.join(cur))
        if all(len(p) <= MAX_CHARS * 1.2 for p in parts):
            return [p for p in parts if p.strip()]
    return [text[i:i + MAX_CHARS] for i in range(0, len(text), MAX_CHARS)]


def split_problems(text: str) -> list[str] | None:
    """Split a problem block on `N.` enumerators when they form a clean run."""
    lines = text.splitlines()
    starts = [i for i, l in enumerate(lines) if ENUM_RE.match(l)]
    if len(starts) < 3:
        return None
    nums = [int(ENUM_RE.match(lines[i]).group(1)) for i in starts]
    ascending = sum(1 for a, b in zip(nums, nums[1:]) if b > a)
    if ascending < len(nums) * 0.7:  # OCR-scrambled enumeration: keep the block whole
        return None
    out = []
    if starts[0] > 0:
        out.append("\n".join(lines[:starts[0]]))
    for i, s in enumerate(starts):
        e = starts[i + 1] if i + 1 < len(starts) else len(lines)
        out.append("\n".join(lines[s:e]))
    return [p for p in out if p.strip()]


def chunk_book(pages_dir: Path, book_slug: str, out_dir: Path) -> dict:
    metas = sorted(pages_dir.glob("*_meta.json"))
    skip = Counter()
    units = []  # (type, text, page_num, page_label)
    cur_type, cur_lines, cur_pages = "explanation", [], []

    def flush():
        nonlocal cur_lines, cur_pages
        text = "\n".join(cur_lines).strip()
        if text:
            units.append((cur_type, text, cur_pages[:]))
        cur_lines, cur_pages = [], []

    for mp in metas:
        meta = json.loads(mp.read_text())
        ok, reason = page_ok(meta)
        if not ok:
            skip[reason] += 1
            continue
        skip["used"] += 1
        ocr = mp.with_name(mp.name.replace("_meta.json", "_ocr.md"))
        if not ocr.exists():
            skip["missing_ocr"] += 1
            continue
        text = HEADER_RE.sub("", nfkc(ocr.read_text())).strip()
        ptag = (meta.get("page_num"), str(meta.get("page_label")))
        for line in text.splitlines():
            btype = classify_boundary(line)
            if btype:
                flush()
                cur_type = btype
            cur_lines.append(line)
            if not cur_pages or cur_pages[-1] != ptag:
                cur_pages.append(ptag)
    flush()

    # problem_set subdivision + size guardrails + merge-small
    refined = []
    for utype, text, pages in units:
        pieces = None
        if utype == "problem_set":
            pieces = split_problems(text)
        if pieces:
            first = True
            for p in pieces:
                ptype = "problem_set" if first and not ENUM_RE.match(p.splitlines()[0]) else "problem"
                for sub in split_oversize(p):  # a "problem" can span pages of solution prose
                    refined.append((ptype, sub, pages))
                first = False
        else:
            for p in split_oversize(text):
                refined.append((utype, p, pages))

    merged = []
    for utype, text, pages in refined:
        if merged and len(text) < MIN_CHARS and merged[-1][0] == utype \
                and len(merged[-1][1]) + len(text) <= MAX_CHARS:
            ptype, ptext, ppages = merged[-1]
            merged[-1] = (ptype, ptext + "\n" + text,
                          ppages + [pg for pg in pages if pg not in ppages])
        else:
            merged.append((utype, text, list(pages)))

    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"{book_slug}_chunks_v1.jsonl"
    seen_h = set()
    stats = Counter()
    with out_path.open("w") as f:
        for i, (utype, text, pages) in enumerate(merged):
            h = content_hash(text)
            if h in seen_h:
                stats["dropped_duplicate"] += 1
                continue
            seen_h.add(h)
            stats[utype] += 1
            f.write(json.dumps({
                "chunk_id": f"{book_slug}_s0_{i:05d}",
                "book": book_slug,
                "chunk_type": utype,
                "page_start": pages[0][0] if pages else None,
                "page_end": pages[-1][0] if pages else None,
                "page_labels": [p[1] for p in pages],
                "content": text,
                "content_hash": h,
                "word_count": len(text.split()),
                "source": "station0_v1",
            }, ensure_ascii=False) + "\n")
    return {"book": book_slug, "pages": dict(skip), "chunks": dict(stats),
            "total_chunks": sum(v for k, v in stats.items() if k != "dropped_duplicate"),
            "out": str(out_path)}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("stores", nargs="+", help="page-store dirs (or a parent holding <book>/ dirs)")
    ap.add_argument("--out-dir", default="data/factory/chunks")
    args = ap.parse_args()

    reports = []
    for store in args.stores:
        sp = Path(store)
        book_dirs = [sp] if list(sp.glob("*_meta.json")) else sorted(
            d for d in sp.iterdir() if d.is_dir() and list(d.glob("*_meta.json")))
        for d in book_dirs:
            slug = re.sub(r"[^A-Za-z0-9_]+", "_", d.name if d.name != "pages" else d.parent.name)
            reports.append(chunk_book(d, slug, Path(args.out_dir)))
            r = reports[-1]
            print(f"{r['book']}: {r['total_chunks']} chunks from {r['pages'].get('used', 0)} pages "
                  f"(skipped: { {k: v for k, v in r['pages'].items() if k != 'used'} }) -> {r['out']}")
    (Path(args.out_dir) / "station0_report.json").write_text(json.dumps(reports, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
