#!/usr/bin/env python3
"""Vision re-pass harness for MASTER_corpus.jsonl (build now, run when keys land).

Selects every vision-work item in the corpus, groups them into page-anchored
tasks, renders the needed PDF pages, and (once ANTHROPIC_API_KEY exists in
.env) submits them through the Message Batches API (50% cost) with page images
as vision input. Results land as raw JSONL for a human/LLM review step that
emits data/corpus/patches/*.patch.jsonl files (same pattern as the Sinha
grid-key recovery) — results are NEVER auto-applied to MASTER.

Work-item classes (queried from MASTER):
  needs_vision        q-level extra.needs_vision (incl. "options not in text
                      layer" from the 2026-09-02 Sinha grid pass)
  needs_reextraction  q-level extra.needs_reextraction (fused hint/solution
                      prose; grid key preserved in patch files)
  chart_vision        record-level extra.needs_chart_vision / needs_vision
  truncated_essay     the 4 GRE essay fragments

Subcommands:
  inventory             counts by class x book, PDF availability
  build [--book B] [--limit N]
                        write task manifest + render page images (offline)
  station1 --book B     verbatim full-book page sweep (offline): extract every
                        page's text layer to the shared page store
                        (data/vision_pass/pages/<book>/NNNN_ocr.md + _meta.json,
                        same artifact contract as page_ocr_pipeline.py), flag
                        poor-text-layer pages needs_render for the vision batch,
                        print a per-book quality report. This is the Station-1
                        digitizer lane the RAG factory's verbatim re-chunk
                        consumes (chunking itself is RAG-owned, downstream) —
                        one sweep serves both the vision pass and RAG, so each
                        book is only processed once. MinerU/Docling bake-off
                        may later replace the extractor; the artifact contract
                        stays.
  submit --tasks FILE   create a message batch  [requires ANTHROPIC_API_KEY]
  poll --batch ID       processing status       [requires ANTHROPIC_API_KEY]
  collect --batch ID    write raw results JSONL [requires ANTHROPIC_API_KEY]

Usage:
  python3 tools/extraction/vision_pass_harness.py inventory
  python3 tools/extraction/vision_pass_harness.py build --book Sinha --limit 20
"""

import argparse
import base64
import collections
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
MASTER = ROOT / "data/corpus/MASTER_corpus.jsonl"
WORKDIR = ROOT / "data/vision_pass"
RES = ROOT / "incoming/Resources"
MODEL_DEFAULT = "claude-opus-5"

