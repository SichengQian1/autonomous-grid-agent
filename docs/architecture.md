# Architecture

## Objectives

- Return a valid response on every turn.
- Keep normal decision latency far below the platform deadline.
- Separate protocol safety from strategic experimentation.
- Support deterministic replay and rule changes.
- Use Python 3.11 standard-library functionality at runtime.

## Decision Layers

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

The zero-exception protocol foundation is implemented:

- dependency-free HTTP lifecycle and safe fallback
- defensive parsing into immutable turn models
- cross-turn feedback, news, and LLM-budget state
- internal action and decision objects
- centralized action validation and response serialization
- side normalization and base-footprint geometry

The baseline is enabled through `BaselinePlanner`:

- `navigation.py`: bounded BFS, occupied cells, threat avoidance and reservations.
- `defense.py`: footprint-based build rings, firing positions and controller pairing.
- `layout.py`: optional frontline direction, joint weapon/wall plans, wall-class
  geometry and bounded night-pressure summaries.
- `maintenance.py`: wall build/repair/upgrade ranking that follows construction
  dependencies, item budget and delivery tasks.
- `ballistics.py`: shared projectile blockers, excluding walls and bases but retaining weapon buildings.
- `combat.py`: threat scoring, ray/area damage and joint target allocation.
- `economy.py`: building, gathering, sales, supply purchases and upgrades.
- `resources.py`: per-mineral closure windows and validated news interpretations.
- `tasks.py`: LLM correlation, task feedback, restricted sandbox diagnostics and treasure clues.
- `planning.py`: shared gold/target reservations and incremental action validation.
- `strategy.py`: day/night scheduling, return deadlines and safe night supply runs.
- `configuration.py`: validated local JSON configuration.
- `turnlog.py`: optional bounded per-turn request/response/decision envelopes
  to a directory or stderr, written after the HTTP response.
- `turncrypto.py`: stdlib-only ChaCha20 + HMAC-SHA256 authenticated encryption
  with scrypt/PBKDF2 key derivation for turn logs.

News replies are consumed before role decisions in either phase. Night release
proofs are recomputed from committed attacks; controller pairing ranks the joint
effective fire of surviving role/weapon combinations.

An identical retry reuses its response; stale turns do not mutate state. Match
restarts reset planner and LLM state. Expensive searches share a cooperative
monotonic deadline; this is not OS-level preemption. Server exceptions retain the
empty-command fallback.

## Design Rules

- Runtime fields override fallback constants.
- Unknown input fields do not cause failure.
- Missing optional fields use explicit defaults.
- Strategy produces internal actions; only the protocol layer creates response JSON.
- All high-risk strategies remain configurable until supported by repeatable evidence.
