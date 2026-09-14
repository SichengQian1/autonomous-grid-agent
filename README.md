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

The current implementation provides defensive request models, cross-turn state,
internal action objects, centralized validation and serialization, and a
protocol-safe empty strategy. Competitive planners are enabled only after their
rules and tests are ready.

## Safety

Before committing or pushing, inspect the staged file list and confirm that local source material, logs, replays, archives, and unsanitized fixtures are excluded.
