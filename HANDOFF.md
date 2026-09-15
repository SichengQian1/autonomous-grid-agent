# Engineering Handoff

This file is the durable handoff for implementation work. Update it whenever a
change affects behavior, architecture, tests, assumptions, or the team workflow.
Keep it public-safe: do not paste official text, private URLs, identifiers, or raw
match logs here.

## Confirmed Direction

- Target Python 3.11.10 with standard-library runtime code.
- Optimize match win rate under a zero-exception safety constraint.
- v0.2 primary weapon experiment: two rocket launchers and one railgun.
- First comparison: two railguns and one rocket launcher.
- Treat task score and income as primary differentiators when defensive readiness
  remains safe.
- Keep opponent modeling in the architecture, but v0.2 disables cross-map fire and
  summon pressure until the development/defense baseline is calibrated.
- Place weapons behind the base. Build the centre-front wall first, add side cover,
  and reserve two permanent rear corridor cells. Dynamic remove/rebuild is outside V1.

## Source and Repository Boundaries

- `all/` contains local reference material and is read-only and excluded from Git.
- `local/` contains private working notes and is excluded from Git.
- Competition code lives in `solution/`.
- Tests use only synthetic or sanitized data.
- Do not commit, push, upload, or launch a match without explicit user approval.

## Team Workflow

Before a change:

1. Read `AGENTS.md`, this handoff, and the relevant public-safe design document.
2. Read `local/reference/README.md` and the relevant local topic digest before
   reopening official PDFs or SDK files. Reopen originals only for conflicts,
   missing visual details, changed hashes, or requirement updates.
3. Inspect `git status` and preserve unrelated work.
4. State the rule source and list any unverified assumptions.
5. Add or identify a failing synthetic test for bug fixes.

After a change:

1. Run `make test PYTHON=<python-3.11-or-newer>`.
2. Start the server through `run.sh` and run the HTTP smoke diagnostic.
3. Inspect the exact changed-file list and ensure local reference material remains
   excluded.
4. Update this file with behavior, reason, verification, assumptions, and next work.

## Release Workflow

- `VERSION` is the release source of truth and uses `v<major>.<minor>`.
- Keep compatible iterations on `codex/v<major>` and increment only the minor
  suffix. Start a new major branch only for a major strategy or architecture update.
- Run `python tools/build_submission.py` to create
  `submissions/v<major>/submission-v<major>.<minor>.tar.gz`.
- The builder includes every `solution/*.py` module under the proven top-level
  `CoreGeek/` layout, validates the entry list, and prints the SHA-256.
- Before upload, verify the archive from a clean extraction, retain its Git revision
  and SHA-256, and upload that exact file without repacking it.

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
- `solution/grid.py`: occupied cells and bounded eight-direction pathfinding.
- `solution/movement.py`: joint next-cell reservation and collision avoidance.
- `solution/defense.py`: normalized front/rear geometry and defensive layout.
- `solution/economy.py`: defense budget, construction, and resource value.
- `solution/logistics.py`: runtime-shop repair and upgrade workflow.
- `solution/combat.py`: controllers, release levels, and projected target allocation.
- `solution/tasking.py`: task, LLM, sandbox-result, and treasure state machines.
- `solution/opponent.py`: opponent evidence and global strategic modes.
- `solution/planner.py`: full-match orchestration and degradation boundaries.
- `solution/telemetry.py`: bounded sanitized `AGLOG2` records.

The V1 planner is active. It produces validated construction, movement, economy,
recall, combat, task, treasure, upgrade, and evidence-gated strategic actions. An
empty command map remains only a deliberate wait or final safety fallback.

## Change Log

### 2026-09-15 - v0.3 opening failure repair and restricted-zone regression

Runtime evidence and cause:

- The returned v0.2 log has 99 decoded turns: all 13 attempted weapon builds failed,
  first-night weapons/walls were both zero, task score remained zero, and the base
  was absent by round 99. This is a failed platform run, despite earlier synthetic
  tests passing. The earlier harness permitted construction on arbitrary cells and
  incorrectly turned all collected resources into stone.
