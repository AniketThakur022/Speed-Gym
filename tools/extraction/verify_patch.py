#!/usr/bin/env python3
"""Two-gate verifier for corpus patches. Run BEFORE apply_key_patch.py.

Norm adopted 2026-09-03 (from RAG's bank v1.2 postmortem): a validity gate
proves output is WELL-FORMED, never that it still SAYS THE SAME THING. Their
KaTeX render gate passed 99.66% while missing all three bugs the rewrite
introduced (currency $ shredded, \\neq collapsed to "eq" by an over-broad
regex, dropped connectives turning alternatives into a simultaneous system);
a token-bag diff caught every one. So every content-rewriting pass runs both:

  GATE 1  validity     — patch rows well-formed; targets exist; additive
                         actions never silently overwrite existing values.
  GATE 2  preservation — for any row that REWRITES text, the tokens must be
                         accounted for. For vision-derived text the reference
                         is the source page's OCR (data/vision_pass/pages/...):
                         tokens in the output that appear nowhere on the cited
                         page are possible fabrication; content tokens on the
                         page that vanish from a rewrite are possible loss.

Gate 2 reports RATES and outliers rather than pass/fail per token, because OCR
is itself lossy — a low match rate is a signal to inspect, not proof of a bug.

Usage:
    python3 verify_patch.py <patch.jsonl> [--pages-book <StoreDirName>]
"""

import argparse
import collections
import json
import re
import sys
import unicodedata
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
MASTER = ROOT / "data/corpus/MASTER_corpus.jsonl"
PAGES = ROOT / "data/vision_pass/pages"

ADDITIVE = {"key", "format", "flag", "suspect", "difficulty", "clear_chart_flag", "clear_needs_vision", "options_check"}
# correct_key intentionally REPLACES a value; it must state what it supersedes.
CORRECTING = {"correct_key"}
REWRITE = {"text", "options", "record_tags", "markdown", "directions"}
WORD = re.compile(r"[A-Za-z]{3,}|\d+")


def toks(s):
    s = unicodedata.normalize("NFKC", str(s or "")).casefold()
    return collections.Counter(WORD.findall(s))


def load_master():
    recs = {}
    with MASTER.open() as f:
        for line in f:
            r = json.loads(line)
            recs[r["set_id"]] = r
    return recs


# MASTER book name -> page-store directory. Sinha's store predates the shared
# layout and lives with the recovered package; everything else follows the
# page_ocr_pipeline artifact shape under data/vision_pass/pages/.
PAGE_STORES = {
    "Sinha": ROOT / "incoming/topic_browser_full_package/cat_data/CAT_DI_LR_Nishit_K_Sinha/pages",
    "Arun Sharma Quant": PAGES / "Arun_Sharma_Quant",
    "Arun Sharma": PAGES / "Arun_Sharma",
    "Hall & Knight": PAGES / "Hall_&_Knight",
    "Tyra": PAGES / "Tyra", "Bird": PAGES / "Bird", "Bhatia": PAGES / "Bhatia",
    "Manhattan 5 lb": PAGES / "Manhattan_5_lb",
    "Manhattan GMAT Verbal": PAGES / "Manhattan_GMAT_Verbal",
    "Manhattan Logic Games": PAGES / "Manhattan_Logic_Games",
    "Manhattan Quant": PAGES / "Manhattan_Quant",
    "Hogg": PAGES / "Hogg", "Schaum": PAGES / "Schaum", "ETS GRE": PAGES / "ETS_GRE",
}


