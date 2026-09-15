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

The baseline planner is enabled. See `docs/baseline.md` for strategy behavior,
configuration, validation evidence and remaining assumptions. New modules separate
navigation, defense, layout, maintenance, combat, economy, task handling and
shared planning context.

## Change Log

### 2026-09-15 - Commit frontline work

- User authorized local commits. Grouped implementation, configurations, tests
  and the layout diagnostic in `0fdaf9e`; strategy and handoff documents follow
  in a separate commit.
- Inspected changed files and diffs. Official/local materials remain ignored and
  untracked; fixtures are synthetic. No credentials or private paths were found
  in the pending content. No push, upload or official match was performed.
- Code is unchanged from the verification recorded below: 138 tests, compilation,
  four layout checks and 20 HTTP checks passed.

### 2026-09-15 - Bases also permit weapon fire

- User confirmed bases, like walls, do not block weapon trajectories. The shared
  projectile blocker helper excludes both types for combat and layout coverage.
  Their footprints still block movement; weapon-building occlusion remains
  configurable and unverified. This supersedes earlier base-occlusion assumptions.
- Added a regression covering railgun/gatling shots through friendly/enemy bases,
  layout coverage and unchanged movement occupancy. All four subcases failed
  before the fix and now pass.
- All 138 tests and bytecode compilation passed under Python 3.11.15. Both
  frontline configurations passed left/right layout diagnostics. All four configs
  passed startup plus five HTTP checks each; test servers were stopped.
- Updated strategy, architecture and implementation-plan documents. No commit,
  push or official match was run; match strength and the exact target runtime
  remain unverified.

### 2026-09-15 - Fix six frontline review findings

Changes:

- Separate travel to the shop from a submitted purchase. Only a committed buy
  reserves purchase cash; its owner can continue travel, retry failures and deliver
  the item. Unknown receipts and delivery jobs expire without permanent blocking.
- Check live medicine, base-emergency and unfinished-weapon reserves on every wall
  purchase, including current-turn commitments and unresolved earlier purchases.
- User confirmed walls do not block weapon trajectories. `ballistics.py` now
  supplies the same wall-free projectile blockers to combat and layout. Walls
  remain movement obstacles; other buildings retain configurable occlusion.
- Keep existing walls in geometric membership, separate `wall_order` from those
  categories, and enforce the cap against living plus committed wall builds.
- Rank repair/upgrade work by danger, short-term survival and recovery per gold
  plus estimated role-action cost. Useful carried supplies remain eligible even
  when no longer listed in the shop. The action-cost weight is experimental.
- Preserve risk-based front/flank construction order through actual execution;
  pressured near-front flanks can precede unfinished frontage on either side.

Verification:

- Seven minimal regression cases failed before fixes; 13 added tests now cover
  those findings plus purchase failure/timeout, engine-level delivery, concurrent
  wall reservations, emergency cash and mirrored flank construction.
- All 137 tests and bytecode compilation passed under Python 3.11.15.
- Both frontline configurations passed left/right layout diagnostics. Baseline,
  balanced, frontline and frontline-balanced each passed startup plus five HTTP
  checks (day, night, malformed JSON, non-object body and empty object).
- Test servers were stopped. No commit, push, upload or official match was run.

Still unverified: exact target environment, non-wall building occlusion, actual
robot interception by walls, and competitive outcomes. Synthetic tests establish
the repaired action/state behavior, not win rate.

### 2026-09-15 - Frontline defense layout and wall maintenance

Changes and reasons:

- Added an opt-in `frontline` layout that infers a horizontal approach from the
  base footprint, jointly places rocket/rear and line-weapon side-rear sites,
  and builds a short front wall segment with rear-side gates.
- Wall repair/upgrade ranking uses observed damage and nearby pressure, with a
  daily gold fraction for wall items and pending delivery state. Night
  maintenance never takes a committed controller and does not change release
  proofs.
- Default `legacy` behaviour is unchanged. `config/frontline.json` and
  `config/frontline-balanced.json` enable the candidate mode.

Verification:

- 124 tests passed under local Python 3.11.15, including the previous 99 and new
  layout/maintenance/configuration cases. Bytecode compilation passed.
- Layout diagnostics with `--verify` passed for both sides on both frontline
  configs. First synthetic layout search was about 33 ms locally.
- `run.sh` HTTP smoke passed for baseline, frontline, and frontline-balanced;
  malformed JSON and non-object bodies still returned `{"roleCommandMap": {}}`.
  Local test servers were terminated after verification.
- No official match, submission, commit or push was performed.

Remaining evidence:

- Front walls are not a verified damage barrier. Walls are now confirmed
  transparent to weapon trajectories; other building occlusion stays conservative.
- Direction priors come from user observation, not a proven spawn table.
- Synthetic tests do not establish match win rate. Platform paired comparisons
  need a separate authorization.

