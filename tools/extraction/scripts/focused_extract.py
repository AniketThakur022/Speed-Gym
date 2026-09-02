"""
Focused Chapter-Aware Extractor
================================
Reads chapter_aware_index.json and processes bundles in strict order:
  Phase 1 → End-of-chapter exercises
  Phase 2 → End-of-book tests  
  Phase 3 → In-chapter problems

Each bundle is split into micro-units (≤3000 chars) before hitting llama3.2:3b.
Progress is tracked per-bundle with resume support.
Every record gets: extracted_at, extraction_phase, chapter, question_number.
"""
import re, json, sys, logging, asyncio, aiohttp
from pathlib import Path
from datetime import datetime, timezone

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler("data/extraction_phase3/cat/extraction.log", encoding="utf-8"),
    ]
)
log = logging.getLogger(__name__)

# ── Config ──
BASE_DIR = Path("data/extraction_phase3/cat")
OLLAMA_URL = "http://127.0.0.1:11434/v1/chat/completions"
MODEL = "llama3.2:3b"
MAX_UNIT_CHARS = 3000
TIMEOUT_SECS = 300

TOPIC_MAP = {
    "CAT_DI_LR_Arun_Sharma": "CAT_DI",
    "CAT_DI_LR_Nishit_K_Sinha": "CAT_DI",
    "CAT_LR_LSAT_Logic_Games": "CAT_LR",
    "CAT_VARC_Part1": "CAT_Verbal",
    "CAT_VARC_Part2": "CAT_Verbal",
}

# Explicitly skipped books (scope / data-quality reasons)
SKIP_LIST = {"CAT_DI_LR_Arun_Sharma"}

# ── Micro-unit splitter ──

def split_to_micro_units(text, bundle_name):
    """Split a bundle into micro-units that a 3B model can handle.
    Keeps passage/table context attached to its questions."""
    units = []
    
    # Strategy 1: "Directions for Questions N-M" blocks
    dir_pattern = r'(?:Directions?\s+for\s+Questions?\s*[\d\s\u2013\-to,and]+[:\.]?|Based on the (?:above|following|given) (?:data|table|information|passage|chart|graph))'
    dir_splits = list(re.finditer(dir_pattern, text, re.IGNORECASE))
    
    if dir_splits:
        for i, match in enumerate(dir_splits):
            start = match.start()
            end = dir_splits[i+1].start() if i+1 < len(dir_splits) else len(text)
            chunk = text[start:end].strip()
            if chunk and len(chunk) > 50:
                units.append({"text": chunk[:MAX_UNIT_CHARS], "source_bundle": bundle_name,
                              "unit_idx": len(units), "split_method": "directions"})
        return units if units else None
    
    # Strategy 2: Split by page markers, accumulating context
    pages = re.split(r'<!-- PAGE page_\d+ -->', text)
    context_buffer = ""
    
    for page in pages:
        page = page.strip()
        if not page: continue
        
        q_on_page = re.findall(r'^\s*(\d+)\.\s+\S', page, re.MULTILINE)
        has_table = bool(re.search(r'^\|.*\|$', page, re.MULTILINE))
        has_figure = bool(re.search(r'\[FIGURE:', page))
        
        if (has_table or has_figure) and len(q_on_page) < 2:
            # This is context (table/figure) — buffer it
            context_buffer += "\n" + page
            continue
        
        if q_on_page:
            unit_text = (context_buffer + "\n" + page).strip() if context_buffer else page.strip()
            if len(unit_text) > MAX_UNIT_CHARS:
                # Split further: one unit per ~5 questions
                lines = unit_text.split('\n')
                sub_chunk = ""
                for line in lines:
                    sub_chunk += line + "\n"
                    if len(sub_chunk) > MAX_UNIT_CHARS:
                        units.append({"text": sub_chunk.strip(), "source_bundle": bundle_name,
                                      "unit_idx": len(units), "split_method": "overflow_split"})
                        sub_chunk = context_buffer + "\n" if context_buffer else ""
                if sub_chunk.strip() and len(sub_chunk.strip()) > 50:
                    units.append({"text": sub_chunk.strip(), "source_bundle": bundle_name,
                                  "unit_idx": len(units), "split_method": "overflow_tail"})
            else:
                units.append({"text": unit_text, "source_bundle": bundle_name,
                              "unit_idx": len(units), "split_method": "page_boundary"})
            context_buffer = ""
        elif not has_table and not has_figure:
            # Text-only page with no questions — might be a passage for VARC
            if len(page) > 300:
                context_buffer += "\n" + page
    
    # Flush remaining context
    if context_buffer.strip() and len(context_buffer.strip()) > 100:
        units.append({"text": context_buffer.strip()[:MAX_UNIT_CHARS], "source_bundle": bundle_name,
                      "unit_idx": len(units), "split_method": "trailing_context"})
    
    if not units and len(text.strip()) > 100:
        units.append({"text": text[:MAX_UNIT_CHARS], "source_bundle": bundle_name,
                      "unit_idx": 0, "split_method": "whole_bundle"})
    
    return units


