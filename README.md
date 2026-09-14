# Autonomous Grid Agent

Python 3.11 project for a turn-based autonomous agent.

## Requirements

- Python 3.11
- No runtime dependencies outside the Python standard library

## Run

```bash
bash run.sh 8000
```

The service listens on `0.0.0.0:<port>` and accepts JSON `POST` requests at `/`.
If the system `python3` is not Python 3.11 or newer, select an interpreter with
`PYTHON_BIN=/path/to/python3.11 bash run.sh 8000`.

## Test

```bash
make test
```

The interpreter used by development commands can be selected with
`make test PYTHON=/path/to/python3.11`.

To exercise a running server:

```bash
make smoke PORT=8000
```

## Layout

```text
solution/           submission source code
tests/              synthetic and sanitized tests
tools/diagnostics/  bounded read-only diagnostic tools
docs/               public-safe technical documentation
local/              confidential local notes, excluded from Git
all/                confidential source material, excluded from Git
```

The baseline planner is enabled: it builds defenses, gathers and sells resources,
uses upgrades, returns controllers before night, coordinates weapon fire, and
resumes nearby supply runs after the local threat is cleared. Task solving uses
validated structured LLM responses and bounded task-sandbox diagnostics.

Select a strategy configuration with:

```bash
AGENT_CONFIG=config/baseline.json bash run.sh 8000
# Comparison composition:
AGENT_CONFIG=config/balanced.json bash run.sh 8000
```

An omitted configuration uses baseline defaults. Invalid configuration fails
explicitly at startup. A configuration containing `{"enabled": false}` restores
the empty-command behavior. See `docs/baseline.md` for mechanics and limits.

Synthetic HTTP checks and bounded local replay:

```bash
python3.11 tools/diagnostics/smoke_http.py --port 8000 --scenario day
python3.11 tools/diagnostics/smoke_http.py --port 8000 --scenario night
python3.11 tools/diagnostics/replay.py local/turns.jsonl --limit 100
```

Replay reads one request object per JSONL line and prints only aggregate metrics.
It never executes emitted sandbox commands or sends requests to a platform.

## Safety

Before committing or pushing, inspect the staged file list and confirm that local source material, logs, replays, archives, and unsanitized fixtures are excluded.
