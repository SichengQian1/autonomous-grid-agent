# Baseline strategy

This is a functional competition-protocol baseline, with local synthetic evidence.
It has not been evaluated for match win rate on the official platform.

## Scheduling

1. Validate the map and living base; maintain cross-turn feedback.
2. Use carried medicine when health is low, or a matching carried station upgrade
   when the base is critically damaged and a role is adjacent.
3. Jointly pair living humans and weapon subsets, preferring validated effective
   fire at night, then readiness and reachable return cost.
4. During the day, reserve return time plus a margin before accepting more work.
5. Construct the configured three weapons first; add walls with an exit and firing
   lanes. Mine stone for construction, then choose available ore by current
   price/travel cost, excluding news-announced closure windows.
6. Sell batches, buy affordable supplies and deliver compatible upgrade vouchers.
7. Send the pioneer to valuable reachable tasks, preserving time for solving and return.
8. At night, allocate joint fire using threat, effective damage, kills and overkill.

## Night supply runs

No role leaves because the robot count alone is low. After the initial spawn turn,
release is allowed when no relevant robots remain, or the still-staffed weapons
can eliminate every relevant robot in the current turn using conservative damage.
Each additional release is tested together with previously released roles.
Rejected actions contribute no damage. After attacks are added to the response,
the release condition is checked again using only those accepted commands.

Missing observations, unknown robot positions, immediate base threats, cooling
weapons and insufficient damage prevent release. Supplies stay near the base and
routes avoid robot attack/movement envelopes. A new threat triggers reevaluation
and return. Robots belonging to the opponent still contribute to route danger.
The default trip radius is eight cells and the small-wave ceiling is three robots.

## Mining availability

Official news updates a per-mineral calendar before economic planning. Common
Chinese and English closure/reopening expressions are handled locally. Relative
days are anchored to the first observed publication round, so repeated news does
not slide a closure forward. Price increases alone never imply availability.
An unknown closure end remains closed until an explicit reopening or a validated
structured interpretation supplies its bound. Structured news replies share the
daily LLM quota and require source evidence, known resources, bounded rounds and
high confidence. Arbitrary natural-language interpretation still needs live checks.

## Combat

- Gatling bullets hit the first robot along each ray; all directions must fit a
  90-degree cone. Repeated targets fill upgraded volleys when useful.
- Railgun energy is consumed by current robot health along the ray. Concurrent
  planned hits do not incorrectly make nearer robots transparent.
- Rockets score centre and adjacent splash damage, including overlapping impacts.
- Earlier planned damage reduces the value of redundant later attacks.
- Controllers must be alive and adjacent; a controller cannot also act as a human.

Ray-square boundary contacts and building blocking are conservative assumptions.
The default treats buildings as projectile blockers and preserves forward lanes.
`projectile_building_blocking` allows comparison after platform verification.
Runtime positive range and power are required; the baseline does not invent a
range for an unrecognized full-map sentinel or guess an absent weapon power.

## Tasks and treasure

Task acceptance checks travel, task availability, timeout and return reserve.
The pioneer stays at the task while solving and leaves when defense requires it.
LLM replies must echo a request identifier and provide structured content with
sufficient confidence. Late, malformed, low-confidence and repeated answers are
ignored. Requests and diagnostics are bounded; task failure does not block combat.

The sandbox path permits validated Python diagnostics with standard-library
imports and bounded local file reads. Child execution has a ten-second wall limit,
CPU/memory/file-size limits and capped output, inside the platform's task sandbox.
It does not execute model-provided shell commands. AST filtering reduces accidental
unsafe operations; the actual security boundary is the platform sandbox. Sandbox
resource-limit support still needs confirmation on the target machine.

Task solutions are retained as explicitly unverified hints for later tasks.
Historical legends can produce a treasure candidate only with coordinates, an
exact item multiset, opening/closing rounds and quoted source evidence. Inventory,
shop prices and travel are checked before preparation. Nighttime summoning is
allowed within the clue's time window only after the pioneer passes the same
safety gate as a supply run. Replies across dusk are consumed before planning.
A probe is never blindly repeated after feedback. Successful or already-empty
treasure feedback ends treasure search for the match, including pending replies
and later legends; a new match resets that state. Interpretation accuracy and
profitability need live tests.

## Configuration and diagnostics

`AGENT_CONFIG=config/baseline.json` uses two railguns and one rocket.
`AGENT_CONFIG=config/balanced.json` selects the comparison composition.
All tunable defaults live in `solution/rules.py`; JSON overrides are type checked.
A false `enabled` switch restores the safe empty strategy.

`tools/diagnostics/replay.py` accepts a local JSONL file containing one turn request
per line. It reads at most 100 records by default, eight MiB per record and 64 MiB
overall. Output is a bounded summary of action counts, errors, timing and a content
checksum. It writes nothing and never executes sandbox commands or calls a service.

## Verification limits

The synthetic transition harness models movement, construction, trading and
upgrades. It is not a judge, combat simulator or win-rate benchmark. Combat has
separate deterministic unit scenarios. Official payload compatibility, real task
success, target-machine timing and match strength require further evidence.
