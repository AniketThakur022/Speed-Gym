#!/usr/bin/env python3
"""VMSG unified graph loader — ADDITIVE ONLY.

Unifies the 25-book exam corpus (data/exports/vmsg_questions_v1.jsonl, 19,619 rows),
the taxonomy chapter rules (data/taxonomy/taxonomy_v1_1.json), the converted
SolveAlong templates (data/factory/converted/packet_*.jsonl) and the verbatim book
chunks (incoming/.../db_exports/chunks.jsonl) into the live Neo4j serving graph
WITHOUT mutating one byte of it.

HARD INVARIANT
--------------
Every pre-existing label and relationship type count is captured before and after
and asserted UNCHANGED. Additionally the 6 pre-existing :Book nodes are property-
hashed before and after. Everything written uses NEW labels
(:Question :Chapter :ExamTopic :ConvertedTemplate :Chunk :CorpusBook) and NEW
relationship types (FROM_BOOK IN_CHAPTER OF_BOOK EXERCISES EXERCISES_TOPIC COVERS
DERIVED_FROM BRIDGES_TO). No existing node is relabelled, no property overwritten,
nothing deleted.

DELIBERATE DEVIATIONS FROM THE BRIEF (each backed by a measurement, see --stats):
  1. Corpus books absent from the graph get the NEW label :CorpusBook, NOT :Book.
     The brief asked for :Book with source:'corpus', but that would move the
     pre-existing :Book count 6 -> 22 and silently change every serving query that
     counts or scans :Book. FROM_BOOK is still one uniform relationship type, so
     `(:Question)-[:FROM_BOOK]->(b)` reaches all 19,619 rows regardless of label.
  2. :Chunk is keyed on `id` (a uuid), not `content_hash` — the export has no
     content_hash field. A sha256 of `content` is stored as `content_sha256`.
  3. :ConvertedTemplate -[:DERIVED_FROM]-> :Question joins on
     `provenance.question_id`, NOT `sourceDocumentId`. Measured: sourceDocumentId
     is a book#page locator and joins 0/348; provenance.question_id joins 348/348.
  4. BRIDGES_TO carries `evidence:'taxonomy_v1_1.entries.domain'` and
     `semantics:'domain_membership_not_prerequisite'`. There is ZERO name/alias
     evidence linking any ExamTopic to a live :Skill (measured: 0 of 22). The only
     recorded evidence is the taxonomy's own domain field. Bridges are emitted only
     where that domain resolves to a live is_root :Skill; the three GRE-verbal
     topics resolve to domain 'Verbal', which is not a skill, so they get no edge.

Usage:
  python3 scripts/build_unified_graph.py --dry-run     # report what it WOULD write
  python3 scripts/build_unified_graph.py               # load (idempotent, MERGE)
  python3 scripts/build_unified_graph.py --stats       # report current unified state
  python3 scripts/build_unified_graph.py --skip-chunks # everything except :Chunk
"""

from __future__ import annotations

import argparse
import collections
import glob
import hashlib
import json
import os
import re
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
EXPORT = ROOT / "data" / "exports" / "vmsg_questions_v1.jsonl"
TAXONOMY = ROOT / "data" / "taxonomy" / "taxonomy_v1_1.json"
CONVERTED_GLOB = str(ROOT / "data" / "factory" / "converted" / "packet_*.jsonl")
CHUNKS = ROOT / "incoming" / "topic_browser_full_package" / "db_exports" / "chunks.jsonl"
REPORT = ROOT / "data" / "graph" / "unified_graph_report.json"

NEO4J_URI = os.environ.get("NEO4J_URI", "bolt://localhost:7687")
NEO4J_USER = os.environ.get("NEO4J_USER", "neo4j")
NEO4J_PASSWORD = os.environ.get("NEO4J_PASSWORD", "vmsg-dev-password")

BATCH = 1000

# Labels/rel types that belong to the SERVING graph. Their counts must not move.
PROTECTED_LABELS = [
    "Skill", "Problem", "SolveAlong", "Explainer", "Trap", "Sutra", "Book", "User",
    "Achievement", "Cohort", "FamilyAccount", "MarketingTouchpoint", "Referral",
    "RevenueEvent", "SubTopic", "UserJourney",
]
PROTECTED_RELS = [
    "PREREQUISITE_OF", "FRONTIER_OF", "REQUIRES", "TEACHES", "EXPLAINS",
    "NEXT_TOPIC", "MANIFESTS_AS", "APPEARS_IN", "HAS_TRAP", "TRAPS_PRESENT",
    "HAS_SKILL_LEVEL", "COMPLETED",
]

NEW_LABELS = ["Question", "Chapter", "ExamTopic", "ConvertedTemplate", "Chunk", "CorpusBook"]
NEW_RELS = ["FROM_BOOK", "IN_CHAPTER", "OF_BOOK", "EXERCISES", "EXERCISES_TOPIC",
            "COVERS", "DERIVED_FROM", "BRIDGES_TO"]

