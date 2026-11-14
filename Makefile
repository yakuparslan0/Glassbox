# Targets are added as phases land. PYTHON can point at any venv interpreter.
PYTHON ?= python

.PHONY: install test lint schema schema-check serve docker-runner frontend-install frontend-dev frontend-build frontend-test

install:
	$(PYTHON) -m pip install -e "backend[dev]"

test:
	$(PYTHON) -m pytest backend/tests

lint:
	$(PYTHON) -m ruff check backend scripts

# Pydantic models -> docs/schema/glassbox.schema.json + frontend/src/types/generated.ts
schema:
	$(PYTHON) scripts/gen_types.py

schema-check:
	$(PYTHON) scripts/gen_types.py --check

serve:
	$(PYTHON) -m glassbox.cli serve

# Build the locked-down runner image used by SANDBOX_MODE=docker
docker-runner:
	docker build -f docker/runner.Dockerfile -t glassbox-runner backend

frontend-install:
	cd frontend && npm install

frontend-dev:
	cd frontend && npm run dev

frontend-build:
	cd frontend && npm run build

frontend-test:
	cd frontend && npx vitest run
