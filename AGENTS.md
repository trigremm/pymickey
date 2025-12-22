# Repository Guidelines

## Project Structure & Module Organization
- `pymickey/`: Core Python package (CLI entrypoint in `cli.py`, main runner logic in `runner.py`).
- `pymickey_tests/`: Example YAML test scenarios and a small make target (`pymickey.mk`).
- `pyproject.toml`: Packaging metadata and dependencies.
- `Makefile`: Formatting utilities for Python and YAML files.

## Build, Test, and Development Commands
- `pip install -e .`: Install the package in editable mode for local development.
- `pymickey pymickey_tests/test_login.mickey.yaml`: Run a single YAML scenario with the CLI.
- `make -C pymickey_tests test`: Run the sample test target defined in `pymickey_tests/pymickey.mk`.
- `make format`: Run `autoflake`, `isort`, `black`, and `prettier` (YAML only).

## Coding Style & Naming Conventions
- Python follows Black formatting with a 120-column line length.
- Imports are sorted with isort, forced to single-line imports.
- Unused imports/variables are removed via autoflake.
- Indentation is 4 spaces for Python; YAML examples in `pymickey_tests/` follow standard 2-space indentation.
- Scenario files use the `*.mickey.yaml` naming pattern (see `pymickey_tests/test_login.mickey.yaml`).

## Testing Guidelines
- Tests are declarative YAML scenarios executed via the `pymickey` CLI.
- Keep scenario files small and focused; prefer one behavior per file.
- Naming convention: `test_*.mickey.yaml`.
- Example: `pymickey pymickey_tests/test_login.mickey.yaml`.

## Commit & Pull Request Guidelines
- Commit history shows short, imperative messages (e.g., “make format”, “process list response”).
- Use concise subjects; add a brief body if the change is non-trivial.
- PRs should describe behavior changes and include a sample scenario or command output when relevant.

## Configuration Tips
- The CLI entry point is `pymickey` (configured in `pyproject.toml`).
- Dependencies are minimal (`httpx`, `pyyaml`); keep additions lightweight and justified.
