# Targets are added as phases land. PYTHON can point at any venv interpreter.
PYTHON ?= python

.PHONY: install test lint schema schema-check serve docker-runner

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