def page_text(book, page):
    store = PAGE_STORES.get(book, PAGES / book)
    p = store / ("%04d_ocr.md" % int(page))
    if not p.exists():
        return None
    return "\n".join(l for l in p.read_text().splitlines() if not l.startswith("<!--"))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("patch")
    ap.add_argument("--pages-book", help="page-store dir name for preservation reference")
    args = ap.parse_args()

    rows = [json.loads(l) for l in Path(args.patch).read_text().splitlines() if l.strip()]
    master = load_master()

    # ---- GATE 1: validity ----
    problems = collections.Counter()
    examples = collections.defaultdict(list)

    def flag(kind, detail):
        problems[kind] += 1
        if len(examples[kind]) < 3:
            examples[kind].append(detail)

    for e in rows:
        sid, num, act = e.get("set_id"), str(e.get("number", "*")), e.get("action")
        if not sid or not act:
            flag("row missing set_id/action", e); continue
        rec = master.get(sid)
        if rec is None:
            flag("set_id not in MASTER", sid); continue
        if num == "*":
            if act == "directions":
                if (rec.get("directions") or "").strip():
                    flag("CONFLICT: record already has directions", sid)
                if not e.get("directions_source"):
                    flag("directions without provenance", sid)
            continue
        q = next((x for x in (rec.get("questions") or [])
                  if str(x.get("number")) == num), None)
        if q is None:
            flag("question number not in record", "%s #%s" % (sid, num)); continue
        if act == "key":
            existing = q.get("answer_key")
            if existing:
                # distinguish a genuine conflict from a patch already applied:
                # identical value means this is a replay, not a clobber
                if str(existing).strip() == str(e.get("answer_key", "")).strip():
                    problems["(info) already applied — identical key present"] += 1
                else:
                    flag("CONFLICT: would overwrite a DIFFERENT answer_key",
                         "%s #%s: have %r, patch says %r"
                         % (sid, num, existing, e.get("answer_key")))
            v = str(e.get("answer_key", "")).strip()
            if not v:
                flag("empty answer_key", "%s #%s" % (sid, num))
            if not e.get("key_source"):
                flag("key without key_source provenance", "%s #%s" % (sid, num))
        if act == "correct_key":
            if not e.get("why") or not e.get("key_source"):
                flag("correct_key without justification/provenance", "%s #%s" % (sid, num))
            if q.get("answer_key") == e.get("answer_key"):
                problems["(info) already applied — correction present"] += 1
        if act == "options":
            have = q.get("options") or []
            if have:
                if list(have) == list(e.get("options") or []):
                    problems["(info) already applied — identical options present"] += 1
                else:
                    flag("CONFLICT: would overwrite a DIFFERENT option list",
                         "%s #%s: have %r" % (sid, num, have[:2]))
            if len(e.get("options") or []) < 2:
                flag("options list shorter than 2", "%s #%s" % (sid, num))
            if not e.get("options_source"):
                flag("options without provenance", "%s #%s" % (sid, num))
            qx = q.get("extra") or {}
            if qx.get("needs_reextraction") or qx.get("key_suspect"):
                flag("options onto a question whose stem/key is itself flagged",
                     "%s #%s" % (sid, num))
        if act == "options_check" and not e.get("options_check"):
            flag("options_check without a statement", "%s #%s" % (sid, num))
        if act == "clear_needs_vision" and not e.get("resolution"):
            flag("clear_needs_vision without a stated resolution", "%s #%s" % (sid, num))
        if act == "difficulty":
            existing = q.get("difficulty")
            if existing is not None:
                if existing == e.get("difficulty"):
                    problems["(info) already applied — identical difficulty present"] += 1
                else:
                    flag("CONFLICT: would overwrite a DIFFERENT difficulty",
                         "%s #%s: have %r, patch says %r"
                         % (sid, num, existing, e.get("difficulty")))
            d = e.get("difficulty")
            if not isinstance(d, int) or not (1 <= d <= 5):
                flag("difficulty outside the 1-5 scale", "%s #%s: %r" % (sid, num, d))
            if not e.get("difficulty_source"):
                flag("difficulty without provenance", "%s #%s" % (sid, num))
        if act == "format":
            existing = q.get("question_format")
            if existing not in (None, "", "unclassified"):
                if existing == e.get("question_format"):
                    problems["(info) already applied — identical format present"] += 1
                else:
                    flag("CONFLICT: would overwrite a DIFFERENT question_format",
                         "%s #%s: have %r, patch says %r"
                         % (sid, num, existing, e.get("question_format")))

    fails = {k: c for k, c in problems.items() if not k.startswith("(info)")}
    print("GATE 1 validity: %d rows" % len(rows))
    for k, c in problems.most_common():
        tag = "info" if k.startswith("(info)") else "FAIL"
        print("  %s %-45s %5d   %s" % (tag, k, c, examples[k][:2] if examples[k] else ""))
    if not fails:
        print("  pass — all targets exist, no silent overwrites, provenance present")

    # ---- GATE 2: preservation ----
    rw = [e for e in rows if e.get("action") in REWRITE]
    print()
    print("GATE 2 preservation: %d rewriting rows" % len(rw))

    # record_tags carries its own reference: the value currently in MASTER.
    # Relabelling must preserve the normalized-key CONCEPT SET exactly.
    tag_rows = [e for e in rw if e.get("action") == "record_tags"]
    if tag_rows:
        def tag_key(s):
            s = unicodedata.normalize("NFKC", str(s)).strip()
            s = re.sub(r"[_\-\s]+", " ", s)
            s = re.sub(r"\s*:\s*", ": ", s)
            s = re.sub(r"[^\w\s:&/+]", "", s)
            return s.casefold().strip()
        changed = 0
        for e in tag_rows:
            cur = (master[e["set_id"]].get("extra") or {}).get("tags") or []
            if {tag_key(t) for t in cur} != {tag_key(t) for t in e["tags"]}:
                changed += 1
                flag("tag rewrite CHANGES the concept set", e["set_id"])
        print("  record_tags: %d rows checked against MASTER; concept set preserved on %d, "
              "changed on %d" % (len(tag_rows), len(tag_rows) - changed, changed))
        fails = {k: c for k, c in problems.items() if not k.startswith("(info)")}
        rw = [e for e in rw if e.get("action") != "record_tags"]
        if not rw:
            return 0 if not fails else 1

    if not rw:
        print("  n/a — this patch is purely additive (%s)"
              % ", ".join(sorted({e.get("action", "?") for e in rows})))
        return 0 if not fails else 1
    if not args.pages_book and not all(e.get("book") in PAGE_STORES for e in rw):
        print("  SKIPPED — rewriting rows present but no --pages-book reference given.")
        print("  Refusing to certify a content rewrite without a preservation reference.")
        return 1

    unmatched_rates, worst = [], []
    for e in rw:
        pages = e.get("pdf_pages") or ([e["pdf_page"]] if e.get("pdf_page") else [])
        ref = collections.Counter()
        for p in pages:
            t = page_text(e.get("book") or args.pages_book, p)
            if t:
                ref.update(toks(t))
        if not ref:
            continue
        out = toks(e.get("text") or e.get("markdown") or e.get("directions") or " ".join(e.get("options") or []))
        if not out:
            continue
        missing = sum(c for t, c in out.items() if t not in ref)
        rate = missing / max(1, sum(out.values()))
        unmatched_rates.append(rate)
        worst.append((rate, e.get("set_id"), str(e.get("number", "*")),
                      sorted(t for t in out if t not in ref)[:6]))
    if unmatched_rates:
        unmatched_rates.sort()
        med = unmatched_rates[len(unmatched_rates) // 2]
        print("  compared %d rewrites against page OCR" % len(unmatched_rates))
        print("  median off-page token rate: %.1f%%" % (100 * med))
        worst.sort(reverse=True)
        print("  worst offenders (inspect these — tokens on neither the page nor OCR):")
        for rate, sid, num, sample in worst[:5]:
            print("     %5.1f%%  %s #%s  %s" % (100 * rate, sid, num, sample))
    return 0 if not fails else 1


if __name__ == "__main__":
    sys.exit(main())
