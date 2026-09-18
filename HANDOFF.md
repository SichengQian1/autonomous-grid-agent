# Engineering Handoff

This file is the durable handoff for implementation work. Update it whenever a
change affects behavior, architecture, tests, assumptions, or the team workflow.
Keep it public-safe: do not paste official text, private URLs, identifiers, or raw
match logs here.

## Confirmed Direction

- Target Python 3.11.10 with standard-library runtime code.
- Optimize match win rate under a zero-exception safety constraint.
- v0.9 primary weapon experiment: three rocket launchers with two shared operators.
- First comparison: two railguns and one rocket launcher.
- Treat task score and income as primary differentiators when defensive readiness
  remains safe.
- Keep opponent modeling in the architecture, but v0.2 disables cross-map fire and
  summon pressure until the development/defense baseline is calibrated.
- Place weapons behind the base. Build the centre-front wall first, add side cover,
  and reserve four permanent rear corridor cells in the normal layout. Dynamic
  remove/rebuild remains disabled. Two-cell edge-layout fallback is retained.

## Source and Repository Boundaries

- `all/` contains local reference material and is read-only and excluded from Git.
- `local/` contains private working notes and is excluded from Git.
- Competition code lives in `solution/`.
- Tests use only synthetic or sanitized data.
- Standing user authorization (2026-09-16): after requested work, verification and
  confidentiality checks, commit and push completed changes and submission artifacts
  to the configured GitHub remote on `codex/v<major>` without asking again.
- Use explicit staged file lists, preserve unrelated changes, never force-push,
  and verify the remote branch hash after pushing. Platform uploads and matches
  still require separate user instruction.

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
- `solution/travel.py`: shared work, procurement and defensive-return route budgets.
- `solution/defense.py`: normalized front/rear geometry and defensive layout.
- `solution/economy.py`: defense budget, construction, and resource value.
- `solution/logistics.py`: persistent runtime-shop baskets, delivery and maintenance.
- `solution/market.py`: official-news windows, separate from current prices.
- `solution/combat.py`: controllers, release levels, and projected target allocation.
- `solution/tasking.py`: task, LLM, sandbox-result, and treasure state machines.
- `solution/task_programs.py`: generic bounded sandbox procedures.
- `solution/task_answers.py`: answer contracts and canonical rejection fingerprints.
- `solution/task_contracts.py`: current-document shape extraction and proof packaging.
- `solution/task_context.py`: bounded per-task documents, workspace and execution evidence.
- `solution/task_api.py`: bounded API retrieval, completeness evidence and aggregation.
- `solution/task_series.py`: match-local method provenance, compatibility and invalidation.
- `solution/task_audit.py`: sanitized task events, outcome attribution and log budgets.
- `solution/maintenance.py`: threatened front-wall support and retreat.
- `solution/opponent.py`: opponent evidence and global strategic modes.
- `solution/planner.py`: full-match orchestration and degradation boundaries.
- `solution/telemetry.py`: bounded sanitized `AGLOG2` records.

The V1 planner is active. It produces validated construction, movement, economy,
recall, combat, task, treasure, upgrade, and evidence-gated strategic actions. An
empty command map remains only a deliberate wait or final safety fallback.

## Change Log

### 2026-09-18 - v0.11 executable task workflows and readable evidence

Evidence and scope:

- Started on codex/v0 at a68b42580170d6b677f7c045fc6a5bacfa104e46; preserved the
  user's pre-existing AGENTS.md edits outside the release.
- Four returned v0.10 runs: API 0/12 full with all unsubmitted; repair 4/12 full.
  Twenty of 24 tasks never submitted. Average task income was 80 per match and
  40 before the first night. A separate supplied four-run comparison completed
  all 23 accepted tasks for full rewards, averaging 460 task gold and 240 before night.
  These are observed samples, not estimates of future success or total match score.
- The comparison's useful behavior was a short executable specification/checker
  repair loop and actual API records handed to model interpretation. Its automatic
  response flattening, idle-after-completion behavior and unredacted logging were
  not adopted. Historical answers, credentials, project values and raw logs are excluded.
- This release concentrates on tasks and diagnostics. Combat, worker scheduling,
  procurement, movement and protocol behavior retain the previous experiment.

Implementation:

1. The initial task command now runs a bounded current-document bootstrap. Recognized
   repair specifications drive directory creation, project permissions, guarded
   configuration-line changes and task-referenced script newline handling. A unique
   current workspace and checker are required; checker bytes are never modified.
   Up to three repair/check iterations share the existing nine-second sandbox budget.
   Actual checker failure, launch failure and missing proof are distinct. A current
   successful proof is packaged and submitted immediately. Unknown tasks fall back
   to the existing general model/script solver and applied-patch recovery.
2. Supported API tasks resolve current service/credentials/object, make bounded
   request adaptations and discover actual nested records. Offset/limit progression,
   totals, duplicates and explicit end markers determine completeness. A bounded
   negative-object query detects ignored filters when records omit the query field.
   Evidence distinguishes record checks, negative controls and accepted parameters
   without independent response echo. No nonexistent record field is invented.
3. Actual retrieved records and current requirements reach a dedicated model prompt.
   Shape/object/count/category invariants are checked before submitting supported
   candidates. Such candidates are not labeled independently verified or platform-full.
   Ambiguous/large/unsupported responses retain evidence and take the general route.
   The older API executor accepts root-prefixed paths and returns field/data previews
   on mapping failures. Within-task candidates survive unrelated recovery steps.
