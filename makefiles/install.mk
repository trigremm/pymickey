# install.mk - Pip install commands

.PHONY: install i

install:
	pip install -e .

i: install
