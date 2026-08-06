.PHONY: backend-install backend-dev backend-test backend-lint backend-typecheck backend-check

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
