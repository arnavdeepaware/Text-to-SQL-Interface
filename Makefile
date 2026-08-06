.PHONY: backend-install backend-dev backend-test backend-lint backend-typecheck backend-check db-up db-down db-reset db-smoke

UV ?= python3 -m uv

backend-install:
	$(UV) --directory backend sync --all-groups

backend-dev:
	$(UV) --directory backend run uvicorn app.main:create_app --factory --reload

backend-test:
	$(UV) --directory backend run pytest

backend-lint:
	$(UV) --directory backend run ruff check .

backend-typecheck:
	$(UV) --directory backend run mypy

backend-check: backend-lint backend-typecheck backend-test

db-up:
	docker compose up -d postgres

db-down:
	docker compose down

db-reset:
	docker compose down --volumes --remove-orphans
	docker compose up -d postgres

db-smoke:
	./scripts/database-smoke-test.sh