- Rechecked the building diagram and successful construction observations: weapon
  candidates must be distance 1 from the whole 2x2 footprint; wall cells distance 2.
  v0.2 weapon offsets all fell outside the weapon ring and the front wall was too far.
- A depleted candidate list led to ordinary mining rather than a functioning defense.
  Profit-based ore selection did not enforce the stone supply needed for walls.

Changes and reasons:

- Corrected normalized rings, rear weapon preferences, two-cell permanent exit,
  and build validation. Reserve new construction cells against same-turn movement.
- Assign nearby builders, gather batches of stone for walls, and release one worker
  to income after ten walls. This follows the observed opening/stone/defense workflow.
- Keep cooling launchers staffed while threats remain; use nearest joint controller
  assignments and latch pre-night recall until the next day. Recall uses actual
  obstacle-aware path length rather than direct distance through walls. Adjacent carried repairs
  remain available during cooldown without abandoning a control position.
- Reserve the pioneer during asynchronous task waits. Recognize filenames adjacent
  to Chinese text, inspect task/supporting docs together, preserve structured answer
  objects, consume identical results from different commands, bound submission retries,
  and recover from missing command replies. No opponent answers/tokens were embedded.
- Corrected telemetry from `targets` to the actual `targetPos` field. Added readiness,
  map/zone context, failed sites, validation reasons, and task state; logging failure
  cannot erase a valid response. Added `--summary` for existing and new logs.

Verification and release:

- Added an independent synthetic world that rejects invalid weapon/wall rings and
  places valuable copper closer than stone. It reproduced the v0.2 zero-weapon
  failure before the fix. Both sides now complete three weapons by round 5 and
  at least ten walls by round 70, with adjacent controllers and no build failures.
- Updated the existing synthetic harness to enforce building rings and ore types.
- All 106 standard-library tests pass with Python 3.12.14. Both 1,300-turn synthetic
  replays report zero invalid responses and zero failed actions. The exact target
  Python 3.11.10 interpreter is not installed locally; platform verification remains required.
- These are synthetic regression results; robot routing, real survival, task success,
  and actual score/win rate still require a v0.3 platform run.
- Package and publish v0.3 on `codex/v0` using explicit Git file lists. Keep v0.2's
  archive for traceability. Logs, reference materials and PDF renders remain local.
- Fresh extraction passed HTTP smoke, malformed-JSON fallback, and the synthetic
  five-turn three-weapon opening. Artifact: `submissions/v0/submission-v0.3.tar.gz`.
  SHA-256: `4e407d2076011df7429018415a8f8678a642d3a87399816b883db13b56405a73`.

Next workflow:

1. Pull `codex/v0` and upload `submissions/v0/submission-v0.3.tar.gz` directly.
2. Run a simulation; return only the decoder's `--summary` by default.
3. Inspect weapon completion, first-night wall count, task retries and controller
   readiness before tuning more advanced strategy.

### 2026-09-15 - v0.2 development-first strategy and observable runtime

Changes:

- Changed the primary opening to rocket/railgun/rocket and retained the earlier
  railgun/railgun/rocket composition as the comparison variant.
- Moved preferred weapon cells behind the normalized base, added edge-map fallbacks,
  ordered walls centre-front first, and reserved a two-cell rear traffic corridor.
- Added upgrade valuation that includes the user-observed full heal, prioritizes the
  level-three rocket breakpoint, and permits only released roles to maintain at night.
- Reworked active tasks into inspect/LLM/command/LLM-synthesis/submit stages with
  bounded output, repeated-response deduplication, step limits, and command guardrails.
- Added capped sanitized `AGLOG2` turn telemetry plus a read-only decoder for `.log`
  and `.log.xz`. This is reversible obfuscation, not cryptographic secrecy.
- Disabled Boss orders, cross-map attacks, blind treasure probing, and wall removal
  in the default v0.2 configuration.

Reason:

- High-score observations make early task throughput, rocket reach, deliberate walls,
  repair/upgrade timing, and detailed replay evidence higher-value than speculative
  opponent pressure. Rear weapons reduce replacement risk; fixed lanes reduce traffic
  deadlocks; upgrade-healing turns damaged buildings into higher-value upgrade targets.

