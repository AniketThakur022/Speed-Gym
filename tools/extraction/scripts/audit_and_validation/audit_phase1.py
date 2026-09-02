import json, os, re
from collections import Counter

base = "/workspace/Phase 1 - Speed Gym"
files = [
    "Vedic_Mathematics__Tirthaji_.jsonl",
    "Vedic_Mathematics_Secrets.jsonl",
    "Vedic_Mathematics_Made_Easy__Dhaval_Bhatia_.jsonl",
    "The_Number_Sense___How_the_Mind_Creates_Mathematics__Revised.jsonl",
    "The_Essentials_of_Vedic_Mathematics__Rajesh_Thakur_.jsonl",
    "Bird___Basic_Engineering_Mathematics__5th_Edition_.jsonl",
    "Ayres__Schmidt___Schaum_s_Outline_of_College_Mathematics__3r.jsonl",
]

def is_missing(val):
    return val is None

def is_empty(val):
    if val is None:
        return True
    if isinstance(val, (list, dict, str)):
        return len(val) == 0
    return False

placeholder_patterns = [
    re.compile(r"placeholder", re.I),
    re.compile(r"blank[_\s]?page", re.I),
    re.compile(r"intentionally left blank", re.I),
    re.compile(r"empty_page", re.I),
    re.compile(r"no content", re.I),
    re.compile(r"incomplete", re.I),
    re.compile(r"no specific information", re.I),
    re.compile(r"too brief to summarize", re.I),
    re.compile(r"start of knowledge source", re.I),
    re.compile(r"waiting for input", re.I),
]

def is_placeholder(record):
    # Check status field
    status = record.get("status")
    if isinstance(status, str):
        low = status.lower()
        if low in {"empty_page", "incomplete", "blank_page", "intentionally_blank", "placeholder"}:
            return True
    # Check summary and content text for placeholders
    summary = record.get("summary", "")
    raw_text = record.get("raw_text", "")
    recovery = record.get("recovery_status", "")
    content = record.get("content", "")
    for text in [summary, raw_text, recovery, str(content)]:
        for pat in placeholder_patterns:
            if pat.search(text):
                return True
    return False

media_keywords = re.compile(r"\b(image|chart|diagram|table|figure)\b", re.I)

def mentions_media(record):
    for field in ["summary", "topic", "sub_topic"]:
        val = record.get(field, "")
        if isinstance(val, str) and media_keywords.search(val):
            return True
    return False

results = {}
for fname in files:
    fpath = os.path.join(base, fname)
    total = 0
    stats = {
        "raw_formulas_present": 0, "raw_formulas_missing": 0,
        "data_points_present": 0, "data_points_missing": 0,
        "source_reference_present": 0, "source_reference_missing": 0,
        "entities_present_nonempty": 0, "entities_empty": 0,
        "logic_steps_present_nonempty": 0, "logic_steps_empty": 0,
        "placeholder_records": 0,
        "media_mentions": 0,
    }
    first_five = []
    if not os.path.exists(fpath):
        results[fname] = {"error": "file not found"}
        continue
    with open(fpath, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except Exception as e:
                continue
            total += 1

            # field presence/empty
            rf = rec.get("raw_formulas")
            if is_missing(rf):
                stats["raw_formulas_missing"] += 1
            else:
                stats["raw_formulas_present"] += 1

            dp = rec.get("data_points")
            if is_missing(dp):
                stats["data_points_missing"] += 1
            else:
                stats["data_points_present"] += 1

            sr = rec.get("source_reference")
            if is_missing(sr):
                stats["source_reference_missing"] += 1
            else:
                stats["source_reference_present"] += 1

            ent = rec.get("entities")
            if is_empty(ent):
                stats["entities_empty"] += 1
            else:
                stats["entities_present_nonempty"] += 1

            ls = rec.get("logic_steps")
            if is_empty(ls):
                stats["logic_steps_empty"] += 1
            else:
                stats["logic_steps_present_nonempty"] += 1

            if is_placeholder(rec):
                stats["placeholder_records"] += 1

            if mentions_media(rec):
                stats["media_mentions"] += 1

            if total <= 5:
                first_five.append(rec)

    results[fname] = {
        "total_records": total,
        "stats": stats,
        "first_five": first_five,
    }

# Print structured report
print("=" * 80)
print("PHASE 1 - SPEED GYM JSONL AUDIT REPORT")
print("=" * 80)
for fname in files:
    r = results[fname]
    print(f"\n{'─' * 80}")
    print(f"FILE: {fname}")
    print(f"{'─' * 80}")
    if "error" in r:
        print(f"  ERROR: {r['error']}")
        continue
    total = r["total_records"]
    s = r["stats"]
    print(f"  Total records: {total}")
    print(f"\n  1. FIELD PRESENCE / EMPTY ANALYSIS")
    print(f"     raw_formulas    : present={s['raw_formulas_present']} | missing={s['raw_formulas_missing']}")
    print(f"     data_points     : present={s['data_points_present']} | missing={s['data_points_missing']}")
    print(f"     source_reference: present={s['source_reference_present']} | missing={s['source_reference_missing']}")
    print(f"     entities        : present & non-empty={s['entities_present_nonempty']} | empty/missing={s['entities_empty']}")
    print(f"     logic_steps     : present & non-empty={s['logic_steps_present_nonempty']} | empty/missing={s['logic_steps_empty']}")

    print(f"\n  2. MEDIA MENTIONS (image/chart/diagram/table/figure in summary/topic/sub_topic)")
    print(f"     Count: {s['media_mentions']} ({s['media_mentions']/max(total,1)*100:.1f}%)")

    print(f"\n  3. PLACEHOLDER / EMPTY CONTENT RECORDS")
    print(f"     Count: {s['placeholder_records']} ({s['placeholder_records']/max(total,1)*100:.1f}%)")

# First 5 records completeness deep dive for Tirthaji
print(f"\n{'=' * 80}")
print("4. FIRST 5 RECORDS OF Vedic_Mathematics__Tirthaji_.jsonl — COMPLETENESS CHECK")
print(f"{'=' * 80}")
tirthaji = results["Vedic_Mathematics__Tirthaji_.jsonl"]
for i, rec in enumerate(tirthaji["first_five"], 1):
    print(f"\n  Record {i} (chunk_idx={rec.get('chunk_idx', 'N/A')})")
    # Determine if placeholder
    placeholder = is_placeholder(rec)
    print(f"    Is placeholder/empty: {placeholder}")
    # List keys
    keys = sorted(rec.keys())
    print(f"    Keys present ({len(keys)}): {keys}")
    # Check critical fields
    for field in ["summary", "topic", "record_type", "entities", "logic_steps", "data_points", "raw_formulas", "source_reference"]:
        val = rec.get(field)
        if is_missing(val):
            status = "MISSING"
        elif is_empty(val):
            status = "EMPTY"
        else:
            status = "OK"
        print(f"    {field:20s}: {status}")

print("\n" + "=" * 80)
print("AUDIT COMPLETE")
print("=" * 80)
