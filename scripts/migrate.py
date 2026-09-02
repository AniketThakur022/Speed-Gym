#!/usr/bin/env python3
"""VMSG migrations — applies db/postgres/*.sql then db/neo4j/*.cypher.

Pure Python drivers (psycopg + neo4j), no psql/cypher-shell needed, so the
same tool works against local Docker and managed cloud tiers. Applied files
are recorded in schema_migrations; re-runs are no-ops. Files under
db/neo4j/loaders/ and reference_queries.cypher are never applied.

Usage:
  python3 scripts/migrate.py            # apply pending
  python3 scripts/migrate.py --dry-run  # list pending without applying
  python3 scripts/migrate.py --pg-only / --neo4j-only
"""

from __future__ import annotations

import argparse
import hashlib
import os
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PG_DIR = ROOT / "db" / "postgres"
NEO_DIR = ROOT / "db" / "neo4j"

DATABASE_URL = os.environ.get("DATABASE_URL", "postgresql://vmsg:vmsg@localhost:5432/vmsg")
NEO4J_URI = os.environ.get("NEO4J_URI", "bolt://localhost:7687")
NEO4J_USER = os.environ.get("NEO4J_USER", "neo4j")
NEO4J_PASSWORD = os.environ.get("NEO4J_PASSWORD", "vmsg-dev-password")


def sha256(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def _order_key(path: Path) -> tuple[int, str]:
    """Order by the numeric prefix, not lexicographically.

    Plain string sorting puts "100_gaming.sql" BEFORE "10_create_core.sql"
    (compare "10" then '0' < '_'), so a fresh database would try to create the
    gaming tables before the users table they reference. The lost build
    renumbered to 00/10/20/... for exactly this class of ordering hazard.
    """
    match = re.match(r"^(\d+)", path.name)
    return (int(match.group(1)) if match else 10**9, path.name)


def pg_migrations() -> list[Path]:
    return sorted(PG_DIR.glob("*.sql"), key=_order_key)


def neo4j_migrations() -> list[Path]:
    return sorted(
        (p for p in NEO_DIR.glob("*.cypher") if p.name != "reference_queries.cypher"),
        key=_order_key,
    )


def split_cypher(text: str) -> list[str]:
    """Split a cypher file into statements (';' at end of line; // comments stripped)."""
    lines = [l for l in text.splitlines() if not l.strip().startswith("//")]
    statements, buf = [], []
    for line in lines:
        buf.append(line)
        if line.rstrip().endswith(";"):
            stmt = "\n".join(buf).strip().rstrip(";").strip()
            if stmt:
                statements.append(stmt)
            buf = []
    tail = "\n".join(buf).strip()
    if tail:
        statements.append(tail)
    return statements


def migrate_postgres(dry_run: bool) -> None:
    import psycopg

    with psycopg.connect(DATABASE_URL) as conn:
        conn.execute(
            """CREATE TABLE IF NOT EXISTS schema_migrations (
                   filename TEXT PRIMARY KEY,
                   checksum VARCHAR(64) NOT NULL,
                   applied_at TIMESTAMPTZ DEFAULT NOW()
               )"""
        )
        applied = {r[0] for r in conn.execute("SELECT filename FROM schema_migrations")}
        for path in pg_migrations():
            key = f"postgres/{path.name}"
            if key in applied:
                print(f"  = {key} (applied)")
                continue
            if dry_run:
                print(f"  > {key} (pending)")
                continue
            sql = path.read_text()
            print(f"  + {key} ...", end=" ", flush=True)
            conn.execute(sql)
            conn.execute(
                "INSERT INTO schema_migrations (filename, checksum) VALUES (%s, %s)",
                (key, sha256(sql)),
            )
            conn.commit()
            print("ok")


def migrate_neo4j(dry_run: bool) -> None:
    import psycopg
    from neo4j import GraphDatabase

    # Ledger of applied cypher migrations also lives in Postgres.
    with psycopg.connect(DATABASE_URL) as conn:
        conn.execute(
            """CREATE TABLE IF NOT EXISTS schema_migrations (
                   filename TEXT PRIMARY KEY,
                   checksum VARCHAR(64) NOT NULL,
                   applied_at TIMESTAMPTZ DEFAULT NOW()
               )"""
        )
        applied = {r[0] for r in conn.execute("SELECT filename FROM schema_migrations")}
        pending = []
        for path in neo4j_migrations():
            key = f"neo4j/{path.name}"
            if key in applied:
                print(f"  = {key} (applied)")
            elif dry_run:
                print(f"  > {key} (pending)")
            else:
                pending.append((key, path))
        if dry_run or not pending:
            return

        driver = GraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USER, NEO4J_PASSWORD))
        try:
            with driver.session() as session:
                for key, path in pending:
                    text = path.read_text()
                    statements = split_cypher(text)
                    if any(re.search(r"\$rows\b", s) for s in statements):
                        print(f"  ! {key} skipped: requires $rows params (loader, not a migration)")
                        continue
                    print(f"  + {key} ...", end=" ", flush=True)
                    for stmt in statements:
                        session.run(stmt).consume()
                    conn.execute(
                        "INSERT INTO schema_migrations (filename, checksum) VALUES (%s, %s)",
                        (key, sha256(text)),
                    )
                    conn.commit()
                    print("ok")
        finally:
            driver.close()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--pg-only", action="store_true")
    ap.add_argument("--neo4j-only", action="store_true")
    args = ap.parse_args()

    print(f"Postgres: {DATABASE_URL.split('@')[-1]}")
    if not args.neo4j_only:
        migrate_postgres(args.dry_run)
    print(f"Neo4j: {NEO4J_URI}")
    if not args.pg_only:
        migrate_neo4j(args.dry_run)
    print("done")
    return 0


if __name__ == "__main__":
    sys.exit(main())
