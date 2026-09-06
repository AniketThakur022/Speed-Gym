#!/usr/bin/env python3
"""Build CANDIDATE mock-exam pool files from the flattened question export.

Contract (services/api/app/mocks/sources.py, StaticPoolSource):
    [{question_id, kind, text, options?, correct_answer, skill?, difficulty?}]
A tag's file is loaded only if question_id, text and kind are all non-empty,
and the section then keeps items whose `kind` is in ITS OWN `kinds` tuple —
so the same question is `tita` in a CAT pool and `numeric` in a GMAT/GRE one.

These are written to data/mocks/pools/candidates/ and are NOT bound. Binding
is the owner's serving-path decision; wiring is then a rename into the parent
directory.

THE ANSWER IS THE HIGH-CONSEQUENCE FIELD. For `mcq` the engine compares the
learner's answer to `correct_answer`, and separately maps option letters by
INDEX (chr(ord('a') + i)). So a pool is only safe if the emitted letter is the
index of the correct option in the emitted list. This builder therefore
resolves every key to an index, re-emits options with their printed tags
stripped, and DROPS any question whose key cannot be resolved to exactly one
option — an unresolvable key silently marks correct learners wrong.

Usage:
    python3 build_mock_pools.py [--out data/mocks/pools/candidates]
"""

from __future__ import annotations

import argparse
import collections
import json
import re
import unicodedata
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
EXPORT = ROOT / "data/exports/vmsg_questions_v1.jsonl"
MASTER = ROOT / "data/corpus/MASTER_corpus.jsonl"

# ---------------------------------------------------------------- key parsing
BARE_LETTER = re.compile(r"^\(?([a-eA-E])\)?[.:]?$")
CHOICE_PREFIX = re.compile(r"^\s*choices?\s+([a-fA-F])\b", re.I)
ALTERNATIVE = re.compile(r"^\s*alternative\s+([1-9])\b", re.I)
LETTER_TAG = re.compile(r"^\s*\(?([a-fA-F])\)[.)]?\s+|^\s*([a-fA-F])[.)]\s+")
NUMBER_TAG = re.compile(r"^\s*\(?([1-9])\)[.)]?\s+|^\s*([1-9])[.)]\s+")
MULTI_ANSWER = re.compile(r";|\band\b|,\s*\w+\s*,", re.I)
NUMERIC = re.compile(r"^[-−+]?\d[\d,]*(?:\.\d+)?$")


def render_table(t: dict) -> str:
    """A printed data table as text. Faithful: the learner reads the same
    numbers the book prints, in the same shape — no task change, unlike
    describing a chart in words."""
    cols = [str(c) for c in (t.get("columns") or [])]
    rows = [[str(c) for c in r] for r in (t.get("rows") or [])]
    if not rows:
        return ""
    out = [" | ".join(cols)] if cols else []
    out += [" | ".join(r) for r in rows]
    return "\n".join(out)


def norm(s) -> str:
    s = unicodedata.normalize("NFKC", str(s or ""))
    return " ".join(s.lower().split()).strip(" .")


def strip_tag(opt: str) -> str:
    """Remove a printed option tag: '(a) 17' / 'a. 17' / '1) 17' -> '17'."""
    s = LETTER_TAG.sub("", str(opt))
    if s == str(opt):
        s = NUMBER_TAG.sub("", str(opt))
    return s.strip()


def tag_sequence(options: list) -> str | None:
    """'letter' if the printed tags run a,b,c…; 'number' if 1,2,3…; else None.

    Only a clean sequence proves index == letter, which is what the engine
    assumes. A broken or partial sequence means we cannot trust position.
    """
    lets, nums = [], []
    for o in options:
        m = LETTER_TAG.match(str(o))
        lets.append(m.group(1) or m.group(2) if m else None)
        m2 = NUMBER_TAG.match(str(o))
        nums.append(m2.group(1) or m2.group(2) if m2 else None)
    if all(lets) and [c.lower() for c in lets] == [chr(97 + i) for i in range(len(options))]:
        return "letter"
    if all(nums) and [int(c) for c in nums] == list(range(1, len(options) + 1)):
        return "number"
    return None


