# install.mk - Pip install commands

.PHONY: install

install: pull
	pip install -e .

i: install