Verification boundary:

- 97 standard-library unit tests pass under Python 3.14.6, including the original
  30 protocol-foundation tests and new geometry, task, upgrade, and telemetry cases.
- Both 1,300-round synthetic sides finish with zero invalid responses, zero failed
  actions, three weapons, non-negative gold, and sub-5 ms observed decision peaks.
- The source tree and a clean extraction of `submission-v0.2.tar.gz` both start and
  return valid JSON through the HTTP smoke test.
- The v0.2 archive SHA-256 is
  `5f78ba161763ee410e9339c51aa3188c638ad41add3b7f82072a246c75a06fc0`.
- Unit tests and synthetic replay validate our protocol, geometry, scheduling,
  task-state, logging-codec, and safety behavior only.
- Exact build legality, real routing, upgrade settlement, night activity, task judging,
  weapon effectiveness, and match strength remain `UNVERIFIED_PLATFORM_BEHAVIOR`
  until a v0.2 platform log is returned.

Workflow:

1. Build `submissions/v0/submission-v0.2.tar.gz` from `VERSION`.
2. Upload that exact archive and run one low-stakes simulation.
3. Download the `.log`, optionally compress it to `.log.xz`, and decode it with
   `tools/diagnostics/decode_match_log.py`.
4. Compare construction results, task cycle time, first-night damage, upgrade actions,
   error codes, and final score before changing v0.2 defaults.

### 2026-09-15 - v0.1 branch and reproducible submission package

Changes:

- Established `codex/v0` as the isolated `v0.x` iteration branch and set `VERSION`
  to `v0.1`.
- Added a standard-library archive builder that packages the complete runtime under
  top-level `CoreGeek/`, validates every member, and prints a SHA-256 checksum.
- Added the versioned `submissions/v0/` artifact location and synthetic tests that
  prevent missing runtime modules, extra files, unsafe paths, or a broken wrapper.

Reason:

- Every platform upload must be reproducible and traceable to one code revision;
  manual file selection risks silently omitting newly added strategy modules.

Verification:

- 89 standard-library synthetic unit tests pass under Python 3.14.6, including three
  release-builder tests and the original 30 protocol-foundation tests.
- The generated `v0.1` archive contains only `CoreGeek/main3.py` and all 20
  `solution/*.py` modules; its builder and an independent archive listing agree.
- A clean extraction of the generated archive starts successfully and returns valid
  JSON for the bounded HTTP smoke request.
- The exact `v0.1` archive SHA-256 is recorded in the commit and publication report.
- Exact Python 3.11.10 execution remains a work-computer/platform calibration step.

Workflow:

- Compatible fixes become `v0.2`, `v0.3`, and so on on `codex/v0`.
- A major strategy or architecture generation starts `codex/v1` and `v1.0`.
- `main` is not updated by iteration work unless the user explicitly requests it.

### 2026-09-15 - V1 active full-match code loop

Changes:

- Added bounded occupied-cell modeling, eight-direction pathfinding, legal diagonal
  passage, interaction-cell routing, and conservative three-role reservations.
- Added base-quadrant coordinate normalization and the `USER_OBSERVED` rule that the
  normalized threat is forward while the fixed role exit remains behind the base.
- Added two-railgun/one-rocket construction objectives, distinct worker/site
  reservations, failed-build blacklisting, forward wall layers, and conservative
  degradation after a rear threat observation.
- Added dynamic defense/emergency/offensive budgets, resource value, mining, selling,
  runtime-shop purchasing, wall construction, repair, and upgrade logistics.
- Added distance-plus-buffer pre-night recall, weapon/controller assignment, four
  effective controller-release levels, threat scoring, projected overkill control,
  railgun-line value, rocket-area value, cooldown handling, and explicit
  `targetTeam` gating for cross-map fire.
- Added task/LLM/sandbox and treasure state machines with strict structured parsing,
  bounded output, confidence gates, result feedback, and safe failure recovery.
- Added opponent observations, `DEFEND`/`DEVELOP`/`SCORE_RACE`/`PRESSURE`/`FINISH`
  modes, and reserve/evidence-gated one-or-two-Boss purchase/use logic.
