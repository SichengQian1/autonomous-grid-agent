#!/usr/bin/env bash
set -eu

SCRIPT_DIR="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
PYTHON_BIN="${PYTHON_BIN:-python3}"
cd "$SCRIPT_DIR"
exec "$PYTHON_BIN" -m solution.main "$@"