# MASTER book name -> source PDF (None = no PDF recovered)
BOOK_PDFS = {
    "Tyra": RES / "Phase 1 - Speed Gym/2015.136155.Magical-Book-On-Quicker-Maths_text.pdf",
    "Schaum": RES / "Phase 1 - Speed Gym/Ayres, Schmidt - Schaum_s Outline of College Mathematics [3rd Edition].pdf",
    "Bird": RES / "Phase 1 - Speed Gym/Bird - Basic Engineering Mathematics [5th Edition].pdf",
    "Dehaene": RES / "Phase 1 - Speed Gym/The Number Sense _ How the Mind Creates Mathematics, Revised -- Stanislas Dehaene -- Rev_ and updated ed_, New York, New York State, 2011 -- Oxford -- 9780199753871 -- fa449990528800ab8a482ff4f6a46699 -- Anna’s Arch.pdf",
    "Bhatia": RES / "Phase 1 - Speed Gym/pdfcoffee.com_vedic-mathematics-made-easy-dhaval-bhatia-pdf-free.pdf",
    "Vedic Secrets": RES / "Phase 1 - Speed Gym/pdfcoffee.com_vedic-mathematics-secrets-pdf-free.pdf",
    "Arun Sharma Quant": RES / "Phase 3 - CAT Pillar/pdf/Arun Sharma - How to Prepare for Quantitative Aptitude for the CAT-McGraw Hill Education (2018).pdf",
    "Arun Sharma": RES / "Phase 3 - CAT Pillar/pdf/pdfcoffee.com-how-to-prepare-for-data-interpretation-and-logical-reasoning-for-cat-arun-sharma.pdf",
    "Sinha": RES / "Phase 3 - CAT Pillar/pdf/logical-reasoning-and-data-interpretation-for-cat-by-nishit-k-si-027ec9cbb8b72.pdf",
    "Hall & Knight": RES / "Phase 3 - CAT Pillar/pdf/higheralgebraseq00hall.pdf",
    "Manhattan Logic Games": RES / "Phase 3 - CAT Pillar/_OceanofPDF.com_Logic_Games__LSAT_Strategy_Guide_4th_Edit_-_Manhattan_Prep.pdf",
    "Strang": RES / "Phase 3 - GMAT Pillar/Gilbert Strang - Introduction to Linear Algebra [5th Edition] (2016).pdf",
    "Manhattan GMAT Verbal": RES / "Phase 3 - GMAT Pillar/_OceanofPDF.com_GMAT_All_the_Verbal_-_Manhattan_Prep.pdf",
    "Manhattan Quant": RES / "Phase 3 - GMAT Pillar/_OceanofPDF.com_GRE_All_the_Quant_-_Manhattan_Prep.pdf",
    "ETS GRE": RES / "Phase 3 - GRE Pillar/1681988027The Official Guide to the GRE® General Test, Third Edition.pdf",
    "Manhattan 5 lb": RES / "Phase 3 - GRE Pillar/_OceanofPDF.com_5_lb_Book_of_GRE_Practice_Problems_4th_Ed_-_Manhattan_Prep.pdf",
    "ETS GRE Verbal": RES / "Phase 3 - GRE Pillar/ETS-GRE-Verbal-practice-questions-2014.pdf",
    "Knuth": RES / "Phase 3 - Universal Logic Engine/Concrete Mathematics - 2Nd Edition - Knuth - A Foundation For Computer Science - (New - Complete - Not Ocr) no marges.pdf",
    "Hogg": RES / "Phase 3 - Universal Logic Engine/Hogg - Probability and Statistical Inference.pdf",
    "Mosteller": RES / "Phase 3 - Universal Logic Engine/dokumen.pub_fifty-challenging-problems-in-probability-with-solutions-dover-books-on-mathematics-revised-ed-9780486134963-0486134962.pdf",
    # Staged (non-MASTER) books swept for the RAG page store only:
    "Tirthaji": RES / "Phase 1 - Speed Gym/toaz.info-vedic-mathematicsorignal-book-pr_8a2ffa2809f58b15549e5b731f26bb32.pdf",
    # No PDF recovered: Thakur, RS Aggarwal, Lewis, ETS GRE Writing Pool, CAT LR Bank
    "Thakur": None, "RS Aggarwal": None, "Lewis": None,
    "ETS GRE Writing Pool": None, "CAT LR Bank": None,
}

# Sinha pages are pre-rendered by the OCR pipeline — reuse instead of re-rendering
PRERENDERED = {
    "Sinha": ROOT / "incoming/topic_browser_full_package/cat_data/CAT_DI_LR_Nishit_K_Sinha/pages",
}

