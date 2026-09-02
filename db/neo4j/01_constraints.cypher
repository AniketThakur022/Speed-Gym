// ============================================================================
// VMSG Neo4j migration 01 — constraints & indexes for the LIVE graph schema
// Schema source of truth: db_exports/manifest.json (2026-06-03 export of the
// live DB). Live labels: Skill / Problem / SolveAlong / Explainer / Trap /
// Sutra / Book — NOT the stale :Technique/:LogicTrap DDL labels.
// ============================================================================

// Uniqueness on each label's export key field
CREATE CONSTRAINT skill_name IF NOT EXISTS
FOR (s:Skill) REQUIRE s.name IS UNIQUE;

CREATE CONSTRAINT sutra_name IF NOT EXISTS
FOR (s:Sutra) REQUIRE s.name IS UNIQUE;

CREATE CONSTRAINT book_name IF NOT EXISTS
FOR (b:Book) REQUIRE b.name IS UNIQUE;

CREATE CONSTRAINT explainer_template_id IF NOT EXISTS
FOR (e:Explainer) REQUIRE e.template_id IS UNIQUE;

CREATE CONSTRAINT problem_template_id IF NOT EXISTS
FOR (p:Problem) REQUIRE p.template_id IS UNIQUE;

CREATE CONSTRAINT solvealong_template_id IF NOT EXISTS
FOR (sa:SolveAlong) REQUIRE sa.template_id IS UNIQUE;

// Trap: NO uniqueness. The export keys 776 nodes by trap_id and 132 by
// trap_name; 24 category-level names span ~908 nodes (2026-06-03 graph fix:
// the old logictrap_name uniqueness constraint was dropped deliberately —
// do not re-add it). Non-unique indexes only:
CREATE INDEX trap_id_idx IF NOT EXISTS FOR (t:Trap) ON (t.trap_id);
CREATE INDEX trap_name_idx IF NOT EXISTS FOR (t:Trap) ON (t.trap_name);

// Query-path indexes
CREATE INDEX skill_topic_idx IF NOT EXISTS FOR (s:Skill) ON (s.topic);
CREATE INDEX skill_name_norm_idx IF NOT EXISTS FOR (s:Skill) ON (s.name_norm);
CREATE INDEX problem_topic_idx IF NOT EXISTS FOR (p:Problem) ON (p.topic);
CREATE INDEX problem_technique_idx IF NOT EXISTS FOR (p:Problem) ON (p.technique);
CREATE INDEX problem_validation_idx IF NOT EXISTS FOR (p:Problem) ON (p.validation_status);
CREATE INDEX solvealong_technique_norm_idx IF NOT EXISTS FOR (sa:SolveAlong) ON (sa.technique_norm);
CREATE INDEX solvealong_topic_idx IF NOT EXISTS FOR (sa:SolveAlong) ON (sa.topic);
CREATE INDEX explainer_topic_idx IF NOT EXISTS FOR (e:Explainer) ON (e.topic);
CREATE INDEX explainer_technique_norm_idx IF NOT EXISTS FOR (e:Explainer) ON (e.technique_norm);
