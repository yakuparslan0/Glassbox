# GlassBox developer commands. PYTHON can point at any venv interpreter:  make test PYTHON=~/.venvs/glassbox/bin/python
PYTHON ?= python

.PHONY: install dev test test-backend test-frontend lint schema schema-check build serve docker-runner docker

install:
	$(PYTHON) -m pip install -e "backend[dev]"
	cd frontend && npm ci

# API + UI together (installs the frontend dependencies on first use)
dev:
	$(PYTHON) scripts/dev.py

test: test-backend test-frontend

test-backend:
	$(PYTHON) -m pytest backend/tests

test-frontend:
	cd frontend && npx vitest run

lint:
	$(PYTHON) -m ruff check backend scripts
	cd frontend && npx tsc --noEmit

# Pydantic models -> docs/schema/glassbox.schema.json + frontend/src/types/generated.ts
schema:
	$(PYTHON) scripts/gen_types.py

schema-check:
	$(PYTHON) scripts/gen_types.py --check

build:
	cd frontend && npm run build

serve:
	$(PYTHON) -m glassbox.cli serve

# the locked-down runner image used by SANDBOX_MODE=docker
docker-runner:
	docker build -f docker/runner.Dockerfile -t glassbox-runner backend

# runner + API + web images (read docs/SECURITY.md before exposing anything)
docker: docker-runner
	docker build -f docker/api.Dockerfile -t glassbox-api .
	docker build -f docker/web.Dockerfile -t glassbox-web .
