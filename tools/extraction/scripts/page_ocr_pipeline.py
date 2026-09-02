#!/usr/bin/env python3
"""
Page-by-Page OCR Pipeline
=========================
Processes a CAT book PDF page-by-page:
  1. Render each page to PNG at configurable DPI
  2. Extract text via PyMuPDF (fast, layout-aware)
  3. Fall back to Tesseract OCR for image-heavy pages
  4. Output per-page: .png, .md, .json
  5. Create page_manifest.json for the UI

Usage:
    python -X utf8 scripts/page_ocr_pipeline.py --book CAT_DI_LR_Nishit_K_Sinha
    python -X utf8 scripts/page_ocr_pipeline.py --book CAT_DI_LR_Nishit_K_Sinha --pages 1-50
    python -X utf8 scripts/page_ocr_pipeline.py --book CAT_DI_LR_Nishit_K_Sinha --resume

Docker:
    docker compose -f docker-compose.ocr.yml exec ocr python scripts/page_ocr_pipeline.py --book CAT_DI_LR_Nishit_K_Sinha
"""

import argparse
import json
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import fitz  # PyMuPDF
import pytesseract
from pdf2image import convert_from_path
from PIL import Image

# ── Config ──
BASE_DIR = Path("data/extraction_phase3/cat")
OCR_DPI = int(Path(__file__).parent.parent.joinpath(".ocr_dpi").read_text().strip() if Path(__file__).parent.parent.joinpath(".ocr_dpi").exists() else 300)
TESSERACT_LANG = "eng+equ"  # English + math equations

# Book ID → Raw PDF filename mapping
# (Add your PDFs here. The script searches the project root for these.)
PDF_MAP = {
    "CAT_DI_LR_Nishit_K_Sinha": {
        "candidates": [
            "logical-reasoning-and-data-interpretation-for-cat-by-nishit-k-si-027ec9cbb8b72.pdf",
            "Nishit_K_Sinha_DI.pdf",
        ],
        "subject": "DI",
    },
    "CAT_LR_LSAT_Logic_Games": {
        "candidates": [
            "_OceanofPDF.com_Logic_Games__LSAT_Strategy_Guide_4th_Edit_-_Manhattan_Prep.pdf",
            "LSAT_Logic_Games.pdf",
        ],
        "subject": "LR",
    },
    "CAT_VARC_Part1": {
        "candidates": [
            "VARC Arun sharma_part_1_250.pdf",
            "VARC_Part1.pdf",
        ],
        "subject": "Verbal",
    },
    "CAT_VARC_Part2": {
        "candidates": [
            "VARC Arun sharma_part_2_251_430.pdf",
            "VARC Arun sharma_part_251_430.pdf",
            "VARC_Part2.pdf",
        ],
        "subject": "Verbal",
    },
}

# Search paths for PDFs (project root and common subdirs)
PDF_SEARCH_PATHS = [
    Path("."),
    Path("./pdfs"),
    Path("./raw"),
    Path("../"),
    Path("Phase 3 - CAT Pillar")
]


def log(msg: str):
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{ts}] {msg}", flush=True)


def find_pdf(book_id: str) -> Path:
    """Find the raw PDF for a given book ID."""
    candidates = PDF_MAP.get(book_id, {}).get("candidates", [])
    for search_dir in PDF_SEARCH_PATHS:
        for candidate in candidates:
            p = search_dir / candidate
            if p.exists():
                log(f"Found PDF: {p.resolve()}")
                return p.resolve()
    # Try wildcard search
    for search_dir in PDF_SEARCH_PATHS:
        for pdf in search_dir.glob("*.pdf"):
            if book_id.lower().replace("_", " ") in pdf.name.lower().replace("_", " "):
                log(f"Found PDF (wildcard): {pdf.resolve()}")
                return pdf.resolve()
    raise FileNotFoundError(
        f"Could not find PDF for {book_id}. Searched for: {candidates}. "
        f"Place the PDF in the project root or update PDF_MAP in this script."
    )


