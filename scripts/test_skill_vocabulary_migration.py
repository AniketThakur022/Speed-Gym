#!/usr/bin/env python3
"""Prove the paired mastery migration against SEEDED rows, then roll back.

The live mastery tables are empty, so applying the migration against them proves
nothing. This seeds a row into every skill-keyed surface — including the two
cases that actually bite: a UNIQUE-constraint collision where a user already
holds state under BOTH the loser and the survivor, and a JSONB object keyed by
skill name — runs the real migration code, asserts, and ROLLS BACK.

    python3 scripts/test_skill_vocabulary_migration.py
"""
from __future__ import annotations

import sys
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from migrate_skill_vocabulary import (  # noqa: E402
    DATABASE_URL, NEO4J_URI, NEO4J_USER, NEO4J_PASSWORD,
    build_plan, migrate_pg_keys, repoint_qmatrix,
)

FAILURES: list[str] = []


def check(name, actual, expected):
    ok = actual == expected
    print(f"  [{'OK ' if ok else 'FAIL'}] {name}: {actual!r}"
          + ("" if ok else f" (expected {expected!r})"))
    if not ok:
        FAILURES.append(name)


def main() -> int:
    import psycopg
    from neo4j import GraphDatabase

    driver = GraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USER, NEO4J_PASSWORD))
    with driver.session() as neo:
        plan = build_plan(neo)
    driver.close()

    # Use the live plan when there is one. Once the migration has been applied
    # the plan is empty by construction, so fall back to a SYNTHETIC plan built
    # from real surviving skill names — the point is to exercise the migration
    # code against seeded rows, and that must stay possible on a migrated DB.
    if plan["merges"]:
        loser, survivor = sorted(plan["merges"].items())[0]
        gone = plan["deletes"][0]
    else:
        with GraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USER, NEO4J_PASSWORD)) as d2:
            with d2.session() as neo:
                survivor = neo.run(
                    "MATCH (s:Skill)-[:PREREQUISITE_OF]->() RETURN s.name AS n "
                    "ORDER BY n LIMIT 1").single()["n"]
        loser = survivor.lower() if survivor.lower() != survivor else survivor + " (variant)"
        gone = "Chapter 11"
        plan = {"merges": {loser: survivor}, "deletes": [gone],
                "reasons": {loser: "synthetic"}, "groups": [], "nodes": {}, "conflicts": []}
        print("(live plan is empty — migration already applied; using a synthetic plan)")
    print(f"seeding with loser={loser!r} -> survivor={survivor!r}, structural={gone!r}\n")

    uid = uuid.uuid4()
    with psycopg.connect(DATABASE_URL, autocommit=False) as pg:
        cur = pg.cursor()
        cur.execute("INSERT INTO users (id, email) VALUES (%s, %s)",
                    (uid, f"vocab-test-{uid}@example.invalid"))

        # 1. plain rename
        cur.execute("INSERT INTO user_technique_states (id, user_id, technique_id, "
                    "mastery_score) VALUES (%s,%s,%s,%s)", (uuid.uuid4(), uid, loser, 71))
        # 2. UNIQUE(user_id, technique_id) collision: same user already holds the survivor
        cur.execute("INSERT INTO user_technique_states (id, user_id, technique_id, "
                    "mastery_score) VALUES (%s,%s,%s,%s)", (uuid.uuid4(), uid, survivor, 42))
        # 3. no-unique table -> plain UPDATE
        cur.execute("INSERT INTO technique_state_transitions (id, user_id, technique_id, "
                    "to_state) VALUES (%s,%s,%s,%s)", (uuid.uuid4(), uid, loser, 'fragile'))
        # 4. two key columns on one table
        cur.execute("INSERT INTO sinking_skills (user_id, technique_id, "
                    "technique_canonical_id) VALUES (%s,%s,%s)", (uid, loser, loser))
        # 5. JSONB object KEYED by skill name
        cur.execute("INSERT INTO bkt_state_snapshots (user_id, technique_states, "
                    "snapshot_reason) VALUES (%s,%s::jsonb,%s)",
                    (uid, '{"%s": {"pLearned": 0.61}}' % loser, 'session_end'))
        # 6. JSONB collision: both keys present in one blob
        cur.execute("INSERT INTO bkt_state_snapshots (user_id, technique_states, "
                    "snapshot_reason) VALUES (%s,%s::jsonb,%s)",
                    (uid, '{"%s": {"pLearned": 0.61}, "%s": {"pLearned": 0.9}}'
                     % (loser, survivor), 'session_end'))
        # 7. pending outbox payload (a drained row must NOT be touched)
        for status in ("pending", "drained"):
            cur.execute("INSERT INTO sync_outbox (user_id, event_id, event_type, payload, "
                        "status) VALUES (%s,%s,%s,%s::jsonb,%s)",
                        (uid, uuid.uuid4(), 'session_end',
                         '{"technique_states": {"%s": {"pLearned": 0.5}}}' % loser, status))
        # 8. Q-matrix rows: a plain re-point and a PK collision
        cur.execute("INSERT INTO problem_requirements (skill_name, template_id) "
                    "VALUES (%s,%s) ON CONFLICT DO NOTHING", (loser, 'VOCAB_TEST_1'))
        cur.execute("INSERT INTO problem_requirements (skill_name, template_id) "
                    "VALUES (%s,%s) ON CONFLICT DO NOTHING", (loser, 'VOCAB_TEST_2'))
        cur.execute("INSERT INTO problem_requirements (skill_name, template_id) "
                    "VALUES (%s,%s) ON CONFLICT DO NOTHING", (survivor, 'VOCAB_TEST_2'))
        cur.execute("INSERT INTO problem_requirements (skill_name, template_id) "
                    "VALUES (%s,%s) ON CONFLICT DO NOTHING", (gone, 'VOCAB_TEST_3'))

        print("running migrate_pg_keys + repoint_qmatrix against the seeded rows:")
        migrate_pg_keys(cur, plan, dry=False)
        repoint_qmatrix(cur, plan, dry=False)

        print("\nassertions:")
        cur.execute("SELECT technique_id, mastery_score FROM user_technique_states "
                    "WHERE user_id = %s ORDER BY technique_id", (uid,))
        rows = cur.fetchall()
        check("uts: collision collapsed to one row", len(rows), 1)
        check("uts: survivor's own row kept (not the loser's)", rows[0], (survivor, 42))

        cur.execute("SELECT technique_id FROM technique_state_transitions WHERE user_id=%s", (uid,))
        check("transitions: renamed", cur.fetchone()[0], survivor)

        cur.execute("SELECT technique_id, technique_canonical_id FROM sinking_skills "
                    "WHERE user_id=%s", (uid,))
        check("sinking_skills: both key columns renamed", cur.fetchone(), (survivor, survivor))

        cur.execute("SELECT technique_states FROM bkt_state_snapshots WHERE user_id=%s "
                    "ORDER BY technique_states::text", (uid,))
        blobs = [r[0] for r in cur.fetchall()]
        check("bkt: no blob still carries the loser key",
              any(loser in b for b in blobs), False)
        check("bkt: every blob now carries the survivor key",
              all(survivor in b for b in blobs), True)
        check("bkt: plain rename preserved the value",
              sorted(b[survivor]["pLearned"] for b in blobs), [0.61, 0.9])

        cur.execute("SELECT status, payload->'technique_states' FROM sync_outbox "
                    "WHERE user_id=%s ORDER BY status", (uid,))
        ob = dict(cur.fetchall())
        check("outbox: pending row rekeyed", list(ob['pending'].keys()), [survivor])
        check("outbox: drained row left alone (historical record)",
              list(ob['drained'].keys()), [loser])

        cur.execute("SELECT skill_name, template_id FROM problem_requirements "
                    "WHERE template_id LIKE 'VOCAB_TEST%%' ORDER BY template_id")
        qm = cur.fetchall()
        check("q-matrix: re-pointed, PK collision dropped, structural row deleted",
              qm, [(survivor, 'VOCAB_TEST_1'), (survivor, 'VOCAB_TEST_2')])

        # Idempotency: a second pass over the same rows must change nothing.
        before = (rows, blobs, qm)
        migrate_pg_keys(cur, plan, dry=False)
        repoint_qmatrix(cur, plan, dry=False)
        cur.execute("SELECT technique_id, mastery_score FROM user_technique_states "
                    "WHERE user_id=%s ORDER BY technique_id", (uid,))
        check("idempotent: uts unchanged on second pass", cur.fetchall(), before[0])
        cur.execute("SELECT skill_name, template_id FROM problem_requirements "
                    "WHERE template_id LIKE 'VOCAB_TEST%%' ORDER BY template_id")
        check("idempotent: q-matrix unchanged on second pass", cur.fetchall(), before[2])

        pg.rollback()
        print("\nrolled back — no seeded row persisted.")

    print(f"\n{'FAILED: ' + ', '.join(FAILURES) if FAILURES else 'ALL CHECKS PASSED'}")
    return 1 if FAILURES else 0


if __name__ == "__main__":
    raise SystemExit(main())