# chunks.jsonl book_id -> live :Book.name. Evidence: the 6 short ids ARE the live
# :Book names verbatim; the 8 long ids are the publisher-title forms of the same
# volumes (Ayres/Schmidt = Schaum's; Bhatia = Vedic Made Easy; ...). The last two
# are corpus books with no live :Book node.
CHUNK_BOOK_ALIASES = {
    "Vedic_Mathematics__Tirthaji_": "Tirthaji_Vedic_Math",
    "Ayres__Schmidt___Schaum_s_Outline_of_College_Mathematics__3r": "Schaums_College_Math",
    "Bird___Basic_Engineering_Mathematics__5th_Edition_": "Bird_Engineering_Math",
    "The_Number_Sense___How_the_Mind_Creates_Mathematics__Revised": "Number_Sense",
    "Vedic_Mathematics_Made_Easy__Dhaval_Bhatia_": "Vedic_Made_Easy",
    "Vedic_Mathematics_Secrets": "Vedic_Secrets",
}
# chunk book_ids with no live :Book — routed to the corpus book of the same volume
CHUNK_BOOK_TO_CORPUS = {
    "The_Essentials_of_Vedic_Mathematics__Rajesh_Thakur_": "thakur_essentials_vedic",
    "dokumen_pub_fifty_challenging_problems_in_probability_with_s": "mosteller_fifty_problems",
}

STOPWORDS = {"and", "the", "of", "a", "an", "in", "on", "for", "to", "with"}

# corpus book_canonical_id -> live :Book.name. EXPLICIT, not heuristic: the live
# names are short slugs whose tokens do not subset the corpus titles
# ("schaum" vs "schaums"), so fuzzy matching silently lost one book. This map is
# cross-checked at runtime against the export's own `book_in_graph` flag.
CORPUS_BOOK_TO_LIVE = {
    "bird_basic_engineering_math": "Bird_Engineering_Math",
    "schaum_college_math": "Schaums_College_Math",
    "bhatia_vedic_made_easy": "Vedic_Made_Easy",
    "vedic_secrets": "Vedic_Secrets",
}

# taxonomy_v1_1's chapter normalizer (factory/taxonomy/build_v1_1.py:41,86) —
# it strips a leading "Ch 1:" / "12)" style prefix BEFORE lowercasing. Reusing the
# plain norm() here silently matched only 37 of 371 chapters instead of 258.
CHAPTER_PREFIX = re.compile(r"^\s*(ch(apter)?\s*\d+\s*[.:)-]?\s*|\d+\s*[.:)]\s*)", re.I)


def chapter_norm(s: str) -> str:
    return norm(CHAPTER_PREFIX.sub("", (s or "").strip()))


# ---------------------------------------------------------------- matching ----
def norm(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", (s or "").lower()).strip()


def tokenset(s: str) -> frozenset:
    return frozenset(w for w in norm(s).split() if w and w not in STOPWORDS)


# --------------------------------------------------------- reviewed aliases ---
ALIAS_PROPOSED = ROOT / "data/taxonomy/cat_quant_subject_aliases.json"
ALIAS_REVIEW = ROOT / "data/taxonomy/cat_quant_subject_aliases.REVIEW.json"


def load_reviewed_aliases():
    """Subject -> live :Skill name, taking the REVIEW file as authoritative.

    A proposed alias is applied only where the corpus-evidence review returned a
    CONFIRM verdict. A REJECTed mapping is dropped and reported: the reviewer
    judged those questions on what they contain, and 'Averages and Alligations'
    -> 'Averages' failed because all 40 rows come from an Alligations chapter and
    27 use mixture language. Attaching them to Averages would teach the wrong
    skill, which is exactly the failure a name-similarity match makes silently.
    """
    if not ALIAS_REVIEW.exists():
        return {}, {"reviewed": 0, "confirmed": 0, "rejected": [], "unreviewed": []}
    review = json.loads(ALIAS_REVIEW.read_text())
    confirmed, rejected = {}, []
    for a in review.get("aliases", []):
        subject, target = a.get("subject"), a.get("proposed")
        if str(a.get("verdict", "")).upper().startswith("CONFIRM"):
            confirmed[subject] = target
        else:
            rejected.append({"subject": subject, "proposed": target,
                             "verdict": a.get("verdict")})
    # Any mapping the proposal asserts but the review never cleared stays OUT.
    unreviewed = []
    if ALIAS_PROPOSED.exists():
        proposed = json.loads(ALIAS_PROPOSED.read_text())
        seen = {a.get("subject") for a in review.get("aliases", [])}
        for row in proposed.get("taxonomy_subject_to_existing_skill", []):
            if row.get("taxonomy_subject") not in seen:
                unreviewed.append(row.get("taxonomy_subject"))
    return confirmed, {"reviewed": len(review.get("aliases", [])),
                       "confirmed": len(confirmed), "rejected": rejected,
                       "unreviewed": unreviewed}


class SkillMatcher:
    """Three-tier skill_key -> live :Skill.name matcher.

    Tier 1 exact, tier 2 case/punctuation-normalized, tier 3 word-order/stopword-
    insensitive token set. Tiers 2 and 3 fire ONLY on an unambiguous single
    candidate, so a collision in the live vocabulary can never silently pick one.
    """

    CONFIDENCE = {"reviewed_alias": 1.0, "exact": 1.0, "normalized": 0.9,
                  "tokenset": 0.75}

    def __init__(self, names, aliases=None):
        self.exact = set(names)
        # Evidence-reviewed aliases outrank every string tier: they encode what the
        # questions contain, which no matcher can see.
        self.aliases = {k: v for k, v in (aliases or {}).items() if v in self.exact}
        self.by_norm = collections.defaultdict(list)
        self.by_tokens = collections.defaultdict(list)
        for n in names:
            self.by_norm[norm(n)].append(n)
            self.by_tokens[tokenset(n)].append(n)
        self.norm_collisions = sum(1 for v in self.by_norm.values() if len(v) > 1)
        self.token_collisions = sum(1 for v in self.by_tokens.values() if len(v) > 1)

    def match(self, key):
        if not key:
            return None, None
        if key in self.aliases:
            return self.aliases[key], "reviewed_alias"
        if key in self.exact:
            return key, "exact"
        c = self.by_norm.get(norm(key))
        if c and len(c) == 1:
            return c[0], "normalized"
        c = self.by_tokens.get(tokenset(key))
        if c and len(c) == 1:
            return c[0], "tokenset"
        return None, None


# ------------------------------------------------------------------ neo4j -----
def connect():
    try:
        from neo4j import GraphDatabase
    except ImportError:
        sys.exit("neo4j driver missing. Run with the project venv: .venv/bin/python")
    return GraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USER, NEO4J_PASSWORD))