def ensure_dirs(book_id: str) -> Path:
    """Create the output directory structure for a book."""
    book_dir = BASE_DIR / book_id
    pages_dir = book_dir / "pages"
    pages_dir.mkdir(parents=True, exist_ok=True)
    return book_dir


def render_page_to_png(doc: fitz.Document, page_num: int, book_id: str, dpi: int = 300) -> Path:
    """Render a single PDF page to PNG."""
    page = doc[page_num]
    # Use matrix for high-DPI rendering
    mat = fitz.Matrix(dpi / 72, dpi / 72)
    pix = page.get_pixmap(matrix=mat, alpha=False)
    png_path = BASE_DIR / book_id / "pages" / f"{page_num + 1:04d}.png"
    pix.save(str(png_path))
    return png_path


def extract_text_pymupdf(page: fitz.Page) -> Tuple[str, float]:
    """Extract text using PyMuPDF. Returns (text, confidence_estimate)."""
    raw_text = page.get_text("text")
    # Heuristic confidence: word count / total characters ratio
    if not raw_text:
        return "", 0.0
    words = len(raw_text.split())
    chars = len(raw_text)
    confidence = min(1.0, (words / max(1, chars)) * 3)  # heuristic: ~0.33 words/char = good
    return raw_text.strip(), confidence


def extract_text_tesseract(pil_image: Image.Image) -> Tuple[str, float]:
    """Extract text using Tesseract OCR. Returns (text, confidence)."""
    try:
        # Run Tesseract with confidence data
        data = pytesseract.image_to_data(
            pil_image,
            lang=TESSERACT_LANG,
            output_type=pytesseract.Output.DICT,
        )
        text_parts = []
        total_conf = 0
        word_count = 0
        for i, word in enumerate(data["text"]):
            if word.strip():
                text_parts.append(word)
                conf = int(data["conf"][i]) if data["conf"][i] != "-1" else 0
                total_conf += conf
                word_count += 1
        text = " ".join(text_parts)
        avg_conf = (total_conf / max(1, word_count)) / 100 if word_count > 0 else 0.0
        return text, avg_conf
    except Exception as e:
        log(f"Tesseract error: {e}")
        return "", 0.0


def extract_text_markdown(page: fitz.Page) -> str:
    """Extract text preserving markdown-like structure (headings, bold, etc.)."""
    # Try to get structured text with formatting
    blocks = page.get_text("blocks")
    md_parts = []
    for block in blocks:
        if len(block) >= 7:
            x0, y0, x1, y1, text, block_no, block_type = block[:7]
            if text.strip():
                # Heuristic: large text blocks might be headings
                if y1 - y0 > 20:  # tall block = heading
                    md_parts.append(f"\n## {text.strip()}\n")
                else:
                    md_parts.append(text.strip())
    return "\n\n".join(md_parts)


def classify_page(page: fitz.Page, pymupdf_text: str, tesseract_text: str) -> Dict:
    """Classify page type based on content heuristics."""
    text = (pymupdf_text or tesseract_text).lower()
    images = page.get_images()
    drawings = page.get_drawings()
    
    result = {
        "has_images": len(images) > 0,
        "has_drawings": len(drawings) > 0,
        "has_table": "table" in text or "column" in text or "|" in text,
        "has_math": any(sym in text for sym in ["=", "+", "-", "×", "÷", "√", "∑", "∫", "π"]),
        "word_count": len(text.split()),
        "has_diagram": len(images) > 0 and len(drawings) > 0,
    }
    
    # Page type heuristic
    if len(text.strip()) < 50:
        result["page_type"] = "blank"
    elif any(kw in text for kw in ["answer", "solution", "key", "explanation"]):
        result["page_type"] = "answer_key"
    elif any(kw in text for kw in ["exercise", "practice", "problem", "question"]):
        result["page_type"] = "problem_dense"
    elif result["has_images"] or result["has_drawings"]:
        result["page_type"] = "diagram"
    elif result["word_count"] > 100 and not result["has_table"]:
        result["page_type"] = "instructional"
    elif result["has_table"]:
        result["page_type"] = "table"
    else:
        result["page_type"] = "mixed"
    
    return result


