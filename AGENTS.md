# Project Instructions

## 1. Project Goal

This repository contains a competition agent whose primary objective is to finish in the top three.

All architecture, implementation, testing, and optimization decisions must serve these goals, in order:

1. Keep the program stable and produce zero competition-level exceptions.
2. Maximize match win rate rather than optimizing an isolated metric.
3. Prevent our base from being destroyed before the opponent's base.
4. Maximize task, treasure, survival, and combat score subject to the safety constraints above.
5. Remain easy to test, replay, tune, and adapt when the rules change.

Do not sacrifice reliability, development speed, or verifiability merely for stylistic elegance.

## 2. Repository Boundaries

The official source material, SDK archives, examples, and reference demo are stored under `all/`.

Rules:

- Treat `all/` as confidential, local-only, and read-only.
- Never modify, rename, delete, publish, commit, or upload anything under `all/`.
- Never develop the final submission directly inside an extracted official SDK or demo directory.
- `all/CoreGeek/` is the extracted minimal Python SDK.
- `all/CoreGeek 2/` is the extracted full reference demo.
- The reference demo is useful for understanding the protocol, but it is not an authoritative or competitive strategy.
- `local/reference/` contains the maintained local-only digest and source inventory. Read its `README.md` and the relevant topic file before reopening PDFs or rescanning SDK/demo files. The digest saves context but never overrides newer specifications or actual platform behavior.
- Create the competition implementation under `solution/`.
- Keep tests under `tests/` and narrowly scoped diagnostic utilities under `tools/diagnostics/` when those directories are needed.
- Keep temporary files, generated logs, replays, caches, and test outputs out of official-material directories.

The project is intended to be transferred through GitHub and pulled onto a separate work computer. GitHub content must be limited to original implementation code and deliberately sanitized supporting files.

Before any commit, push, archive, or upload:

1. Inspect the exact file list and diff.
2. Confirm that `all/` is excluded.
3. Confirm that official documents, official archives, internal request/response samples, downloaded logs, and other confidential source material are excluded.
4. Confirm that no secret, credential, employee identifier, internal hostname, internal URL, team identifier, or confidential path is present.
5. Confirm that test fixtures are synthetic or sanitized.

When Git tracking is configured, confidential and local-only paths must also be protected by `.gitignore`. A `.gitignore` entry is an additional safeguard, not a substitute for inspecting the staged file list.

Do not upload repository content or use remote services without the user's explicit instruction for that specific operation. The plan to use GitHub later is not standing authorization to push automatically.

## 3. Public-Code Content Rules

Source code must contain only implementation-relevant technical content.

- Use English identifiers and filenames.
- Chinese comments are allowed for complex rules, strategic decisions, and non-obvious invariants.
- Do not add company introductions, company names, organizational descriptions, slogans, internal project background, internal links, or similar material to source code or public documentation.
- Do not copy official prose into comments, documentation, tests, commit messages, or fixtures.
- Describe game rules in neutral technical language only when required to explain the implementation.
- Do not embed real internal IDs, account names, hostnames, URLs, or logs. Use synthetic placeholders in tests.

## 4. Source-of-Truth Order

When sources disagree, use this order of authority:

1. Actual competition-platform requests and observed runtime behavior.
2. The newest interface specification.
3. The newest task specification.
4. Official request and response examples.
5. The reference demo.
6. Historical assumptions and hard-coded defaults.

Prefer runtime values such as the following over documentation constants:

- `attackRange`
- `attackPower`
- `level`
- `cooldown`
- shop prices
- task rewards and timeouts
- map dimensions and map elements

When a rule cannot be confirmed:

- Mark it explicitly as an unverified hypothesis.
- Design the smallest safe experiment that can distinguish the possibilities.
- Keep the behavior configurable where practical.
- Do not silently convert the hypothesis into a permanent hard-coded rule.

## 5. Technology Constraints

Use Python 3.11 for the final submission. The target interpreter is Python 3.11.10.

Target environment and limits:

- CentOS 7.6
- 4 CPU cores
- 8 GB memory
- normal turn response deadline: 5 seconds
- task sandbox command limit: 15 seconds
- no dependencies outside the supplied SDK environment
- task sandbox has no external network access

