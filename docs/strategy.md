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
- First weapon composition to test: two railguns and one rocket launcher.
- Keep a balanced gatling/railgun/rocket composition as the first comparison.
- Build walls according to observed threat lanes rather than a permanently fixed template.
- Keep the legacy centre-facing sites as the default. The optional `frontline`
  layout places the rocket rearward, line weapons on side-rear firing lanes, and
  a short front wall with rear-side gates. Flank cells may be filled before the
  frontage target when crowding pressure is observed. This remains a candidate.
- Use tasks as a primary score and income engine when return-to-base safety permits.

## Unverified High-Value Hypotheses

- A global-range weapon may be able to earn score from robots targeting the opponent.
- Projectile interaction with weapon buildings remains unverified; walls and bases permit weapon fire.
- A dynamically opened and closed wall gate may outperform a permanent opening.
- Upgrading a damaged structure may be more valuable than upgrading it immediately because upgrades restore health.
- Summon orders are profitable only when the opponent is near a defensive threshold.

Each hypothesis must be converted into a small platform experiment and recorded in `docs/experiments.md` before it becomes a default strategy.

## Baseline Match Phases

### Opening

- Establish three weapons.
- Start stone collection for critical walls.
- Send the pioneer toward the highest-value safe task opportunity.
- Learn initial robot spawn and path behavior.

### Midgame

- Rotate task locations efficiently.
- Complete critical defenses.
- Upgrade according to measured wave pressure.
- Accumulate and verify treasure constraints.
- Estimate opponent pressure from globally visible information.

### Endgame

- Avoid risky travel when survival is uncertain.
- After the initial nighttime spawn observation, allow nearby supply runs if no
  relevant robots remain, or the remaining staffed weapons can conservatively
  kill all relevant robots this turn. Test multiple releases cumulatively.
- Count only accepted attack commands toward cleanup; recent failures or actions
  rejected during planning cannot authorize departures.
- Missing robot observations, critical nearby threats, insufficient damage or
  cooling weapons prevent release. Reevaluate every turn and recall roles as
  danger returns. Do not treat a low robot count as sufficient evidence.
- Reserve emergency consumables when their expected value exceeds another upgrade.
- Select defensive, score-race, or pressure mode from observed state.


## Implemented Boundaries

The baseline is enabled, but composition and economic thresholds remain
experimental. Build rings are confirmed: weapon cells have Chebyshev distance
one from the complete base footprint; wall cells have distance two. A permanent
entrance and forward firing corridors remain open.

Tasks require a reachable task point and a solving window plus return reserve.
Active tasks keep the pioneer in place until safety requires withdrawal. Runtime
prices drive income and purchases. The baseline uses carried medicine and can
spend a matching station voucher immediately when the base is critically damaged.
Mining closure/reopening news limits which resources may be gathered, independently
of their price. Controller assignment considers surviving roles and usable weapon
subsets jointly, with effective nighttime fire taking priority over weapon level.

Only defensive mode is enabled by default. Cross-map scoring is an explicit
experimental switch; summon-order pressure and dynamic gates are not enabled.
Treasure parsing validates shape, inventory, time, bounds and source evidence;
LLM confidence alone does not establish that its interpretation is correct.
Safe nighttime treasure windows are supported. Successful or already-empty
treasure feedback persists until the next match and prevents further probing.
See `baseline.md` for verification scope and remaining platform checks.

Walls and bases block movement but do not block weapon trajectories (user-confirmed).
Keep weapon-building occlusion configurable and conservative. Prioritize actual
front/flank pressure with a shared construction order; retain built-wall classes
for maintenance and apply the wall cap to living plus committed structures.