4. Match-local API hints retain authentication style, parameter and response/paging
   methods, excluding credential values and answers. Subsequent tasks rebind and
   revalidate; changed methods invalidate. Actual workflow reuse has a distinct event,
   and new tasks clear old reuse markers. Fixed repair SOP execution is not counted
   as runtime learning merely because the same routine runs again.
5. Readable local traces add document/model/command chunks, fingerprints, part counts,
   byte/truncation metadata, concrete checker/API failures and request/command IDs.
   Non-sensitive numbers and calculations remain readable; authentication, cookies,
   account identifiers, private addresses and current repair proofs are redacted first.
   Identical status alone no longer merges different failures. Repeated type-only
   plans are reduced and settlement retains budget. Traces remain bounded, not unlimited.
   `decode_match_log.py --trace --task-id T002 --detail-limit 128` reads the new evidence.
6. Submission transport caches compressed programs by workflow family, omitting
   unused helpers so the larger bootstrap fits the existing command limit.

Validation and limits:

- Preserved failing synthetic cases before implementation. The 16 new workflow tests
  cover real-data-to-model-to-submit, immediate proof submission, three tasks with
  fresh credentials/objects and fewer repeated requests, ignored filters, nested
  records without city fields, offset pagination, changed project paths, dynamic
  proofs, checker preservation, business failure, unknown-project fallback, stale
  result rejection, trace chunking, budgets, redaction and actual command transport.
- Full suite: 276 tests pass, including the two-side 1300-turn synthetic regression.
  Related task regressions were rerun after final logging/prompt adjustments.
- Source and clean archive HTTP checks cover malformed JSON and both sides through
  round 71 with independently restricted building cells: three rockets, 12/13 walls,
  two operators staffing all three weapons. These do not emulate official tasks.
- Runtime source passes Python 3.11 syntax parsing; tests run under local Python
  3.14.6. Exact Python 3.11.10 remains untested locally.
- Read-only comparison-document compatibility checks recognized the supplied task
  contracts and relevant requirement forms; no complete original project replay was
  possible or claimed. Automatic support remains limited to recognized structures.
- Next matches must compare per-category full/unsubmitted rates, repair 3/3 runs,
  first-night task income, second/third-task request counts and elapsed time, and
  protocol/survival regressions. No real v0.11 score or win-rate improvement is yet proven.
- Release: `submissions/v0/submission-v0.11.tar.gz` (33 runtime files including entrypoint).
- SHA-256: `b512dce54484d33ff3cd78aac0b8bb90fafae76191d356b7c8e4fce4f8fe52d2`.

### 2026-09-18 - v0.10 task execution, checker recovery and method coverage

Evidence and scope:

- Started on codex/v0 at 22411cd51340481ebb49ef0134f55bfd472666a6; preserved the
  user's pre-existing AGENTS.md edit outside the release.
- Eight returned v0.9 runs: API tasks 0 full / 5 partial / 19 zero, repair tasks
  7 full / 17 zero. Thirty-five of 48 tasks never submitted. Nine API tasks executed
  only document inspection. All five partial API submissions contained empty statistics;
  three were incorrectly considered internally checked. No method reuse was observed.
- Repair failures included checker-launch failures with existing working directories,
  repeated old patches after prior writes, and scalar proofs rejected until packaged
  as required objects. Exact interpreter failures are not recoverable from older logs;
  CRLF is a reproduced possible cause, not a confirmed explanation of every incident.
- This release changes task execution and diagnostics only. Weapon composition, layout,
  combat priorities, worker/procurement policy and the HTTP/protocol boundary are retained.

Changes:

1. Derive answer shapes from current explicitly labeled JSON examples, JSON Schema
   or field/type rows. Ignore example values; conflicting requirements require
   clarification. Preserve rejected API plans and request only the missing contract,
   with explicit rejection events and a bounded correction cycle. Complete API prompt
   examples include the required contract/filter fields.
2. Keep current-task headers, method and body after HTTP 200 while correcting data
   interpretation; explicit reset remains available and authentication failure clears
   that state. Recover a unique nested record array only when the current filter checks
   against its actual rows; pagination and completeness validation still apply.
3. Generic Python statistics without executor retrieval evidence cannot fast-submit
   as checked. Retain valid computed candidates for deadline partial credit; preserve
   separate failed-business-assertion handling. This may delay a valid custom solver,
   so measure unsupported task variants rather than silently trusting empty data.
4. Record applied-patch receipts keyed to the task and content fingerprints. A retry
   skips only confirmed prior writes; changed files and new tasks invalidate receipts.
   Checker evidence includes launch stage, errno, entry/working-directory checks and
   interpreter availability. Recognized shell/Python shebang issues can use explicit
   interpreter invocation without modifying the checker. Do not infer a pass from launch.
5. Separate proof extraction from the current submission contract. Repair procedures
   package scalar proofs before schema validation; ordinary successful scripts can
   supply explicit JSON or a uniquely labeled current proof without another LLM call.
   Explicit checker failure blocks extraction. Arbitrary stdout is not a proof.
6. Ordinary-script proof workflows now enter match-local provenance tracking, including
   current contract, extraction style and abstract steps, excluding source, paths,
   patch values and proof values. Compatible later-task extraction can actually use
   that method. API procedures can derive compatibility from current bindings rather
   than requiring the model to author the metadata. Partial outcomes remain provisional.
