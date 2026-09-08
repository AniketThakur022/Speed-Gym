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

## Review fixes (blocks 5–9 adversarial pass, 2026-09-06)

- **Backups never land in the repo.** `scripts/backup.sh` defaults to
  `$HOME/vmsg-backups` and REFUSES any destination inside the working tree that
  git does not ignore; `backups/` and `*.pgdump` are gitignored. The nightly
  `tools/daily_commit.sh` runs `git add -A && git push`, so the old `./backups`
  default would have published every `users` row (emails, scrypt hashes,
  kids-mode ages) and `refresh_tokens` to GitHub. Nothing had been dumped yet —
  verified: no `backups/` in any commit and no dump in history.
- **Prod secrets actually come from `.env`.** Compose gives `environment:`
  precedence over `env_file:` and MERGES the two files' maps, so the base
  compose's dev literals (`JWT_SECRET: dev-only-change-me`, `POSTGRES_PASSWORD:
  vmsg`, …) silently won and prod would have signed JWTs with a secret that is
  public in this repo. `docker-compose.prod.yml` now restates each secret as
  `${VAR:?}`, so it is taken from `.env` and compose refuses to start without it.
- **Rate limiting no longer trusts a forged `X-Forwarded-For`.** The header is
  client-supplied on a direct connection (uvicorn runs without
  `--proxy-headers`; Traefik appends), so rotating it gave every request its own
  bucket and password-spraying `/auth/login` was unbounded. `TRUSTED_PROXIES`
  (empty by default = trust nothing) lists the proxies whose header is believed,
  and the RIGHTMOST hop is taken — the address the proxy actually observed.
- **CORS wraps the hardening stack.** Starlette runs the last-added middleware
  outermost, so CORS added first sat innermost and the 429/413 responses that
  RateLimit/BodyLimit short-circuit carried no `Access-Control-Allow-Origin` —
  browsers dropped them and the PWA saw a generic network error, then retried
  into the limiter. `expose_headers` now publishes `X-RateLimit-*`,
  `Retry-After` and `X-Request-Id` so the client can read its own budget.

## Prod port exposure (found 2026-09-09 while wiring the self-hosted data tier)

`docker-compose.prod.yml` carried `ports: []` for the data services under a
comment saying "DB ports are NOT published". **It did not unpublish them.**
Compose MERGES port sequences across files, so the base file's bindings
survived and a production bring-up would have published Postgres 5432, Neo4j
7474 **and** 7687, pgbouncer 6432 and an unauthenticated Redis 6379 on
`0.0.0.0` — the Ledger, the graph and the session store on the public internet.
Same family as the `env_file` precedence defect above: an override that reads
correctly but loses to compose's merge rules.

Fixed with `ports: !override []`, which replaces the list instead of merging.
The API and game server now bind to `127.0.0.1` (override with `APP_BIND_IP`)
so the TLS proxy is the only public entrance. `tests/test_deployment_config.py`
renders the real `docker compose config` and fails if any data service is
published, or if anything binds to all interfaces — reading the YAML would not
have caught this, because the YAML looked right.
