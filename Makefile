PYTHON := uv run python

.PHONY: install run test test-integration

install:
	uv sync

run:
	$(PYTHON) -m gemini_demo

test:
	uv run pytest

test-integration:
	RUN_GEMINI_INTEGRATION=1 uv run pytest -m integration
