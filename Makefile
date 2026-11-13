# Targets are added as phases land. PYTHON can point at any venv interpreter.
PYTHON ?= python

.PHONY: install test lint

install:
	$(PYTHON) -m pip install -e "backend[dev]"

test:
	$(PYTHON) -m pytest backend/tests

lint:
	$(PYTHON) -m ruff check backend
