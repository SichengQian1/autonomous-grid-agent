PYTHON ?= python3
PORT ?= 8000
PACKAGE_CONFIG ?= frontline

.PHONY: test run smoke package

test:
	$(PYTHON) -m unittest discover -s tests -v
	$(PYTHON) -m compileall -q solution tests tools

run:
	bash run.sh $(PORT)

smoke:
	$(PYTHON) tools/diagnostics/smoke_http.py --port $(PORT)

package:
	$(PYTHON) tools/package_submission.py --config $(PACKAGE_CONFIG)
