# Strategy

## Global Objective

Use a lexicographic decision hierarchy:

1. valid response and service survival
2. avoid our base being destroyed first
3. defensive readiness before night
4. task and treasure value
5. efficient combat score
6. opponent-dependent score stealing or pressure
7. economic optimization

## Confirmed Implementation Constraints

- The final implementation uses Python 3.11.
- Normal decision responses must finish within the platform deadline.
- The core cannot depend on packages outside the supplied environment.
- Three roles must be coordinated to avoid destination conflicts and swaps.
- Strategy must work from either side through coordinate normalization.
- Runtime attributes and shop/task data are authoritative.

## Current Experimental Baseline

- Build all three weapon slots as early as safely possible.
- v0.3 primary composition: two rocket launchers and one railgun.
- Keep two railguns and one rocket launcher as the first comparison.
- Place weapons behind the base, flanking rather than occupying the rear traffic
  corridor. Build the centre-front wall first, then front extensions and side walls.
- Keep two permanent rear corridor cells open for role traffic.
- Build weapons only one cell from the whole base footprint and walls only two
  cells away. These are distinct rings; moving a weapon farther behind the base
  cannot override its permitted building area.
- Use both workers to complete three weapons; collect stone in batches for the
  initial ten walls. Then release one worker for income while the other completes
  the remaining wall plan. Copper profitability must not preempt the stone quota.
- Do not dynamically remove and rebuild the opening in V1. Reconsider only if
  platform evidence shows flanking or a changed spawn pattern.
- Use tasks as a primary score and income engine when return-to-base safety permits.
- `USER_OBSERVED`: after normalization, the primary robot threat is on the
  positive-x/front side; the fixed activity exit is on the negative-x/rear side.
- A rear/side robot observation or unexplained rear-sector base damage invalidates
  the aggressive fixed-opening assumption and enables conservative geometry.

## Unverified High-Value Hypotheses

- A global-range weapon may be able to earn score from robots targeting the opponent.
- Ordinary projectile paths may interact with friendly walls differently from rockets.
- A fixed rear opening may retain safe role access without creating a robot route.
- `USER_OBSERVED`: upgrading a base, wall, or weapon restores it to full health.
  v0.2 therefore scores both the upgrade breakpoint and restored health, while still
  rushing one level-three rocket for its global-range breakpoint.
- Summon orders are profitable only when the opponent is near a defensive threshold.

Each hypothesis must be converted into a small platform experiment and recorded in `docs/experiments.md` before it becomes a default strategy.

All build-cell legality, night economy, projectile/wall interaction, overlapping
rocket settlement, cross-map kill ownership, wave composition, Boss timing, task
judging, and treasure details are `UNVERIFIED_PLATFORM_BEHAVIOR` until practice
telemetry promotes them to a runtime observation.

## Planned Match Phases

### Opening

- Establish two rockets and one railgun behind the base.
- Start stone collection for critical walls.
- Send the pioneer toward the highest-value safe task opportunity.
- Learn initial robot spawn and path behavior.

### Midgame

- Rotate task locations efficiently.
- Complete critical defenses.
- Upgrade according to measured wave pressure.
- Accumulate and verify treasure constraints.
- Estimate opponent pressure from globally visible information.

## v0.3 Safety Gates

- Boss-order purchases and use are disabled.
- Cross-map attacks are disabled even when `targetTeam` is present.
- Blind treasure probes are disabled; an attempt requires complete high-confidence
  coordinates, day, and non-empty owned items.
- Wall removal is never planned.
- While own-side threats remain, every weapon keeps a controller even during rocket
  cooldown. A cooling operator may use an adjacent carried item without moving.
- A task's pioneer stays reserved during LLM/command waits; optional logistics
  cannot move it off the active task point.
- Pre-night recall stays active for the rest of that day once triggered.
  Its deadline includes obstacle-aware return paths, not just straight-line distance.

### Endgame

- Avoid risky travel when survival is uncertain.
- Reserve emergency consumables when their expected value exceeds another upgrade.
- Select defensive, score-race, or pressure mode from observed state.
