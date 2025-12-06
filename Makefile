.PHONY: f format

f: format

format:
	black .
	isort .
	npx prettier --write "**/*.yaml"
