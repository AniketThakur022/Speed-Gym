#!/usr/bin/env python3
"""Deterministic taxonomy surface-normalizer for MASTER_corpus.jsonl.

Scope is deliberately narrow: this collapses SURFACE variants of the same
label (casing, underscore/hyphen/space separators, stray punctuation, unicode
form). It does NOT decide semantics — it will never merge two genuinely
different labels, and it does not map corpus labels onto the Neo4j :Skill
vocabulary, because as of 2026-09-03 no canonical vocabulary exists to map to
(see the taxonomy note in the extraction-pipeline-state memory: only 12 of 107
corpus topics match any :Skill name even after normalization, and 80% of the
467 :Skill nodes are `is_stub` placeholders).

Usage:
    python3 taxonomy.py report          # collapse statistics, no writes
    python3 taxonomy.py patch <out>     # emit a tag-normalization patch
"""

import collections
import json
import re
import sys
import unicodedata
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
MASTER = ROOT / "data/corpus/MASTER_corpus.jsonl"


def norm_key(s):
    """Fold a label to its comparison key (lowercase, separator-insensitive)."""
    s = unicodedata.normalize("NFKC", str(s)).strip()
    s = re.sub(r"[_\-\s]+", " ", s)
    s = re.sub(r"\s*:\s*", ": ", s)
    s = re.sub(r"[^\w\s:&/+]", "", s)
    return s.casefold().strip()


def canonical_form(variants):
    """Pick the display form for a variant cluster.

    House style first, frequency second: a canonical vocabulary should look
    uniform, so a spaced Title Case form wins over a more frequent
    hyphen/underscore or all-lowercase spelling of the same label. All-caps
    forms (SSC, RRB) are kept as-is since they are acronyms, not shouting.
    Deterministic.
    """
    def score(item):
        label, count = item
        spaced = "_" not in label and "-" not in label
        acronym = label.isupper() and len(label) <= 5
        titleish = acronym or (any(c.isupper() for c in label) and not label.isupper())
        return (not spaced, not titleish, -count, len(label), label)
    return sorted(variants.items(), key=score)[0][0]


def collect():
    """Return {field: {norm_key: Counter(raw -> occurrences)}}."""
    fields = {"tags": collections.defaultdict(collections.Counter)}
    with MASTER.open() as f:
        for line in f:
            r = json.loads(line)
            for t in ((r.get("extra") or {}).get("tags") or []):
                fields["tags"][norm_key(t)][t] += 1
    return fields


def cmd_report():
    fields = collect()
    for name, clusters in fields.items():
        raw = sum(len(v) for v in clusters.values())
        print("%s: %d raw labels -> %d normalized (collapse %d)"
              % (name, raw, len(clusters), raw - len(clusters)))
        multi = {k: v for k, v in clusters.items() if len(v) > 1}
        print("  %d clusters have >1 surface form" % len(multi))
        for k, v in sorted(multi.items(), key=lambda kv: -sum(kv[1].values()))[:10]:
            print("     %-28s <- %s" % (canonical_form(v), sorted(v)))


def cmd_patch(out):
    fields = collect()
    mapping = {}
    for k, variants in fields["tags"].items():
        if len(variants) > 1:
            canon = canonical_form(variants)
            for raw in variants:
                if raw != canon:
                    mapping[raw] = canon
    entries = []
    with MASTER.open() as f:
        for line in f:
            r = json.loads(line)
            tags = (r.get("extra") or {}).get("tags") or []
            if not tags:
                continue
            new = []
            for t in tags:
                new.append(mapping.get(t, t))
            # de-duplicate while preserving order (variants may now collide)
            seen, deduped = set(), []
            for t in new:
                if t not in seen:
                    seen.add(t)
                    deduped.append(t)
            if deduped != tags:
                entries.append({"set_id": r["set_id"], "action": "record_tags",
                                "tags": deduped,
                                "tags_source": "taxonomy.py surface-normalization "
                                               "2026-09-03 (casing/separator variants only; "
                                               "no semantic merging)"})
    Path(out).write_text("\n".join(json.dumps(e, ensure_ascii=False) for e in entries) + "\n")
    print("mapped %d variant labels -> canonical; %d records rewritten -> %s"
          % (len(mapping), len(entries), out))


if __name__ == "__main__":
    if len(sys.argv) < 2:
        raise SystemExit(__doc__)
    if sys.argv[1] == "report":
        cmd_report()
    elif sys.argv[1] == "patch":
        cmd_patch(sys.argv[2])
    else:
        raise SystemExit(__doc__)