# ── LLM call ──

PROMPT_TEMPLATE = """Extract problems as a JSON array. Each problem:
{{"q":"full question text with number prefix","opts":["(a) ...","(b) ...","(c) ...","(d) ..."],"ans":"b","diff":3}}

Rules:
- Keep EXACT question number prefix like "12. Which..."
- Include ALL answer options verbatim
- diff: 1=easy, 5=hard
- If there is shared passage/table context, put it in "ctx" field
- Return [] if no problems found
- Output ONLY valid JSON array

Content:
---
{content}
---"""


def _safe_diff(val):
    """Safely coerce difficulty value to 1-5 integer."""
    if val is None:
        return 3
    try:
        return max(1, min(5, int(val)))
    except (ValueError, TypeError):
        return 3


def _save_failed_response(text, attempt, reason):
    """Write raw LLM response to .failed_llm/ for post-mortem debugging."""
    dump_dir = Path("data/extraction_phase3/cat/.failed_llm")
    dump_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S_%f")
    fname = dump_dir / f"failed_{reason}_attempt{attempt}_{stamp}.json"
    try:
        fname.write_text(text, encoding='utf-8')
        log.info(f"  Saved failed response to {fname}")
    except Exception as e:
        log.warning(f"  Could not save failed response: {e}")


def _parse_json_flex(text):
    """Try multiple strategies to extract a JSON array from LLM text."""
    if not text or not isinstance(text, str):
        return None
    
    # 1. Clean markdown fences
    cleaned = re.sub(r'^```(?:json)?\s*', '', text, flags=re.IGNORECASE | re.MULTILINE)
    cleaned = re.sub(r'```\s*$', '', cleaned, flags=re.MULTILINE).strip()
    
    # 2. Try to isolate outermost array
    start = cleaned.find('[')
    end = cleaned.rfind(']')
    if start >= 0 and end > start:
        candidate = cleaned[start:end+1]
    else:
        # maybe it's a single object
        start = cleaned.find('{')
        end = cleaned.rfind('}')
        candidate = cleaned[start:end+1] if start >= 0 and end > start else cleaned
    
    # 3. Standard parse
    try:
        return json.loads(candidate)
    except json.JSONDecodeError:
        pass
    
    # 4. Fix common LLM JSON mistakes (trailing commas, missing brackets)
    fixed = re.sub(r',\s*([}\]])', r'\1', candidate)  # remove trailing commas
    fixed = re.sub(r'([{\[]\s*),', r'\1', fixed)       # remove leading commas
    try:
        return json.loads(fixed)
    except json.JSONDecodeError:
        pass
    
    # 5. Try to extract individual objects with regex (flat)
    objects = []
    for obj_match in re.finditer(r'\{[^{}]*\}', candidate):
        try:
            obj = json.loads(obj_match.group())
            objects.append(obj)
        except json.JSONDecodeError:
            continue
    if objects:
        return objects
    
    # 6. Deep extraction for nested objects (single level of nesting)
    for obj_match in re.finditer(r'\{[^{}]*(?:\{[^{}]*\}[^{}]*)*\}', candidate):
        try:
            obj = json.loads(obj_match.group())
            if obj not in objects:
                objects.append(obj)
        except json.JSONDecodeError:
            continue
    if objects:
        return objects
    
    # 7. Fallback: regex-based question extraction from raw text
    questions = _extract_questions_regex(cleaned)
    if questions:
        return questions
    
    return None


