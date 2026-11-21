.PHONY: install snapshot run test lint browser kestra lineage

export PYTHONPATH := src

install:
	pip install -r requirements.txt
	python3 -m playwright install chromium

snapshot:
	python3 -m recession_watch snapshot

run:
	python3 -m recession_watch run --from-snapshot

test:
	python3 -m pytest -q --ignore=tests/test_browser.py

browser:
	python3 -m pytest -q tests/test_browser.py

lint:
	ruff check src tests

kestra:
	bash scripts/run_kestra.sh

lineage:
	python3 -m recession_watch run --from-snapshot