def snapshot(session):
    """Full label + relationship-type census, plus a property fingerprint of the
    pre-existing :Book nodes (the one label the brief wanted us to extend)."""
    labels = {}
    for rec in session.run("CALL db.labels() YIELD label RETURN label ORDER BY label"):
        lab = rec["label"]
        n = session.run(f"MATCH (n:`{lab}`) RETURN count(n) AS c").single()["c"]
        labels[lab] = n
    rels = {}
    for rec in session.run("MATCH ()-[r]->() RETURN type(r) AS t, count(*) AS c ORDER BY t"):
        rels[rec["t"]] = rec["c"]
    books = {}
    for rec in session.run(
        "MATCH (b:Book) WHERE NOT b:CorpusBook RETURN b.name AS name, properties(b) AS p ORDER BY b.name"
    ):
        books[rec["name"]] = hashlib.sha256(
            json.dumps(rec["p"], sort_keys=True, default=str).encode()
        ).hexdigest()[:16]
    totals = session.run(
        "MATCH (n) RETURN count(n) AS c"
    ).single()["c"]
    total_rels = session.run("MATCH ()-[r]->() RETURN count(r) AS c").single()["c"]
    return {"labels": labels, "rels": rels, "book_fingerprints": books,
            "total_nodes": totals, "total_rels": total_rels}


def protected_view(snap):
    return {
        "labels": {k: v for k, v in snap["labels"].items() if k in PROTECTED_LABELS},
        "rels": {k: v for k, v in snap["rels"].items() if k in PROTECTED_RELS},
        "book_fingerprints": snap["book_fingerprints"],
    }


def assert_unchanged(before, after):
    """Compare only the SERVING surface. New labels/rel types are expected to appear."""
    b, a = protected_view(before), protected_view(after)
    problems = []
    for lab in set(b["labels"]) | set(a["labels"]):
        if b["labels"].get(lab, 0) != a["labels"].get(lab, 0):
            problems.append(f"LABEL {lab}: {b['labels'].get(lab,0)} -> {a['labels'].get(lab,0)}")
    for rel in set(b["rels"]) | set(a["rels"]):
        if b["rels"].get(rel, 0) != a["rels"].get(rel, 0):
            problems.append(f"REL {rel}: {b['rels'].get(rel,0)} -> {a['rels'].get(rel,0)}")
    for name in set(b["book_fingerprints"]) | set(a["book_fingerprints"]):
        if b["book_fingerprints"].get(name) != a["book_fingerprints"].get(name):
            problems.append(f"BOOK PROPERTIES MUTATED: {name}")
    return problems


def write_batches(session, cypher, rows, label=""):
    """UNWIND writes in chunks of BATCH. Returns rows sent."""
    sent = 0
    for i in range(0, len(rows), BATCH):
        chunk = rows[i:i + BATCH]
        session.run(cypher, rows=chunk)
        sent += len(chunk)
    return sent


# ------------------------------------------------------------------ build -----
def load_sources(skip_chunks=False):
    src = {}
    questions = []
    with open(EXPORT) as f:
        for line in f:
            line = line.strip()
            if line:
                questions.append(json.loads(line))
    src["questions"] = questions

    src["taxonomy"] = json.loads(TAXONOMY.read_text())

    converted = []
    for path in sorted(glob.glob(CONVERTED_GLOB)):
        with open(path) as f:
            for line in f:
                line = line.strip()
                if line:
                    converted.append(json.loads(line))
    src["converted"] = converted

    chunks = []
    if not skip_chunks and CHUNKS.exists():
        with open(CHUNKS) as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                d = json.loads(line)
                d.pop("embedding", None)  # 1536 floats/row — never goes in the graph
                chunks.append(d)
    src["chunks"] = chunks
    return src


