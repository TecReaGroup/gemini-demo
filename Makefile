PYTHON := uv run python

install:
	uv sync

run:
	$(PYTHON) -m gemini_demo

