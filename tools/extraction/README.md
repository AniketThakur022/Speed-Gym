# tools/extraction — recovered extraction tooling (curated copy)

Version-controlled copy of the extraction tooling recovered on 2026-09-02 from
the Drive zip's July-12 `topic_browser_full_package` (the working data itself
stays in `incoming/`, which is gitignored for size). Curated by the
**Speed Gym data extraction** chat; original package README preserved as
[PACKAGE_README.md](PACKAGE_README.md).

## Contents

- `scripts/` — verbatim copy of the recovered pipeline scripts:
  `page_ocr_pipeline.py` (PyMuPDF render → PyMuPDF text → tesseract `eng+equ`
  fallback → per-page `NNNN.png` / `NNNN_ocr.md` / `NNNN_meta.json` +
  `page_manifest.json`), the OCR Docker stack (`Dockerfile.ocr`,
  `docker-compose.ocr.yml`, `deploy_ocr.ps1` — Windows wrapper, superseded on
  macOS by running compose directly or native PyMuPDF), enrichment
  (`enrichment_launcher.py`, `focused_extract.py`, `batch1_enrichment.py`),
  `audit_and_validation/` (multi-LLM jury, SymPy validators),
  `pattern_identification/`, `quant_extraction/text_to_math_extractor/`.
- `dashboards/` — the five verification UIs (`index.html`, `cat.html`,
  `explorer.html`, `page_view.html`, `problem_view.html`) + `docs/`.
  One fix applied vs recovered state: `explorer.html` `BOOK_FILES` first entry
  was missing its `../cat_data/` prefix, silently dropping
  CAT_DI_LR_Arun_Sharma (377 records) — fixed here and in the served copy
  (original kept as `explorer.html.orig.bak` in `incoming/`).
- `rebuild_page_manifest.py` — new utility: restores a book's
  `page_manifest.json` from surviving `pages/*_meta.json` after a partial
  pipeline run clobbers it (`build_manifest()` writes only the current run's
  pages). Already applied to the Sinha book (was 1 page, restored to 305).
- `ontology_registry.yaml` — recovered canonical-alias registry (16 sutras,
  techniques, traps, skills, strategies; Vedic-math scope only) — seed input
  for corpus taxonomy normalization.

## Running the dashboards (macOS)

Dashboards are static HTML fetching `../cat_data/...`, so serve the package
root (dashboards and cat_data must stay siblings):

```bash
python3 -m http.server 8888 --directory "incoming/topic_browser_full_package"
```

Then open `http://localhost:8888/dashboards/index.html` (hub),
`page_view.html` (page OCR verifier), `explorer.html`, `problem_view.html`.
A `topic-browser-dashboards` entry in `.claude/launch.json` does the same.

Verified working 2026-09-02 (all five). Notes:
- Only CAT_DI_LR_Nishit_K_Sinha has page-OCR data (pages 1–305 of 396;
  306–396 — the solutions tail — never OCR'd).
- `page_view.html`'s book dropdown lists only 4 books (Sinha, LSAT, VARC1/2 —
  matches `PDF_MAP` in `page_ocr_pipeline.py`).
- Page-type chips ("answer_key" etc.) come from a keyword heuristic and
  over-fire (Sinha: 140/305 flagged answer_key, incl. the Preface).
- `index.html`/`cat.html` stats are embedded snapshots from 2026-07-08
  (738 records / 3 books), not live.

## OCR pipeline on this machine

Native: `pymupdf` is installed; `pytesseract`/`pdf2image`/`tesseract` are NOT.
`page_ocr_pipeline.py --no-tesseract` works natively (PyMuPDF text layer
only — poor on this scanned corpus, ~0.45–0.55 confidence). For real OCR use
the Docker stack (`docker compose -f scripts/docker-compose.ocr.yml up -d`,
then exec `python scripts/page_ocr_pipeline.py --book <BOOK_ID>`), install
tesseract locally (`brew install tesseract`), or render pages with PyMuPDF
and read them with a vision model. `BASE_DIR` in the script is the relative
`data/extraction_phase3/cat` — run it from a directory laid out like the
package root (or point it at `incoming/topic_browser_full_package/cat_data`).

Known pipeline gotcha: any non-`--resume` partial run overwrites
`page_manifest.json` with just that run's pages — fix with
`rebuild_page_manifest.py`.

## Corpus patch tooling (added 2026-09-02 → 2026-09-05)

Every change to `data/corpus/MASTER_corpus.jsonl` is a patch file under
`data/corpus/patches/`, gated by `verify_patch.py` and applied by
`apply_key_patch.py`. Patches are idempotent and replayable; never edit
MASTER by hand.

```bash
python3 tools/extraction/verify_patch.py data/corpus/patches/<patch>.jsonl && \
python3 tools/extraction/apply_key_patch.py data/corpus/patches/<patch>.jsonl
```

Actions (one JSON row per `(set_id, number)`; `number: "*"` = record level):

| action | writes | overwrites? | required provenance |
|---|---|---|---|
| `key` | `answer_key`, `key_source` | never | `key_source` |
| `correct_key` | replaces `answer_key`; keeps the old one in `extra.key_superseded` | **yes, on purpose** | `key_source`, `why`, `previous_source` |
| `options` | `options`, `extra.options_source` | never (empty list only) | `options_source`, `book`, `pdf_pages` (Gate 2 reference) |
| `options_check` | `extra.options_check` = `confirmed: …` / `disputed: …` | additive | statement |
| `format` | `question_format`, `extra.format_source` | fills `unclassified` only | `format_source` |
| `difficulty` | `difficulty`, `extra.difficulty_source` | never | `difficulty_source` |
| `flag` / `suspect` | `extra.needs_reextraction` / `extra.key_suspect` | additive | `reason` |
| `clear_needs_vision` | `extra.needs_vision=False`, `extra.needs_vision_resolution` | additive | `resolution` |
| `clear_chart_flag` | record `extra.needs_chart_vision=False` | additive | `resolution` |
| `record_tags` | record `extra.tags` | rewrite (Gate 2 checks concept set) | `tags_source` |

Gates: **Gate 1 validity** (targets exist, additive actions never clobber a
different value, provenance present) and **Gate 2 preservation** (rewriting
rows are token-bag-diffed against the source page OCR; the verifier refuses to
certify a rewrite without a reference). `PAGE_STORES` in `verify_patch.py`
maps MASTER book names to page stores (Sinha's lives in `incoming/`).

Twin-number caveat: 12 Sinha records hold two entries under one number; a row
addressed to that number lands on both. The export blocks the whole twin group
(`duplicate_question_number_in_record`), so this is contained, but it is why
applied counts can exceed row counts.

### A method failure worth remembering (2026-09-04)

`sinha_s034x0_q01_25` was keyed from a printed grid 22 pages away because a
fingerprint agreed 4/0 with existing keys while the adjacent grid showed 1/3.
The four agreements were with hint-derived keys that were themselves wrong:
corrupt priors selected the wrong grid and made the right one look wrong.
Nine keys were wrong; corrected by `correct_key` from the page image.
Rule now: fingerprint validation is only as strong as the keys it validates
against, and a large page distance outranks it. Independent vision reads of
the true question pages are the tie-breaker.