7. Add plan rejection, independent verifier snippets, patch application flags and
   checker-start details to sanitized diagnostics. Preserve safe protocol schema keys,
   explicitly mark masked program literals, and omit bulky optional details before
   losing failure events. Document reads are no longer counted as execution failures.
   Learning no longer depends on whether an audit event fits its logging budget.

Verification:

- Seven synthetic pipeline regressions were saved and failed before the implementation.
  Added further cases for nested API records, task-local request recovery, dynamic
  proofs across three tasks, incompatible contracts, receipt invalidation, explicit
  checker failure, JSON Schema variants and bounded sanitized evidence.
- 260 unittest cases passed, including both 1300-turn synthetic sides. Tests use
  prescribed synthetic model outputs and local services, not real-model task success evidence.
- Source and clean-archive HTTP checks passed on both sides: malformed JSON, null/list
  fallback and 71-turn restricted opening. Three rockets, 12/13 walls and two operators
  covering three guns; maximum observed HTTP latency 49.3 ms.
- Runtime modules and embedded task program parse with Python 3.11 syntax rules;
  local execution uses Python 3.14.6, not the exact target Python 3.11.10.
- Archive contains 32 runtime files: entrypoint and 31 modules. Bytes match current
  source, with no tests, logs, references, task data or credentials.
- Release: `submissions/v0/submission-v0.10.tar.gz`.
- SHA-256: `16f152d8eb12b88702a3ac9feefc95dbdc39c90b55d564e6bf8321d1c99d267b`.

Remaining boundaries and next evidence:

- No official match was launched. Do not claim stable API full success, three-of-three
  repair success, higher score or better survival from synthetic tests.
- Contract inference covers explicit supported forms; ambiguous/unrecognized prose
  still needs the model. Actual authentication and business semantics still need
  current documents and runtime evidence. Nested-path recovery cannot resolve ambiguity.
- Learned ordinary-script workflows cover extraction/packaging and abstract operating
  steps, not automatic reproduction of arbitrary project patches. Later-task reduced
  exploration and full correctness must be measured, not inferred from a reuse counter.
- Compare read-only/no-solver tasks, successful API retrieval, empty-result false
  verification, checker recovery, first-attempt submission format, full/unsubmitted
  rates by category, later-task timings and early task income. Check survival/protocol
  regressions while keeping the unchanged defense baseline as the comparison.

### 2026-09-17 - v0.9 shared rockets, task SOPs and task evidence

Scope and evidence:

- Started on codex/v0 at 88d820e6c7179e8b083cc14d194f0bb21e2b0261.
  The pre-existing AGENTS.md edit was preserved and excluded from this release.
- The latest seven-run review of v0.8 found API tasks: 0 full, 4 partial, 17 zero;
  repair tasks: 4 full, 17 zero. Of 42 tasks, 33 never submitted. All 48 observed
  missing-file events were repair tasks, and all 30 answer-schema events were API
  tasks. These are different samples from the earlier release entry below.
- Partial API rewards do not prove pagination was the sole cause. Missing-file
  categories do not identify one universal path error. Own observed repair baseline
  remains at most two of three full successes per run, not three of three.
- The user explicitly authorized the primary composition and operating changes.
  No original match data, task projects, answers or credentials are release inputs.

Changes:

1. Three rockets occupy requested normalized diagram cells 12, 14 and 15. The shared
   post at 16 covers two rockets; a second post covers the remaining one. Use actual
   cooldown, one action per operator, dynamic assignment and generic-layout fallback.
   Four rear wall cells stay open. Projected damage reduces repeated targeting of
   already lethal small/medium groups; immediate threats to a damaged base can override.
2. Two operators defend the first two nights while a spare worker can mine safely.
   From night three, a worker carrying wall items supports front walls 3, 4, 2, 1,
   moving when necessary and retreating from unprotected danger. Maintenance uses
   low health and estimated incoming damage, not automatic full-health upgrading.
3. Actual return paths use two total margin turns. Weapon upgrades progress through
   all level-two guns, then all level-three guns, before ordinary base development.
   Purchased weapon vouchers can accompany daytime work and be used on-route or at
   recall. A voucher-carrying spare must return. Day-one pioneer prioritizes tasks;
   later funded procurement can precede a new task, never interrupt an active one.
4. API tasks use a callable deterministic executor for filter validation, bounded
   pagination, stable-ID deduplication, repeated-page detection, total/end evidence,
   and explicit field computations. A short page alone never proves completion.
   Contracts, field comparisons and failures remain explicit. Complete current-task
   data can be cached for recalculation; missing cache files cause fresh retrieval.
5. Repair procedures distinguish documentation and project directories, perform
   bounded unique-file recovery and confirm the checker before patching. Patch
   match counts and execution evidence are retained. Local executable checkers and
   structured/text proof extraction are supported without statistical verification
   gates. Fresh task-bound successful proofs take the fast submission path.
6. Per-task candidates and match-local methods have separate lifetimes. Method tiers
   distinguish observations, executed procedures and platform-full outcomes. Reuse
   requires fresh bindings and a matching declared contract; runtime contradictions
   invalidate methods. Stored templates exclude old answers, authentication bindings,
   project patch values and check invocation paths. New matches reset series state.
7. Auxiliary verifier exceptions preserve a structurally valid computed candidate
   for deadline submission; an explicit failed business assertion does not authorize
   that fallback. Schema details identify fields and types, including supported aliases.
   Mismatched task envelopes and unsolicited stale model results cannot recycle proofs.