def degenerate_options(options: list) -> str | None:
    """Why this option list cannot be put in front of a learner, or None.

    The export's `playable` verdict tests that an option list EXISTS, not that
    it is coherent. Extraction damage leaves lists like ['Point','Point',
    'Point','Point'] or ['', '', '', '', 'What will come in place of'] — every
    one of which is unanswerable even though the key resolves cleanly.
    """
    vals = [norm(strip_tag(o)) for o in options]
    if any(not v for v in vals):
        return "an option is empty"
    if len(set(vals)) != len(vals):
        return "two options are identical"
    # A single-character option is legitimate — Sinha's ordering puzzles answer
    # with a person's initial ('U','W','Y','Z'). Punctuation with no
    # alphanumeric content at all (',', '&') is extraction debris.
    if any(not any(ch.isalnum() for ch in v) for v in vals):
        return "an option is punctuation debris, not an answer"
    return None


def resolve_index(key: str, options: list) -> tuple[int | None, str]:
    """Resolve an answer key to exactly one option index. Returns (index, how)."""
    k = str(key or "").strip()
    if not k or len(options) < 2:
        return None, "no key or too few options"
    seq = tag_sequence(options)
    bare = [norm(strip_tag(o)) for o in options]

    m = BARE_LETTER.match(k)
    if m:
        i = ord(m.group(1).lower()) - 97
        return (i, "bare letter") if i < len(options) else (None, "letter beyond option count")
    m = CHOICE_PREFIX.match(k)
    if m:
        i = ord(m.group(1).lower()) - 97
        return (i, "Choice X prefix") if i < len(options) else (None, "letter beyond option count")
    m = ALTERNATIVE.match(k)
    if m:
        i = int(m.group(1)) - 1
        return (i, "Alternative N") if i < len(options) else (None, "alternative beyond option count")

    nk = norm(strip_tag(k))
    hits = [i for i, b in enumerate(bare) if b and b == nk]
    if len(hits) == 1:
        return hits[0], "matches option text"
    if len(hits) > 1:
        return None, "key text matches more than one option"

    # A bare ordinal against number-tagged options ('2' with '1) 2', '2) 3') is
    # genuinely ambiguous — the ordinal and an option's VALUE collide. Refuse.
    if seq == "number" and NUMERIC.match(k):
        return None, "ambiguous ordinal vs value (number-tagged options)"
    if MULTI_ANSWER.search(k) and len(nk) > 3:
        return None, "key names more than one answer (multi-select mis-typed)"
    return None, "unresolvable key"


# ---------------------------------------------------------- section membership
# A bare "Verbal" token must match: Manhattan 5 lb names its chapters "Verbal
# Diagnostic Test" and "Verbal Practice Section 1: Easy", which an earlier
# topic-only version of this regex missed — putting 37 vocabulary and reading
# questions into the QUANT pool and simultaneously keeping them out of the
# verbal one. One regex gates both directions, so the bug was double-ended.
VERBAL_CHAPTERS = re.compile(
    r"\bverbal\b|reading comprehension|text completion|sentence equivalence|"
    r"logic-based reading|mixed practice|critical reasoning|sentence structure|"
    r"assumption family|evidence family|structure-based family|the foundation", re.I)

# Chapters no exam in scope tests. GRE and GMAT quant exclude trigonometry and
# calculus outright and CAT tests neither, so a learner meeting one concludes
# they have a preparation gap that does not exist.
OUT_OF_SYLLABUS = re.compile(
    r"differentiation|integration|trigonometr|trigonometric waveform|exponential function|"
    r"multinomial theorem|theory of equations|scales of notation|surds and imaginary|"
    r"theory of numbers|harmonical progression|determinants|continued fractions|"
    r"convergency|summation of series", re.I)

# An item that names a figure but carries no rendered table cannot be answered:
# the chart's values are not in the text, only a paraphrase of them.
CHART_IN_TEXT = re.compile(
    r"following (graph|chart|figure|diagram)|bar (graph|chart)|pie chart|line graph|"
    r"figure \d|the graph (above|below)|study the (graph|chart|figure)", re.I)

# A reading-comprehension stem needs its passage. These stems are meaningless
# without one, and the ETS sets lost their passages in extraction.
RC_STEM = re.compile(r"\bthe passage\b|\bthe author\b|primarily concerned|"
                     r"according to the passage", re.I)

