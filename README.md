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

The v0.21 candidate is based directly on v0.18, with three scoped changes: unrestricted map-half resource selection, late-day ore liquidation before wall procurement, and a third-front-wall support post with upgraded-wall preference and return-to-post checks. The v0.19/v0.20 strategy additions are not active.

The v0.21 candidate implementation is active. It includes
eight-direction pathfinding, joint role movement, mirrored defensive geometry,
construction/economy/recall planning, threat-weighted combat, task and treasure
state machines, bounded encoded telemetry, and opponent modes. Summon pressure remains disabled. From night three, level-three rockets prioritize
opponent small/medium robots for the first ten turns, with an immediate home-danger override.
The wall engineer stocks surplus-funded Bombs by day after defense supplies. One engineer builds and maintains walls, retains five rebuilding stones, and
times wall purchases around daytime mining. The other worker mines and joins final-night wall defense; the pioneer
handles tasks and weapon upgrades as the primary gun operator; official news and
folk clues feed separate market and treasure decisions.
v0.21 uses one shared pioneer gun post, stable wall support, two-day ore holding,
explicit defense deadlines, and source-indexed treasure preparation with confirmed
night guard handovers. Known next-day treasure expeditions use the preceding night
for a safe trip after the miner confirms gun control. Treasure semantics are delegated to the platform model using daily raw folklore
and current catalog properties. Structural guards, a cumulative material budget,
two opening attempts and platform feedback bound execution. See [the operating guide](docs/operating-logic.md).
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

For `v0.21`, this produces `submissions/v0/submission-v0.21.tar.gz`. The archive
contains top-level `CoreGeek/`, its `main3.py` entrypoint, and every module under
`solution/`; it excludes repository documentation, tests, diagnostics, logs, and
local source material. Minor updates advance `v0.x` on branch `codex/v0`; only a
major strategy or architecture generation starts `codex/v1`.

## Decode match telemetry

The agent writes bounded `AGLOG3` records to standard error. v0.12 uses a generated
256-bit project key, fresh random 96-bit nonces, and ChaCha20-Poly1305 authenticated
encryption ([RFC 8439](https://datatracker.ietf.org/doc/html/rfc8439)). It requires no
third-party runtime packages. The keyring is intentionally published in
`solution/log_keys.py` at the user's request for zero-setup decoding. **Anyone with
this repository or submission can decrypt these logs; this is not public secrecy.**
The pure-Python codec is for telemetry only, is not constant-time, and has not had
an independent security audit. Sensitive fields are still redacted before encryption.

Pull the repository, then decode in PowerShell. `--output` writes UTF-8 directly
and refuses to overwrite an existing file:

```powershell
python .\tools\diagnostics\decode_match_log.py "D:\path\to\match.log.xz" --output decoded.jsonl
```

For a compact shareable diagnosis, use `--summary` without `--output`.
Use `--pioneer --day 6` to inspect pioneer activity, no-command intervals and missing-turn coverage.

The decoder accepts v0.2–v0.21 formats and decoded JSONL, including `.xz` files.
Keep historical key IDs when rotating the active key. Decoding restores recorded,
bounded, sanitized events; it cannot recover unrecorded or redacted content.
v0.5 also records command rejection/error categories, changing mine locations,
individual recalls, carrier ownership, and strategy fallback counts. It records
task progress reasons, current prices, procurement stages, and why
each weapon did not fire. Readiness and day/night boundaries are retained under
a whole-match log budget.

Turn events exclude task contents. Dedicated task events include bounded sanitized
requirements, model responses and command evidence; credentials, proof values, team
identifiers and internal URLs are redacted. Logging is capped.

The v0.6 iteration preserves task documents and discovered workspaces across command
failures, shares physical return budgets across work and recall, cashes out complete
mining trips, and plans three level-two front walls from day two when funds permit.
Telemetry adds task workspace/evidence readiness and document counts without text.
These are regression-tested changes, not a claim of competitive task success.

The v0.7 iteration fixes occupied delivery goals and independent owned-item delivery,
protects basic upgrade funding, stages idle pioneers near the shop, and supports
execution-backed Python answers without an extra synthesis round.
See [the current worker and task flow](docs/operating-logic.md) for the detailed logic.

## Safety

Before committing or pushing, inspect the staged file list and confirm that local source material, logs, replays, archives, and unsanitized fixtures are excluded.

The v0.11 task workflow first reads the current task and attempts a bounded executable
procedure. Supported repair specifications drive directory, permission and configuration
changes followed by the original checker. API queries retain actual records, adapt
request bindings from current documents/errors, check pagination, and give the current
data to the model for interpretation. Unknown tasks retain the general solver route.
Match-local API method hints are revalidated with fresh credentials and query objects.
Retrieved-data candidates are distinct from independently verified calculations and
platform-confirmed full success. v0.12 accepts direct, wrapped, and string-serialized
API answer objects through the same evidence and schema gates. Repair workflows retain
the v0.11 path. On day five, base level two and one level-three core wall take precedence
over remaining weapon upgrades; by day six both front walls 2/3 are due. Front walls
1/4 stop at level two. The pioneer stocks up to two repair items from day five when
affordable after required development funding. Wall support ranks estimated exposure
and travel time; robot targets are not observable. See operating logic for limits.

Task diagnostics: use `--tasks` for summaries, or
`--trace --task-id T002 --detail-limit 128` for readable bounded evidence, including
linked document/program chunks, concrete failures, submission and outcome. Credentials
and repair proofs are redacted before encoding. Chunk omissions/truncation and budgets
are explicit; the trace is not a promise of unlimited full transcripts.
See [operating logic](docs/operating-logic.md) for the three-rocket shared-control
experiment, deferred voucher delivery, two-turn recall margin and task SOPs.