8. Bounded sanitized task events include anonymous task/category ordinals, document
   fingerprints/truncation, selected program/exception evidence, API page/field checks,
   repair paths/match counts, submission shape, feedback, reuse and outcome provenance.
   Unknown output object keys are anonymized as well as values.
   Known buy/sell/build effects are deducted before reward classification; ambiguous
   settlements remain unknown. Proof values are excluded. Encoding follows redaction.
   Event/task/match budgets and drop counters protect response and log limits.
9. Read-only diagnostics support legacy logs and decoded JSONL, category summaries,
   per-task timelines/details, failure reasons and method reuse/ordinal timings:
   `python tools/diagnostics/decode_match_log.py match.jsonl.xz --tasks`, or
   `--task-id T002 --detail-limit 24` for bounded detail.

Verification and artifact:

- Saved failing synthetic regressions before implementation for candidate loss,
  legal executable checker rejection and requested layout/configuration.
- 232 unittest cases passed on Python 3.14.6, including both 1300-turn synthetic
  regressions. API fixtures vary response shape, ignored filters/page size, totals,
  repeated/overlapping pages, authentication, cache and fresh task bindings. Repair
  fixtures vary directories/configuration and dynamic proofs; ambiguous paths and
  patches fail explicitly. Audit tests cover redaction, budgets and mixed coin events.
- Source and clean-archive HTTP checks passed on both sides, including malformed
  JSON, null/list fallback and 71-turn restricted construction. Each produced three
  rockets, 12/13 walls and two operators covering all three guns. Maximum observed
  HTTP latency was 139.6 ms. This is synthetic opening evidence only.
- All 30 runtime modules and embedded sandbox parse using Python 3.11 syntax rules.
  Execution on exact Python 3.11.10 remains unverified locally.
- Archive contains 31 runtime files: entrypoint and 30 modules; source bytes match.
  No tests, logs, private references, task projects or credentials are included.
- Release: `submissions/v0/submission-v0.9.tar.gz`.
- SHA-256: `10b0bd864af9f7179def979cd792e7237bc6ebb5dcf577677014d7505a6b1a59`.

Limits and next match acceptance:

- No official match was launched. Prescribed synthetic solver inputs do not establish
  real-model success, platform scores, win rate, or stable three-of-three repairs.
- Fresh interface interpretation and applicability still require model decisions;
  saved methods alone do not establish effective self-improvement. Compare second/
  third-task exploration count, elapsed turns and full outcomes, not only reuse flags.
- Measure full/partial/zero/unsubmitted by category, three-of-three repair runs,
  earlier task funds, actual weapon upgrade turns and protocol/survival regressions.
- Observe shared-operator missed shots, four-cell rear exposure, two-turn recall
  lateness, third-night support safety and real splash/damage semantics. These changes
  are authorized experiments, not proven survival improvements.
- Unknown reward attribution stays unknown. Limited legacy logs cannot reveal missing
  historical programs, exact patches, answers or checker outputs.

### 2026-09-16 - v0.8 task verification, recovery and development funding

Evidence and scope:

- Started from clean codex/v0 at eebab3dbaa9ad8aae9a2748b629a6d565bd31092.
  User approved task-system and money-system improvements and standing publication.
- Seven returned runs: 42 tasks, 7 full completions, 17 partial settlements, 18 zero
  rewards; mean task gold about 119 per run. Fifteen tasks never submitted and twenty
  encountered missing-file categories. Partial settlement is counted at task end,
  including timeouts. Exact failing paths/programs are unavailable in sanitized logs.
- No third-level weapons/walls observed. Last supplied records still contain bases;
  no final-score or exact destruction claim. Source logs and analysis remain private.

Changes:

1. Keep repair/check and API fast submission; generic computed JSON now needs a
   field/type contract plus separately executed candidate-referencing assertions.
   Solver and verifier share one bounded sandbox call. Non-executed assertions,
   missing fields, wrong types and failed verification cannot produce a checked answer.
   Contracts/checks can still be mistaken; they are not the official judge.
2. Mark document truncation and support bounded continuation. Return directory/file
   evidence on missing paths; support workspace-relative source inspection. Envelopes
   remain parseable under output limits. Real text checker results can be extracted
   using one unique pattern; no copied proof or answer values.
3. Retain failed-program fingerprints, reject unchanged failed programs and rejected
   answers, and seed old-output signatures at acceptance. Preserve task context during
   recovery; clear it between tasks. Bound steps by timeout and reserve finishing time.
   Near deadline, a structurally valid computed candidate may be submitted for partial
   credit, but a failed latest execution cannot recycle an old candidate.
4. Continue development savings through key level-two front walls, the first
   level-three rocket from day three, key level-three walls from day four, then the
   other rocket. Actual shop items/prices and carried vouchers determine funds.
   Critical structures outrank development purchases. Dates are tunable hypotheses.
5. Urgent liquidation counts this worker's inventory, not all workers' combined
   holdings. Underfunded development suppresses speculative waiting for higher prices.
6. Telemetry adds stages, schema/check status and rejection counts without content.
   Read-only log summaries identify end-of-task full/partial/zero observations and
   mark mixed income rather than equating every failed task with zero reward.

Verification:

- Six minimal regressions failed on v0.7 before implementation; all pass now.
- 192 unittest cases passed on Python 3.14.6, including both 1300-turn synthetic
  sides with zero invalid responses, dropped/failed actions and planner failures.
- Actual subprocess tests cover randomized computation/verification, failed and
  unexecuted checks, scalar zero answers, text proof extraction, document tails,
  missing-file evidence, stale output rejection, duplicates and deadline recovery.
  Solver/check programs are prescribed test inputs, not a live LLM benchmark.
