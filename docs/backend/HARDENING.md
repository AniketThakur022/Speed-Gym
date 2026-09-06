# Hardening (block 9)

Code: `services/api/app/middleware.py` (installed first in `main.py`), settings
`RATE_LIMIT_PER_MINUTE` (300; 0 disables) and `BEHIND_TLS`; tests `test_hardening.py`.

- **Rate limiting** — fixed one-minute window in Redis per learner (JWT subject) or IP.
  Every response carries `X-RateLimit-Limit` / `X-RateLimit-Remaining` (the contract's
  header); over the limit → 429 + `Retry-After`. Redis down = fail open (traffic
  shaping is not a security boundary). Exempt: `/health`, `/ready`, `/api/config`
  (the kill-switch must answer during an incident), `/api/webhooks/*` (providers retry
  forever on 429), `/internal/*` (loopback, key-guarded).
- **Security headers** on every response; HSTS only when `BEHIND_TLS=true`.
- **Body cap** by Content-Length: 1 MB, 4 MB for `/sync` batches → 413 before any
  handler runs.
- **Request id** (`X-Request-Id`, generated when absent) + one-line JSON access log.
- **Backups** — `scripts/backup.sh` (Postgres custom-format dump, Neo4j data tar, a tar of
  the gitignored `incoming/` corpus, a git bundle of every branch, SHA256SUMS) into
  `BACKUP_DIR`. The project died once from having none; run it nightly and copy the
  directory somewhere durable. `make backup`.
- **Production compose** — `docker-compose.prod.yml`: no published DB ports, `.env`
  secrets, restart policies, API healthcheck, Celery worker+beat service. `make prod-up`.
- **CI** — PWA typecheck added; `security` job runs `pip-audit` and `npm audit`
  (advisory until the baseline is clean).
- **Load** — `scripts/load/smoke.js` (k6, p95 < 500 ms on health/config/plans).

Still open: OWASP ZAP baseline scan and container image signing (GATE-02) need the
deployed host; Traefik TLS termination config lives with the droplet, not here.
