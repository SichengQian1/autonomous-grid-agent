# Engineering Handoff

This file is the durable handoff for implementation work. Update it whenever a
change affects behavior, architecture, tests, assumptions, or the team workflow.
Keep it public-safe: do not paste official text, private URLs, identifiers, or raw
match logs here.

## Confirmed Direction

- Target Python 3.11.10 with standard-library runtime code.
- Optimize match win rate under a zero-exception safety constraint.
- Initial weapon experiment: two railguns and one rocket launcher.
- First comparison: one gatling, one railgun, and one rocket launcher.
- Treat task score and income as primary differentiators when defensive readiness
  remains safe.
- Keep cross-map score stealing and pressure behavior disabled until platform
  experiments verify their mechanics.

## Source and Repository Boundaries

- `all/` contains local reference material and is read-only and excluded from Git.
- `local/` contains private working notes and is excluded from Git.
- Competition code lives in `solution/`.
- Tests use only synthetic or sanitized data.
- Do not commit, push, upload, or launch a match without explicit user approval.

## Team Workflow

Before a change:

1. Read `AGENTS.md`, this handoff, and the relevant public-safe design document.
2. Inspect `git status` and preserve unrelated work.
3. State the rule source and list any unverified assumptions.
4. Add or identify a failing synthetic test for bug fixes.

After a change:

1. Run `make test PYTHON=<python-3.11-or-newer>`.
2. Start the server through `run.sh` and run the HTTP smoke diagnostic.
3. Inspect the exact changed-file list and ensure local reference material remains
   excluded.
4. Update this file with behavior, reason, verification, assumptions, and next work.

## Current Architecture

- `solution/main.py`: process lifecycle and HTTP safety boundary.
- `solution/engine.py`: serialized state ingestion and planner boundary.
- `solution/models.py`: defensive request models.
- `solution/geometry.py`: positions, distance, station footprint, side transform.
- `solution/rules.py`: centralized constants and strategy configuration.
- `solution/actions.py`: internal actions and decisions.
- `solution/validation.py`: fail-closed action validation.
- `solution/protocol.py`: validated response serialization and safe fallback.
- `solution/state.py`: cross-turn feedback/news state and LLM call budget.

The competitive planner is intentionally empty. The service currently returns a
valid empty command map after parsing and ingesting each turn.

## Change Log

### 2026-09-14 - Public repository initialization

Changes:

- Created the public repository `SichengQian1/autonomous-grid-agent` for the
  sanitized implementation and supporting engineering files.
- Kept local reference material, private notes, source documents, archives, logs,
  caches, and generated files outside the publication set.
- Used an account-associated noreply address for repository-local commit identity.

Reason:

- The implementation needs a transferable collaboration baseline without exposing
  local-only source material or development-machine context.

Publication workflow:

1. Inspect status, unstaged changes, ignore matches, and the exact untracked list.
2. Scan publication candidates for private paths, URLs, credentials, and identifiers.
3. Add only explicit sanitized files.
4. Inspect the staged diff and staged file list before committing.
5. Push `main`, then confirm the remote branch with a read-only Git query.

### 2026-09-14 - Zero-exception protocol foundation

Changes:

- Split the initial single-file server into protocol, model, geometry, rules,
  actions, validation, state, engine, and lifecycle modules.
- Added defensive parsing for map, friendly and enemy units, robots, tasks, shops,
  news, action feedback, treasure feedback, LLM output, command output, and errors.
- Added internal action objects so strategy code cannot write wire JSON directly.
- Added validation for actor eligibility, phase, coordinates, adjacency, controllers,
  cooldown, weapon target counts, gatling angles, inventory, and shop/resource data.
- Added a protocol-safe fallback and a hard strategy time budget boundary.
- Added state reset/deduplication and daily LLM budget tracking that recovers from
  missing or empty responses.
- Changed `run.sh` to launch the package with `python -m` and accept `PYTHON_BIN` for
  local interpreter selection.
- Added synthetic unit tests for parsing, geometry, normalization, state, LLM budget,
  validation, serialization, and fallback behavior.

Reason:

- Every later strategy depends on a stable compatibility and validation boundary.
- Runtime payloads may omit documented fields or include later fields.
- Invalid upgraded-weapon target counts and controller conflicts are competition-level
  risks that must be blocked centrally.

Verification:

- 30 synthetic unit tests passed under Python 3.12.14, which exercises language
  features compatible with the Python 3.11 target.
- Bytecode compilation passed for `solution/`, `tests/`, and `tools/diagnostics/`.
- `run.sh` started the server successfully with an explicit Python interpreter.
- A valid synthetic HTTP request returned `{"roleCommandMap": {}}`.
- Malformed JSON and a non-object JSON body both returned the same safe response;
  predictable bad requests produced one-line warnings rather than tracebacks.
- The local reference request sample contains a trailing delimiter and is not valid
  strict JSON. It was rejected safely, so synthetic fixtures remain the automated
  compatibility baseline until a valid platform payload is observed.
- Git ignore checks confirmed that reference material, local notes, root documents,
  archives, caches, and generated bytecode are excluded.

Observed local environment:

- The default macOS `python3` is Python 3.9.6 and is not a valid test interpreter.
- Use an explicit Python 3.11+ executable through `PYTHON` and `PYTHON_BIN` locally.

Unverified assumptions:

- Round numbering is one-based for day/night boundaries.
- The defender side is normalized through a 180-degree map rotation.
- Omitting a role from `roleCommandMap` is the safe wait behavior.
- Unknown future item types are rejected until their target requirements are known.

Next work:

1. Re-run the suite under the exact Python 3.11.10 target on the work computer.
2. Add occupied-cell modeling and eight-direction pathfinding.
3. Add joint next-step reservations and collision tests.
4. Implement the safe opening construction planner behind a feature flag.
5. Convert each unverified mechanic into a bounded practice experiment.
