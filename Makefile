# VMSG dev workflow. DBs need Docker Desktop (or a compatible engine).

VENV ?= .venv/bin

.PHONY: db-up db-down migrate seed verify-files verify-db test test-api typecheck api-dev game-dev backup smoke prod-up

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

backup:
	./scripts/backup.sh

smoke:
	k6 run -e API=$${API:-http://localhost:8000} scripts/load/smoke.js

prod-up:
	docker compose -f docker-compose.yml -f docker-compose.prod.yml --profile app up -d --build
