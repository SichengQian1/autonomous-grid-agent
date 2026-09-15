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
- task, bounded LLM/sandbox, news, and confidence-gated treasure state
- opponent pressure modes and reserve-gated summon/cross-map decisions
- two-side ten-day synthetic regression and bounded log summarization

Platform-dependent mechanics remain configurable and feedback-gated. Synthetic
tests prove internal behavior only; practice telemetry is required for calibration.

## Active Modules

- `grid.py`: occupancy and pathfinding
- `movement.py`: joint next-step scheduling
- `defense.py`: normalized threat geometry and fixed opening
- `economy.py`: construction targets, resource value, and defense budget
- `logistics.py`: upgrade and repair purchasing/use
- `combat.py`: controller release and target allocation
- `tasking.py`: task, LLM, sandbox, and treasure state machines
- `opponent.py`: global modes and Boss threshold evaluation
- `planner.py`: full-match orchestration and module degradation

## Design Rules

- Runtime fields override fallback constants.
- Unknown input fields do not cause failure.
- Missing optional fields use explicit defaults.
- Strategy produces internal actions; only the protocol layer creates response JSON.
- All high-risk strategies remain configurable until supported by repeatable evidence.
