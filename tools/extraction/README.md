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
