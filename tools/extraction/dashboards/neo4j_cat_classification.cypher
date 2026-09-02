// ═══════════════════════════════════════════════════════════════════
// CAT Node Classification & Q-Matrix Ingestion
// Generated: 2026-07-08
// Source: /workspace/data/extraction_phase3/cat/
// ═══════════════════════════════════════════════════════════════════

// ── SECTION 1: Create Exam Node ──────────────────────────────────────

MERGE (exam:Exam {name: "CAT", full_name: "Common Admission Test"})
SET exam.subjects = ["Quant", "VARC", "DI", "LR"],
    exam.total_records = 738,
    exam.books = ["CAT_DI_LR_Nishit_K_Sinha", "CAT_VARC_Part1", "CAT_VARC_Part2"];

// ── SECTION 2: Create Subject Nodes ──────────────────────────────────

MERGE (s_di:Subject {name: "DI", exam: "CAT", full_name: "Data Interpretation & Logical Reasoning"});
MERGE (s_varc:Subject {name: "VARC", exam: "CAT", full_name: "Verbal Ability & Reading Comprehension"});

CREATE CONSTRAINT subject_name IF NOT EXISTS
FOR (s:Subject) REQUIRE (s.name, s.exam) IS UNIQUE;

// Link subjects to exam
MERGE (s_di)-[:PART_OF]->(exam);
MERGE (s_varc)-[:PART_OF]->(exam);

// ── SECTION 3: Classify Existing Problems as CAT ─────────────────────

// For each Problem node with source_book matching CAT books, add exam_type
MATCH (p:Problem)
WHERE p.source_book IN ["CAT_DI_LR_Nishit_K_Sinha", "CAT_VARC_Part1", "CAT_VARC_Part2"]
SET p.exam_type = "CAT",
    p.exam_name = "Common Admission Test";

// Link Problems to Subject nodes
MATCH (p:Problem)
WHERE p.source_book = "CAT_DI_LR_Nishit_K_Sinha"
MERGE (p)-[:BELONGS_TO_SUBJECT]->(s:Subject {name: "DI", exam: "CAT"});

MATCH (p:Problem)
WHERE p.source_book IN ["CAT_VARC_Part1", "CAT_VARC_Part2"]
MERGE (p)-[:BELONGS_TO_SUBJECT]->(s:Subject {name: "VARC", exam: "CAT"});

// Link Problems to Exam
MATCH (p:Problem)
WHERE p.exam_type = "CAT"
MERGE (p)-[:BELONGS_TO_EXAM]->(exam:Exam {name: "CAT"});

// ── SECTION 4: Create Cluster Explainer Nodes ────────────────────────

// 90 cluster explainers (from data/extraction_phase3/cat/explainers/explainers.jsonl)
// Run via batch script: python3 assembly_line/neo4j_ingest_explainers.py

// ── SECTION 5: Create Q-Matrix Entry Nodes ───────────────────────────

// 738 Q-matrix entries (from data/extraction_phase3/cat/qmatrix/qmatrix_entries.jsonl)
// Run via batch script: python3 assembly_line/neo4j_ingest_qmatrix.py

// ── SECTION 6: Create Cluster Nodes & Link to Problems ───────────────

// For each unique cluster (subtopic + technique + trap_types + difficulty)
// Create a :Cluster node and link all problems sharing it

// Example Cypher for cluster linking (run via batch):
// MATCH (p:Problem {exam_type: "CAT"})
// WITH p.explainer_cluster_id AS cid, collect(p) AS problems
// WHERE cid IS NOT NULL
// MERGE (c:Cluster {cluster_id: cid})
// WITH c, problems
// UNWIND problems AS p
// MERGE (p)-[:BELONGS_TO_CLUSTER]->(c);

// ── SECTION 7: Create LogicTrap Nodes for DI Custom Traps ────────────