Prefer the Python standard library for the core implementation. Do not add a third-party dependency or change the submission language without the user's explicit approval.

Do not assume that software installed on the development machine is available in the competition environment.

## 6. Strategic Priorities

Use the following decision hierarchy:

1. Produce a valid response and keep the service alive.
2. Avoid our base being destroyed first.
3. Put living controllers into safe defensive positions before night.
4. Complete high-value tasks and treasure objectives efficiently.
5. Maximize robot kills while minimizing overkill and wasted actions.
6. Decide dynamically whether to defend, steal score, or pressure the opponent.
7. Optimize resource income when it does not endanger the priorities above.

Weapon composition, upgrade order, wall layout, economy thresholds, and timing thresholds must be configurable and supported by experiments.

The initial experimental weapon baseline is:

- two railguns
- one rocket launcher

This is a hypothesis to test, not a permanent rule. Keep the balanced gatling/railgun/rocket composition available for comparison.

## 7. Architecture

Keep these responsibilities separate:

- HTTP server and lifecycle
- protocol parsing and serialization
- defensive request compatibility
- game model and cross-turn state
- map and coordinate normalization
- joint multi-role movement planning
- daytime economy and construction
- nighttime combat and targeting
- task, LLM, and sandbox state machines
- opponent-pressure estimation
- action validation and safety fallback
- diagnostics, replay, and tests

Do not accumulate the entire implementation in one `main3.py` file.

Strategy code must create internal action objects. A single protocol layer must validate and serialize those objects into the response format.

Support both sides of the map through a normalized strategic coordinate system rather than two independent strategies.

Centralize tunable rules and parameters. Do not duplicate the same rule constant across modules.

## 8. Reliability Red Lines

Five competition-level exceptions can disable the program. Stability has priority over local score.

Validate every outgoing response for at least the following:

- JSON serialization succeeds.
- `roleCommandMap` has the required structure.
- every action name is recognized.
- all required fields are present.
- target coordinates are inside the map.
- movement targets are adjacent.
- the role type is permitted to perform the action.
- the action is permitted in the current day/night phase.
- a weapon controller is alive and adjacent to the weapon.
- a rocket is not cooling down.
- one role is not assigned mutually exclusive actions.
- gatling and rocket target counts equal the current weapon level.
- multiple gatling targets satisfy the 90-degree constraint.
- used or sacrificed items actually exist in the backpack.

Catch unexpected strategy failures at the server boundary and return the protocol-safe fallback:

```json
{"roleCommandMap": {}}
```

Logging, tracebacks, and debugging output must never corrupt the HTTP response. Keep diagnostic output bounded.

Design normal turn computation to finish far below the 5-second deadline. Use an internal hard cutoff with enough time left to return a safe response.

## 9. Defensive Parsing

Specifications, examples, and platform payloads may differ.

- Use safe defaults for optional fields.
- Do not assume arrays are non-empty.
- Do not assume examples contain every documented field.
- Do not hard-code role IDs when roles can be identified by `roleType` and state.
- Ignore unknown fields without crashing.
- Preserve compatibility when new fields appear.
- Missing, delayed, malformed, or empty LLM output must not break basic movement or combat.
- Feed `lastRoundRoleActionResults`, `errors`, `lastCmdResult`, and treasure result codes back into the state machine.

## 10. LLM and Task Rules

Outside a self-evolution task, the platform permits at most three LLM calls per game day. Calls made during an active self-evolution task do not consume that daily quota.

- Manage LLM calls through a dedicated budget and request-state component.
- Do not waste daily calls on repeated prompts.
- Request structured, machine-parseable output.
- Never translate LLM output directly into a game command without validation.
- Validate coordinates, items, time conditions, answer shape, and confidence.
- Preserve official-news and folk-legend history across turns.
- Convert repeated task-solving discoveries into reusable procedures.
- Bound sandbox command duration and output.
- Task failure must not block the normal game response.

Before accepting a task, consider:

- task timeout
- turns remaining before night
- return distance to the defensive area
- safety margin
- whether the base can safely operate without the pioneer

## 11. Movement Rules

Movement uses eight directions and Chebyshev distance.