def plan(src, live_skills, live_books):
    """Pure function: source data + live vocabularies -> everything to write.

    Returns (payload, stats). No I/O, no writes — this is what --dry-run reports.
    """
    aliases, alias_stats = load_reviewed_aliases()
    matcher = SkillMatcher(live_skills, aliases)
    stats = collections.OrderedDict()
    stats["reviewed_aliases"] = alias_stats
    questions = src["questions"]
    tax = src["taxonomy"]

    stats["export_rows"] = len(questions)
    qids = {q["question_id"] for q in questions}
    stats["export_distinct_question_ids"] = len(qids)

    # ---- books -------------------------------------------------------------
    book_rows = {}
    for q in questions:
        bid = q.get("book_canonical_id")
        if bid and bid not in book_rows:
            book_rows[bid] = {"book_canonical_id": bid, "book": q.get("book"),
                              "book_title": q.get("book_title")}
    # map corpus book -> live :Book.name via the explicit, audited map
    live_set = set(live_books)
    book_to_live = {bid: (CORPUS_BOOK_TO_LIVE.get(bid) if CORPUS_BOOK_TO_LIVE.get(bid) in live_set else None)
                    for bid in book_rows}
    corpus_only = {b: m for b, m in book_rows.items() if not book_to_live[b]}
    # cross-check the map against the export's own book_in_graph flag
    flagged = {q.get("book_canonical_id") for q in questions if q.get("book_in_graph")}
    mapped = {b for b, v in book_to_live.items() if v}
    stats["book_map_agrees_with_book_in_graph_flag"] = (flagged == mapped)
    stats["book_map_flag_disagreements"] = sorted(flagged ^ mapped)
    stats["live_books_with_zero_corpus_questions"] = sorted(live_set - set(book_to_live.values()))
    stats["corpus_books_total"] = len(book_rows)
    stats["corpus_books_matching_live_Book"] = sum(1 for v in book_to_live.values() if v)
    stats["corpus_books_needing_new_node"] = len(corpus_only)
    stats["corpus_book_to_live_book_map"] = {k: v for k, v in book_to_live.items() if v}

    # ---- exam topics -------------------------------------------------------
    key_rows = collections.Counter()
    key_playable = collections.Counter()
    for q in questions:
        sk = (q.get("taxonomy") or {}).get("skill_key")
        if sk:
            key_rows[sk] += 1
            if q.get("playable"):
                key_playable[sk] += 1
    skill_map = {}      # skill_key -> (live name, tier)
    topic_keys = {}     # skill_key -> row count (no live skill)
    for k, c in key_rows.items():
        m, tier = matcher.match(k)
        if m:
            skill_map[k] = (m, tier)
        else:
            topic_keys[k] = c
    stats["rows_with_skill_key"] = sum(key_rows.values())
    stats["distinct_skill_keys"] = len(key_rows)
    stats["skill_keys_matched"] = len(skill_map)
    stats["skill_keys_unmatched"] = len(topic_keys)
    stats["match_tier_keys"] = dict(collections.Counter(t for _, t in skill_map.values()))
    stats["match_tier_rows"] = dict(collections.Counter(
        {t: sum(key_rows[k] for k, (_, tt) in skill_map.items() if tt == t) for t in
         ("exact", "normalized", "tokenset")}))
    stats["rows_attaching_to_live_skill"] = sum(key_rows[k] for k in skill_map)
    stats["rows_attaching_to_exam_topic"] = sum(topic_keys.values())
    stats["live_vocab_norm_collisions"] = matcher.norm_collisions
    stats["live_vocab_tokenset_collisions"] = matcher.token_collisions

    tax_entries = {e["label"]: e for e in tax["entries"]}
    topic_nodes = []
    for k, c in sorted(topic_keys.items()):
        e = tax_entries.get(k) or {}
        topic_nodes.append({
            "name": k, "rows": c, "playable_rows": key_playable.get(k, 0),
            "domain": e.get("domain"), "taxonomy_id": e.get("id"),
            "taxonomy_status": e.get("status"), "confidence": e.get("confidence"),
            "type": e.get("type"), "source": "corpus_skill_key_absent_from_graph",
        })

    # ---- bridges (evidence-gated) -----------------------------------------
    bridges = []
    no_bridge = []
    for t in topic_nodes:
        dom = t["domain"]
        m, tier = matcher.match(dom) if dom else (None, None)
        if m and tier == "exact":
            bridges.append({"topic": t["name"], "skill": m,
                            "evidence": "taxonomy_v1_1.entries.domain",
                            "semantics": "domain_membership_not_prerequisite",
                            "confidence": t.get("confidence") or "medium",
                            "rows": t["rows"]})
        else:
            no_bridge.append({"topic": t["name"], "domain": dom, "rows": t["rows"],
                              "reason": "domain absent from live :Skill vocabulary"
                                        if dom else "taxonomy entry carries no domain"})
    stats["exam_topics_with_bridge"] = len(bridges)
    stats["exam_topics_without_bridge"] = len(no_bridge)
    stats["bridge_gap_detail"] = no_bridge
    stats["bridge_name_alias_evidence_found"] = 0  # measured: none exists

    # ---- chapters ----------------------------------------------------------
    chap = {}
    for q in questions:
        ch = q.get("chapter")
        if not ch:
            continue
        bid = q.get("book_canonical_id")
        key = f"{bid}::{ch}"
        if key not in chap:
            chap[key] = {"chapter_key": key, "book_canonical_id": bid, "chapter": ch,
                         "chapter_norm": chapter_norm(ch), "questions": 0}
        chap[key]["questions"] += 1
    stats["rows_with_chapter"] = sum(c["questions"] for c in chap.values())
    stats["rows_without_chapter"] = len(questions) - stats["rows_with_chapter"]
    stats["distinct_chapters"] = len(chap)

    # chapter rules -> COVERS
    rules = tax["chapter_rules"]
    rule_index = {(r["canonical_book_id"], r["normalized"]): r for r in rules}
    stats["chapter_rules"] = len(rules)
    covers_skill, covers_topic, covers_dead = [], [], []
    matched_chapters = set()
    for key, c in chap.items():
        r = rule_index.get((c["book_canonical_id"], c["chapter_norm"]))
        if not r:
            continue
        matched_chapters.add(key)
        sk = r["skill_key"]
        m, tier = matcher.match(sk)
        if m:
            covers_skill.append({"chapter_key": key, "skill": m, "skill_key": sk,
                                 "match_tier": tier, "rule_questions": r.get("questions")})
        elif sk in topic_keys:
            covers_topic.append({"chapter_key": key, "topic": sk,
                                 "rule_questions": r.get("questions")})
        else:
            covers_dead.append({"chapter_key": key, "skill_key": sk})
    stats["chapters_matched_by_rule"] = len(matched_chapters)
    stats["chapters_unmatched_by_rule"] = len(chap) - len(matched_chapters)
    stats["covers_to_skill"] = len(covers_skill)
    stats["covers_to_exam_topic"] = len(covers_topic)
    stats["covers_unresolvable"] = len(covers_dead)
    stats["covers_unresolvable_detail"] = covers_dead[:20]

    # rule skill_keys that name neither a live Skill nor a corpus ExamTopic ->
    # these need ExamTopic nodes too, or the COVERS edge is lost
    extra_topics = {}
    for r in rules:
        sk = r["skill_key"]
        if matcher.match(sk)[0] or sk in topic_keys:
            continue
        extra_topics[sk] = extra_topics.get(sk, 0) + (r.get("questions") or 0)
    stats["rule_only_topic_keys"] = extra_topics

    # ---- questions ---------------------------------------------------------
    qnodes, ex_skill, ex_topic, in_chapter, from_book = [], [], [], [], []
    orphan = collections.Counter()
    for q in questions:
        t = q.get("taxonomy") or {}
        bid = q.get("book_canonical_id")
        qid = q["question_id"]
        text = q.get("text") or ""
        qnodes.append({
            "question_id": qid,
            "set_id": q.get("set_id"),
            "number": q.get("number"),
            "book": q.get("book"),
            "book_canonical_id": bid,
            "chapter": q.get("chapter"),
            "text": text[:4000],
            "text_len": len(text),
            "answer_key": q.get("answer_key"),
            "answer_provenance": q.get("answer_provenance"),
            "question_format": q.get("question_format"),
            "difficulty": q.get("difficulty"),
            "playable": bool(q.get("playable")),
            "taxonomy_status": t.get("taxonomy_status"),
            "skill_key": t.get("skill_key"),
            "bkt_joinable": bool(t.get("bkt_joinable")),
            "resolved_by": t.get("resolved_by"),
            "source": "corpus_v1",
        })
        if bid:
            live = book_to_live.get(bid)
            from_book.append({"question_id": qid, "book_key": live or bid,
                              "live": bool(live)})
        else:
            orphan["question_without_book"] += 1
        if q.get("chapter"):
            in_chapter.append({"question_id": qid,
                               "chapter_key": f"{bid}::{q['chapter']}"})
        else:
            orphan["question_without_chapter"] += 1
        sk = t.get("skill_key")
        if sk and sk in skill_map:
            name, tier = skill_map[sk]
            ex_skill.append({"question_id": qid, "skill": name, "source_key": sk,
                             "match_tier": tier,
                             "confidence": SkillMatcher.CONFIDENCE[tier]})
        elif sk:
            ex_topic.append({"question_id": qid, "topic": sk})
        else:
            orphan["question_without_skill_key"] += 1

    # ---- converted templates ----------------------------------------------
    conv_nodes, derived = [], []
    conv_orphans = []
    for c in src["converted"]:
        prov = c.get("provenance") or {}
        qid = prov.get("question_id")
        conc = c.get("concept") or {}
        conv_nodes.append({
            "id": c["id"], "domain": c.get("domain"),
            "technique_name": conc.get("technique_name"),
            "category": conc.get("category"), "sub_category": conc.get("sub_category"),
            "difficulty": c.get("difficulty"),
            "difficulty_inferred": bool(c.get("difficulty_inferred")),
            "expected_time": c.get("expected_time"),
            "generation_method": c.get("generationMethod"),
            "trust": c.get("trust"),
            "source_document_id": c.get("sourceDocumentId"),
            "provenance_question_id": qid,
            "version": c.get("version"),
        })
        if qid and qid in qids:
            derived.append({"template_id": c["id"], "question_id": qid,
                            "join": "provenance.question_id"})
        else:
            conv_orphans.append(c["id"])
    stats["converted_templates"] = len(conv_nodes)
    stats["converted_joined_to_question"] = len(derived)
    stats["converted_orphans"] = len(conv_orphans)
    stats["converted_join_field"] = "provenance.question_id (sourceDocumentId joins 0/348)"

    # ---- chunks ------------------------------------------------------------
    chunk_nodes, chunk_book = [], []
    chunk_orphan_books = collections.Counter()
    for c in src["chunks"]:
        content = c.get("content") or ""
        bid = c.get("book_id")
        chunk_nodes.append({
            "id": c["id"], "book_id": bid, "chunk_type": c.get("chunk_type"),
            "page_number": c.get("page_number"),
            "content": content[:4000], "content_len": len(content),
            "content_sha256": hashlib.sha256(content.encode()).hexdigest(),
            "schema_version": c.get("schema_version"),
            "created_at": str(c.get("created_at")) if c.get("created_at") else None,
        })
        target = None
        if bid in live_books:
            target = ("live", bid)
        elif bid in CHUNK_BOOK_ALIASES:
            target = ("live", CHUNK_BOOK_ALIASES[bid])
        elif bid in CHUNK_BOOK_TO_CORPUS:
            cb = CHUNK_BOOK_TO_CORPUS[bid]
            target = ("live", book_to_live[cb]) if book_to_live.get(cb) else ("corpus", cb)
        if target:
            chunk_book.append({"chunk_id": c["id"], "book_key": target[1],
                               "live": target[0] == "live"})
        else:
            chunk_orphan_books[bid] += 1
    stats["chunks"] = len(chunk_nodes)
    stats["chunks_joined_to_book"] = len(chunk_book)
    stats["chunk_book_ids_unjoinable"] = dict(chunk_orphan_books)

    # ---- orphan classes ----------------------------------------------------
    orphans = {
        "question_without_book": orphan["question_without_book"],
        "question_without_chapter": orphan["question_without_chapter"],
        "question_without_skill_key": orphan["question_without_skill_key"],
        "question_with_skill_key_but_no_live_skill": len(ex_topic),
        "chapter_without_taxonomy_rule": stats["chapters_unmatched_by_rule"],
        "exam_topic_without_bridge_to_skill": len(no_bridge),
        "converted_template_without_question": len(conv_orphans),
        "chunk_without_book": sum(chunk_orphan_books.values()),
    }

    payload = {
        "corpus_books": [dict(m, source="corpus") for b, m in corpus_only.items()],
        "questions": qnodes,
        "chapters": list(chap.values()),
        "exam_topics": topic_nodes + [
            {"name": k, "rows": 0, "playable_rows": 0,
             "domain": (tax_entries.get(k) or {}).get("domain"),
             "taxonomy_id": (tax_entries.get(k) or {}).get("id"),
             "taxonomy_status": (tax_entries.get(k) or {}).get("status"),
             "confidence": (tax_entries.get(k) or {}).get("confidence"),
             "type": (tax_entries.get(k) or {}).get("type"),
             "source": "taxonomy_chapter_rule_only"}
            for k in sorted(extra_topics)
        ],
        "converted": conv_nodes,
        "chunks": chunk_nodes,
        "rel_from_book": from_book,
        "rel_in_chapter": in_chapter,
        "rel_of_book": [{"chapter_key": c["chapter_key"],
                         "book_key": book_to_live.get(c["book_canonical_id"]) or c["book_canonical_id"],
                         "live": bool(book_to_live.get(c["book_canonical_id"]))}
                        for c in chap.values()],
        "rel_exercises": ex_skill,
        "rel_exercises_topic": ex_topic,
        "rel_covers_skill": covers_skill,
        "rel_covers_topic": covers_topic,
        "rel_derived_from": derived,
        "rel_bridges_to": bridges,
        "rel_chunk_from_book": chunk_book,
    }
    return payload, stats, orphans