### 2026-09-15 - Frontline defense implementation plan

- Added `docs/frontline-defense-implementation-plan.md` for the next implementation
  handoff: observed enemy direction, shared wall/weapon layout, maintenance budgets,
  delivery feedback, configuration, regression scenarios and acceptance commands.
- This is a plan only. The current strategy and configuration remain unchanged.
- Included crowding-driven spillover near the front flanks: those walls may be
  built before the frontage is complete and maintained by observed pressure,
  without treating lateral movement as a new global attack direction.
- Front-wall interception and building/projectile interaction still need platform
  evidence; the proposed mode retains legacy comparison and conservative fallbacks.

### 2026-09-14 - Five baseline audit fixes

Changes and reasons:

- Night supply release counts only admissible attacks and is rechecked after
  committing commands, so blocked or rejected fire cannot justify a departure.
- Controller assignment considers weapon subsets after casualties and ranks
  joint effective fire before readiness and travel cost. A cooling high-level
  weapon no longer displaces a usable adjacent weapon solely due to level.
- Added mining closure/reopening state with publication-anchored dates and source-
  checked structured news replies. Economic scoring excludes closed mines even
  when prices rise; uncertain closure ends remain conservative.
- Enabled treasure preparation/summoning at night after the defensive release
  gate, with inventory, route and time checks. Consume news replies before action
  planning so replies across dusk remain usable.
- Successful or already-empty treasure feedback is terminal for the match,
  suppressing stale replies and new legends until match reset.

Verification:

- Preserved five synthetic reproductions before the fixes, then added boundary
  coverage for commit rejection, dusk replies, dangerous/invalid treasure windows,
  terminal-state reset, mining dates, negated reopening and shared LLM quota.
- All 99 tests passed under local Python 3.11.15; bytecode compilation passed.
- Both baseline and balanced configurations started through `run.sh` and each
  passed 11 synthetic HTTP requests, including attack failure recovery, malformed
  bodies and a correlated daytime-news/nighttime-treasure exchange.
- Local test servers were terminated after verification. No official match,
  submission, commit or push was performed for these fixes.

Remaining evidence:

- Confirm exact Python 3.11.10/CentOS behavior, real action-result timing and damage
  rules, and diverse news/legend interpretations using sanitized platform evidence.
- Synthetic correctness checks do not establish competitive win rate.

### 2026-09-14 - Playable baseline on qwj/baseline

Changes:

- Enabled the modular baseline with eight-direction navigation, joint reservations,
  construction, resource sales, supply purchases, upgrades and defensive return timing.
- Confirmed build rings against the full base footprint: radius one for weapons,
  radius two for walls. Keep a permanent exit and conservative firing lanes.
- Added joint weapon targeting using runtime range/power, robot threat and health,
  gatling ray/angle rules, railgun energy and rocket splash/cooldown.
- Added safe night supply runs: after spawn, release roles only with an empty threat
  set or a conservative remaining-firepower cleanup proof. Reevaluate every turn.
- Added correlated structured task solving, bounded sandbox diagnostics, feedback
  parsing, news history and guarded treasure preparation/probing.
- Extended validation for occupancy, joint destinations/gold, build rings/materials,
  backpack capacity and upgrade compatibility. Suppress recently rejected actions.
- Added exact-retry caching, stale-turn rejection and match-level LLM/planner reset.
- Added baseline/balanced JSON configurations and a read-only JSONL replay diagnostic.

Verification:

- Python 3.11.15 local verification; exact 3.11.10/CentOS execution remains pending.
- 77 tests cover protocol regression, movement, weapons, state machines, configuration,
  economy and two 260-turn synthetic transitions, one for each side.
- Both synthetic economies build three weapons by round four, then collect, sell
  and upgrade. The first-night scenario has three distinct controllers firing.
- A separate 100-turn randomized check returned valid responses; observed maximum
  latency was about 12.5 ms. A 200-robot synthetic turn took about 14.3 ms locally.
- HTTP startup through `run.sh` and synthetic day/night requests passed; malformed
  JSON, non-object bodies and missing optional fields returned safe JSON.
- Bounded replay of 130 synthetic snapshots reported zero validation issues and
  zero decision failures. Missing input failed without exposing source content.

Remaining work/evidence:

1. Run the tests under the exact target interpreter and verify sandbox helper limits.
2. Replay sanitized live requests to check damage/ray edges, full-map range encoding,
   phase boundaries and the interpretation of per-projectile `attackPower`.
3. Verify task prompt/result contracts on actual tasks; generic restricted Python
   diagnostics cannot solve every task requiring other tools or filesystem writes.
4. Measure real match base survival, score, task completion and exception counts;
   compare weapon compositions over multiple maps/sides. No official match was run.
5. Keep cross-map scoring, summon pressure and dynamic gates disabled until supported.

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
