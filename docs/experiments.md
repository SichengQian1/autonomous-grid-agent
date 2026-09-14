# Experiments

Record repeatable evidence here. Do not include confidential logs, real internal identifiers, internal URLs, or unsanitized source material.

## Experiment Template

### Question

What exact hypothesis is being tested?

### Variants

- Control:
- Candidate:

### Environment

- Code revision:
- Sanitized map label:
- Side:
- Number of matches:

### Metrics

- wins / draws / losses:
- average score:
- base survival:
- base health remaining:
- task completion:
- combat score:
- invalid actions:
- response failures:
- decision latency:

### Result

- Observations:
- Confounders:
- Conclusion:
- Confidence:
- Follow-up:
- Promote to default strategy: yes / no

## Experiment Queue

1. Two railguns plus one rocket versus the balanced three-weapon composition.
2. Projectile interaction with friendly walls.
3. Kill ownership for robots targeting the opponent.
4. Dynamic gate versus permanent opening.
5. Early weapon upgrade versus early base upgrade.
6. Summon-order threshold behavior.

## Baseline local verification - 2026-09-14

- Interpreter: Python 3.11.15 on the local development machine.
- Two original synthetic economy scenarios, 260 transitions per side.
- Both completed the configured three weapons by round four and subsequently
  gathered, sold, bought and upgraded without negative gold or occupied moves.
- First-night integration produced three attacks with distinct living controllers.
- 130 independent synthetic snapshots passed the bounded replay diagnostic with
  zero validation issues and zero decision failures.
- Combat unit cases cover penetration, first-hit rays, splash, cooldown, upgraded
  target counts, overkill and conservative night release decisions.
- A randomized 100-turn probe observed approximately 12.5 ms maximum local latency;
  a separate 200-robot snapshot took approximately 14.3 ms.
- These are functional/latency checks. No win-rate or official base-survival claim
  is supported by them, and no configuration is promoted as competitively optimal.

## Added platform checks

- Confirm weapon `attackPower` is per projectile for gatling and rocket volleys.
- Confirm ray-square edge contacts, building occlusion and full-map range encoding.
- Compare nighttime supply runs enabled/disabled at matched maps and sides.
- Verify sandbox resource limits and task/treasure extraction on actual contracts.
