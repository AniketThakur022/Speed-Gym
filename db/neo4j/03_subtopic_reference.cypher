// ============================================================================
// VMSG Neo4j migration 03 — Subtopic Reference Library (DDL ONLY)
// Source: db_exports/extend_neo4j_subtopic_reference.cypher. That file's
// APOC $rows loaders and data-dependent MERGE passes are seed-time work —
// preserved at db/neo4j/loaders/subtopic_reference_loader.cypher and driven
// by the content tooling, never by migrate.py (FIX #7 discipline).
// ============================================================================

CREATE CONSTRAINT subtopic_id IF NOT EXISTS
FOR (s:SubTopic) REQUIRE s.subtopic_id IS UNIQUE;

CREATE INDEX subtopic_topic_idx IF NOT EXISTS FOR (s:SubTopic) ON (s.topic);
CREATE INDEX subtopic_category_idx IF NOT EXISTS FOR (s:SubTopic) ON (s.category);
CREATE INDEX subtopic_status_idx IF NOT EXISTS FOR (s:SubTopic) ON (s.content_status);
