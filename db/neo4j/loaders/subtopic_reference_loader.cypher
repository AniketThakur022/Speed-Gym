// Neo4j extension: Subtopic Reference Library nodes and relationships
// Adds :SubTopic nodes and HAS_TECHNIQUE / HAS_TRAP / HAS_EXPLAINER relationships.
// Run after the main webapp_brain graph is loaded.

// ---------------------------------------------------------------------------
// 1. Create :SubTopic nodes from the 28 subtopic explainers
// ---------------------------------------------------------------------------
CALL apoc.periodic.iterate(
  'UNWIND $rows AS row RETURN row',
  'MERGE (s:SubTopic {subtopic_id: row.subtopic_id})
   SET s.category           = row.category,
       s.topic              = row.topic,
       s.sutra              = row.sutra,
       s.sutra_sanskrit     = row.sutra_sanskrit,
       s.translation        = row.translation,
       s.applicability_type = row.applicability_type,
       s.content_status     = row.metadata.content_status,
       s.review_status      = row.metadata.review_status,
       s.completeness_score = row.metadata.completeness_score,
       s.total_techniques   = row.total_techniques,
       s.total_templates    = row.total_templates,
       s.updated_at         = datetime()',
  {batchSize: 100, parallel: false, params: {rows: $rows}}
) YIELD batches, total, errorMessages
RETURN batches, total, errorMessages;

// ---------------------------------------------------------------------------
// 2. Link existing :Sutra nodes to :SubTopic where names match
// ---------------------------------------------------------------------------
MATCH (s:SubTopic)
WHERE s.sutra IS NOT NULL
MATCH (su:Sutra)
WHERE toLower(su.name) = toLower(s.sutra)
  OR toLower(su.name) CONTAINS toLower(s.sutra)
  OR toLower(s.sutra) CONTAINS toLower(su.name)
MERGE (s)-[:DERIVED_FROM]->(su);

// ---------------------------------------------------------------------------
// 3. Create :Technique nodes for each L1-L5 difficulty tab and link to SubTopic
// ---------------------------------------------------------------------------
CALL apoc.periodic.iterate(
  'UNWIND $rows AS row
   UNWIND keys(row.techniques_by_difficulty) AS level
   WITH row, level, row.techniques_by_difficulty[level] AS tech
   RETURN row.subtopic_id AS sid, level, tech',
  'MATCH (s:SubTopic {subtopic_id: sid})
   MERGE (t:Technique {technique_id: tech.technique_id})
   SET t.name           = tech.name,
       t.focus          = tech.focus,
       t.difficulty_level = level,
       t.example_problem  = tech.example.problem,
       t.example_answer   = tech.example.answer,
       t.template_count   = tech.template_count
   MERGE (s)-[:HAS_TECHNIQUE]->(t)',
  {batchSize: 100, parallel: false, params: {rows: $rows}}
) YIELD batches, total, errorMessages
RETURN batches, total, errorMessages;

// ---------------------------------------------------------------------------
// 4. Link existing content nodes to :SubTopic by sub_topic/topic overlap
// ---------------------------------------------------------------------------
// Problems that mention the subtopic
MATCH (s:SubTopic)
MATCH (p:Problem)
WHERE toLower(p.sub_topic) = toLower(s.subtopic_id)
   OR toLower(p.topic)     = toLower(s.topic)
   OR toLower(p.technique)  = toLower(s.subtopic_id)
WITH s, p
LIMIT 10000
MERGE (s)-[:HAS_PRACTICE_PROBLEM]->(p);

// Explainers that belong to this subtopic
MATCH (s:SubTopic)
MATCH (e:Explainer)
WHERE toLower(e.sub_topic) = toLower(s.subtopic_id)
   OR toLower(e.technique)  = toLower(s.subtopic_id)
WITH s, e
LIMIT 10000
MERGE (s)-[:HAS_EXPLAINER]->(e);

// SolveAlong templates
MATCH (s:SubTopic)
MATCH (sa:SolveAlong)
WHERE toLower(sa.sub_topic) = toLower(s.subtopic_id)
   OR toLower(sa.technique)  = toLower(s.subtopic_id)
WITH s, sa
LIMIT 10000
MERGE (s)-[:HAS_SOLVE_ALONG]->(sa);

// Traps attached via existing HAS_TRAP/TEACHES relationships stay intact;
// optionally surface top traps under the subtopic
MATCH (s:SubTopic)
MATCH (tr:Trap)
WHERE toLower(tr.technique) = toLower(s.subtopic_id)
   OR toLower(tr.sub_category) CONTAINS toLower(s.subtopic_id)
WITH s, tr
LIMIT 10000
MERGE (s)-[:HAS_TRAP]->(tr);

// ---------------------------------------------------------------------------
// 5. Subtopic prerequisite chain (placeholder — edit when pedagogy map is ready)
// ---------------------------------------------------------------------------
// Vedic Math foundation before advanced sutras
MATCH (foundation:SubTopic {subtopic_id: "nikhilam_sutra"})
MATCH (advanced:SubTopic)
WHERE advanced.subtopic_id IN [
  "urdhva_tiryak", "yavadunam", "ekanyunena_purvena",
  "puranapuranabhyam", "chalana_kalanabhyam", "seshanyakena_caramena"
]
MERGE (foundation)-[:PREREQUISITE_OF]->(advanced);

// Foundation arithmetic chain
MATCH (basic:SubTopic {subtopic_id: "school_foundation"})
MATCH (arith:SubTopic)
WHERE arith.subtopic_id IN [
  "addition_tricks", "subtraction_tricks", "multiplication_tricks", "division_tricks"
]
MERGE (basic)-[:PREREQUISITE_OF]->(arith);

// ---------------------------------------------------------------------------
// 6. Cross-category dedup gate — templates served in one path exclude from others
// ---------------------------------------------------------------------------
// Template → Topic relationship for context-aware routing
MATCH (sa:SolveAlong)
SET sa.content_paths = ['foundation'];  // default: Foundation path

// Mark cross-path templates (appear in multiple categories)
// Example: Nikhilam templates serve both Vedic Math and General Maths
MATCH (s:SubTopic {subtopic_id: "nikhilam_sutra"})
MATCH (s)-[:HAS_SOLVE_ALONG]->(sa:SolveAlong)
SET sa.content_paths = ['foundation', 'vedic_math', 'general_maths'];

// Exam Prep templates (future)
MATCH (s:SubTopic)
WHERE s.topic = 'Exam Prep'
MATCH (s)-[:HAS_SOLVE_ALONG]->(sa:SolveAlong)
SET sa.content_paths = ['exam_prep'];

// ---------------------------------------------------------------------------
// 7. Dedup query: exclude templates seen in last 7 days
// ---------------------------------------------------------------------------
// MATCH (sa:SolveAlong)
// WHERE sa.subtopic_id = $subtopic_id
//   AND sa.difficulty_level <= $max_difficulty
//   AND NOT sa.template_id IN $recently_seen_ids    ← from Postgres user_recently_seen
//   AND NOT sa.params_hash IN $dedup_hashes          ← from Postgres user_params_dedup
// RETURN sa.template_id, sa.difficulty, sa.content_paths
// ORDER BY rand()
// LIMIT $count;

// ---------------------------------------------------------------------------
// 8. Helper indexes
// ---------------------------------------------------------------------------
CREATE INDEX subtopic_id_idx FOR (s:SubTopic) ON (s.subtopic_id);
CREATE INDEX subtopic_topic_idx FOR (s:SubTopic) ON (s.topic);
