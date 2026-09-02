#!/usr/bin/env python3
"""
Quant Option Filler — Quant Arun Sharma
========================================
Fills missing `options` for Quant_Arun TITA (Type In The Answer) records.

Two strategies:
  1. Regex: Extract options from bundle markdown if MCQ options exist but were missed
  2. Generate: For TITA questions with worked solutions, compute the answer and
     generate plausible distractors to create (a)-(e) MCQ options.

Usage:
    python3 scripts/quant_option_filler.py --dry-run --limit 20 --verbose
    python3 scripts/quant_option_filler.py
"""
import argparse
import json
import logging
import random
import re
from pathlib import Path
from typing import Any, Dict, List, Optional

logging.basicConfig(level=logging.INFO, format='%(asctime)s [OPTFILL] %(levelname)s %(message)s')
logger = logging.getLogger(__name__)

BOOK_DIR = Path('/workspace/data/extraction_phase3/cat/CAT_Quant_Arun_Sharma')
BUNDLES_DIR = BOOK_DIR / 'bundles'
INPUT_FILE = BOOK_DIR / 'records_rematched.jsonl'
OUTPUT_FILE = BOOK_DIR / 'records_with_options.jsonl'

# Regex patterns
ANSWER_KEY_RE = re.compile(r'(\d+)\s*[.)]\s*\(([a-e])\)', re.MULTILINE)
SOLUTION_RE = re.compile(r'(?:Solution|Solutions|Ans\.?|Answer)\s*[:=]?\s*(.+?)(?=\n\s*\d+[.)]\s|\n#|\n\*\*Problem|\Z)', re.DOTALL | re.IGNORECASE)
QUESTION_NUM_RE = re.compile(r'^\s*(\d+)\s*[.)]\s')
OPTION_RE = re.compile(r'\(([a-e])\)\s*(.+?)(?=\s*\([a-e]\)|\s*\n\s*\n|\s*$)', re.DOTALL)
NUMERIC_ANS_RE = re.compile(r'[=:]?\s*(?:Answer|Ans)\s*[:=]?\s*₹?\$?\s*(\d+(?:\.\d+)?)', re.IGNORECASE)


def load_records(path: Path) -> List[Dict]:
    records = []
    with open(path, encoding='utf-8') as f:
        for line in f:
            if line.strip():
                records.append(json.loads(line))
    return records


def save_records(records: List[Dict], path: Path):
    with open(path, 'w', encoding='utf-8') as f:
        for r in records:
            f.write(json.dumps(r, ensure_ascii=False) + '\n')


def load_bundle(bundle_source: str, cache: Dict[str, str]) -> str:
    """Load bundle markdown, cached."""
    if bundle_source in cache:
        return cache[bundle_source]
    path = BUNDLES_DIR / f'{bundle_source}.md'
    if not path.exists():
        cache[bundle_source] = ''
        return ''
    md = path.read_text(encoding='utf-8')
    cache[bundle_source] = md
    return md


def extract_answer_key(bundle_md: str) -> Dict[int, str]:
    """Extract answer key: {question_num: letter}."""
    result = {}
    for m in ANSWER_KEY_RE.finditer(bundle_md):
        qnum = int(m.group(1))
        letter = m.group(2)
        if qnum not in result:
            result[qnum] = letter
    return result


def find_solution_for_question(bundle_md: str, qnum: int) -> Optional[str]:
    """Find the worked solution text following a numbered question."""
    # Find the question in the markdown
    pattern = re.compile(rf'(?:^|\n)\s*{qnum}\s*[.)]\s+.+?(?=\n\s*\d+\s*[.)]\s|\n#|\Z)', re.DOTALL)
    m = pattern.search(bundle_md)
    if not m:
        return None
    # Look for solution text after the question
    after_q = bundle_md[m.end():m.end()+2000]
    # Try to find "Solution:" or "Ans:" pattern
    sol_match = SOLUTION_RE.search(after_q)
    if sol_match:
        sol_text = sol_match.group(1).strip()[:500]
        return sol_text
    # Try to find a numerical answer
    num_match = NUMERIC_ANS_RE.search(after_q[:500])
    if num_match:
        return f'Answer: {num_match.group(1)}'
    return None