PROMPTS = {
    "needs_vision": (
        'SCOPE — read carefully. This is targeted fact extraction for specific numbered exercise items, NOT page transcription. Return ONLY the fields asked for, for ONLY the listed items. Do not transcribe, summarise or reproduce the rest of the page, its narrative, worked solutions or surrounding prose. If an item is not on the page, say so rather than substituting nearby content.\n\n'
        "You are repairing a flawed extraction of specific exercise items.\n"
        "The attached image(s) are the cited page(s). For EACH item listed below, find the printed "
        "question and return exact text: the question stem (fix flattened super/subscripts using ^ "
        "and _ or LaTeX), the answer options in order (empty list if the question has none printed), "
        "and, if a figure/chart is essential, a structured transcription of it.\n\nItems:\n{items}\n\n"
        "Return ONLY a JSON array, one object per item:\n"
        '[{{"set_id": ..., "number": ..., "text": ..., "options": [...], '
        '"figure": null | {{"kind": "table|bar_chart|line_chart|pie_chart|venn|diagram", ...numeric data...}}, '
        '"printed_answer_if_visible": null | "(a)"-"(e)", "confidence": "high|medium|low", "note": ...}}]\n'
        "If an item is not on these pages, return it with \"text\": null and explain in note."
    ),
    "needs_reextraction": (
        'SCOPE — read carefully. This is targeted fact extraction for specific numbered exercise items, NOT page transcription. Return ONLY the fields asked for, for ONLY the listed items. Do not transcribe, summarise or reproduce the rest of the page, its narrative, worked solutions or surrounding prose. If an item is not on the page, say so rather than substituting nearby content.\n\n'
        "A previous extraction captured hints/solution prose instead of the printed question. "
        "The attached image(s) show the exercise pages. For EACH item below, extract the TRUE printed "
        "question with that number from this exercise: full stem and options. The expected answer key "
        "from the printed answer grid is given as a hint — do not invent questions.\n\nItems:\n{items}\n\n"
        "Return ONLY a JSON array with objects: set_id, number, text, options, directions_if_shared, "
        "confidence, note. Null text + note if the numbered question is not on these pages."
    ),
    "chart_vision": (
        "Transcribe the chart/table/diagram on the attached page(s) into structured data for the "
        "record below. Return ONLY a JSON object: {{\"set_id\": ..., \"stimulus\": [{{\"kind\": "
        "\"table|bar_chart|line_chart|pie_chart|venn|diagram\", \"title\": ..., \"columns\"/\"x_labels\"/"
        "\"labels\": [...], \"rows\"/\"series\"/\"values\": [...], \"unit\": ...}}], \"confidence\": ..., "
        "\"note\": ...}}. Record: {items}"
    ),
    "truncated_essay": (
        "The attached page(s) contain a scored sample GRE essay whose extraction was truncated. "
        "Transcribe the COMPLETE printed essay text verbatim. Return ONLY a JSON object: "
        "{{\"set_id\": ..., \"text\": ..., \"confidence\": ..., \"note\": ...}}. Item: {items}"
    ),
    "page_digitization": (
        "Transcribe the attached scanned book page to faithful verbatim markdown for a retrieval "
        "corpus. Preserve reading order (columns top-to-bottom, left before right), headings as "
        "markdown headings, math with ^ / sqrt() / a/b fractions, tables as markdown tables, and "
        "mark figures as [FIGURE: one-line description]. No commentary, no summarization — verbatim "
        "text only.\n"
        "LINE BREAKS: reflow running prose into natural unwrapped paragraphs — one paragraph per "
        "line, with a blank line between paragraphs. Do NOT reproduce the page's physical line "
        "wrapping, and do not hyphenate-split words across lines (rejoin any word the print breaks "
        "at a line end). Downstream grounding cites exact character spans, and mimicking column "
        "wrapping breaks that alignment. Keep genuine line structure only where the break carries "
        "meaning: table rows, answer-grid entries, verse, numbered list items, and displayed "
        "equations each stay on their own line.\n"
        "Return ONLY a JSON object: {{\"page\": <pdf page>, \"print_label\": ..., "
        "\"markdown\": ..., \"has_figures\": bool, \"confidence\": \"high|medium|low\"}}. "
        "Context: {items}"
    ),
    "answer_grid": (
        "The attached image is a page from a book's ANSWERS section: numbered answers grouped "
        "under exercise headings (e.g. 'IV. a. Pages 31, 32'). The answers are mathematical "
        "expressions. Transcribe the ENTIRE page faithfully, reading each column top-to-bottom in "
        "print order. Use ^ for superscripts, sqrt() for roots, a/b for fractions, and keep mixed "
        "numbers like 3 1/2 explicit. Return ONLY a JSON array of exercise blocks: "
        '[{{"exercise": "IV. a.", "question_pages": "31, 32", "answers": {{"1": ..., "2": ..., ...}}, '
        '"illegible": ["numbers you could not read"]}}]. '
        "Do not guess illegible values — list them in illegible. Context: {items}"
    ),
}


