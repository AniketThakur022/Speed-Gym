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

# NEVER default inside the working tree: tools/daily_commit.sh runs `git add -A`
# at 03:00 and pushes, so a dump written under the repo would publish every
# users row (emails, password hashes, kids-mode ages) and refresh_tokens to
# GitHub. Default outside the repo, and refuse any destination the nightly
# commit could pick up.
BACKUP_DIR="${BACKUP_DIR:-$HOME/vmsg-backups}"
STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
DEST="$BACKUP_DIR/$STAMP"

REPO_ROOT="$(pwd -P)"
mkdir -p "$BACKUP_DIR"
BACKUP_ABS="$(cd "$BACKUP_DIR" && pwd -P)"
case "$BACKUP_ABS/" in
  "$REPO_ROOT"/*)
    # Inside the repo: only allowed if git actually ignores it.
    if ! git check-ignore -q "$BACKUP_ABS" 2>/dev/null; then
      echo "REFUSING: BACKUP_DIR ($BACKUP_ABS) is inside the repo and is NOT gitignored." >&2
      echo "The nightly auto-commit would push the database dump to GitHub." >&2
      echo "Set BACKUP_DIR to a path outside $REPO_ROOT (e.g. an external disk)." >&2
      exit 1
    fi
    ;;
esac

mkdir -p "$DEST"
chmod 700 "$BACKUP_ABS" "$DEST" 2>/dev/null || true

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
