# VMSG dev workflow. DBs need Docker Desktop (or a compatible engine).

VENV ?= .venv/bin

.PHONY: db-up db-down migrate seed verify-files verify-db test test-api typecheck api-dev game-dev

db-up:
	docker compose up -d postgres neo4j redis

db-down:
	docker compose down

migrate:
	$(VENV)/python scripts/migrate.py

seed:
	$(VENV)/python scripts/seed.py

verify-files:
	python3 scripts/verify_seed.py --files

verify-db:
	$(VENV)/python scripts/verify_seed.py --db

test:
	npx vitest run

test-api:
	cd services/api && ../../$(VENV)/python -m pytest -q

typecheck:
	npm run typecheck

api-dev:
	cd services/api && ../../$(VENV)/uvicorn app.main:app --reload --port 8000

game-dev:
	cd apps/game-server && npm run dev
