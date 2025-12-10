.PHONY: f format

f: format

format:
	autoflake --remove-all-unused-imports --remove-unused-variables --in-place --recursive .
	isort --force-single-line-imports --line-length 120 .
	black --line-length 120 .
	npx prettier --write "**/*.yaml"
