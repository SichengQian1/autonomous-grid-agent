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
tools/build_submission.py  reproducible submission archive builder
submissions/        versioned platform-ready archives
docs/               public-safe technical documentation
local/              confidential local notes, excluded from Git
all/                confidential source material, excluded from Git
```

The v0.5 candidate implementation is active. It includes
eight-direction pathfinding, joint role movement, mirrored defensive geometry,
construction/economy/recall planning, threat-weighted combat, task and treasure
state machines, bounded encoded telemetry, and opponent modes. Summon pressure and
cross-map attacks are disabled by default. One worker builds rear weapons and stone-funded walls while another mines and
delivers upgrade/repair items. The pioneer prioritizes tasks; official news and
folk clues feed separate market and treasure decisions.
Unknown platform mechanics retain safe fallbacks and require practice calibration.

On a Windows development computer, run the service directly from PowerShell:

```powershell
python -m solution.main 8000
```

The synthetic replay is a regression harness, not an official simulator:

```bash
python tools/diagnostics/synthetic_replay.py --side challenger
python tools/diagnostics/synthetic_replay.py --side defender
```

## Build a submission

The current iteration is recorded in `VERSION`. From PowerShell, generate and
validate the exact platform archive with:

```powershell
python tools/build_submission.py
```

For `v0.5`, this produces `submissions/v0/submission-v0.5.tar.gz`. The archive
contains top-level `CoreGeek/`, its `main3.py` entrypoint, and every module under
`solution/`; it excludes repository documentation, tests, diagnostics, logs, and
local source material. Minor updates advance `v0.x` on branch `codex/v0`; only a
major strategy or architecture generation starts `codex/v1`.

## Decode match telemetry

The agent writes bounded `AGLOG2` records to standard error, which the platform may
expose as its downloadable `.log`. The format is compressed, integrity-checked, and
reversibly obscured; because its decoder is public, it is not cryptographic secrecy.
Decode either the original log or a user-compressed `.log.xz` in PowerShell:

```powershell
python .\tools\diagnostics\decode_match_log.py "D:\path\to\match.log.xz" > decoded.jsonl
```

For a compact shareable diagnosis, add `--summary` instead of redirecting output.
This accepts v0.2–v0.5 logs and already-decoded JSONL, including `.xz` files.
v0.5 also records command rejection/error categories, changing mine locations,
individual recalls, carrier ownership, and strategy fallback counts. It records
task progress reasons, current prices, procurement stages, and why
each weapon did not fire. Readiness and day/night boundaries are retained under
a whole-match log budget.

Task text, prompts, answers, command output, team IDs, names, and URLs are never
written to these records. Logging is capped so diagnostics cannot grow without bound.

## Safety

Before committing or pushing, inspect the staged file list and confirm that local source material, logs, replays, archives, and unsanitized fixtures are excluded.
