PYTHON ?= python3
PORT ?= 8000

.PHONY: test run smoke replay submission

test:
	$(PYTHON) -m unittest discover -s tests -v
	$(PYTHON) -m compileall -q solution tests tools/diagnostics

run:
	bash run.sh $(PORT)

smoke:
	$(PYTHON) tools/diagnostics/smoke_http.py --port $(PORT)

replay:
	$(PYTHON) tools/diagnostics/synthetic_replay.py --side challenger
	$(PYTHON) tools/diagnostics/synthetic_replay.py --side defender

submission:
	$(PYTHON) tools/build_submission.py
