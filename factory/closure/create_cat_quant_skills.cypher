// CAT quant skills — RUN WITH BACKEND. Touches the BKT mastery join surface.
// Derived 2026-09-09 by an evidence panel over sampled corpus questions, each edge
// adversarially reviewed; 9 of 33 proposed edges were struck. Verified by direct
// tabulation before writing: every prerequisite name exists verbatim as a :Skill,
// and the 24 edges introduce ZERO new cycles (the graph's 3 existing cycles are
// pre-existing and are NOT fixed by this script — see the escalations doc).
//
// STEP 1 — create only the genuinely missing skills. Six of the nine subjects map
// onto skills that already exist; creating nodes for those would re-fragment the
// vocabulary the 2026-09-08 migration consolidated.
UNWIND $new_skills AS s
MERGE (k:Skill {name: s.name})
  ON CREATE SET k.topic = s.topic, k.is_stub = false, k.is_root = false,
                k.display_label = s.display_label,
                k.evidence_questions = s.evidence_questions,
                k.source = 'cat_quant_panel_2026-09-09',
                k.created_by = 'rag_cat_quant_2026-09-09';

// STEP 2 — prerequisite edges (dependent -> prerequisite).
UNWIND $edges AS e
MATCH (a:Skill {name: e.from}), (b:Skill {name: e.to})
MERGE (a)-[r:REQUIRES]->(b)
  ON CREATE SET r.created_by = 'cat_quant_panel_2026-09-09'
SET r.source = e.source, r.confidence = e.confidence;

// STEP 3 — NOT INCLUDED HERE ON PURPOSE. Re-pinning :Problem.mastery_key to split
// Arithmetic 296 / Algebra 200 / Basic Operations 103 is the change that actually
// moves learner mastery, and it must run through scripts/migrate_skill_vocabulary.py's
// pinning path with its paired Postgres/JSONB migration, not as a loose SET here.