def extract_correct_value_from_solution(solution_text: str) -> Optional[str]:
    """Extract the final numeric/string answer from a worked solution."""
    # Try "Answer: X" or "Ans: X" pattern
    m = NUMERIC_ANS_RE.search(solution_text)
    if m:
        return m.group(1)
    # Try last number in solution
    nums = re.findall(r'(\d+(?:\.\d+)?)', solution_text)
    if nums:
        return nums[-1]
    return None


def generate_distractors(correct_value: str, correct_letter: str) -> List[Dict[str, str]]:
    """Generate plausible distractors for a numeric answer."""
    try:
        val = float(correct_value)
    except (ValueError, TypeError):
        # Non-numeric answer — can't generate distractors
        return []

    distractors = []
    used = {val}
    # Strategy: 10% off, 20% off, sign flip (for negatives), double, half
    deltas = [val * 0.1, val * 0.2, val * -0.1, val * 0.5, val * 2.0, 10.0, 100.0]
    random.seed(42)  # Deterministic
    for delta in deltas:
        d = round(val + delta, 2) if abs(val) > 1 else round(val + delta, 4)
        if d not in used and d != val:
            used.add(d)
            distractors.append(d)
            if len(distractors) >= 4:
                break

    # If not enough, add simple offsets
    while len(distractors) < 4:
        d = round(val + len(distractors) + 1, 2)
        if d not in used:
            used.add(d)
            distractors.append(d)
        else:
            used.add(d)

    # Build options with correct answer at correct_letter
    letters = ['a', 'b', 'c', 'd', 'e']
    correct_idx = letters.index(correct_letter) if correct_letter in letters else 0
    options = []
    d_idx = 0
    for i, letter in enumerate(letters):
        if i == correct_idx:
            options.append({'letter': letter, 'text': str(int(val) if val == int(val) else val)})
        else:
            if d_idx < len(distractors):
                d = distractors[d_idx]
                options.append({'letter': letter, 'text': str(int(d) if d == int(d) else d)})
                d_idx += 1
            else:
                options.append({'letter': letter, 'text': str(int(val) if val == int(val) else val)})

    return options[:5]  # Cap at 5 options


def try_regex_options(record: Dict, bundle_md: str, answer_key: Dict[int, str]) -> Optional[List[Dict]]:
    """Strategy 1: Try to find MCQ options in the bundle that were missed."""
    summary = record.get('summary', '')
    # Get question number from summary
    qnum_match = QUESTION_NUM_RE.match(summary)
    if not qnum_match:
        return None
    qnum = int(qnum_match.group(1))

    # Find the question in the bundle and check for options
    pattern = re.compile(rf'(?:^|\n)\s*{qnum}\s*[.)]\s+(.+?)(?=\n\s*\d+\s*[.)]\s|\n#|\Z)', re.DOTALL)
    m = pattern.search(bundle_md)
    if not m:
        return None

    qtext = m.group(1).strip()
    # Try to extract options from the question text
    opts = []
    for opt_match in OPTION_RE.finditer(qtext):
        opts.append({'letter': opt_match.group(1), 'text': opt_match.group(2).strip()})

    if len(opts) >= 2:
        return opts
    return None