# ------------------------------------------------------------------ write -----
CONSTRAINTS = [
    "CREATE CONSTRAINT unified_question_id IF NOT EXISTS FOR (n:Question) REQUIRE n.question_id IS UNIQUE",
    "CREATE CONSTRAINT unified_chapter_key IF NOT EXISTS FOR (n:Chapter) REQUIRE n.chapter_key IS UNIQUE",
    "CREATE CONSTRAINT unified_examtopic_name IF NOT EXISTS FOR (n:ExamTopic) REQUIRE n.name IS UNIQUE",
    "CREATE CONSTRAINT unified_converted_id IF NOT EXISTS FOR (n:ConvertedTemplate) REQUIRE n.id IS UNIQUE",
    "CREATE CONSTRAINT unified_chunk_id IF NOT EXISTS FOR (n:Chunk) REQUIRE n.id IS UNIQUE",
    "CREATE CONSTRAINT unified_corpusbook_id IF NOT EXISTS FOR (n:CorpusBook) REQUIRE n.book_canonical_id IS UNIQUE",
    "CREATE INDEX unified_question_book IF NOT EXISTS FOR (n:Question) ON (n.book_canonical_id)",
    "CREATE INDEX unified_question_playable IF NOT EXISTS FOR (n:Question) ON (n.playable)",
    "CREATE INDEX unified_question_skill_key IF NOT EXISTS FOR (n:Question) ON (n.skill_key)",
    "CREATE INDEX unified_chunk_book IF NOT EXISTS FOR (n:Chunk) ON (n.book_id)",
]