def process_page(
    doc: fitz.Document,
    page_num: int,
    book_id: str,
    use_tesseract: bool = True,
    dpi: int = 300,
) -> Dict:
    """Process a single page: render + OCR + classify."""
    page = doc[page_num]
    page_label = page.get_label() or str(page_num + 1)
    
    log(f"Processing page {page_num + 1} / {len(doc)} (label: {page_label})")
    
    # 1. Render to PNG
    png_path = render_page_to_png(doc, page_num, book_id, dpi=dpi)
    
    # 2. PyMuPDF text extraction (fast, layout-aware)
    pymupdf_text, pymupdf_conf = extract_text_pymupdf(page)
    pymupdf_md = extract_text_markdown(page)
    
    # 3. Tesseract OCR (fallback for image-heavy pages)
    tesseract_text = ""
    tesseract_conf = 0.0
    if use_tesseract and (pymupdf_conf < 0.6 or len(page.get_images()) > 0):
        log(f"  → Running Tesseract (PyMuPDF confidence: {pymupdf_conf:.2f})")
        pil_img = Image.open(png_path)
        tesseract_text, tesseract_conf = extract_text_tesseract(pil_img)
    
    # 4. Choose best text
    if tesseract_conf > pymupdf_conf:
        best_text = tesseract_text
        best_conf = tesseract_conf
        ocr_source = "tesseract"
    else:
        best_text = pymupdf_text
        best_conf = pymupdf_conf
        ocr_source = "pymupdf"
    
    # 5. Save OCR markdown
    ocr_md = f"""<!-- PAGE {page_num + 1} -->
<!-- OCR_SOURCE: {ocr_source} -->
<!-- OCR_CONFIDENCE: {best_conf:.2f} -->
<!-- PYMUFPDF_CONF: {pymupdf_conf:.2f} -->
<!-- TESSERACT_CONF: {tesseract_conf:.2f} -->
<!-- LABEL: {page_label} -->

{pymupdf_md if pymupdf_md else best_text}

---

## Raw OCR Text

{best_text}
"""
    ocr_path = BASE_DIR / book_id / "pages" / f"{page_num + 1:04d}_ocr.md"
    ocr_path.write_text(ocr_md, encoding="utf-8")
    
    # 6. Classify page
    classification = classify_page(page, pymupdf_text, tesseract_text)
    
    # 7. Metadata
    meta = {
        "page_num": page_num + 1,
        "page_label": page_label,
        "image_path": str(png_path.relative_to(BASE_DIR)),
        "ocr_path": str(ocr_path.relative_to(BASE_DIR)),
        "dimensions": {
            "width": int(page.rect.width),
            "height": int(page.rect.height),
        },
        "word_count": classification["word_count"],
        "ocr_confidence": round(best_conf, 3),
        "ocr_source": ocr_source,
        "pymupdf_confidence": round(pymupdf_conf, 3),
        "tesseract_confidence": round(tesseract_conf, 3),
        "has_images": classification["has_images"],
        "has_drawings": classification["has_drawings"],
        "has_table": classification["has_table"],
        "has_math": classification["has_math"],
        "has_diagram": classification["has_diagram"],
        "page_type": classification["page_type"],
        "processed_at": datetime.now(timezone.utc).isoformat(),
    }
    
    meta_path = BASE_DIR / book_id / "pages" / f"{page_num + 1:04d}_meta.json"
    meta_path.write_text(json.dumps(meta, indent=2, ensure_ascii=False), encoding="utf-8")
    
    log(f"  → Saved: {png_path.name}, {ocr_path.name}, {meta_path.name} (type: {classification['page_type']}, words: {classification['word_count']}, conf: {best_conf:.2f})")
    
    return meta


