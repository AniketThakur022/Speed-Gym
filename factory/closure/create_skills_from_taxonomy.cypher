// :Skill creation worklist — taxonomy_v1.1 graph_backed:false subjects, evidence-ordered by question volume.
// RUN WITH BACKEND: new :Skill nodes touch the BKT mastery join surface. Do not run unilaterally.
// After MERGE: (1) re-run factory/closure/skill_dag_builder.py — unresolved chain mentions may now resolve;
// (2) rebuild closure via factory/closure/live_load.py (shadow diff, then promote);
// (3) the Q-matrix (PREREQUISITE_OF -> :Problem) is NOT created here — that is the corpus->graph mapping block.
UNWIND $skills AS s
MERGE (k:Skill {name: s.name})
ON CREATE SET k.topic = s.topic, k.is_stub = false, k.is_root = false,
              k.source = 'taxonomy_v1_1', k.created_by = 'rag_skill_worklist_2026-09-05',
              k.display_label = s.display_label, k.evidence_questions = s.questions
RETURN count(k) AS merged;