def _extract_questions_regex(text):
    """Last resort: extract questions using regex patterns from raw text."""
    if not text:
        return None
    results = []
    # Pattern: number. question text... (a) ... (b) ... (c) ... (d) ...
    pattern = r'(?:^|\n)\s*(\d+)\s*[\.\)]\s*(.*?)\s*(?=\n\s*\d+\s*[\.\)]|\Z)'
    for m in re.finditer(pattern, text, re.DOTALL):
        q_num = m.group(1)
        q_block = m.group(2).strip()
        opts = re.findall(r'\([a-d]\)\s*(.*?)(?=\s*\([a-d]\)\s*|\Z)', q_block, re.DOTALL)
        if opts:
            q_text = re.split(r'\s*\([a]\)\s*', q_block, maxsplit=1)[0].strip()
            results.append({
                "q": f"{q_num}. {q_text}",
                "opts": [f"({chr(97+i)}) {opt.strip()}" for i, opt in enumerate(opts)],
                "ans": "",
                "diff": 3
            })
    return results if results else None


async def call_llm(session, text):
    """Send text to llama3.2:3b and return parsed JSON list.
    
    Implements multiple JSON parsing fallbacks, per-attempt temperature
    increase, and saves unparseable responses for later inspection.
    """
    base_temp = 0.05
    prompt = PROMPT_TEMPLATE.format(content=text[:MAX_UNIT_CHARS])
    
    for attempt in range(3):
        payload = {
            "model": MODEL,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": round(base_temp + (0.05 if attempt == 1 else 0.15 if attempt == 2 else 0), 2),
            "max_tokens": 4096,
        }
        
        try:
            async with session.post(
                OLLAMA_URL, json=payload,
                timeout=aiohttp.ClientTimeout(total=TIMEOUT_SECS, connect=15)
            ) as resp:
                if resp.status == 429:
                    backoff = 2 ** attempt + 5
                    log.warning(f"  HTTP 429 rate limited, backing off {backoff}s")
                    await asyncio.sleep(backoff)
                    continue
                if resp.status != 200:
                    log.warning(f"  HTTP {resp.status}, retry {attempt+1}/3")
                    await asyncio.sleep(2 ** attempt)
                    continue
                
                raw = await resp.text()
                
                try:
                    data = json.loads(raw)
                except json.JSONDecodeError:
                    # Ollama sometimes returns plain text on error
                    data = raw
                
                if not isinstance(data, dict):
                    log.warning(f"  LLM returned non-dict: {type(data)}")
                    _save_failed_response(raw, attempt, "non_dict")
                    continue
                
                content = data.get("choices", [{}])[0].get("message", {}).get("content", "[]")
                
                parsed = _parse_json_flex(content)
                if parsed is not None:
                    return parsed if isinstance(parsed, list) else [parsed] if isinstance(parsed, dict) else []
                
                # All parsing strategies failed — save for debugging
                _save_failed_response(content, attempt, "json_parse")
                log.warning(f"  JSON parse failed, retry {attempt+1}/3")
                await asyncio.sleep(2 ** attempt)
                
        except aiohttp.ClientConnectorError:
            log.error(f"  Cannot connect to Ollama at {OLLAMA_URL}. Is it running?")
            return None
        except asyncio.TimeoutError:
            log.warning(f"  Timeout ({TIMEOUT_SECS}s), retry {attempt+1}/3")
            await asyncio.sleep(5)
        except Exception as e:
            log.warning(f"  Error: {str(e)[:80]}, retry {attempt+1}/3")
            await asyncio.sleep(2 ** attempt)
    
    return None  # all retries exhausted


