ifeq ($(OS),Windows_NT)
PYTHON := .venv/Scripts/python.exe
else
PYTHON := .venv/bin/python
endif
BOOTSTRAP ?= python
OUTPUT ?= backups/library.sqlite3
BACKUP ?=

.PHONY: install setup run check lint sast test mutation migrate backup restore verify
install setup:
	$(BOOTSTRAP) setup_local.py
run:
	$(PYTHON) app.py run
check verify:
	$(PYTHON) scripts/checks.py verify
lint sast test mutation:
	$(PYTHON) scripts/checks.py $@
migrate:
	$(PYTHON) app.py migrate
backup:
	$(PYTHON) app.py backup --output "$(OUTPUT)"
restore:
	$(PYTHON) app.py restore --input "$(BACKUP)" --output "$(OUTPUT)"