- Funding regressions cover advanced vouchers at current prices, critical repair
  priority, front-wall milestones, personal-stock liquidation and forecast suppression.
- Source and clean-archive HTTP checks passed on both sides, including malformed JSON,
  null/list fallbacks and 71-turn restricted construction. Three weapons, 12/13 walls,
  three controllers in place; maximum observed HTTP latency 140.9 ms.
- All 26 runtime modules and embedded sandbox parse under Python 3.11 syntax.
  Exact Python 3.11.10 execution remains unverified locally.
- Archive has 27 runtime files (entrypoint plus modules), matching source bytes;
  no reference data, tests, analysis, logs or credentials are included.
- The new read-only task outcome summary reproduces all 7 full, 17 partial and
  18 zero-reward endings across the seven old logs, totaling 832 observed task gold.

Release:

- `submissions/v0/submission-v0.8.tar.gz`
- SHA-256: `f8c9f8ae7a39064a16ecf189250cfc21a80dd94594d880cd794d246f57886af8`
- Publication to codex/v0 is covered by standing authorization. No official match
  or platform submission has been run.

Next calibration:

- Compare full/partial/zero results, no-submit tasks, missing-file retries and first-night
  task gold. Four tasks/320 gold before night is a target, not a verified v0.8 result.
- Check advanced purchase-to-use timing, critical wall upkeep and whether savings
  reduce maintenance at a dangerous time. Task and funding improvements do not prove
  better match survival or a particular score. No platform upload or match was started.


### 2026-09-16 - v0.7 delivery access, development savings and task execution

Evidence and scope:

- Based on v0.6 `47227c31e108ea3e8fc35e10d4f0b9db5d8fa329`, with a clean initial
  `codex/v0` worktree. User requested autonomous v0.7 implementation and publication.
- Four returned sequences contain 633/485/489/481 consecutive turns, with last scores
  505/282/393/265 and bases still present. These are recorded state scores, not confirmed
  final match totals. Local planner failures and validation drops are zero in all four.
- Each run upgrades a rocket before the first night (use turns 46/53/52/47), but only
  2/1/2/1 tasks succeed from six accepts each. All four have one successful first-night
  task for 80 gold, versus four tasks/320 gold in the reference examples. Missing-file,
  unsupported-command and command-budget categories accompany continued task timeouts.
  Raw commands are absent, so exact syntax/path causes cannot be claimed from categories.
- On the mirrored opening, a pioneer occupies the first building cell. Moving it away
  and building next turn explains the observed initial worker wait. It is not a blanket
  opening pause; the other worker and pioneer both receive movement commands.
- A base voucher purchased at 290 is used only at 432. An idle pioneer occupies the
  delivery interaction goal, which the old yield logic explicitly excluded. A frozen
  scene reproduces the courier stall; with goal yielding it reaches use after 16 moves.
  Another carrier's ownership also blocked independent carried-item deliveries.
- Three bases remain level one through their last records. Repeated optional wall
  spending prevents accumulating the next basic upgrade; idle pioneers coexist with
  busy worker couriers. Per-run summaries/hashes and reconstruction remain local-only.

Changes:

1. Yield lower-priority idle roles occupying delivery goals, while preserving occupied
   next-cell, collision, task-lock and firing protections. A role gets only one yield.
2. Let any role deliver owned maintenance items independently of the purchase carrier;
   allow simultaneous independent deliveries after nighttime threats clear. Recall use
   is restricted to owned items so it cannot bypass the procurement budget.
3. Protect the next basic upgrade fund: first level-two rocket; level-two base from
   day two; remaining level-one guns. Critical repairs remain eligible. Optional repairs,
   wall upgrades and spare fixers use surplus. The three-front-wall target is retained
   subject to funded basic development, not guaranteed by the second night.
4. Prefer idle pioneers for new cleared-night procurement. In daytime, sufficiently
   long task cooldowns can accommodate shopping. With no valid task, pioneers can stage
   near the shop when the route/cooldown/return budgets fit, freeing miners for income.
5. Preserve the last two attempted programs alongside documents/results; expose
   workspace-relative filenames and support relative repair paths in the discovered cwd.
   Add bounded direct Python execution, including recognized Python source in command
   fields, and common local shell command forms. Token-boundary checks avoid accidental
   substring rejection. These close reproduced compatibility gaps, not every logged error.
6. A program explicitly marked as final can submit its successfully computed last JSON
   line directly; ordinary inspection/script output still requires synthesis. Checked
   and computed results are distinguished. Errors/non-JSON/truncation cannot auto-submit.
   A live runtime task phase takes precedence over the estimated timeout boundary;
   inactive phases clear evidence. Command limit is eight; submission limit remains three.
7. Add a bounded command-kind diagnostic; no source, paths, prompts or answers are logged.
   Detailed current worker/task behavior is in `docs/operating-logic.md`.

Verification:

- Five new minimal regressions failed on v0.6 before implementation, then passed.
- 168 unittest cases passed on Python 3.14.6. Included both 1300-turn synthetic sides
  with zero invalid responses, dropped actions, failed actions and planner failures.
- Actual subprocess transport solves a fresh generated dataset in a nested workspace
  and submits the computed result without another LLM round. Actual repair/check runs
  verify cwd-relative patches. Tests cover failure/non-JSON suppression, program retention,
  deadline-boundary completion, independent delivery, goal yielding, saving and pioneer
  staging/task protection. LLM solver programs are prescribed, not a model benchmark.