WRITES = [
    ("corpus_books", "CorpusBook nodes", """
        UNWIND $rows AS r
        MERGE (b:CorpusBook {book_canonical_id: r.book_canonical_id})
        SET b.book = r.book, b.book_title = r.book_title, b.source = 'corpus'
    """),
    ("exam_topics", "ExamTopic nodes", """
        UNWIND $rows AS r
        MERGE (t:ExamTopic {name: r.name})
        SET t.corpus_rows = r.rows, t.playable_rows = r.playable_rows,
            t.domain = r.domain, t.taxonomy_id = r.taxonomy_id,
            t.taxonomy_status = r.taxonomy_status, t.confidence = r.confidence,
            t.entry_type = r.type, t.source = r.source
    """),
    ("chapters", "Chapter nodes", """
        UNWIND $rows AS r
        MERGE (c:Chapter {chapter_key: r.chapter_key})
        SET c.book_canonical_id = r.book_canonical_id, c.chapter = r.chapter,
            c.chapter_norm = r.chapter_norm, c.question_count = r.questions,
            c.source = 'corpus_v1'
    """),
    ("questions", "Question nodes", """
        UNWIND $rows AS r
        MERGE (q:Question {question_id: r.question_id})
        SET q += r
    """),
    ("converted", "ConvertedTemplate nodes", """
        UNWIND $rows AS r
        MERGE (t:ConvertedTemplate {id: r.id})
        SET t += r
    """),
    ("chunks", "Chunk nodes", """
        UNWIND $rows AS r
        MERGE (c:Chunk {id: r.id})
        SET c += r
    """),
    ("rel_from_book", "FROM_BOOK", """
        UNWIND $rows AS r
        MATCH (q:Question {question_id: r.question_id})
        CALL (r) {
          WITH r WHERE r.live MATCH (b:Book {name: r.book_key}) RETURN b AS bk
          UNION
          WITH r WHERE NOT r.live MATCH (b:CorpusBook {book_canonical_id: r.book_key}) RETURN b AS bk
        }
        MERGE (q)-[:FROM_BOOK]->(bk)
    """),
    ("rel_of_book", "OF_BOOK", """
        UNWIND $rows AS r
        MATCH (c:Chapter {chapter_key: r.chapter_key})
        CALL (r) {
          WITH r WHERE r.live MATCH (b:Book {name: r.book_key}) RETURN b AS bk
          UNION
          WITH r WHERE NOT r.live MATCH (b:CorpusBook {book_canonical_id: r.book_key}) RETURN b AS bk
        }
        MERGE (c)-[:OF_BOOK]->(bk)
    """),
    ("rel_in_chapter", "IN_CHAPTER", """
        UNWIND $rows AS r
        MATCH (q:Question {question_id: r.question_id})
        MATCH (c:Chapter {chapter_key: r.chapter_key})
        MERGE (q)-[:IN_CHAPTER]->(c)
    """),
    ("rel_exercises", "EXERCISES", """
        UNWIND $rows AS r
        MATCH (q:Question {question_id: r.question_id})
        MATCH (s:Skill {name: r.skill})
        MERGE (q)-[e:EXERCISES]->(s)
        SET e.match_tier = r.match_tier, e.source_key = r.source_key,
            e.confidence = r.confidence, e.created_by = 'build_unified_graph'
    """),
    ("rel_exercises_topic", "EXERCISES_TOPIC", """
        UNWIND $rows AS r
        MATCH (q:Question {question_id: r.question_id})
        MATCH (t:ExamTopic {name: r.topic})
        MERGE (q)-[e:EXERCISES_TOPIC]->(t)
        SET e.created_by = 'build_unified_graph'
    """),
    ("rel_covers_skill", "COVERS->Skill", """
        UNWIND $rows AS r
        MATCH (c:Chapter {chapter_key: r.chapter_key})
        MATCH (s:Skill {name: r.skill})
        MERGE (c)-[e:COVERS]->(s)
        SET e.source = 'taxonomy_v1_1.chapter_rules', e.skill_key = r.skill_key,
            e.match_tier = r.match_tier, e.rule_questions = r.rule_questions
    """),
    ("rel_covers_topic", "COVERS->ExamTopic", """
        UNWIND $rows AS r
        MATCH (c:Chapter {chapter_key: r.chapter_key})
        MATCH (t:ExamTopic {name: r.topic})
        MERGE (c)-[e:COVERS]->(t)
        SET e.source = 'taxonomy_v1_1.chapter_rules', e.rule_questions = r.rule_questions
    """),
    ("rel_derived_from", "DERIVED_FROM", """
        UNWIND $rows AS r
        MATCH (t:ConvertedTemplate {id: r.template_id})
        MATCH (q:Question {question_id: r.question_id})
        MERGE (t)-[e:DERIVED_FROM]->(q)
        SET e.join = r.join
    """),
    ("rel_bridges_to", "BRIDGES_TO", """
        UNWIND $rows AS r
        MATCH (t:ExamTopic {name: r.topic})
        MATCH (s:Skill {name: r.skill})
        MERGE (t)-[e:BRIDGES_TO]->(s)
        SET e.evidence = r.evidence, e.semantics = r.semantics,
            e.confidence = r.confidence, e.corpus_rows = r.rows,
            e.created_by = 'build_unified_graph'
    """),
    ("rel_chunk_from_book", "Chunk FROM_BOOK", """
        UNWIND $rows AS r
        MATCH (c:Chunk {id: r.chunk_id})
        CALL (r) {
          WITH r WHERE r.live MATCH (b:Book {name: r.book_key}) RETURN b AS bk
          UNION
          WITH r WHERE NOT r.live MATCH (b:CorpusBook {book_canonical_id: r.book_key}) RETURN b AS bk
        }
        MERGE (c)-[:FROM_BOOK]->(bk)
    """),
]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--stats", action="store_true")
    ap.add_argument("--skip-chunks", action="store_true")
    ap.add_argument("--report", default=str(REPORT))
    args = ap.parse_args()

    t0 = time.time()
    driver = connect()
    with driver.session() as s:
        if args.stats:
            snap = snapshot(s)
            print(json.dumps({
                "labels": snap["labels"], "rels": snap["rels"],
                "total_nodes": snap["total_nodes"], "total_rels": snap["total_rels"],
            }, indent=2))
            driver.close()
            return 0

        before = snapshot(s)
        live_skills = [r["name"] for r in s.run("MATCH (n:Skill) RETURN n.name AS name")]
        live_books = [r["name"] for r in s.run("MATCH (n:Book) WHERE NOT n:CorpusBook RETURN n.name AS name")]
        print(f"live vocabulary: {len(live_skills)} :Skill, {len(live_books)} :Book")

        src = load_sources(skip_chunks=args.skip_chunks)
        print(f"sources: {len(src['questions'])} questions, "
              f"{len(src['converted'])} converted, {len(src['chunks'])} chunks")

        payload, stats, orphans = plan(src, live_skills, live_books)

        planned = {k: len(v) for k, v in payload.items()}
        if args.dry_run:
            print("\n=== DRY RUN — would write ===")
            for k, v in planned.items():
                print(f"  {k:26s} {v:7d}")
            print("\n=== orphan classes ===")
            for k, v in orphans.items():
                print(f"  {k:44s} {v:7d}")
            print("\n=== stats ===")
            print(json.dumps(stats, indent=2, default=str))
            driver.close()
            return 0

        for c in CONSTRAINTS:
            s.run(c)

        written = collections.OrderedDict()
        for key, label, cypher in WRITES:
            rows = payload.get(key, [])
            t = time.time()
            n = write_batches(s, cypher, rows)
            written[label] = n
            print(f"  wrote {label:26s} {n:7d}  ({time.time()-t:.1f}s)")

        after = snapshot(s)

    problems = assert_unchanged(before, after)
    wall = time.time() - t0

    actual_new = {}
    with driver.session() as s:
        for lab in NEW_LABELS:
            actual_new[lab] = s.run(f"MATCH (n:`{lab}`) RETURN count(n) AS c").single()["c"]
        actual_rels = {}
        for rt in NEW_RELS:
            actual_rels[rt] = s.run(f"MATCH ()-[r:`{rt}`]->() RETURN count(r) AS c").single()["c"]
        # edge breakdown by target label for the polymorphic types
        actual_rels["FROM_BOOK(Question->Book)"] = s.run(
            "MATCH (:Question)-[r:FROM_BOOK]->(:Book) RETURN count(r) AS c").single()["c"]
        actual_rels["FROM_BOOK(Question->CorpusBook)"] = s.run(
            "MATCH (:Question)-[r:FROM_BOOK]->(:CorpusBook) RETURN count(r) AS c").single()["c"]
        actual_rels["FROM_BOOK(Chunk->Book)"] = s.run(
            "MATCH (:Chunk)-[r:FROM_BOOK]->(:Book) RETURN count(r) AS c").single()["c"]
        actual_rels["COVERS(Chapter->Skill)"] = s.run(
            "MATCH (:Chapter)-[r:COVERS]->(:Skill) RETURN count(r) AS c").single()["c"]
        actual_rels["COVERS(Chapter->ExamTopic)"] = s.run(
            "MATCH (:Chapter)-[r:COVERS]->(:ExamTopic) RETURN count(r) AS c").single()["c"]

        # ---- servability reach, measured IN the unified graph ---------------
        # NB PREREQUISITE_OF is Skill->Problem (see memory neo4j-live-graph-schema).
        reach = {}
        reach["questions_total"] = s.run("MATCH (q:Question) RETURN count(q) AS c").single()["c"]
        reach["questions_playable"] = s.run(
            "MATCH (q:Question {playable:true}) RETURN count(q) AS c").single()["c"]
        reach["questions_reaching_live_skill"] = s.run(
            "MATCH (q:Question)-[:EXERCISES]->(:Skill) RETURN count(DISTINCT q) AS c").single()["c"]
        reach["questions_playable_and_reaching_live_skill"] = s.run(
            "MATCH (q:Question {playable:true})-[:EXERCISES]->(:Skill) "
            "RETURN count(DISTINCT q) AS c").single()["c"]
        reach["questions_on_skills_with_existing_problems"] = s.run(
            "MATCH (s:Skill)-[:PREREQUISITE_OF]->(:Problem) WITH collect(DISTINCT s) AS ss "
            "MATCH (q:Question)-[:EXERCISES]->(s2:Skill) WHERE s2 IN ss "
            "RETURN count(DISTINCT q) AS c").single()["c"]
        reach["questions_on_skills_with_zero_problems"] = (
            reach["questions_reaching_live_skill"] - reach["questions_on_skills_with_existing_problems"])
        reach["questions_with_prerequisite_closure"] = s.run(
            "MATCH (q:Question)-[:EXERCISES]->(:Skill)-[:REQUIRES]->() "
            "RETURN count(DISTINCT q) AS c").single()["c"]
        reach["questions_on_stub_skills"] = s.run(
            "MATCH (q:Question)-[:EXERCISES]->(s:Skill) WHERE s.is_stub "
            "RETURN count(DISTINCT q) AS c").single()["c"]
        reach["distinct_skills_touched"] = s.run(
            "MATCH (:Question)-[:EXERCISES]->(s:Skill) RETURN count(DISTINCT s) AS c").single()["c"]
        reach["skill_vocabulary_exercised_pct"] = round(
            100.0 * reach["distinct_skills_touched"] / max(1, before["labels"].get("Skill", 1)), 1)
        reach["chunks_sharing_a_book_with_questions"] = s.run(
            "MATCH (c:Chunk)-[:FROM_BOOK]->(b)<-[:FROM_BOOK]-(:Question) "
            "RETURN count(DISTINCT c) AS c").single()["c"]
        reach["converted_templates_reaching_live_skill"] = s.run(
            "MATCH (:ConvertedTemplate)-[:DERIVED_FROM]->(q:Question)-[:EXERCISES]->(:Skill) "
            "RETURN count(DISTINCT q) AS c").single()["c"]
    driver.close()

    report = {
        "generated": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "loader": "scripts/build_unified_graph.py",
        "wall_seconds": round(wall, 1),
        "serving_graph_unchanged": not problems,
        "invariant_violations": problems,
        "before": before,
        "after": after,
        "protected_before": protected_view(before),
        "protected_after": protected_view(after),
        "planned_writes": planned,
        "rows_sent": written,
        "new_label_counts": actual_new,
        "new_rel_counts": actual_rels,
        "orphans": orphans,
        "reach": reach,
        "stats": stats,
    }
    Path(args.report).parent.mkdir(parents=True, exist_ok=True)
    Path(args.report).write_text(json.dumps(report, indent=2, default=str))

    print(f"\nwall: {wall:.1f}s   report: {args.report}")
    if problems:
        print("\n!!! SERVING GRAPH MUTATED — THIS IS A BUG !!!")
        for p in problems:
            print("   ", p)
        return 2
    print("serving graph VERIFIED UNCHANGED "
          f"({len(protected_view(before)['labels'])} labels, "
          f"{len(protected_view(before)['rels'])} rel types, 6 :Book fingerprints)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