def load_env_key():
    key = os.environ.get("ANTHROPIC_API_KEY")
    if not key and (ROOT / ".env").exists():
        for line in (ROOT / ".env").read_text().splitlines():
            if line.strip().startswith("ANTHROPIC_API_KEY="):
                key = line.split("=", 1)[1].strip().strip('"').strip("'")
    return key or None


def iter_master():
    with MASTER.open() as f:
        for line in f:
            yield json.loads(line)


def collect_items():
    """Yield (klass, book, set_id, pdf_pages, payload) work items."""
    for r in iter_master():
        book, sid, pages = r["book"], r["set_id"], r.get("pdf_pages") or []
        rex = r.get("extra") or {}
        if rex.get("needs_chart_vision") or isinstance(rex.get("needs_vision"), str):
            yield ("chart_vision", book, sid, pages,
                   {"reason": rex.get("needs_vision") or "needs_chart_vision",
                    "directions": (r.get("directions") or "")[:300]})
        if r.get("content_type") == "essay_sample_fragment":
            yield ("truncated_essay", book, sid, pages, {"partial": (r.get("text") or "")[:200]})
        for q in r.get("questions") or []:
            qex = q.get("extra") or {}
            if qex.get("needs_reextraction"):
                yield ("needs_reextraction", book, sid, pages,
                       {"number": q.get("number"), "reason": qex["needs_reextraction"],
                        "directions": (r.get("directions") or "")[:300]})
            elif qex.get("needs_vision"):
                yield ("needs_vision", book, sid, pages,
                       {"number": q.get("number"), "reason": qex["needs_vision"],
                        "current_text": (q.get("text") or "")[:200]})


def cmd_inventory(_args):
    counts = collections.Counter()
    books = collections.Counter()
    no_pages = collections.Counter()
    for klass, book, sid, pages, _ in collect_items():
        counts[klass] += 1
        books[(book, klass)] += 1
        if not pages:
            no_pages[book] += 1
    print("work items by class:", dict(counts.most_common()))
    print("\nby book:")
    for (book, klass), n in sorted(books.items()):
        pdf = BOOK_PDFS.get(book)
        tag = "pdf-ok" if (pdf and pdf.exists()) or book in PRERENDERED else "NO-PDF"
        print("  %-22s %-18s %5d  [%s]" % (book, klass, n, tag))
    if no_pages:
        print("\nitems with NO pdf_pages (cannot target):", dict(no_pages))


def group_tasks(book_filter=None, limit=None):
    """Group items into page-anchored tasks: (klass, book, page-span) -> items."""
    groups = collections.defaultdict(list)
    for klass, book, sid, pages, payload in collect_items():
        if book_filter and book != book_filter:
            continue
        pdf = BOOK_PDFS.get(book)
        if not pages or (book not in PRERENDERED and not (pdf and pdf.exists())):
            continue
        span = tuple(sorted(set(pages))[:4])
        groups[(klass, book, span)].append({"set_id": sid, **payload})
    tasks = []
    for (klass, book, span), items in sorted(groups.items()):
        tasks.append({"task_id": "%s__%s__p%s" % (klass, book.replace(" ", "_"),
                                                  "-".join(map(str, span))),
                      "class": klass, "book": book, "pages": list(span), "items": items})
        if limit and len(tasks) >= limit:
            break
    return tasks