- An additional targeted check confirmed critical wall maintenance can still spend
  while saving for a base upgrade. Existing emergency maintenance regressions also pass.
- Source and clean-extraction HTTP tests passed on both sides: malformed JSON/null/list
  safe fallbacks plus 71 restricted opening turns, three staffed guns and 12/13 walls.
  Maximum observed HTTP latency across those local checks was 70.1 ms.
- All 25 runtime modules plus the embedded sandbox parse under Python 3.11 syntax.
  Exact Python 3.11.10 runtime verification remains outstanding.
- Archive contains 26 runtime files; module bytes match source. No tests, raw logs,
  reference material or analysis are packaged.

Release:

- `submissions/v0/submission-v0.7.tar.gz`
- SHA-256: `b56b896769abdca0dcddb9484ed51fab41666461633333ef759aebcfa09ac72e`
- GitHub publication is covered by standing authorization. No platform upload or match.

Next calibration:

- Obtain v0.7 task completions/income before first night and overall, especially whether
  direct computation shortens successful tasks and whether remaining failures are path,
  syntax, logic or answer-shape failures. A computed answer may still be wrong.
- Compare base/weapon upgrade use rounds, purchase-to-use delay, worker sale income and
  pioneer holding time excluding active tasks, safe recall and shop readiness.
- Check that saving does not starve necessary walls under actual pressure. Both savings
  and front-wall counts are configurable. Frozen scenes and synthetic worlds cannot prove
  official survival, win rate, treasure success or a score approaching 2000.

### 2026-09-16 - v0.6 task evidence, operating routes and second-night front walls

Evidence and scope:

- Based on v0.5 commit `6673d27ced1c9cf7944cf8656bdfd64004bb1855` on `codex/v0`.
  User approved the operating update and requested earlier level-two walls; standing
  authorization covers GitHub publication. No official match or platform upload.
- Two returned runs end at rounds 370/371, scores 139/135 and base health 25/40.
  Both bases remain in the last records; these are not confirmed final scores.
- Each run accepts six tasks with zero successful task income. Five expire; the last
  is interrupted after recall. In the reference runs first-day tasks contribute
  approximately 560/554 points and 480 gold. Non-task scores match at the first two
  day boundaries (40 and 95), so task operations dominate the early measured gap.
- One purchased voucher remains unused for 93 rounds. A reproduced future-route
  reservation suppresses courier movement; recall and critical-only nighttime use
  then delay the first rocket upgrade. Raw command details are absent: diagnostic
  categories do not prove the exact failing file or permission for every task.
- One third-day worker-action trace has 106 moves, 17 collections and no sales; carried
  resources at one observed point would sell for 99 at current prices. Completing
  cash-out before recall matters more than nominal collected inventory.
- Detailed source hashes, comparison and raw logs remain local-only.

Changes:

1. Retain bounded task documents, discovered workspace and recent results. Execute
   scripts and checks in the discovered directory; missing requested documents are
   reported rather than silently substituted. Failure blocks unsupported answers;
   checked procedure results can submit directly. Reset context between tasks.
2. Share obstacle-aware work/delivery/return budgets and traffic margins across task
   acceptance, economy, shopping and recall. Planned shopping includes delivery/use,
   not just arriving at the shop. Task duration remains an estimate.
3. Reserve only the next two cells of a higher-priority future route for goal avoidance;
   retain all current-step collision and yield protections. Adjacent owned deliveries
   can finish during recall when physical return time remains. Idle night operators
   may use carried upgrades; firing retains priority and operators stay in range.
4. Rank complete mining/sale/return trips, trim batches to remaining daylight and
   estimate depletion from successful own collections. Compare continuation against
   immediate cash-out, including team stock needed for upgrades. Retain own-half
   mining, current prices and evidence-backed price windows.
5. Starting on day two, target three level-one front walls for level two. Choose
   damaged front walls first and value upgrade healing. Preserve the first rocket
   fund except for critical maintenance. Remaining level-one weapons and urgent base
   survival continue competing for funds; completion before night is conditional.
6. Log task workspace readiness, retained-document count and execution-evidence state,
   plus bounded procedure error categories, without task documents or answers.

Verification:

- Five minimal synthetic incidents failed before the fixes and passed afterward.
- 157 unittest cases passed under Python 3.14.6, including both 1300-turn synthetic
  sides with zero invalid responses, dropped/failed actions and planner failures.
- Added actual subprocess task transport through a random nested workspace: discover,
  fail a checker, retain requirements, repair, execute the checker and submit its
  freshly generated answer. Also checked relative multiline scripts, malformed context,
  obstacle-aware task refusal, cash conversion, firing/maintenance priority and mirrored
  three-front-wall selection. Solver instructions in tests are prescribed, not real LLMs.
- All 25 runtime modules and the embedded sandbox program parse as Python 3.11 syntax.
  Exact Python 3.11.10 execution remains untested locally.

Release:

- Archive: `submissions/v0/submission-v0.6.tar.gz` (26 runtime files including entrypoint).
- SHA-256: `53ee4f7761d1a69b946a79bfe56f633f2ea3b1d7e959c95e91dd160eec24be7d`.
- Source and clean-extraction HTTP checks passed for both sides, including malformed
  JSON, null/list bodies and 71 opening turns. The restricted synthetic world reached
  three staffed guns and 12/13 walls; maximum observed HTTP latency was 89.7 ms.
  Archive module bytes exactly matched the source; no tests, logs or references are included.

Next evidence and limitations:

