// Idempotent loader for derived Skill->Skill REQUIRES edges (RAG workstream).
// Run AFTER the graph is re-seeded from db_exports. Params: $edges = rows of
// {from, to, source, support} from data/factory/skill_requires_edges_v1.jsonl.
// Curated live edges are untouched (MERGE matches them); derived edges carry provenance.
UNWIND $edges AS e
MATCH (a:Skill {name: e.from}), (b:Skill {name: e.to})
MERGE (a)-[r:REQUIRES]->(b)
ON CREATE SET r.source = e.source, r.support = e.support, r.created_by = 'skill_dag_builder_v1'
SET r.support = e.support;