def try_generate_options(record: Dict, bundle_md: str, answer_key: Dict[int, str]) -> Optional[List[Dict]]:
    """Strategy 2: Generate options from worked solution + answer key."""
    summary = record.get('summary', '')
    correct_answer = (record.get('correct_answer') or '').strip().lower()
    if not correct_answer or correct_answer not in 'abcde':
        return None

    # Get question number
    qnum_match = QUESTION_NUM_RE.match(summary)
    qnum = int(qnum_match.group(1)) if qnum_match else None

    # Verify against answer key if available
    if qnum and qnum in answer_key:
        if answer_key[qnum].lower() != correct_answer:
            # Answer key disagrees — skip this record
            return None

    # Find solution text
    if qnum:
        solution = find_solution_for_question(bundle_md, qnum)
    else:
        solution = None

    if not solution:
        # No solution found — can't generate options
        return None

    # Extract correct value from solution
    correct_value = extract_correct_value_from_solution(solution)
    if not correct_value:
        return None

    # Generate distractors
    options = generate_distractors(correct_value, correct_answer)
    if options:
        return options

    return None


def process_record(
    record: Dict,
    bundle_cache: Dict[str, str],
    answer_key_cache: Dict[str, Dict[int, str]],
    stats: Dict
) -> Dict:
    """Process one record: fill options if missing."""
    if record.get('options') and len(record.get('options', [])) > 0:
        stats['already_has'] += 1
        return {}

    bundle_source = record.get('source_reference') or record.get('_bundle_source') or ''
    if not bundle_source:
        stats['no_source'] += 1
        return {}

    bundle_md = load_bundle(bundle_source, bundle_cache)
    if not bundle_md:
        stats['no_bundle'] += 1
        return {}

    if bundle_source not in answer_key_cache:
        answer_key_cache[bundle_source] = extract_answer_key(bundle_md)
    answer_key = answer_key_cache[bundle_source]

    # Strategy 1: Regex
    options = try_regex_options(record, bundle_md, answer_key)
    if options:
        stats['regex_filled'] += 1
        return {'options': options, '_options_source': 'regex_bundle'}

    # Strategy 2: Generate from solution
    options = try_generate_options(record, bundle_md, answer_key)
    if options:
        stats['generated_filled'] += 1
        return {'options': options, '_options_source': 'generated_from_solution'}

    stats['still_missing'] += 1
    return {'_options_source': 'failed'}


def main():
    parser = argparse.ArgumentParser(description='Quant Option Filler — Arun Sharma')
    parser.add_argument('--dry-run', action='store_true', help='Preview without writing')
    parser.add_argument('--limit', type=int, default=0, help='Process N records only')
    parser.add_argument('--verbose', action='store_true', help='Verbose output')
    args = parser.parse_args()

    logger.info(f'Loading records from {INPUT_FILE}')
    records = load_records(INPUT_FILE)
    logger.info(f'Loaded {len(records)} records')

    missing_opts = sum(1 for r in records if not r.get('options') or r.get('options') == [])
    has_opts = sum(1 for r in records if r.get('options') and len(r.get('options', [])) > 0)
    logger.info(f'Missing options: {missing_opts}, Has options: {has_opts}')

    if args.limit:
        records = records[:args.limit]
        logger.info(f'Limited to {len(records)} records')

    bundle_cache: Dict[str, str] = {}
    answer_key_cache: Dict[str, Dict[int, str]] = {}
    stats = {
        'already_has': 0,
        'regex_filled': 0,
        'generated_filled': 0,
        'still_missing': 0,
        'no_source': 0,
        'no_bundle': 0,
    }

    for i, r in enumerate(records):
        result = process_record(r, bundle_cache, answer_key_cache, stats)
        for k, v in result.items():
            r[k] = v
        if args.verbose:
            src = result.get('_options_source', 'kept')
            if src != 'kept':
                logger.info(f'[{i+1}] {src}: {r.get("summary","")[:60]}')

    logger.info(f'Processing complete: {stats}')

    if not args.dry_run:
        save_records(records, OUTPUT_FILE)
        logger.info(f'Output written to {OUTPUT_FILE}')

    total_with_opts = sum(1 for r in records if r.get('options') and len(r.get('options', [])) > 0)
    logger.info(f'Final: {total_with_opts}/{len(records)} have options ({100*total_with_opts/max(len(records),1):.1f}%)')


if __name__ == '__main__':
    main()