- This release has no official match evidence and no claim of 2000 points or sustained
  survival. Test worlds do not represent real enemy pressure or LLM quality.
- Return sanitized v0.6 summaries: task accept/command/error/submit/completion and gold;
  day-one/day-two purchases and actual use; second-night front-wall levels/health,
  base health and staffed guns; third-day collect/sell/move counts and carried stock.
- Inspect whether task context persists through actual failures, deliveries finish
  before recall, and stock becomes spendable income. If failures persist, request a
  narrowly redacted command/checker excerpt rather than entire sensitive task files.
- Dynamic traffic, unknown competitor mine depletion, greedy multi-stop routing and
  estimated task duration remain limitations requiring platform calibration.

### 2026-09-16 - v0.5 local economy, individual recall and task command compatibility

Evidence and scope:

- Based on published v0.4 commit `f9f9161c861729a6d33785b62c010eb04410eca7`
  on `codex/v0`. The user requested this v0.5 update and GitHub publication.
  No platform submission or match was launched here.
- Two returned v0.4 runs have 354/365 consecutive records, ending at score 107/112
  with base health 30/45. The base is still present: neither destruction nor final
  score is confirmed. Three rear weapons exist by state rounds 14/13; third-night
  telemetry contains no unstaffed weapon. Layout alone did not fix performance.
- First-night walls are only 4/8, task income is zero, and no weapon/base upgrades
  occur. Reference runs had 16/18 walls, four tasks for 320 gold and a level-two
  rocket before the first night. The operating gap is still substantial.
- Own-side ore is visible while the worker travels to opponent-side copper.
  Mine value omitted home-return cost. One remote worker triggered team-wide recall,
  stopping nearby wall work. A sixteen-stone opening batch also delayed construction
  when the first finite mine depleted.
- A worker accepted a procurement order after night clearance, but daytime engineer
  scheduling skipped delivery. Carrier ownership blocked other couriers until expiry;
  repairs stayed in inventory while the task-exhausted pioneer waited at home.
- Task telemetry confirms repeated rejections/timeouts but omits raw commands. The
  reference workflow uses local cd and multiline solvers, both rejected by v0.4.
  This reproduced compatibility gap is not a proven explanation for every failed task.
  Original logs, source hashes and detailed comparison remain in ignored local analysis.

Changes:

1. Default mining stays in the normalized home half. Rank complete collection/sale/
   return trips, penalize long returns, and retain batching and live prices. Partial
   inventory can be sold when no safe local mine remains. No location is copied from
   a match. Nearest rear construction begins first; first stone batches are ten.
2. Recall is computed and latched per role. Nearby workers keep working while distant
   roles return. Static route time includes a separate traffic allowance; unassigned
   roles still return toward the base. Dynamic humans cannot erase all controller
   approach candidates, and empty goals cannot raise an exception.
3. Resume carried procurement orders before daytime engineer work. Allow that worker
   to deliver/use items and recover interrupted trips instead of stranding goods.
4. Reserve early discretionary money for the first level-two rocket. Optional wall
   purchases wait, critical maintenance remains available, and the first rocket can
   use the cash reserve after mandatory construction. Cash-out targets use shop prices.
5. Accept local cd and multiline heredoc/quoted Python commands. Transport multiline
   scripts as one encoded command with bounded process-group lifetime and output.
   Generic procedures, dynamic checker answers, five command steps and recovery remain.
   Script success alone is not a checked answer. Missing submit feedback is no longer
   counted as success. Rejection and sandbox categories contain no command/output text.
6. Log mine changes within each day, selected mines, recalled roles, engineer/carrier,
   task failure categories and planner exception counts. Clear stale activity labels.
   The summary decoder exposes category/activity turn counts, not sensitive contents.
7. Synthetic replay now fails on strategy exceptions as well as invalid responses,
   failed actions and validator drops. Development exposed an empty-goal recall exception
   which previous replay assertions missed despite producing protocol-safe fallbacks;
   it was fixed before packaging, and a fault-injection test verifies this new check.

Verification and limits:

- 145 unittest cases pass under Python 3.14.6, including both 1,300-turn synthetic
  sides with zero planner exceptions, rejected actions, failed actions or invalid
  responses. This is regression evidence, not a match score or win rate.
- Independent finite-mine opening fixtures have three operators before first night,
  10/13 walls without prescribed task income, and no illegal construction. The income
  fixtures prescribe four successful tasks and show upgrade delivery; they do not
  measure real LLM performance and still fall below reference wall counts.
- Added synthetic incident checks for both-side local mining, independent recall,
  engineer repair delivery, first-rocket funding with emergency overrides, command
  acceptance, actual encoded multiline execution and dynamic result submission,
  mine-change telemetry and missing task feedback.
- Source startup via run.sh and clean archive startup both pass malformed JSON,
  non-object JSON and eight-turn independently restricted HTTP construction checks.
- All 23 runtime modules and the sandbox program parse as Python 3.11; exact 3.11.10
  execution remains unavailable locally. The archive has exactly CoreGeek/main3.py
  plus 23 solution modules whose extracted bytes match reviewed source.
- Candidate: `submissions/v0/submission-v0.5.tar.gz`.
  SHA-256: `862c563c472e3c72a054ce8c06b00fc2c43a4cdc45f6f7719543599ebab107e4`.
  Earlier artifacts remain unchanged and SHA256SUMS includes v0.5.

Next platform checks:

