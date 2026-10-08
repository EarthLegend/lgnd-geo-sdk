.PHONY: sync lint fmt test docs docs-serve

sync:
	uv sync

lint:
	uv run pre-commit run --all-files --show-diff-on-failure

fmt:
	uv run ruff check --fix .
	uv run ruff format .

test:
	uv run pytest

docs:
	uv run mkdocs build --strict

docs-serve:
	uv run mkdocs serve
