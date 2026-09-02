#!/usr/bin/env python3
"""Station 3 — grounded extraction via LangExtract (SETTLED 2026-09-02).

Replaces the July ungrounded prompting (focused_extract.py / Ollama llama3.2:3b,
whose "entities" outputs are untrusted). Hard rule from the factory PDF: every
fact must cite exact supporting source characters or it is DISCARDED.

Pilot scope (as planned pre-loss): the Tirthaji book chunks from the recovered
Ledger export — Station 1/2 output already exists there, so this isolates
Station 3. Resumable via a checkpoint file (station-2 convention).

DATA CAVEAT (verified 2026-09-02): the legacy chunks' `content` is LLM-written
SUMMARY prose from the July enrichment, not verbatim book text — so pilot
extractions ground to summaries, validating Station-3 MECHANICS only.
Production runs require verbatim chunks from a Station 0/1 re-pass over the
recovered source PDFs (incoming/Resources) before extraction provenance
reaches the book itself.

Model backends (choose via env / flags; NO key ever read from recovered files):
  --provider ollama  : local, e.g. --model llama3.2:3b (needs `ollama pull` first)
  --provider openai  : OPENAI_API_KEY from owner .env (key policy 2026-09-02)
  --provider gemini  : GEMINI_API_KEY from owner .env
Run `--list-slice` to preview the pilot input with no model and no langextract.

Outputs (data/factory/station3_pilot/):
  extractions.jsonl  {chunk_id, book_id, page, class, text, attributes,
                      start, end, grounding: exact|fuzzy}
  report.json        chunks processed, per-class counts, grounding/discard rates
  checkpoint.json    processed chunk ids (delete to restart)
"""

import argparse
import json
import os
import re
import unicodedata
from collections import Counter
from pathlib import Path

PROMPT = """Extract structured facts from this Vedic mathematics teaching text.
Extract only what is explicitly present, using exact spans from the text:
- skill: a named mathematical skill, method, or concept being taught
- worked_example: a concrete calculation demonstrated step by step
- trap: a mistake, pitfall, or error pattern the text warns about
- sutra_reference: an explicit mention of a Vedic sutra by name
Never paraphrase; extraction_text must be copied verbatim from the source."""


def nfkc(s: str) -> str:
    return unicodedata.normalize("NFKC", s or "")


def fold(s: str) -> str:
    return re.sub(r"\s+", " ", s).strip().casefold()


def build_examples():
    import langextract as lx
    ex1_text = nfkc(
        "The Ekadhika Purva sutra, meaning 'by one more than the previous one', converts "
        "fractions like 1/19 into recurring decimals. Take 19: the previous digit is 1, "
        "so Ekadhika is 2. Multiply successively: 1, 2, 4, 8, 16... Students often forget "
        "to carry when the product exceeds 9, which breaks the whole chain."
    )
    ex1 = lx.data.ExampleData(text=ex1_text, extractions=[
        lx.data.Extraction(extraction_class="sutra_reference", extraction_text="Ekadhika Purva",
                           attributes={"canonical": "Ekādhikena Pūrveṇa"}),
        lx.data.Extraction(extraction_class="skill",
                           extraction_text="converts fractions like 1/19 into recurring decimals",
                           attributes={"name": "Ekadhika recurring-decimal conversion"}),
        lx.data.Extraction(extraction_class="worked_example",
                           extraction_text="Take 19: the previous digit is 1, so Ekadhika is 2. Multiply successively: 1, 2, 4, 8, 16",
                           attributes={"technique": "Ekadhika multiplication chain"}),
        lx.data.Extraction(extraction_class="trap",
                           extraction_text="forget to carry when the product exceeds 9",
                           attributes={"category": "PROCEDURAL_ERROR"}),
    ])
    ex2_text = nfkc(
        "Nikhilam multiplication works best near a base. To multiply 97 by 96, note the "
        "deficiencies 3 and 4 from 100. Cross-subtract: 97-4 = 93. Multiply deficiencies: "
        "3 x 4 = 12. Answer: 9312. Choosing a base far from both numbers makes the "
        "deviations large and defeats the method."
    )
    ex2 = lx.data.ExampleData(text=ex2_text, extractions=[
        lx.data.Extraction(extraction_class="skill", extraction_text="Nikhilam multiplication works best near a base",
                           attributes={"name": "Nikhilam base multiplication"}),
        lx.data.Extraction(extraction_class="worked_example",
                           extraction_text="To multiply 97 by 96, note the deficiencies 3 and 4 from 100. Cross-subtract: 97-4 = 93. Multiply deficiencies: 3 x 4 = 12. Answer: 9312",
                           attributes={"technique": "Nikhilam", "answer": "9312"}),
        lx.data.Extraction(extraction_class="trap",
                           extraction_text="Choosing a base far from both numbers makes the deviations large",
                           attributes={"category": "TECHNIQUE_ERROR"}),
    ])
    return [ex1, ex2]


