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

The zero-exception protocol foundation is implemented:

- dependency-free HTTP lifecycle and safe fallback
- defensive parsing into immutable turn models
- cross-turn feedback, news, and LLM-budget state
- internal action and decision objects
- centralized action validation and response serialization
- side normalization and base-footprint geometry

Competitive planners have not yet been enabled. The current planner returns no
role commands after safely ingesting the turn.

## Design Rules

- Runtime fields override fallback constants.
- Unknown input fields do not cause failure.
- Missing optional fields use explicit defaults.
- Strategy produces internal actions; only the protocol layer creates response JSON.
- All high-risk strategies remain configurable until supported by repeatable evidence.
