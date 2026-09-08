# Deployment — Phase 1 (self-hosted, 2 droplets)

Owner decision **2026-09-09**: **Neo4j is self-hosted on our own droplet, not
AuraDB Free** (`decisions-2026-09-09` memory). Everything below implements
architecture §3.2 (Phase-1 physical topology) and §15 (security).

## Why self-hosted

The prerequisite-closure design carries a long OOM analysis that exists *only*
because AuraDB Free pins the JVM to a ceiling we cannot raise. Owning the
process means the heap and page cache are ours to size, so that whole failure
mode disappears. It also keeps the graph — which holds the mastery keys the
Decision Engine reads — on infrastructure we control and can back up ourselves.
The cost is that backups, upgrades and monitoring are now our job; see
**Backups** below, which is not optional given this project already lost its
codebase once to a missing backup.

## Topology

Two shared-CPU droplets, 4 GB RAM each, inside a VPC private network
(INF-SEQ-01). DB and Redis bind to VPC-local addresses only.

| | Droplet A (edge + app) | Droplet B (data) |
| --- | --- | --- |
| Runs | TLS proxy, FastAPI, game server, Celery worker | Postgres + pgvector, Neo4j, Redis |
| Public | 80/443 only | nothing |
| Compose | `docker-compose.app.yml` | `docker-compose.data.yml` |

**Droplet B (bring this up first):**

```bash
DATA_BIND_IP=10.0.0.3 docker compose \
  -f docker-compose.yml -f docker-compose.prod.yml -f docker-compose.data.yml \
  up -d
```

**Droplet A:**

```bash
DATA_HOST=10.0.0.3 docker compose \
  -f docker-compose.yml -f docker-compose.prod.yml -f docker-compose.app.yml \
  --profile app up -d --no-deps api game-server worker
```

`--no-deps` is load-bearing: the base file's `api` has `depends_on` the
databases, so without it compose starts a second, empty Postgres and Neo4j on
Droplet A and the API silently talks to the wrong one.

`DATA_BIND_IP` and `DATA_HOST` have no defaults — an unset value fails the
command instead of binding the Ledger to every interface.

## The RAM budget is the binding constraint

Architecture §3.2 says so explicitly, and risk #8 names the Phase-1 RAM crunch.
Droplet B's ceilings are Neo4j heap ≤1 GB, Neo4j page cache ≤1 GB, Postgres
`shared_buffers` ≤1 GB, Redis `maxmemory` ≤512 MB with `allkeys-lru`.

What is configured, and what it actually costs:

A "4 GB" droplet is 4 GiB = 4096 MiB. Ubuntu + dockerd need roughly 400 MiB, so
the container budget is about **3700 MiB**.

| Service | Setting | `mem_limit` | Real footprint |
| --- | --- | --- | --- |
| Neo4j | heap 1 G (initial = max), page cache 512 M | 2048 MiB | ~1.9 G incl. metaspace + threads |
| Postgres | `shared_buffers=640MB`, `effective_cache_size=1GB`, `work_mem=8MB`, `max_connections=100` | 960 MiB | ~0.9 G with pgbouncer pooling |
| Redis | `maxmemory 512mb`, `allkeys-lru` | 640 MiB | ~0.56 G incl. fragmentation |
| **Total** | | **3648 MiB** | ~448 MiB left for OS + dockerd |

**Two numbers deliberately sit under their ceiling, and this is the reason.**
Running the documented *maxima* together — Neo4j heap 1 G **plus** page cache
1 G (≈2.4 G with JVM overhead), Postgres 1 G (≈1.3 G), Redis 512 M (≈0.56 G) —
totals ≈4.25 G before the OS gets anything, which does not fit 4 GiB. So page
cache is held at 512 M and `shared_buffers` at 640 M. The graph is small
(28.8k nodes / 58.7k edges), so 512 M of page cache still holds it comfortably;
revisit only if the graph grows past roughly 10× that. Every value stays within
the architecture's ceilings — they are maxima, not targets.

This is architecture risk #8 (the Phase-1 RAM crunch) in concrete numbers, and
the documented relief is Stage 1.5: split the data tier onto its own droplet,
after which page cache can go to the full 1 G.

`mem_limit` is set on every service so an overrunning JVM is killed rather than
starving Postgres and Redis on the same box. Without it, one leak takes the
whole data tier down and the failure looks like random query timeouts.

**Do not run both tiers on one droplet.** The app runtimes add roughly
1 G (API) + 0.5 G (game server) + 0.75 G (worker); with the data tier's 3.6 G
that is ~5.9 G on a 4 GB box. The single-host invocation in
`docker-compose.prod.yml` is for staging and local prod-parity only.

## Secrets

Every secret comes from `.env` on each droplet (gitignored, never committed).
`docker-compose.prod.yml` restates each one as `${VAR:?}`, so compose refuses to
start when one is missing rather than falling back to the dev literal that is
public in this repo — see the review note in `docs/backend/HARDENING.md`.

Required on both droplets: `POSTGRES_PASSWORD`, `NEO4J_PASSWORD`, `JWT_SECRET`
(must be byte-identical on A and B's app services — the game server verifies the
API's tokens), `OFFLINE_TOKEN_SECRET`, `INTERNAL_API_KEY`, `TRUSTED_PROXIES`.

`TRUSTED_PROXIES` must list the TLS proxy's address, and nothing else. Set it
wrongly and the rate limiter believes a client-supplied `X-Forwarded-For`.

## Backups

`scripts/backup.sh` dumps Postgres, archives the Neo4j data directory and
bundles the git history. Run it on **Droplet B**, nightly, with `BACKUP_DIR`
pointing at a volume that is **not** on the droplet — the script refuses any
destination inside the repo that git does not ignore, because the nightly
auto-commit would otherwise push the dump to GitHub.

Neo4j Community has no online dump, so the archive step is only consistent if
writers are quiesced: stop the worker (`docker compose stop worker`) or take the
backup during the nightly window when the factory is idle. **A backup that has
never been restored is a hypothesis** — restore into a scratch droplet once
before launch and check `scripts/verify_seed.py` passes against it.

## Monitoring thresholds (GATE-08)

Postgres pool >75 %, Neo4j heap >70 %, Redis latency >1 ms, event ingest >5 ms,
next-problem >300 ms. `GET /health` and `GET /ready` are unauthenticated and
rate-limit exempt for exactly this.

## The two launch gates this unblocks

Both needed a deployed host and now have a target:

- **Security scan** — OWASP ZAP against Droplet A's public surface, plus
  confirmation that Droplet B answers on no public interface (`nmap` from
  outside the VPC should find nothing).
- **Load test** — Phase-1 SLA is 100 req/s at p95 <250 ms with <0.1 % errors
  (AB-03), and 500 concurrent WebSocket duels at p95 msg-latency <100 ms
  (PERF-05). Run k6 against Droplet A; watch the Droplet B thresholds above,
  since the RAM budget — not CPU — is what will bend first.
