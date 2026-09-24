# Strategy

The versioned sections below preserve historical decisions. Current v0.21 behavior
is described in [the operating guide](operating-logic.md) and [HANDOFF](../HANDOFF.md).
v0.21 uses the complete v0.18 baseline. Its changes are unrestricted map-half
resource selection, sale-before-wall-supply trips timed to return before night,
and a wall-three support post. Similar repair urgency favors upgraded walls;
imminent collapse and actual worker danger retain priority. Treasure, task,
combat, ore holding on days one/two and other recall behavior remain at v0.18.

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
- v0.9 primary composition: three rocket launchers.
- Keep two railguns and one rocket launcher as the first comparison.
- Place three rockets in cells 14, 15 and 16, with one shared pioneer control post
  behind cell 15. Build the centre-front wall first, then front extensions and side walls.
- Keep four permanent rear corridor cells open for role traffic.
- Build weapons only one cell from the whole base footprint and walls only two
  cells away. These are distinct rings; moving a weapon farther behind the base
  cannot override its permitted building area.
- Assign one engineer to three weapons and batches of stone-funded walls. Start the
  other worker on income immediately. Collect an initial ten-stone batch and build before starting another batch;
  do not delay all walls while chasing a depleted mine for a sixteen-stone batch.
  Every wall must preserve structural access to control positions and living roles.
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
  v0.5 scores both restored health and weapon development, prioritizes critical
  maintenance, and favors level-two weapons before optional level-three upgrades.
- Summon orders are profitable only when the opponent is near a defensive threshold.

Each hypothesis must be converted into a small platform experiment and recorded in `docs/experiments.md` before it becomes a default strategy.

All build-cell legality, night economy, projectile/wall interaction, overlapping
rocket settlement, cross-map kill ownership, wave composition, Boss timing, task
judging, and treasure details are `UNVERIFIED_PLATFORM_BEHAVIOR` until practice
telemetry promotes them to a runtime observation.

## Planned Match Phases

### Opening

- Establish three rockets in the specified rear-half layout.
- Start stone collection for critical walls.
- Send the pioneer toward the highest-value safe task opportunity.
- Learn initial robot spawn and path behavior.

### Midgame

- Rotate task locations efficiently.
- Complete critical defenses.
- Upgrade according to measured wave pressure.
- Accumulate and verify treasure constraints.
- Estimate opponent pressure from globally visible information.

## v0.5 Safety Gates

- Boss-order purchases and use are disabled.
- Cross-map attacks are disabled even when `targetTeam` is present.
- Blind treasure probes are disabled; an attempt requires complete high-confidence
  coordinates, day, and non-empty owned items.
- Wall removal is never planned.
- While own-side threats remain, every weapon keeps a controller even during rocket
  cooldown. A cooling operator may use a carried item or move one safe cell while
  remaining adjacent to its weapon; a firing operator cannot be borrowed.
- A task's pioneer stays reserved during LLM/command waits; optional logistics
  cannot move it off the active task point.
- Recall latches separately for each role until the next day. A remote role cannot
  freeze a nearby builder. Return deadlines include obstacle-aware paths and
  a combined two-turn safety allowance; shared-control coverage and late arrivals require calibration.

### Endgame

- Avoid risky travel when survival is uncertain.
- Reserve emergency consumables when their expected value exceeds another upgrade.
- Select defensive, score-race, or pressure mode from observed state.

## Operating Cycle

- The pioneer selects reachable tasks using each runtime deadline and the return
  budget. A ten-turn task is not discarded merely because travel takes time before
  acceptance. Task completion/expiry clears stale output and answers.
- Generic bounded sandbox procedures inspect files, apply unique local edits and
  run a checker, or fetch all pages of a loopback API and compute declared fields.
  Actual checked output may be submitted directly. Local cd commands and multiline
  solver scripts are supported with bounded execution/output; script success alone
  does not mark an answer checked. No answer cache crosses tasks.
- Economy workers retain a mine while its return per travel/collection/sale turn
  remains competitive. Default mining stays within the normalized home half and
  prices the return trip as well as sale travel; inaccessible or distant mines
  cannot displace a safe local option solely through a high price. Default batches are ten items, with earlier sale at six
  when working capital or recall requires it. Depletion causes replanning.
