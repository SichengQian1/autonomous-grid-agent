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
- Use tasks as a primary score and income engine when return-to-base safety permits.

## Unverified High-Value Hypotheses

- A global-range weapon may be able to earn score from robots targeting the opponent.
- Ordinary projectile paths may interact with friendly walls differently from rockets.
- A dynamically opened and closed wall gate may outperform a permanent opening.
- Upgrading a damaged structure may be more valuable than upgrading it immediately because upgrades restore health.
- Summon orders are profitable only when the opponent is near a defensive threshold.

Each hypothesis must be converted into a small platform experiment and recorded in `docs/experiments.md` before it becomes a default strategy.

## Planned Match Phases

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
- Reserve emergency consumables when their expected value exceeds another upgrade.
- Select defensive, score-race, or pressure mode from observed state.