def to_canonical(raw_q, unit, book, chapter, phase_label):
    """Convert raw LLM output to canonical record with full provenance."""
    if not isinstance(raw_q, dict):
        log.warning(f"  to_canonical called with non-dict: {type(raw_q)}")
        return None
    now = datetime.now(timezone.utc).isoformat()
    topic = TOPIC_MAP.get(book, "CAT_Quant")
    q_text = raw_q.get("q", "")
    q_num = re.match(r'^(\d+)', q_text)
    
    return {
        "summary": q_text,
        "content": q_text,
        "record_type": f"CAT_{'DI' if 'DI' in topic else 'LR' if 'LR' in topic else 'VARC' if 'Verbal' in topic else 'QUANT'}_RECORD",
        "exam_type": "CAT",
        "topic": topic,
        "sub_topic": "General",
        "source_reference": unit["source_bundle"],
        "source_book": book,
        "chapter": chapter,
        "chunk_idx": unit.get("unit_idx", 0),
        "model": MODEL,
        "schema_version": "3.2",
        "status": "extracted",
        "page_type": "exercise",
        "exam_section": "CAT",
        "extraction_phase": phase_label,
        "data_points": {
            "problem_format": "DI" if "DI" in topic else "LR" if "LR" in topic else "RC" if "Verbal" in topic else "PS",
            "options": raw_q.get("opts", []),
            "correct_answer": raw_q.get("ans", ""),
            "difficulty": _safe_diff(raw_q.get("diff")),
            "context": raw_q.get("ctx", ""),
            "question_number": q_num.group(1) if q_num else "0",
            "trap_tags": [],
            "pedagogical_notes": "",
        },
        "tags": [],
        "raw_formulas": [],
        "entities": [],
        "diagram_ids": [],
        "table_ids": [],
        "logic_steps": [],
        "_bundle_source": unit["source_bundle"],
        "_unit_idx": unit["unit_idx"],
        "_split_method": unit["split_method"],
        "extracted_at": now,
    }


# ── Progress tracker ──

class ProgressTracker:
    def __init__(self, book_name):
        self.book = book_name
        self.file = BASE_DIR / book_name / "extraction_progress.json"
        self.data = {"completed": [], "failed": [], "stats": {}, "started_at": None}
        if self.file.exists():
            try: self.data = json.loads(self.file.read_text(encoding='utf-8'))
            except: pass
        if not self.data.get("started_at"):
            self.data["started_at"] = datetime.now(timezone.utc).isoformat()
    
    def is_done(self, bundle_name):
        return bundle_name in self.data["completed"]
    
    def mark_done(self, bundle_name, records_count):
        self.data["completed"].append(bundle_name)
        self.data["stats"][bundle_name] = {
            "records": records_count,
            "completed_at": datetime.now(timezone.utc).isoformat()
        }
        self._save()
    
    def mark_failed(self, bundle_name, reason):
        self.data["failed"].append({"bundle": bundle_name, "reason": reason,
                                     "at": datetime.now(timezone.utc).isoformat()})
        self._save()
    
    def _save(self):
        with open(self.file, 'w', encoding='utf-8') as f:
            json.dump(self.data, f, indent=2, ensure_ascii=False)


# ── Main extraction loop ──

