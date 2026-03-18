# format.mk - Ruff-based Python formatting and linting

.PHONY: format-lint format-ruff format-yaml f format

format-lint:
	ruff check --fix . || true

format-ruff:
	ruff format .

format-yaml:
	npx prettier --write "**/*.yaml"

format: format-lint format-ruff format-yaml

f: format