def build_manifest(book_id: str, page_metas: List[Dict]) -> Path:
    """Create the master page_manifest.json for a book."""
    manifest = {
        "book_id": book_id,
        "subject": PDF_MAP.get(book_id, {}).get("subject", "Unknown"),
        "total_pages": len(page_metas),
        "processed_at": datetime.now(timezone.utc).isoformat(),
        "pages": page_metas,
        "stats": {
            "by_type": {},
            "by_confidence": {
                "high": 0,    # > 0.8
                "medium": 0,  # 0.5 - 0.8
                "low": 0,     # < 0.5
            },
            "total_words": sum(p["word_count"] for p in page_metas),
            "has_images": sum(1 for p in page_metas if p["has_images"]),
            "has_tables": sum(1 for p in page_metas if p["has_table"]),
        },
    }
    
    # Build type stats
    for p in page_metas:
        t = p["page_type"]
        manifest["stats"]["by_type"][t] = manifest["stats"]["by_type"].get(t, 0) + 1
        
        c = p["ocr_confidence"]
        if c > 0.8:
            manifest["stats"]["by_confidence"]["high"] += 1
        elif c > 0.5:
            manifest["stats"]["by_confidence"]["medium"] += 1
        else:
            manifest["stats"]["by_confidence"]["low"] += 1
    
    manifest_path = BASE_DIR / book_id / "page_manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")
    log(f"Manifest saved: {manifest_path}")
    return manifest_path


def load_progress(book_id: str) -> set:
    """Load which pages have already been processed."""
    pages_dir = BASE_DIR / book_id / "pages"
    if not pages_dir.exists():
        return set()
    done = set()
    for f in pages_dir.glob("*_meta.json"):
        try:
            m = json.loads(f.read_text())
            done.add(m["page_num"])
        except:
            pass
    return done


def main():
    parser = argparse.ArgumentParser(description="Page-by-page OCR pipeline for CAT books")
    parser.add_argument("--book", required=True, help="Book ID (e.g., CAT_DI_LR_Nishit_K_Sinha)")
    parser.add_argument("--pages", default="all", help="Page range, e.g., '1-50' or 'all'")
    parser.add_argument("--dpi", type=int, default=OCR_DPI, help="Rendering DPI (default: 300)")
    parser.add_argument("--no-tesseract", action="store_true", help="Skip Tesseract, use PyMuPDF only")
    parser.add_argument("--resume", action="store_true", help="Skip already-processed pages")
    args = parser.parse_args()
    
    book_id = args.book
    if book_id not in PDF_MAP:
        log(f"WARNING: {book_id} not in PDF_MAP. Will try wildcard search.")
    
    # Find PDF
    pdf_path = find_pdf(book_id)
    
    # Ensure dirs
    book_dir = ensure_dirs(book_id)
    
    # Open PDF
    doc = fitz.open(str(pdf_path))
    total_pages = len(doc)
    log(f"Book: {book_id}")
    log(f"PDF: {pdf_path}")
    log(f"Total pages: {total_pages}")
    
    # Determine page range
    if args.pages == "all":
        start, end = 0, total_pages
    else:
        m = re.match(r"(\d+)-(\d+)", args.pages)
        if m:
            start, end = int(m.group(1)) - 1, int(m.group(2))
        else:
            start, end = 0, total_pages
    start = max(0, start)
    end = min(total_pages, end)
    
    # Load progress for resume
    done_pages = load_progress(book_id) if args.resume else set()
    if done_pages:
        log(f"Resuming: {len(done_pages)} pages already processed")
    
    # Process pages
    page_metas = []
    for i in range(start, end):
        if i + 1 in done_pages:
            log(f"Page {i + 1}: already done, skipping")
            # Load existing meta
            meta_path = book_dir / "pages" / f"{i + 1:04d}_meta.json"
            if meta_path.exists():
                page_metas.append(json.loads(meta_path.read_text()))
            continue
        
        try:
            meta = process_page(doc, i, book_id, use_tesseract=not args.no_tesseract, dpi=args.dpi)
            page_metas.append(meta)
        except Exception as e:
            log(f"ERROR on page {i + 1}: {e}")
            # Continue with other pages
        
        # Brief pause to avoid thermal throttling on laptops
        time.sleep(0.1)
    
    doc.close()
    
    # Build manifest
    manifest_path = build_manifest(book_id, page_metas)
    
    log("=" * 50)
    log(f"Done! Processed {len(page_metas)} pages.")
    log(f"Manifest: {manifest_path}")
    log(f"Output dir: {book_dir / 'pages'}")
    log("=" * 50)


if __name__ == "__main__":
    main()
