#!/usr/bin/env python3
"""macOS-native complement to page_ocr_pipeline.py (no tesseract required).

Renders a page range of a PDF to the pipeline's exact per-page artifact
contract — pages/NNNN.png (300 DPI), pages/NNNN_ocr.md, pages/NNNN_meta.json —
using PyMuPDF only. OCR text comes from the PDF's text layer (ocr_source
"pymupdf"); on scanned books that layer is weak, so downstream consumers
should treat low-confidence pages as image-first and read the PNG with a
vision model. Does NOT touch page_manifest.json — run rebuild_page_manifest.py
afterwards.

Usage:
    python3 render_pages_native.py <pdf> <book_dir> <first> <last>
"""

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import pymupdf


def classify(page, text: str) -> dict:
    """Mirror page_ocr_pipeline.classify_page heuristics."""
    t = text.lower()
    images = page.get_images()
    drawings = page.get_drawings()
    result = {
        "has_images": len(images) > 0,
        "has_drawings": len(drawings) > 0,
        "has_table": "table" in t or "column" in t or "|" in t,
        "has_math": any(s in t for s in ["=", "+", "-", "×", "÷", "√", "∑", "∫", "π"]),
        "word_count": len(t.split()),
        "has_diagram": len(images) > 0 and len(drawings) > 0,
    }
    if len(t.strip()) < 50:
        result["page_type"] = "blank"
    elif any(k in t for k in ["answer", "solution", "key", "explanation"]):
        result["page_type"] = "answer_key"
    elif any(k in t for k in ["exercise", "practice", "problem", "question"]):
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


def main(pdf_path: str, book_dir: str, first: int, last: int, dpi: int = 300):
    doc = pymupdf.open(pdf_path)
    pages_dir = Path(book_dir) / "pages"
    pages_dir.mkdir(parents=True, exist_ok=True)
    done = 0
    for pno in range(first - 1, min(last, len(doc))):
        page = doc[pno]
        n = pno + 1
        png = pages_dir / f"{n:04d}.png"
        pix = page.get_pixmap(matrix=pymupdf.Matrix(dpi / 72, dpi / 72), alpha=False)
        pix.save(str(png))

        raw = (page.get_text("text") or "").strip()
        words = len(raw.split())
        conf = min(1.0, (words / max(1, len(raw))) * 3) if raw else 0.0
        label = page.get_label() or str(n)

        (pages_dir / f"{n:04d}_ocr.md").write_text(
            f"<!-- PAGE {n} -->\n<!-- OCR_SOURCE: pymupdf -->\n"
            f"<!-- OCR_CONFIDENCE: {conf:.2f} -->\n<!-- PYMUFPDF_CONF: {conf:.2f} -->\n"
            f"<!-- TESSERACT_CONF: 0.00 -->\n<!-- LABEL: {label} -->\n\n{raw}\n",
            encoding="utf-8",
        )
        cls = classify(page, raw)
        meta = {
            "page_num": n,
            "page_label": label,
            "image_path": f"{Path(book_dir).name}/pages/{n:04d}.png",
            "ocr_path": f"{Path(book_dir).name}/pages/{n:04d}_ocr.md",
            "dimensions": {"width": int(page.rect.width), "height": int(page.rect.height)},
            "word_count": cls["word_count"],
            "ocr_confidence": round(conf, 3),
            "ocr_source": "pymupdf",
            "pymupdf_confidence": round(conf, 3),
            "tesseract_confidence": 0.0,
            "has_images": cls["has_images"],
            "has_drawings": cls["has_drawings"],
            "has_table": cls["has_table"],
            "has_math": cls["has_math"],
            "has_diagram": cls["has_diagram"],
            "page_type": cls["page_type"],
            "processed_at": datetime.now(timezone.utc).isoformat(),
        }
        (pages_dir / f"{n:04d}_meta.json").write_text(
            json.dumps(meta, indent=2, ensure_ascii=False), encoding="utf-8"
        )
        done += 1
        if done % 20 == 0:
            print(f"  rendered through page {n}", flush=True)
    print(f"rendered {done} pages ({first}-{min(last, len(doc))}) of {pdf_path} -> {pages_dir}")


if __name__ == "__main__":
    if len(sys.argv) < 5:
        raise SystemExit(__doc__)
    main(sys.argv[1], sys.argv[2], int(sys.argv[3]), int(sys.argv[4]))