- A carrier commits to a basket of up to three destinations, observes inventory
  after purchase, and delivers before reprioritizing. Expired trips recover.
  Carried orders survive night/day transitions, including orders held by the engineer.
  Until one rocket reaches level two, optional wall spending waits; critical repairs
  still take priority. First-rocket funding can use the emergency reserve after
  construction costs are reserved. Runtime shop prices set the cash-out target.
- Live vendor prices govern cash decisions. Only explicit official news or an
  interpretation tied to an actual source span creates a future window. Holding
  stock requires developed defense and working capital; dates are never fixed
  from previous matches. Folk clues do not change market prices.
- Treasure preparation requires multiple known clue days, high confidence,
  complete coordinates/time/items, an affordable shopping list and a safe route.
  Night-only treasure is considered only after threats clear. False confidence
  from an LLM remains a platform calibration risk.

## v0.6 Operating Decisions

- Preserve initial task requirements, discovered relative workspace and recent execution
  results until the task ends. Run scripts/checkers in that workspace. Failed execution
  cannot justify a final answer; bounded checked procedures can submit their output
  directly. Local tests use generated answers, not recorded task solutions.
- Use the same obstacle-aware route and traffic margin for task acceptance, procurement,
  mining cash-out and individual recall. Task duration is still an estimate, not a guarantee.
- Compare selling carried stock with continuing a full collect/sell/return trip. Shorten
  batches when daylight is insufficient. Track successful own collections as a conservative
  mine estimate; competitor depletion remains unknown. Keep all mining in our normalized half.
- Let a courier complete a delivery before a distant returning role reaches that cell.
  Reserve the higher-priority route's next two cells rather than its entire future path;
  next-step collision, occupied-cell and yielding checks remain enforced.
- Use adjacent carried upgrades during recall only while there is time to return. At
  night firing takes priority; idle operators can use carried upgrades without leaving
  their weapon, including healthy weapons that need their first power increase.
- From day two, target three front walls for level two, choosing damaged walls first.
  Preserve the first rocket fund except for critical repairs; remaining level-one guns
  remain valuable. This is a funded procurement target, not a fixed-time free upgrade.
  Upgrade healing remains subject to platform evidence and runtime health.

## v0.7 Operating Corrections

- Empty lower-priority holds yield even when they occupy a delivery goal. This does
  not borrow actors that are executing tasks, constructing or firing.
- Owned goods can be delivered independently of the new-purchase carrier. Cleared-night
  independent deliveries can proceed together; idle pioneers take new procurement first.
- Idle pioneers can stage by the shop only when no task is currently valid, upcoming
  cooldowns leave room and the actual return trip fits. Active tasks remain reserved.
- Preserve the next basic development fund: the first level-two rocket, a level-two
  base from day two, then remaining level-one weapons. Critical repair remains eligible;
  other maintenance uses surplus. Three front-wall upgrades remain a funded goal.
- Retain recent attempted programs alongside documents/results, expose workspace-relative
  filenames, support direct Python source and workspace-relative repair paths. Explicitly
  final, successful JSON computation can be submitted directly. It is execution evidence,
  not proof of correctness. Ordinary script/inspection output still requires synthesis.
- Command count is bounded at eight. A live runtime task phase permits completion at
  the estimated deadline; an inactive phase clears evidence. Submission count remains three.

## v0.8 Task and Funding Candidate

Generic computed JSON requires a field/type contract and independently executed
assertions before fast submission. Provided repair checkers and bounded complete-page
API procedures retain direct-result transport. An unverified but structurally valid
computed candidate may be submitted once at the deadline for possible partial credit.
Task assertions and contracts can still be wrong; judge acceptance is authoritative.

After basic level-two development, protect funds for key front walls, the first
level-three rocket from day three, key level-three front walls from day four, then
the other rocket. Critical maintenance takes precedence. Use actual shop prices;
sell personal stock that closes a funding gap and do not speculate while underfunded.
These timing targets remain configurable hypotheses requiring multi-match calibration.

## v0.9 task and operating acceptance

The current behavior and its limitations are described in `operating-logic.md`.
Task validation must measure full success by category, unsubmitted tasks, later-task
exploration and actual reward arrival. Shared rocket control, smaller recall margins
and delayed voucher use require multi-match tests on both sides. Synthetic checks
prove only the exercised action/transport/state invariants, not score or win rate.