def render_task_pages(task):
    """Ensure page PNGs exist for a task; return image paths."""
    book = task["book"]
    if book in PRERENDERED:
        out = []
        for p in task["pages"]:
            png = PRERENDERED[book] / ("%04d.png" % p)
            if png.exists():
                out.append(png)
        return out
    import pymupdf
    pdf = BOOK_PDFS[book]
    pages_dir = WORKDIR / "pages" / book.replace(" ", "_")
    pages_dir.mkdir(parents=True, exist_ok=True)
    out = []
    doc = None
    for p in task["pages"]:
        png = pages_dir / ("%04d.png" % p)
        if not png.exists():
            if doc is None:
                doc = pymupdf.open(str(pdf))
            if not (1 <= p <= len(doc)):
                continue
            pix = doc[p - 1].get_pixmap(matrix=pymupdf.Matrix(300 / 72, 300 / 72), alpha=False)
            pix.save(str(png))
        out.append(png)
    if doc:
        doc.close()
    return out


def cmd_build(args):
    if args.convertible:
        # Build from the export's own verdict: questions whose ONLY blockers are
        # vision-fixable AND which already carry an answer key, so a successful
        # read converts them to playable immediately. This is a much better
        # target than the raw needs_vision flag, ~45% of which is held by other
        # blockers vision cannot clear (missing key, unclassified format).
        export = ROOT / "data/exports/vmsg_questions_v1.jsonl"
        if not export.exists():
            sys.exit("run build_question_export.py first — this mode reads its verdicts")
        VISION_FIXABLE = {"needs_vision", "text_is_misextracted",
                          "option_format_without_options", "format_options_are_images",
                          "text_too_short", "duplicate_question_number_in_record"}
        want = collections.defaultdict(list)
        for line in export.open():
            r = json.loads(line)
            if r["playable"] or not r["playable_blockers"]:
                continue
            if not set(r["playable_blockers"]) <= VISION_FIXABLE:
                continue
            if not r.get("answer_key"):
                continue
            if args.book and r["book"] != args.book:
                continue
            pages = tuple(sorted(set(r.get("pdf_pages") or []))[:4])
            if not pages:
                continue
            want[(r["book"], pages)].append({
                "set_id": r["set_id"], "number": r["number"],
                "reason": "; ".join(r["playable_blockers"]),
                "answer_key_already_known": r["answer_key"],
                "current_text": (r.get("text") or "")[:200],
            })
        tasks = []
        for (book, pages), items in sorted(want.items(), key=lambda kv: -len(kv[1])):
            tasks.append({"task_id": "convert__%s__p%s" % (book.replace(" ", "_"),
                                                           "-".join(map(str, pages))),
                          "class": "needs_vision", "book": book,
                          "pages": list(pages), "items": items})
        if args.limit:
            tasks = tasks[:args.limit]
        manifest = WORKDIR / "tasks" / ("tasks_convertible_%s.jsonl"
                                        % (args.book or "all").replace(" ", "_"))
    elif args.render_flagged:
        # tasks for every needs_render page in a book's station-1 store
        book = args.render_flagged
        store = WORKDIR / "pages" / book.replace(" ", "_")
        flagged = []
        for mp in sorted(store.glob("[0-9]*_meta.json")):
            m = json.loads(mp.read_text())
            if m.get("needs_render"):
                flagged.append(m["page_num"])
        tasks = [{"task_id": "page_digitization__%s__p%04d" % (book.replace(" ", "_"), p),
                  "class": "page_digitization", "book": book, "pages": [p],
                  "items": {"book": book, "pdf_page": p}}
                 for p in flagged]
        if args.limit:
            tasks = tasks[:args.limit]
        manifest = WORKDIR / "tasks" / ("tasks_digitize_%s.jsonl" % book.replace(" ", "_"))
    elif args.answer_grid:
        # e.g. --answer-grid "Hall & Knight:553-585" — one transcription task per page
        book, span = args.answer_grid.rsplit(":", 1)
        first, last = (int(x) for x in span.split("-"))
        tasks = [{"task_id": "answer_grid__%s__p%04d" % (book.replace(" ", "_"), p),
                  "class": "answer_grid", "book": book, "pages": [p],
                  "items": {"book": book, "pdf_page": p}}
                 for p in range(first, last + 1)]
        manifest = WORKDIR / "tasks" / ("tasks_answer_grid_%s.jsonl" % book.replace(" ", "_"))
    else:
        tasks = group_tasks(args.book, args.limit)
        manifest = WORKDIR / "tasks" / ("tasks_%s.jsonl" % (args.book or "all").replace(" ", "_"))
    manifest.parent.mkdir(parents=True, exist_ok=True)
    n_img = 0
    with manifest.open("w") as f:
        for t in tasks:
            imgs = render_task_pages(t)
            t["images"] = [str(p.relative_to(ROOT)) for p in imgs]
            n_img += len(imgs)
            f.write(json.dumps(t, ensure_ascii=False) + "\n")
    print("built %d tasks (%d page images) -> %s" % (len(tasks), n_img, manifest.relative_to(ROOT)))
    by_class = collections.Counter(t["class"] for t in tasks)
    print("tasks by class:", dict(by_class))