# A stimulus cut off before its constraint list ends on a function word. The
# rules needed to solve the puzzle are simply absent.
TRUNCATED_TAIL = re.compile(
    r"\b(from|in|the|of|and|to|a|an|with|by|not|necessarily|are|is|that|for|on|as|"
    r"who|which|were|was|be|been|but|or|if|than|then|into|при)\s*$", re.I)

# Each rule states WHY a source belongs in a section, because a wrong binding
# puts another exam's questions into a learner's mock.
POOL_RULES = {
    "cat_dilr": {
        "why": "CAT Data Interpretation & Logical Reasoning. Sinha and Arun Sharma DI/LR "
               "are CAT DI/LR books written for this exact section; Manhattan Logic Games "
               "is LSAT analytical reasoning, the same ordering/grouping puzzle form CAT "
               "LR uses.",
        "books": {"Sinha", "Arun Sharma", "Manhattan Logic Games"},
        "kinds": {"multiple_choice": "mcq", "quantitative_comparison": None,
                  "numeric_entry": "tita"},
    },
    "cat_varc": {
        "why": "UNSERVABLE — see the manifest. No CAT verbal source is inside the 25-book "
               "corpus scope; GRE/GMAT verbal is a different exam and is deliberately NOT "
               "substituted.",
        "books": set(),
        "kinds": {},
    },
    "gmat_verbal": {
        "why": "GMAT Verbal Reasoning. Manhattan GMAT Verbal is a GMAT verbal book "
               "(critical reasoning + sentence correction chapters).",
        "books": {"Manhattan GMAT Verbal"},
        "kinds": {"multiple_choice": "mcq"},
        # GMAT Focus dropped Sentence Correction from Verbal Reasoning, and this
        # book's Chapter 3 items are also 2-option practice variants that say so
        # in their own text.
        "deny_chapter": re.compile(r"chapter 3\b|sentence structure", re.I),
    },
    "gmat_di": {
        "why": "GMAT Data Insights — APPROXIMATE, review before binding. Data Insights "
               "(data sufficiency, two-part analysis, multi-source reasoning) has no direct "
               "source in this corpus. These are Sinha/Arun Sharma items built on a printed "
               "DATA TABLE, which is the table-analysis form of Data Insights and the only "
               "part of the section this corpus can honestly serve; neither book carries "
               "chapter metadata, so the table is the signal, not a chapter name.",
        "books": {"Sinha", "Arun Sharma"},
        # mcq only: there is no free-numeric response anywhere on the GMAT, so
        # serving numeric_entry items here would train a format the exam
        # does not contain.
        "kinds": {"multiple_choice": "mcq"},
        "require_data_table": True,
    },
    "gre_verbal": {
        "why": "GRE Verbal Reasoning. ETS GRE Verbal is the official verbal guide; ETS GRE "
               "and Manhattan 5 lb contribute only their verbal chapters (RC / Text "
               "Completion / Sentence Equivalence), never their quant ones.",
        "books": {"ETS GRE Verbal", "ETS GRE", "Manhattan 5 lb"},
        "kinds": {"multiple_choice": "mcq"},
        "require_verbal_chapter": True,
    },
    "quant": {
        "why": "Quantitative pool — an ALTERNATIVE binding only. This tag is currently "
               "served by GraphSource (the Vedic graph); this file is the 25-book corpus "
               "candidate for the same tag, for the serving-path decision. NOTE: source_for() "
               "hardcodes tag=='quant' to GraphSource, so dropping this file into the pools "
               "directory does NOTHING until that branch changes — unlike every other tag, "
               "binding it is a code change, not a file move.",
        # Bird is deliberately absent. "Basic Engineering Mathematics" is not an
        # exam-prep source, and worse, its notation does not survive OCR:
        # 1.3 cubed is served as "Evaluate 1.33" but keyed 2.197, so a learner
        # who reads the stem correctly is marked WRONG. That is worse than an
        # unanswerable question.
        "books": {"Arun Sharma Quant", "Manhattan Quant", "Manhattan 5 lb", "Tyra",
                  "Hall & Knight", "Bhatia", "Hogg", "Schaum", "Thakur",
                  "Vedic Secrets"},
        "kinds": {"multiple_choice": "mcq", "numeric_entry": "numeric",
                  "quantitative_comparison": None},
        "exclude_verbal_chapter": True,
    },
}


