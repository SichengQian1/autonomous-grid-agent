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
It also accepts turn-log envelopes (see below). It never executes emitted sandbox
commands or sends requests to a platform.

## Turn logging

Turn logging is off unless `AGENT_TURN_LOG` is set. The HTTP response is written
first; logging runs afterward and must not delay or fail the reply. Point the
variable at a directory to write per-match files, or at `stderr` for console
only:

```bash
AGENT_TURN_LOG=logs bash run.sh 8000
AGENT_TURN_LOG=stderr bash run.sh 8000
```

Each match writes `match-<timestamp>-<seq>-<team>.jsonl` inside that directory;
a new file starts when the team key changes or the round counter restarts.
Every line is an envelope:

```json
{"meta": {"round": 12, "ms": 3.1, "cacheHit": false, "issues": []},
 "request": {"roundNo": 12, "...": "..."},
 "response": {"roleCommandMap": {"...": "..."}}}
```

`request` is the raw platform payload, `response` is the reply actually sent,
and `meta` summarizes the decision: `round`, `ms` latency, `cacheHit` retries,
`rejected`/`error` fallback reasons, `newMatch`, proposed `proposed` actions,
validator `issues`, `accepted` count, and `prompt`/`cmd` flags. Files stop
growing past 64 MiB per match. A directory sink does not also flood stderr.
Set `AGENT_TURN_LOG=off` (or leave it unset) to disable logging. A missing
directory or write failure never affects responses. The submission archive
does not enable turn logs unless the package is built with `--turn-log` or a
log key.

### Encryption

Set `AGENT_TURN_LOG_KEY` to encrypt every record:

```bash
AGENT_TURN_LOG=logs AGENT_TURN_LOG_KEY='passphrase' bash run.sh 8000
```

Each match file then starts with a plaintext header carrying a random salt and
KDF parameters; every record is encrypted with ChaCha20 and authenticated with
HMAC-SHA256 (encrypt-then-MAC, stdlib-only implementation). Console output is
the same encrypted stream. Records larger than 1 MiB are skipped while
encrypted, and if the key is configured but encryption is unavailable the
record is dropped rather than written in plaintext. Without the key the log
stays plaintext and a warning is printed at startup.

Decrypt a file back into replayable envelopes (or bare requests):

```bash
AGENT_TURN_LOG_KEY='passphrase' python3.11 tools/diagnostics/decrypt_turnlog.py logs/match-XXX.jsonl > plain.jsonl
AGENT_TURN_LOG_KEY='passphrase' python3.11 tools/diagnostics/decrypt_turnlog.py logs/match-XXX.jsonl --requests > requests.jsonl
```

Plaintext envelopes replay directly. Encrypted files are rejected until decrypted:

```bash
python3.11 tools/diagnostics/replay.py logs/match-20260915-120000.000-001-team.jsonl --limit 100
python3.11 tools/diagnostics/replay.py plain.jsonl --limit 100
```

## Build an upload package

```bash
python3.11 tools/package_submission.py
# Equivalent:
make package PYTHON=python3.11
```

The default upload profile is `frontline`, as selected for this submission.
The result is `artifacts/submission-frontline.tar.gz`. This does not change the
configuration used by the repository's normal `run.sh` command.

To package another profile or choose an output filename:

```bash
python3.11 tools/package_submission.py --config baseline
python3.11 tools/package_submission.py --config frontline --output artifacts/upload.tar.gz
```

The archive contains only `CoreGeek/main3.py`, `CoreGeek/run.sh`, the allowlisted
`CoreGeek/solution/*.py` modules and `CoreGeek/config/strategy.json`. It includes
no SDK documents, tests, logs, credentials, Git metadata or installed libraries.
The selected configuration is embedded and takes precedence over `AGENT_CONFIG`.
Inspect source changes before packaging; the allowlist controls filenames, not
arbitrary sensitive text added to otherwise permitted source files.

The builder requires Python 3.11, checks syntax and isolated imports/configuration,
and verifies every archive member. It prints the package SHA256. Identical inputs
produce identical bytes; successful builds replace an existing output atomically.
New runtime modules must be added to `MODULES` in the builder.

Turn logging stays off in the packaged program unless it is requested at
build time. The packaged process cannot read custom environment variables, so
embed a key when encrypted logs are wanted:

```bash
python3.11 tools/package_submission.py --log-key 'passphrase'
python3.11 tools/package_submission.py --gen-log-key   # random key, printed once
python3.11 tools/package_submission.py --turn-log      # plaintext files under logs/
```

The key is written into `main3.py` inside the archive only — never into the
repository. The builder does not pick up `AGENT_TURN_LOG_KEY` from the shell
environment; pass `--log-key` explicitly. Default packages do not write logs.

The SDK's Python layout identifies `CoreGeek/main3.py` and Python 3.11.10. The
archive uses `CoreGeek/` as its top-level directory. The PDF does not specify the
platform's extraction command or archive size limit; platform acceptance remains
to be confirmed. To check a package locally after extraction:

```bash
mkdir -p tmp/package-check
tar -xzf artifacts/submission-frontline.tar.gz -C tmp/package-check
python3.11 tmp/package-check/CoreGeek/main3.py 8000
# Alternatively: PYTHON_BIN=python3.11 bash tmp/package-check/CoreGeek/run.sh 8000
```

The service accepts the port as its only argument and listens on `0.0.0.0`.
Both entry points work from any working directory. No upload is performed by
the packaging command. See `HANDOFF.md` for actual verification results.

## Safety

Before committing or pushing, inspect the staged file list and confirm that local source material, logs, replays, archives, and unsanitized fixtures are excluded.