The planner must account for:

- neutral units and resource zones
- friendly buildings and roles
- visible enemy units
- robots
- multiple friendly roles competing for one destination
- role position swaps
- joint next-step reservations
- replanning when a dynamic obstacle appears

The rules allow diagonal passage between two adjacent obstacles. Do not accidentally apply a generic no-corner-cutting restriction.

## 12. Combat Rules

Do not use nearest-target selection as the only combat policy.

Target scoring should consider:

- estimated turns until the robot threatens the base or a key structure
- robot attack power and health
- kill score
- whether the target can be killed this turn
- overkill
- rocket area damage
- railgun penetration value
- gatling angle and ray constraints
- robot `targetTeam`
- whether attacking an opponent-side robot helps or harms the current match plan

Support distinct high-level modes:

- defensive survival
- cross-map score stealing when mechanics permit it
- pressure mode that stops helping the opponent and may add summon orders

Do not buy or use summon orders without evaluating whether they merely give the opponent extra kill score.

## 13. Testing and Replay

Important strategy changes require tests or replay evidence.

Maintain coverage for:

- protocol parsing and serialization
- action validation
- coordinates and distance
- pathfinding
- multi-role collision prevention
- all weapon targeting rules
- day/night boundaries
- malformed LLM output
- sandbox-result parsing
- side normalization
- previously observed competition failures

When fixing a bug, preserve a minimal reproducible input before changing the implementation.

Do not infer that a strategy is strong from a single match. Compare meaningful samples using win rate, score, base survival, task completion, and error counts.

## 14. Work-Computer Diagnostics

The development environment cannot directly retrieve information from the separate work computer. Do not assume remote access or automatic log transfer.

When work-computer evidence is needed:

1. Create a small, read-only diagnostic script under `tools/diagnostics/`.
2. Make the script inspect only the specific log, file, process, or condition required for the current question.
3. Print a concise, bounded, copyable result by default.
4. Include line limits, byte limits, filters, summaries, or checksums where useful.
5. Avoid printing secrets, environment dumps, credentials, internal URLs, or unrelated context.
6. Let the user run the script on the work computer and paste the sanitized output back.

Prefer, in order:

1. a targeted error excerpt with surrounding lines
2. filtered events for selected rounds or identifiers
3. a summary, count, schema, or checksum
4. a carefully selected chunk of a large file
5. the complete large output only when smaller evidence is insufficient

Diagnostic scripts must be non-destructive unless the user explicitly requests a mutation. They must clearly state expected arguments and must fail safely when an input is missing.

Do not add copied work-computer logs to Git. Convert useful incidents into sanitized synthetic test fixtures.

## 15. Change Workflow

Before modifying code:

1. Read the relevant local digest under `local/reference/`, then reopen original specifications only for conflicts, missing visual details, changed source hashes, or requirement updates.
2. Read the relevant existing implementation.
3. Inspect the current workspace and Git state.
4. Identify affected modules and unverified assumptions.
5. Preserve unrelated user changes.

After modifying code:

1. Run relevant tests.
2. Verify that the program starts and listens on the provided port.
3. Exercise the HTTP interface with a suitable sanitized or local official sample.
4. Confirm that the response is valid JSON.
5. Report changes, verification results, and remaining assumptions.

Without an explicit request, do not:

- delete files
- force-reset Git state
- overwrite official materials
- commit or push code
- upload a submission
- launch an official platform match

## 16. Requirement Changes

The competition is expected to introduce multiple later requirement changes.

- Analyze specification differences before changing code.
- Keep rule parameters centralized.
- Prefer configuration or feature flags for strategy variants.
- Keep protocol parsing backward-compatible where practical.
- Preserve older replays as regression tests.
- Avoid changes that solve one map by breaking general behavior.

## 17. Communication

Discuss the following with the user before implementation:

- changing the submission language or core framework
- changing high-level strategic priorities
- adopting a new primary weapon composition
- adding a dependency
- performing a large-scale refactor
- deleting or moving files
- implementing a high-risk strategy based on an unverified rule
- committing, pushing, uploading, or launching an official match

Small bug fixes, tests, and implementation work already covered by an approved task may be completed directly and reported afterward.
