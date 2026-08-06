.PHONY: backend-install backend-dev backend-test backend-integration-test backend-lint backend-typecheck backend-check backend-check-integration compose-check db-up db-down db-reset db-smoke check

UV ?= python3 -m uv

backend-install:
	$(UV) --directory backend sync --all-groups

backend-dev:
	$(UV) --directory backend run uvicorn app.main:create_app --factory --reload

backend-test:
	$(UV) --directory backend run pytest -m "not integration"

backend-integration-test:
	$(UV) --directory backend run pytest --run-integration -m integration

backend-lint:
	$(UV) --directory backend run ruff check .

backend-typecheck:
	$(UV) --directory backend run mypy

backend-check: backend-lint backend-typecheck backend-test

backend-check-integration: backend-lint backend-typecheck backend-test backend-integration-test

compose-check:
	docker compose config -q

db-up:
	docker compose up -d --wait postgres

db-down:
	docker compose down

db-reset:
	docker compose down --volumes --remove-orphans
	docker compose up -d postgres

db-smoke:
	./scripts/database-smoke-test.sh

check: compose-check backend-check db-up db-smoke backend-integration-test