def cmd_station1(args):
    """Full-book verbatim text sweep into the shared page store (no API, no PNGs).

    Pages whose text layer is too weak to be verbatim-trustworthy are flagged
    needs_render: true in their _meta.json — the vision batch picks those up as
    page-digitization tasks. Everything else is servable verbatim markdown."""
    import re
    import unicodedata
    import pymupdf
    book = args.book
    if book in PRERENDERED:
        print("%s already has a full page store at %s (pipeline artifacts) — skipping" %
              (book, PRERENDERED[book]))
        return
    pdf = BOOK_PDFS.get(book)
    if not (pdf and pdf.exists()):
        sys.exit("no recovered PDF for book %r" % book)
    pages_dir = WORKDIR / "pages" / book.replace(" ", "_")
    pages_dir.mkdir(parents=True, exist_ok=True)
    doc = pymupdf.open(str(pdf))
    stats = {"pages": len(doc), "verbatim_ok": 0, "needs_render": 0, "blank": 0, "chars": 0}
    for pno in range(len(doc)):
        page = doc[pno]
        n = pno + 1
        raw = unicodedata.normalize("NFKC", (page.get_text("text") or "")).strip()
        words = len(raw.split())
        letters = sum(c.isalpha() for c in raw)
        # verbatim-quality gate: enough words AND mostly real characters
        # (garbled OCR layers produce symbol soup; image-only pages produce nothing)
        garbage = len(re.findall(r"[^\w\s.,;:()\[\]{}+\-*/=<>%'\"?!^_|~&#$@\\]", raw))
        if words < 8:
            verdict = "blank" if not page.get_images() else "needs_render"
        elif letters < 0.35 * max(1, len(raw)) or garbage > 0.15 * max(1, len(raw)):
            verdict = "needs_render"
        else:
            verdict = "verbatim_ok"
        stats[verdict if verdict != "verbatim_ok" else "verbatim_ok"] += 1
        stats["chars"] += len(raw)
        (pages_dir / ("%04d_ocr.md" % n)).write_text(
            "<!-- PAGE %d -->\n<!-- OCR_SOURCE: pymupdf -->\n<!-- VERBATIM: %s -->\n"
            "<!-- LABEL: %s -->\n\n%s\n" % (n, verdict, page.get_label() or n, raw),
            encoding="utf-8")
        (pages_dir / ("%04d_meta.json" % n)).write_text(json.dumps({
            "page_num": n, "page_label": page.get_label() or str(n),
            "word_count": words, "ocr_source": "pymupdf",
            "verbatim": verdict == "verbatim_ok", "needs_render": verdict == "needs_render",
            "has_images": bool(page.get_images()),
            "book": book, "pdf": str(pdf.name),
        }, ensure_ascii=False, indent=1), encoding="utf-8")
    doc.close()
    report = {"book": book, "pdf": pdf.name, **stats}
    (pages_dir / "station1_report.json").write_text(json.dumps(report, indent=1))
    print(json.dumps(report, indent=1))


