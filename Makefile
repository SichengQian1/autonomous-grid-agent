PYTHON ?= python3
PORT ?= 8000

.PHONY: test run smoke

test:
	$(PYTHON) -m unittest discover -s tests -v
	$(PYTHON) -m compileall -q solution tests tools/diagnostics

run:
	bash run.sh $(PORT)

smoke:
	$(PYTHON) tools/diagnostics/smoke_http.py --port $(PORT)