- Local versus remote mining, mine depletion/respawn, sale quantities and actual gold.
- Per-role recall and three staffed weapons at 70/71; first-wall timing and wall count.
- Task command categories, first actual successful task and task gold; then timing of
  the first rocket upgrade. Raw task text, tokens and full sensitive logs are unnecessary.
- Cross-day carried repair delivery, third-night base health and sustained upgrades.
- Real score improvement, route safety and survival are unverified until new matches;
  the new mine boundary and return weights may trade some high-price income for safety.


### 2026-09-16 - v0.4 operating-cycle candidate

Status and evidence:

- Based on `f18930a49dd56c815ba11c055ca87b153f247921` on `codex/v0`.
  This revision distributes the v0.4 candidate through GitHub under the standing
  commit/push authorization above. No v0.4 platform upload or match has been performed.
- The returned v0.3 run confirms three weapons by state round 4 and ten walls at
  the first night, but no completed tasks/upgrades. The third night had an
  unstaffed railgun and the base disappeared in round 362. Side/rear robots were
  observed; fixed-gate safety must be reassessed against actual paths.
- Two reference runs had four tasks and 320 task gold before the first night,
  16/18 walls and a level-two rocket. They reached the tenth night in the supplied
  records, not a confirmed final victory. Their raw data remains private.
- The traffic failure combined a side railgun slot with two held rocket operators
  blocking access. A coordinate-only change would not resolve that deadlock.

Implemented groups:

1. Three preferred rear weapon sites, separate control sites, obstacle-aware joint
   assignments, and restricted yielding by idle/cooling roles. Temporary occupancy
   cannot permanently displace a weapon site. Wall building checks reachability.
2. Task state cleanup, short-task eligibility, fenced structured JSON, progress
   diagnostics and bounded retries. Generic sandbox programs inspect local files,
   make unique edits then run a checker, or aggregate complete paginated loopback
   API results. Checked answers can submit directly; answers are never cached across
   task instances. Background news replies cannot swallow task responses.
3. One engineer plus one economy/procurement worker. Persistent stone batches survive
   mine depletion; economic mining uses route-adjusted value, stable targets and
   batch sales. Front walls precede nearby side work rather than alternating faces.
4. Committed purchase baskets and destinations, inventory-confirmed delivery, stale
   trip recovery, critical repair spending from emergency reserves, and level-two
   weapons before optional level-three development. Tasks retain the pioneer by day
   and after a cleared night. Upgrade delivery uses the wire target anchor, avoiding
   repeated validation rejection beside a different cell of the 2x2 base.
5. Live market prices remain authoritative. Explicit official news and source-quoted
   interpretations can create bounded future windows; stock holding requires defense
   and working capital. Folk clues remain separate. Treasure shopping/attempts require
   multi-day evidence, confidence, time/item checks and defense cash reserves.
6. Whole-match telemetry pacing, task/market/logistics diagnostics and per-weapon
   inactivity reasons. Decoder accepts original or decoded compressed logs and avoids
   associating action feedback across missing turns.

Validation approach and limitations:

- Layout and traffic regressions include both sides, complete walls, all six controller
  arrival permutations, and temporary role occupancy. Generic repair tests use fresh
  temporary directories and dynamic checker output; API tests serve multiple local pages.
- Opening fixtures independently enforce build rings, finite mines and unoccupied
  respawn cells. The replay now executes actual purchase/inventory/upgrade transitions
  and checks physical actions independently. It counts rejected planner actions as well
  as malformed responses and failed actions. The earlier harness omitted these checks.
- In the prescribed-answer income fixture, both sides finish four tasks for 320 gold
  and upgrade rockets before night. The LLM replies are deliberately synthetic: this
  proves scheduling and cash conversion only, not real task-solving success.
- First-night walls remain about 12–13 in these finite-mine fixtures, below the reference
  16–18. Do not report the first-day operating target as fully achieved.
- Runtime robot navigation/damage, real LLM/checker compatibility, treasure interpretation,
  sustained repair under pressure, and third-night/ten-day survival remain unverified.
  Night economic actions retain the existing failure-disable guard.
- Python 3.11.10 is still not available locally; Python 3.11 syntax checking is useful
  but is not a substitute for running the exact target interpreter.

Final local verification and candidate artifact:

- 135 unittest cases and bytecode compilation pass under Python 3.14.6.
  Both 1,300-turn synthetic sides report zero invalid responses, failed actions and
  actions dropped by validation. These are internal regression checks, not wins.
- All 23 runtime modules and the embedded sandbox program parse as Python 3.11.
- Source startup via `run.sh` and a clean archive extraction pass HTTP malformed-JSON,
  non-object fallback and an eight-turn independent restricted construction scenario.
- The archive contains only `CoreGeek/main3.py` and 23 `solution/*.py` modules;
  extracted module bytes match the reviewed source. No logs, references or tests ship.
- Local candidate: `submissions/v0/submission-v0.4.tar.gz`.
  SHA-256: `8ba7599cdb8de17b2302eb8ca106b43ea9232a7d106afe5df27580b428adc2a7`.
- `submissions/v0/SHA256SUMS` includes this candidate; previous artifacts are preserved.

Next platform acceptance:

1. Check all three rear weapons and operators at rounds 70/71, wall count and intrusion paths.
2. Check task completion/elapsed turns and actual gold, then first rocket upgrade timing.
3. Check second-day weapon/base upgrades and third-night staffing/repair, not just final score.
4. Check sale batches, delivery delay, live price windows and evidence-gated treasure results.
5. Compare more than one match on both sides; do not infer win rate from a synthetic replay.


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
