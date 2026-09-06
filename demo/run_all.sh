#!/usr/bin/env bash
# Speed Gym — run every workstream demo against the live stack.
#
#   ./demo/run_all.sh            # run all three
#   ./demo/run_all.sh backend    # run one
#
# Requires the dev stack up:  docker compose up -d   (Postgres 5432, Neo4j 7687, Redis 6379)
# and the API on :8000        (uvicorn app.main:app --app-dir services/api)
set -uo pipefail
cd "$(dirname "$0")/.."
ROOT="$PWD"
DOCKER="${DOCKER:-/Applications/Docker.app/Contents/Resources/bin/docker}"
pass=0; fail=0

say()  { printf '\n\033[1;38;5;191m▌ %s\033[0m\n' "$1"; }
ok()   { printf '  \033[0;32m✓\033[0m %s\n' "$1"; pass=$((pass+1)); }
bad()  { printf '  \033[0;31m✗\033[0m %s\n' "$1"; fail=$((fail+1)); }

say "Preflight — is the stack up?"
"$DOCKER" ps --format '{{.Names}}' 2>/dev/null | grep -q speedgym-postgres && ok "Postgres" || bad "Postgres not running"
"$DOCKER" ps --format '{{.Names}}' 2>/dev/null | grep -q speedgym-neo4j    && ok "Neo4j"    || bad "Neo4j not running"
"$DOCKER" ps --format '{{.Names}}' 2>/dev/null | grep -q speedgym-redis    && ok "Redis"    || bad "Redis not running"
[ "$(curl -s -m 3 -o /dev/null -w '%{http_code}' http://localhost:8000/health)" = "200" ] \
  && ok "API :8000" || bad "API not answering on :8000"

run_one() {
  local name="$1"
  local script
  for ext in sh py; do
    [ -f "$ROOT/demo/demo_${name}.${ext}" ] && script="$ROOT/demo/demo_${name}.${ext}" && break
  done
  if [ -z "${script:-}" ]; then bad "no demo script for '$name'"; return; fi
  say "Demo — ${name}"
  case "$script" in
    *.sh) bash "$script" ;;
    *.py) python3 "$script" ;;
  esac && ok "${name} demo completed → demo/output/${name}.json" || bad "${name} demo exited non-zero"
}

if [ $# -gt 0 ]; then
  for a in "$@"; do run_one "$a"; done
else
  for a in backend rag extraction; do run_one "$a"; done
fi

say "Summary"
printf '  %d checks passed, %d failed\n' "$pass" "$fail"
printf '  Captured output: %s/demo/output/*.json\n\n' "$ROOT"
[ "$fail" -eq 0 ]
