# Architecture

## Objectives

- Return a valid response on every turn.
- Keep normal decision latency far below the platform deadline.
- Separate protocol safety from strategic experimentation.
- Support deterministic replay and rule changes.
- Use Python 3.11 standard-library functionality at runtime.

## Planned Layers

```text
HTTP server
  -> request compatibility layer
  -> immutable turn model
  -> cross-turn world state
  -> high-level strategic mode
  -> day/night planners
  -> joint role scheduler
  -> action validator
  -> protocol serializer
```

## Module Boundaries

The intended implementation separates:

- protocol parsing and serialization
- units, positions, inventory, tasks, and map models
- side-independent coordinate normalization
- pathfinding and joint movement reservations
- construction, economy, and return-to-base scheduling
- threat estimation and weapon targeting
- task, LLM, command, and result state machines
- opponent-pressure estimation
- validation, deadline control, and safe fallback
- replay and diagnostics

## Current State

The active V1 code loop is implemented:

- dependency-free HTTP lifecycle and safe fallback
- defensive parsing into immutable turn models
- cross-turn feedback, news, and LLM-budget state
- internal action and decision objects
- centralized action validation and response serialization
- side normalization and base-footprint geometry
- occupied-cell modeling and bounded eight-direction pathfinding
- conservative multi-role next-cell reservation
- mirrored three-weapon and fixed-rear-opening layouts
- defense-aware economy, construction, upgrade, and recall planning
- controller assignment, partial release, and projected-damage targeting
- task, bounded LLM/sandbox, news, and source-bound treasure state
- opponent pressure modes with v0.2 summon/cross-map safety gates disabled
- capped, integrity-checked `AGLOG2` telemetry and a local `.log`/`.log.xz` decoder
- two-side ten-day synthetic regression and bounded log summarization

Platform-dependent mechanics remain configurable and feedback-gated. Synthetic
tests prove internal behavior only; practice telemetry is required for calibration.

## Active Modules

- `grid.py`: occupancy and pathfinding
- `movement.py`: joint next-step scheduling
- `travel.py`: shared work/delivery/return route budgets and recall margins
- `defense.py`: normalized threat geometry and fixed opening
- `economy.py`: construction access checks, persistent mining/sale plans, and defense budget
- `market.py`: current/future price separation and bounded official-news windows
- `logistics.py`: persistent procurement baskets, delivery, critical repair and upgrade use
- `combat.py`: controller release and target allocation
- `tasking.py`: task recovery and LLM/sandbox coordination
- `treasure.py`: source memory, request snapshots, incremental candidates and bounded expeditions
- `treasure_claims.py`: material/source relationships, geometry and time checks; semantic inference stays explicit
- `task_answers.py`: bounded answer field/type contracts and canonical rejection fingerprints
- `task_context.py`: bounded per-task documents, workspace, attempted programs, and execution evidence
- `task_programs.py`: bounded sandbox inspection, repair/check, and API aggregation procedures
- `opponent.py`: global modes and Boss threshold evaluation
- `planner.py`: full-match orchestration and module degradation
- `telemetry.py`: sanitized bounded event encoding and integrity checks

## Design Rules

- Runtime fields override fallback constants.
- Unknown input fields do not cause failure.
- Missing optional fields use explicit defaults.
- Strategy produces internal actions; only the protocol layer creates response JSON.
- All high-risk strategies remain configurable until supported by repeatable evidence.

## v0.9 task evidence and shared control

TaskContext owns one task; TaskSeries keeps bounded match-local method templates
with observed/executed/platform-full provenance and explicit fresh binding checks.
The API executor is transported into the sandbox alongside repair procedures.
TaskAudit emits separately budgeted, redacted evidence and attributes task income
against successful economic actions. The engine isolates audit failures from game
responses. Defense assignment may share a controller across two compatible rockets,
while combat and validation still enforce one weapon action per role per turn.

## v0.10 task recovery

Task contracts are extracted by task_contracts from current answer documentation,
with explicit ambiguity handling. TaskContext retains current-task API bindings;
repair execution records task-scoped patch receipts. Proof extraction and answer
packaging are separate. TaskSeries learns bounded ordinary-script workflow metadata
without retaining script source or proof values. Telemetry reports plan rejection,
checker launch evidence and applied-patch state independently of successful document reads.