def build():
    rows = [json.loads(l) for l in EXPORT.open()]
    pools = collections.defaultdict(list)
    drops = collections.defaultdict(collections.Counter)
    seen = collections.defaultdict(set)

    for q in rows:
        if not q.get("playable"):
            continue
        # The coordinator's constraint, enforced explicitly rather than relied
        # upon: twin-numbered rows go into NO pool.
        if q.get("duplicate_number_in_record"):
            drops["*"]["twin/duplicate row (excluded by contract)"] += 1
            continue
        chk = q.get("options_check") or ""
        book, fmt, chapter = q["book"], q["question_format"], q.get("chapter") or ""

        # A set's stimulus is mixed: mostly prose strings (servable as text),
        # some structured tables (renderable as text without changing the
        # task — the learner reads the same numbers the book prints), and some
        # CHARTS, which the pool contract cannot carry and which nobody can
        # answer from words. Keep the first two, refuse the third.
        stim, chart, had_table = [], None, False
        for s_ in q.get("stimulus") or []:
            if isinstance(s_, str):
                if s_.strip():
                    stim.append(s_.strip())
            elif isinstance(s_, dict):
                k_ = s_.get("kind")
                if k_ == "table":
                    rendered = render_table(s_)
                    if rendered:
                        stim.append(rendered)
                        had_table = True
                elif k_ == "other":
                    d_ = (s_.get("description") or "").strip()
                    if d_:
                        stim.append(d_)
                    else:
                        chart = s_.get("diagram_type") or "other"
                elif k_:
                    chart = k_

        for tag, rule in POOL_RULES.items():
            if book not in rule["books"]:
                continue
            kind = rule["kinds"].get(fmt)
            if not kind:
                drops[tag]["format %s not served by this section" % fmt] += 1
                continue
            if rule.get("require_verbal_chapter") and book != "ETS GRE Verbal" \
                    and not VERBAL_CHAPTERS.search(chapter):
                drops[tag]["not a verbal chapter (%s)" % (chapter or "none")[:34]] += 1
                continue
            if rule.get("exclude_verbal_chapter") and VERBAL_CHAPTERS.search(chapter):
                drops[tag]["verbal chapter excluded from a quant pool"] += 1
                continue
            # These two books carry NO chapter metadata, so DI cannot be
            # separated from LR by chapter. A printed data table is the
            # reliable signal that an item is data interpretation.
            if rule.get("require_data_table") and not had_table:
                drops[tag]["not data interpretation (no data table in the stimulus)"] += 1
                continue
            if chk.startswith("disputed"):
                drops[tag]["option list disputed by an independent read"] += 1
                continue
            if rule.get("deny_chapter") and rule["deny_chapter"].search(chapter):
                drops[tag]["chapter is not on the current exam"] += 1
                continue
            if tag == "quant" and OUT_OF_SYLLABUS.search(chapter):
                drops[tag]["out of syllabus for every exam in scope"] += 1
                continue

            text = (q.get("text") or "").strip()
            item = {"question_id": q["question_id"], "kind": kind, "text": text}

            if kind == "mcq":
                opts = q.get("options") or []
                idx, how = resolve_index(q.get("answer_key"), opts)
                if idx is None:
                    drops[tag]["answer unresolvable: %s" % how] += 1
                    continue
                # Every exam in scope uses 4- or 5-option MCQs. Fewer means a
                # guessing baseline the scaled scoring never assumed.
                if len(opts) < 4:
                    drops[tag]["fewer than 4 options"] += 1
                    continue
                why_bad = degenerate_options(opts)
                if why_bad:
                    drops[tag]["unusable option list: %s" % why_bad] += 1
                    continue
                if tag_sequence(opts) is None and len(opts) > 1:
                    # No clean printed sequence: index==letter is unproven.
                    if not all(LETTER_TAG.match(str(o)) is None for o in opts):
                        drops[tag]["option tags not a clean sequence"] += 1
                        continue
                item["options"] = [strip_tag(o) for o in opts]
                item["correct_answer"] = chr(97 + idx)
            else:
                key = (q.get("answer_key") or "").strip()
                val = key.strip("$").replace(",", "")
                if not NUMERIC.match(val):
                    drops[tag]["numeric answer not a bare number"] += 1
                    continue
                item["correct_answer"] = val

            if chart:
                drops[tag]["needs a figure (%s); pool contract has no figure field" % chart] += 1
                continue
            # Context a learner needs to answer at all: DI/RC sets carry their
            # directions and passage on the RECORD, not on the question.
            ctx = "\n\n".join(x for x in ([q.get("directions"), q.get("passage")] + stim)
                               if isinstance(x, str) and x.strip()).strip()
            if ctx:
                item["text"] = (ctx + "\n\n" + text).strip()
            body = item["text"]
            if len(body) < 12:
                drops[tag]["text too short after assembly"] += 1
                continue
            # The stimulus-kind guard above catches a chart that arrived as a
            # structured object. It does NOT catch one that was OCR'd into a
            # prose string or paraphrased into an "other" description — those
            # reach here naming a figure whose numbers are nowhere in the text.
            if CHART_IN_TEXT.search(body) and "|" not in body:
                drops[tag]["names a figure whose data is not in the text"] += 1
                continue
            # A reading-comprehension stem with no passage attached. 800 chars
            # is well below any real GRE passage, so this only catches orphans.
            if RC_STEM.search(body) and len(body) < 800:
                drops[tag]["reading-comprehension stem with no passage"] += 1
                continue
            if TRUNCATED_TAIL.search(body):
                drops[tag]["stimulus truncated before its constraints end"] += 1
                continue
            if "printed on PDF page" in body:
                drops[tag]["passage replaced by a page pointer"] += 1
                continue
            # A set whose pages JUMP is a mis-merge: sinha_s030x8_q05_08 cites
            # [228, 248, 249] and its four questions come from three unrelated
            # puzzles, none matching its stimulus.
            pp = sorted(set(q.get("pdf_pages") or []))
            if len(pp) > 1 and max(b - a for a, b in zip(pp, pp[1:])) > 3:
                drops[tag]["set pages jump — questions may be from another exercise"] += 1
                continue

            # Not in the contract, but harmless (the engine passes items through
            # untouched) and necessary if StaticPoolSource ever grows a
            # set-aware fetch — 1,426 of cat_dilr's 1,447 items belong to
            # multi-question sets that must be served together to be sane.
            item["set_id"] = q["set_id"]
            sk = (q.get("taxonomy") or {}).get("skill_key")
            if sk:
                item["skill"] = sk
            if q.get("difficulty") is not None:
                item["difficulty"] = float(q["difficulty"])
            item["_source"] = {"book": book, "chapter": q.get("chapter"),
                               "set_id": q["set_id"], "pdf_pages": q.get("pdf_pages"),
                               "answer_key_raw": q.get("answer_key"),
                               "answer_resolved_by": how if kind == "mcq" else "numeric key",
                               "answer_provenance": q.get("answer_provenance")}
            if item["question_id"] in seen[tag]:
                drops[tag]["duplicate question_id within pool"] += 1
                continue
            seen[tag].add(item["question_id"])
            pools[tag].append(item)

    # GRE AWA: essay prompts are essay_prompt records, not question_sets, so
    # they never reach the question export — read them from MASTER.
    #
    # Only "Analyze an Issue" belongs in a GRE mock. The shorter GRE (Sept 2023+)
    # this blueprint models RETIRED the Argument task, so serving an Argument
    # prompt would have a learner practise a task the exam no longer sets. Those
    # prompts are still good writing practice, so they go to a clearly-named
    # separate file rather than being thrown away.
    awa, retired, seen_awa = [], [], set()
    for line in MASTER.open():
        r = json.loads(line)
        if r.get("content_type") != "essay_prompt":
            continue
        text = (r.get("text") or "").strip()
        if len(text) < 20:
            drops["gre_awa"]["prompt too short"] += 1
            continue
        ex = r.get("extra") or {}
        task = (ex.get("task_type") or "").strip()
        # The instruction IS the task: the bare claim does not tell the writer
        # what to argue, so a prompt without it is not answerable.
        instruction = (ex.get("instruction_family") or "").strip()
        full = (text + ("\n\n" + instruction if instruction else "")).strip()
        item = {"question_id": r["set_id"], "kind": "essay", "text": full,
                "correct_answer": None,
                "_source": {"book": r.get("book"), "task_type": task or None,
                            "has_instruction": bool(instruction),
                            "source_url": ex.get("source_url")}}
        if task == "Analyze an Issue":
            key = norm(text)
            if key in seen_awa:
                drops["gre_awa"]["duplicate prompt text"] += 1
            else:
                seen_awa.add(key)
                awa.append(item)
        elif task == "Analyze an Argument":
            retired.append(item)
            drops["gre_awa"]["Analyze an Argument — retired from the GRE in 2023"] += 1
        else:
            drops["gre_awa"]["no task_type — cannot confirm it is an Issue task"] += 1
    pools["gre_awa"] = awa
    pools["_gre_awa_argument_retired"] = retired
    return pools, drops


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="data/mocks/pools/candidates")
    args = ap.parse_args()
    out = ROOT / args.out
    out.mkdir(parents=True, exist_ok=True)

    pools, drops = build()
    manifest = {
        "generated_from": "data/exports/vmsg_questions_v1.jsonl",
        "status": "CANDIDATE — not bound. Binding is the owner's serving-path decision; "
                  "wiring is a move into the parent directory (data/mocks/pools/).",
        "contract": "[{question_id, kind, text, options?, correct_answer, skill?, difficulty?}] "
                    "— services/api/app/mocks/sources.py::StaticPoolSource",
        "answer_convention": "mcq correct_answer is the lowercase option LETTER, and the "
                             "emitted options are re-indexed so letter == position, which is "
                             "what the engine assumes (chr(ord('a') + i)). Printed tags are "
                             "stripped so the client does not render '(a)' twice. tita/numeric "
                             "correct_answer is a bare number.",
        "excluded_always": ["rows the export marks not playable", "twin/duplicate-numbered rows",
                            "rows whose option list an independent read disputed",
                            "any question whose answer key cannot be resolved to exactly one option"],
        "skill_note": "`skill` is the corpus taxonomy skill_key and is used by scoring.py "
                      "ONLY to group a finished mock's per-skill accuracy breakdown. It is not a "
                      "BKT join — bkt_joinable is what mastery gates on, and only about half of "
                      "the resolved rows are graph-backed. GraphSource emits graph :Skill names "
                      "for the same field, so the two vocabularies can appear in one result.",
        "difficulty_note": "difficulty is present on ~17% of rows; the engine's easy/hard ramp "
                           "treats a missing value as easy (1), so the curve is weak until the "
                           "difficulty backfill widens.",
        "pools": {},
    }
    retired = pools.get("_gre_awa_argument_retired") or []
    if retired:
        (out / "gre_awa_argument_retired.json").write_text(json.dumps(
            [{k: v for k, v in it.items() if not k.startswith("_")} for it in retired],
            ensure_ascii=False, indent=1))

    for tag, rule in list(POOL_RULES.items()) + [("gre_awa", {
            "why": "GRE Analytical Writing — official-pool prompts RESTRICTED to \"Analyze an "
                   "Issue\". The shorter GRE (Sept 2023+) this blueprint models retired the "
                   "Argument task, so those prompts go to gre_awa_argument_retired.json "
                   "instead of being served. Each prompt carries its instruction line, "
                   "without which the bare claim does not state the task. The section is "
                   "auto_scored=False: recorded for review, never machine-scored."})]:
        items = pools.get(tag, [])
        clean = [{k: v for k, v in it.items() if not k.startswith("_")} for it in items]
        (out / ("%s.json" % tag)).write_text(json.dumps(clean, ensure_ascii=False, indent=1))
        (out / ("%s.provenance.json" % tag)).write_text(json.dumps(
            [{"question_id": it["question_id"], **it["_source"]} for it in items if "_source" in it],
            ensure_ascii=False, indent=1))
        manifest["pools"][tag] = {
            "count": len(clean), "why": rule.get("why", ""),
            "kinds": sorted({i["kind"] for i in clean}),
            "books": sorted({it["_source"]["book"] for it in items if "_source" in it}),
            "dropped": dict(collections.Counter(drops[tag]).most_common(12)),
        }
    manifest["excluded_twin_rows"] = drops["*"]["twin/duplicate row (excluded by contract)"]
    (out / "MANIFEST.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=1))

    print("wrote %d candidate pools -> %s" % (len(manifest["pools"]), out))
    for tag, m in manifest["pools"].items():
        print("  %-13s %5d  kinds=%-18s books=%s" % (tag, m["count"], ",".join(m["kinds"]) or "-",
                                                     ", ".join(m["books"]) or "-"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