def run_model(text: str, args):
    import langextract as lx
    kwargs = dict(
        text_or_documents=text,
        prompt_description=PROMPT,
        examples=build_examples(),
        model_id=args.model,
        max_char_buffer=2000,
    )
    if args.provider == "ollama":
        kwargs.update(model_url=args.ollama_url, fence_output=False, use_schema_constraints=False)
    elif args.provider == "openai":
        key = os.environ.get("OPENAI_API_KEY")
        if not key:
            raise SystemExit("OPENAI_API_KEY not set (owner .env only — key policy 2026-09-02)")
        kwargs.update(api_key=key, fence_output=True, use_schema_constraints=False)
    elif args.provider == "gemini":
        key = os.environ.get("GEMINI_API_KEY")
        if not key:
            raise SystemExit("GEMINI_API_KEY not set (owner .env only — key policy 2026-09-02)")
        kwargs.update(api_key=key)
    return lx.extract(**kwargs)


def ground(extraction, text: str):
    """Enforce the character-grounding rule. Returns (start, end, 'exact'|'fuzzy') or None."""
    ci = getattr(extraction, "char_interval", None)
    if ci is None or ci.start_pos is None or ci.end_pos is None:
        return None
    s, e = ci.start_pos, ci.end_pos
    if not (0 <= s < e <= len(text)):
        return None
    span, claimed = text[s:e], extraction.extraction_text or ""
    if span == claimed:
        return s, e, "exact"
    if fold(span) == fold(claimed):
        return s, e, "fuzzy"
    return None


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--chunks", default="incoming/topic_browser_full_package/db_exports/chunks.jsonl")
    ap.add_argument("--book-filter", default="Tirthaji")
    ap.add_argument("--limit", type=int, default=40, help="pilot chunk count (0 = all)")
    ap.add_argument("--min-page", type=int, default=0,
                    help="skip pages below this (front matter is not teaching content)")
    ap.add_argument("--provider", choices=["ollama", "openai", "gemini"], default="ollama")
    ap.add_argument("--model", default="llama3.2:3b")
    ap.add_argument("--ollama-url", default="http://localhost:11434")
    ap.add_argument("--out-dir", default="data/factory/station3_pilot")
    ap.add_argument("--list-slice", action="store_true", help="preview input, no model calls")
    args = ap.parse_args()

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    ckpt_path = out_dir / "checkpoint.json"
    done = set(json.loads(ckpt_path.read_text())["done"]) if ckpt_path.exists() else set()

    slice_rows = []
    with Path(args.chunks).open() as f:
        for line in f:
            c = json.loads(line)
            # Two shapes: legacy Ledger export (id/book_id/page_number) and the
            # station-0 verbatim store (chunk_id/book/page_start).
            cid = c.get("id") or c.get("chunk_id")
            book = c.get("book_id") or c.get("book") or ""
            page = c.get("page_number") if "page_number" in c else c.get("page_start")
            if args.book_filter.casefold() not in book.casefold():
                continue
            if args.min_page and (page or 0) < args.min_page:
                continue
            content = nfkc(c.get("content") or "")
            if len(content) < 60:  # skip fragments
                continue
            slice_rows.append({"id": cid, "book_id": book, "page": page, "content": content})
            if args.limit and len(slice_rows) >= args.limit:
                break

    print(f"pilot slice: {len(slice_rows)} chunks (filter={args.book_filter!r}, limit={args.limit})")
    if args.list_slice:
        for r in slice_rows[:5]:
            print(f"  {r['id'][:8]} p{r['page']} {r['content'][:70]!r}")
        return 0

    stats = Counter()
    ext_path = out_dir / "extractions.jsonl"
    with ext_path.open("a") as out:
        for row in slice_rows:
            if row["id"] in done:
                stats["skipped_checkpoint"] += 1
                continue
            result = run_model(row["content"], args)
            for e in (result.extractions or []):
                stats[f"raw_{e.extraction_class}"] += 1
                g = ground(e, row["content"])
                if g is None:
                    stats["discarded_ungrounded"] += 1
                    continue
                s, ee, kind = g
                stats[f"grounded_{kind}"] += 1
                out.write(json.dumps({
                    "chunk_id": row["id"], "book_id": row["book_id"], "page": row["page"],
                    "class": e.extraction_class, "text": e.extraction_text,
                    "attributes": e.attributes or {}, "start": s, "end": ee, "grounding": kind,
                }, ensure_ascii=False) + "\n")
            done.add(row["id"])
            ckpt_path.write_text(json.dumps({"done": sorted(done)}))
            stats["chunks_processed"] += 1

    raw = sum(v for k, v in stats.items() if k.startswith("raw_"))
    grounded = stats["grounded_exact"] + stats["grounded_fuzzy"]
    report = {
        "provider": args.provider, "model": args.model,
        "stats": dict(stats),
        "grounding_rate": round(grounded / raw, 3) if raw else None,
        "note": "ungrounded extractions are DISCARDED per the factory PDF hard rule",
    }
    (out_dir / "report.json").write_text(json.dumps(report, indent=1))
    print(json.dumps(report, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
