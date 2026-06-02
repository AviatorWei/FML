PYTHON  := $(HOME)/anaconda3/envs/fmlwc/bin/python
PYTEST  := $(PYTHON) -m pytest
RUFF    := $(PYTHON) -m ruff
MYPY    := $(PYTHON) -m mypy
SQLITE3 := $(HOME)/anaconda3/envs/fmlwc/bin/sqlite3
DB      ?= fmlwc.db

OUT     ?= player_list.xlsx

.PHONY: test test-v test-cov lint typecheck env-create env-update db-init db-reset db-shell export-players

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

db-init:
	$(PYTHON) scripts/init_db.py $(DB)

db-reset:
	$(PYTHON) scripts/init_db.py $(DB) --reset

db-shell:
	$(SQLITE3) $(DB)

export-players:
	$(PYTHON) scripts/export_players.py --db $(DB) --out $(OUT)
