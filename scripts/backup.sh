#!/usr/bin/env bash
# VMSG backup — the project already died once from having no backup.
# Dumps Postgres (Ledger) and Neo4j (GPS) from the compose stack, archives the
# gitignored incoming/ recovery corpus and bundles the whole git history.
# Run nightly and copy $BACKUP_DIR somewhere durable (external disk, S3, Drive).
#
#   BACKUP_DIR=/Volumes/backup/vmsg ./scripts/backup.sh
set -euo pipefail
cd "$(dirname "$0")/.."
export PATH="/Applications/Docker.app/Contents/Resources/bin:$PATH"

BACKUP_DIR="${BACKUP_DIR:-./backups}"
STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
DEST="$BACKUP_DIR/$STAMP"
mkdir -p "$DEST"

echo "-> Postgres"
docker compose exec -T postgres pg_dump -U vmsg -d vmsg --no-owner --format=custom > "$DEST/vmsg.pgdump"

echo "-> Neo4j data directory (community edition has no online dump; quiesce writers first)"
docker compose exec -T neo4j tar czf - /data/databases /data/transactions > "$DEST/neo4j-data.tgz"

if [ -d incoming ]; then
  echo "-> incoming/ (gitignored recovery corpus)"
  tar czf "$DEST/incoming.tgz" incoming
fi

echo "-> git bundle (every branch, every commit)"
git bundle create "$DEST/repo.bundle" --all

(cd "$DEST" && shasum -a 256 -- * > SHA256SUMS)
du -sh "$DEST"
echo "done: $DEST"
