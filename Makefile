PYTHON := $(HOME)/anaconda3/envs/fmlwc/bin/python
PYTEST  := $(PYTHON) -m pytest
RUFF    := $(PYTHON) -m ruff
MYPY    := $(PYTHON) -m mypy

.PHONY: test test-v test-cov lint typecheck env-create env-update

test:
	$(PYTEST) tests/

test-v:
	$(PYTEST) tests/ -v

test-cov:
	$(PYTEST) tests/ --cov=fmlwc --cov-report=term-missing

lint:
	$(RUFF) check fmlwc/ tests/

typecheck:
	$(MYPY) fmlwc/

env-create:
	conda env create -f environment.yml

env-update:
	conda env update -n fmlwc -f environment.yml --prune