- Added a deterministic two-side, ten-day synthetic regression harness and a
  read-only bounded Windows-compatible log summarizer.
- Expanded validation to include visible movement occupancy, shared gold, weapon
  count, backpack capacity, runtime vendor/shop presence, build occupancy, stone,
  and cumulative item reservations.

Strategic reason:

- This creates the first non-empty vertical slice across all ten days while retaining
  the fail-closed protocol boundary. Construction and defense happen before optional
  economy or pressure, and every speculative mechanic has a disabled/degraded path.

Local verification:

- 86 standard-library synthetic unit tests pass, including the original 30 tests.
- Both sides complete 1,300-turn synthetic regressions with zero invalid responses,
  three final weapons, non-negative gold, and active decisions.
- The local HTTP server starts, accepts the minimal smoke request, and accepts an
  active synthetic request that returns task/build-path actions as valid JSON.
- These results are `synthetic regression passed`; they are not platform win-rate or
  game-mechanic proof.

Evidence status:

- `USER_OBSERVED`: upper-left base is threatened from the right; lower-right base is
  threatened from the left. Normalized front is therefore positive x and the fixed
  exit is behind it.
- `CONFIRMED_SPEC`: movement geometry, day/night boundaries, action shapes, runtime
  weapon fields, controller requirements, and three-weapon cap.
- `UNVERIFIED_PLATFORM_BEHAVIOR`: exact build cells, robot routing/settlement, rear
  opening safety, projectile-wall interaction, rocket overlap, night economy,
  wave/Boss timing, `targetTeam` completeness, cross-map scoring, summon timing and
  stacking, task/LLM/sandbox/treasure judging, and real defense-margin strength.

Next platform work:

1. Package the complete `solution/*.py` set under the proven `CoreGeek/` wrapper.
2. Run low-stakes simulations on both sides and retain revision/archive hashes.
3. Run `tools/diagnostics/summarize_match_log.py` on an exported JSON/JSONL log, or
   manually return the bounded checklist in `docs/platform-calibration.md`.
4. Promote repeatable evidence to `CONFIRMED_RUNTIME`, convert failures to sanitized
   regression fixtures, and tune build candidates, recall margins, combat allocation,
   night economy, and pressure thresholds.

### 2026-09-15 - Local reference digest and fixed-opening V1 decision

Changes:

- Added a local-only structured reference index covering game rules, protocol,
  runtime, SDK/package layout, competition process, source integrity, strategy
  observations, conflicts, and experiment priorities.
- Recorded the evidence hierarchy and the requirement to prefer runtime values over
  static tables when sources disagree.
- Replaced dynamic wall removal/rebuilding in V1 with a fixed opening opposite the
  learned primary threat direction.
- Expanded V1 scope to evaluate task, treasure, opponent, cross-map, and summon
  systems behind safety and evidence gates.

Reason:

- Repeated PDF rendering and SDK scanning wastes time and context; future work should
  consult a maintained local digest first while preserving the official originals as
  final authority.
- A fixed rear opening provides predictable role access with lower action, material,
  and timing risk than routine wall removal.

Verification:

- Fully reviewed the available task, interface, SDK, runtime, platform-operation,
  competition-format, grouping, request/response example, and reference-demo sources.
- Recorded source hashes and known conflicts in the local inventory.
- Confirmed `local/` remains excluded from Git; no official source was modified.

Remaining assumptions:

- Robot approach remains primarily one-directional on both sides and future maps.
- The fixed rear opening is not selected as a robot route.
- Nighttime collection and trade are legal in actual platform execution.
- Natural Boss appearance around day four or five remains an observation, not a
  specified fixed schedule.

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
2. Implement the full-match V1 state/mode interfaces before enabling tactical actions.
3. Add occupied-cell modeling, eight-direction pathfinding, and joint reservations.
4. Implement three-weapon opening construction and fixed-rear-opening wall geometry.
5. Connect economy, combat, controller release, task, treasure, opponent, and summon
   planners through the shared safety boundary.
6. Convert each unverified mechanic into a bounded practice experiment.