async def extract_book(book_name, queue):
    """Process all bundles in the extraction queue for one book."""
    bundles_dir = BASE_DIR / book_name / "bundles"
    records_file = BASE_DIR / book_name / "records.jsonl"
    tracker = ProgressTracker(book_name)
    
    # Filter already-completed from progress tracker
    remaining = [b for b in queue if not tracker.is_done(b["name"])]
    
    if not remaining:
        log.info(f"  All bundles already extracted for {book_name}!")
        return 0
    
    log.info(f"  {len(remaining)} bundles remaining (skipped {len(queue)-len(remaining)} already done)")
    
    total_records = 0
    async with aiohttp.ClientSession() as session:
        current_phase = 0
        for bi, bundle_info in enumerate(remaining):
            # Phase banner
            if bundle_info["extraction_phase"] != current_phase:
                current_phase = bundle_info["extraction_phase"]
                phase_names = {1: "END-OF-CHAPTER EXERCISES", 2: "END-OF-BOOK TESTS", 3: "IN-CHAPTER PROBLEMS"}
                log.info(f"\n  --- PHASE {current_phase}: {phase_names.get(current_phase, '?')} ---")
            
            bf = bundles_dir / f"{bundle_info['name']}.md"
            if not bf.exists():
                log.warning(f"  Bundle file missing: {bf}")
                tracker.mark_failed(bundle_info["name"], "file_missing")
                continue
            
            text = bf.read_text(encoding='utf-8')
            units = split_to_micro_units(text, bundle_info["name"])
            
            chapter = bundle_info.get("chapter", "Unknown")
            phase_label = bundle_info.get("phase_label", "unknown")
            
            log.info(f"  [{bi+1}/{len(remaining)}] {bundle_info['name']} | {chapter[:40]} | "
                     f"{len(units)} units | ~{bundle_info.get('question_count',0)}Q expected")
            
            bundle_records = []
            unit_failures = 0
            
            for ui, unit in enumerate(units):
                # Pre-check: skip units with no questions/options to save GPU time
                q_matches = re.findall(r'^\s*\d+\.\s+\S', unit["text"], re.MULTILINE)
                has_options = bool(re.search(r'\([a-d]\)\s', unit["text"], re.IGNORECASE))
                if not q_matches and not has_options:
                    log.info(f"    Unit {ui+1}/{len(units)}: Skipping context-only unit (no questions/options detected)")
                    continue
                
                result = await call_llm(session, unit["text"])
                
                if result is None:
                    unit_failures += 1
                    log.warning(f"    Unit {ui+1}/{len(units)} FAILED")
                    continue
                
                for raw_q in result:
                    if not isinstance(raw_q, dict):
                        log.warning(f"    Skipping non-dict item from LLM output: {str(raw_q)[:100]}")
                        continue
                    if raw_q.get("q", "").strip():
                        record = to_canonical(raw_q, unit, book_name, chapter, phase_label)
                        if record:
                            bundle_records.append(record)
                
                # Cooling pause
                await asyncio.sleep(1)
            
            # Append to JSONL
            if bundle_records:
                with open(records_file, "a", encoding="utf-8") as f:
                    for r in bundle_records:
                        f.write(json.dumps(r, ensure_ascii=False) + "\n")
                total_records += len(bundle_records)
                log.info(f"    >> {len(bundle_records)} records | Failures: {unit_failures} | "
                         f"Running total: {total_records}")
            else:
                log.warning(f"    >> 0 records (all {len(units)} units produced nothing)")
            
            tracker.mark_done(bundle_info["name"], len(bundle_records))
            
            # Inter-bundle pause
            await asyncio.sleep(2)
    
    return total_records


async def main():
    index_file = BASE_DIR / "chapter_aware_index.json"
    if not index_file.exists():
        log.error("Run build_chapter_index.py first!")
        sys.exit(1)
    
    with open(index_file, 'r', encoding='utf-8') as f:
        full_index = json.load(f)
    
    # Allow filtering by book name via CLI; respect SKIP_LIST
    books = [b for b in full_index.keys() if b not in SKIP_LIST]
    if len(sys.argv) > 1:
        books = [b for b in books if sys.argv[1] in b]
    
    log.info("=" * 60)
    log.info("CHAPTER-AWARE FOCUSED EXTRACTION")
    log.info(f"Model: {MODEL} | Max unit: {MAX_UNIT_CHARS} chars")
    log.info(f"Books: {len(books)} | Started: {datetime.now(timezone.utc).isoformat()}")
    log.info("=" * 60)
    
    grand_total = 0
    for book in books:
        queue = full_index[book]["extraction_queue"]
        log.info(f"\n{'='*60}")
        log.info(f"BOOK: {book}")
        log.info(f"Queue: {len(queue)} bundles")
        log.info(f"{'='*60}")
        
        count = await extract_book(book, queue)
        grand_total += count
        log.info(f"Finished {book}: {count} new records")
    
    log.info(f"\n{'='*60}")
    log.info(f"ALL DONE: {grand_total} total new records")
    log.info(f"{'='*60}")


if __name__ == "__main__":
    asyncio.run(main())