def build_request(task, model):
    """One batch Request per task: page images + class prompt."""
    from anthropic.types.message_create_params import MessageCreateParamsNonStreaming
    from anthropic.types.messages.batch_create_params import Request
    content = []
    for rel in task["images"]:
        data = base64.standard_b64encode((ROOT / rel).read_bytes()).decode()
        content.append({"type": "image",
                        "source": {"type": "base64", "media_type": "image/png", "data": data}})
    prompt = PROMPTS[task["class"]].format(items=json.dumps(task["items"], ensure_ascii=False, indent=1))
    content.append({"type": "text", "text": prompt})
    return Request(custom_id=task["task_id"][:64],
                   params=MessageCreateParamsNonStreaming(
                       model=model, max_tokens=8000,
                       messages=[{"role": "user", "content": content}]))


def require_client():
    key = load_env_key()
    if not key:
        sys.exit("ANTHROPIC_API_KEY not found in environment or .env — vision-model calls are "
                 "HELD until the owner supplies the key (per 2026-09-02 key policy). "
                 "`inventory` and `build` work without it.")
    import anthropic
    return anthropic.Anthropic(api_key=key)


def cmd_submit(args):
    client = require_client()
    tasks = [json.loads(l) for l in Path(args.tasks).read_text().splitlines() if l.strip()]
    reqs = [build_request(t, args.model) for t in tasks]
    batch = client.messages.batches.create(requests=reqs)
    (WORKDIR / "batches.log").open("a").write("%s\t%s\t%d tasks\n" % (batch.id, args.tasks, len(reqs)))
    print("submitted batch %s (%d requests, model %s)" % (batch.id, len(reqs), args.model))


def cmd_poll(args):
    client = require_client()
    b = client.messages.batches.retrieve(args.batch)
    print(b.processing_status, b.request_counts)


def cmd_collect(args):
    client = require_client()
    out = WORKDIR / "results" / ("%s.jsonl" % args.batch)
    out.parent.mkdir(parents=True, exist_ok=True)
    n = 0
    with out.open("w") as f:
        for result in client.messages.batches.results(args.batch):
            row = {"custom_id": result.custom_id, "type": result.result.type}
            if result.result.type == "succeeded":
                msg = result.result.message
                row["text"] = next((b.text for b in msg.content if b.type == "text"), "")
                row["stop_reason"] = msg.stop_reason
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
            n += 1
    print("wrote %d results -> %s (review these into a patch file; never auto-apply)" % (n, out.relative_to(ROOT)))


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("inventory")
    b = sub.add_parser("build")
    b.add_argument("--book"), b.add_argument("--limit", type=int)
    b.add_argument("--answer-grid", dest="answer_grid", metavar="BOOK:FIRST-LAST")
    b.add_argument("--render-flagged", dest="render_flagged", metavar="BOOK")
    b.add_argument("--convertible", action="store_true",
                   help="target questions the export says vision can make playable")
    s1 = sub.add_parser("station1")
    s1.add_argument("--book", required=True)
    s = sub.add_parser("submit")
    s.add_argument("--tasks", required=True), s.add_argument("--model", default=MODEL_DEFAULT)
    p = sub.add_parser("poll")
    p.add_argument("--batch", required=True)
    c = sub.add_parser("collect")
    c.add_argument("--batch", required=True)
    args = ap.parse_args()
    {"inventory": cmd_inventory, "build": cmd_build, "station1": cmd_station1,
     "submit": cmd_submit, "poll": cmd_poll, "collect": cmd_collect}[args.cmd](args)


if __name__ == "__main__":
    main()