// DI-specific trap taxonomy (from Phase 4)
MERGE (lt1:LogicTrap {name: "CONSTRAINT_OVERLOOK", category: "logic", source: "di_custom_taxonomy"});
MERGE (lt2:LogicTrap {name: "POSITION_CONFUSION", category: "logic", source: "di_custom_taxonomy"});
MERGE (lt3:LogicTrap {name: "ADJACENCY_VIOLATION", category: "logic", source: "di_custom_taxonomy"});
MERGE (lt4:LogicTrap {name: "LEFT_RIGHT_CONFUSION", category: "spatial", source: "di_custom_taxonomy"});
MERGE (lt5:LogicTrap {name: "CLOCKWISE_COUNTER_ERROR", category: "spatial", source: "di_custom_taxonomy"});
MERGE (lt6:LogicTrap {name: "STARTING_DIRECTION_ERROR", category: "spatial", source: "di_custom_taxonomy"});
MERGE (lt7:LogicTrap {name: "CONVERSION_ERROR", category: "logic", source: "di_custom_taxonomy"});
MERGE (lt8:LogicTrap {name: "DISTRIBUTION_ERROR", category: "logic", source: "di_custom_taxonomy"});
MERGE (lt9:LogicTrap {name: "PARTICULAR_UNIVERSAL_CONFUSION", category: "logic", source: "di_custom_taxonomy"});
MERGE (lt10:LogicTrap {name: "GENERATION_SKIP", category: "relation", source: "di_custom_taxonomy"});
MERGE (lt11:LogicTrap {name: "GENDER_ASSUMPTION", category: "relation", source: "di_custom_taxonomy"});
MERGE (lt12:LogicTrap {name: "MUTUAL_EXCLUSION_OVERLOOK", category: "logic", source: "di_custom_taxonomy"});
MERGE (lt13:LogicTrap {name: "MANDATORY_PAIRING_MISSED", category: "logic", source: "di_custom_taxonomy"});
MERGE (lt14:LogicTrap {name: "TIE_HANDLING_ERROR", category: "ordering", source: "di_custom_taxonomy"});
MERGE (lt15:LogicTrap {name: "PARTIAL_ORDER_ASSUMPTION", category: "ordering", source: "di_custom_taxonomy"});
MERGE (lt16:LogicTrap {name: "OVERCOUNTING", category: "counting", source: "di_custom_taxonomy"});
MERGE (lt17:LogicTrap {name: "UNDERCOUNTING", category: "counting", source: "di_custom_taxonomy"});
MERGE (lt18:LogicTrap {name: "DATE_OVERFLOW", category: "temporal", source: "di_custom_taxonomy"});
MERGE (lt19:LogicTrap {name: "LEAP_YEAR_OVERSIGHT", category: "temporal", source: "di_custom_taxonomy"});
MERGE (lt20:LogicTrap {name: "FACING_DIRECTION_ERROR", category: "spatial", source: "di_custom_taxonomy"});
MERGE (lt21:LogicTrap {name: "RELATIVE_POSITION_TRAP", category: "spatial", source: "di_custom_taxonomy"});
MERGE (lt22:LogicTrap {name: "INSUFFICIENT_DATA_ASSUMPTION", category: "logic", source: "di_custom_taxonomy"});
MERGE (lt23:LogicTrap {name: "REDUNDANT_CONDITION_TRAP", category: "logic", source: "di_custom_taxonomy"});

// ── SECTION 8: Verification Queries ──────────────────────────────────

// Count CAT-classified problems
// MATCH (p:Problem {exam_type: "CAT"}) RETURN count(p) as cat_problems;

// Count cluster explainers
// MATCH (e:Explainer) WHERE e.cluster_id IS NOT NULL RETURN count(e) as cluster_explainers;

// Count Q-matrix entries
// MATCH (q:QMatrixEntry) RETURN q.subject, count(q) as entries;

// Count DI custom traps
// MATCH (lt:LogicTrap) WHERE lt.source = "di_custom_taxonomy" RETURN count(lt) as di_traps;

// ═══════════════════════════════════════════════════════════════════
// END OF CAT CLASSIFICATION CYPHER
// ═══════════════════════════════════════════════════════════════════