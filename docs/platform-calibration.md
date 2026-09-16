# V1 Platform Calibration

V1 code completion and platform calibration are separate milestones. Local tests and
the synthetic replay verify our own algorithms and protocol shape only. They do not
prove game-engine behavior, match strength, or win rate.

## Evidence Labels

- `USER_OBSERVED`: reported from a practice replay or bounded log summary.
- `CONFIRMED_RUNTIME`: repeatedly present in actual requests/results.
- `UNVERIFIED_PLATFORM_BEHAVIOR`: not yet supported by runtime evidence.

## First Practice Runs

Use low-stakes simulation matches. Retain the exact code revision and archive hash.
For each half, record only a sanitized label and side; do not copy team IDs, names,
private URLs, full prompts, or complete logs into Git.

Prioritize these observations:

1. base side and robot spawn positions;
2. robot positions for the first five turns of each night;
3. robot type/count per night and first natural Boss day;
4. own/enemy clear turn;
5. minimum base, wall, and weapon health;
6. attempted build position and success/failure;
7. night collect/sell/buy result;
8. robot health before/after each weapon type attacks;
9. rocket cooldown transitions;
10. presence/absence of `targetTeam`;
11. Boss-order buy/use/effective-night observations and stacking;
12. action results, error codes, and task/LLM/sandbox/treasure result codes.

## Windows Read-only Summary

If the platform exports JSON or JSONL turn logs, run from the repository root in
PowerShell:

```powershell
python .\tools\diagnostics\summarize_match_log.py "D:\path\to\match-log.jsonl"
```

For an agent `.log`, decoded `.jsonl`, or either format compressed with `.xz`, print a bounded diagnosis:

```powershell
python .\tools\diagnostics\decode_match_log.py "D:\path\to\match.log.xz" --summary
```

Paste only the bounded JSON summary. The tools read bounded records and omit team
identifiers, names, prompts, answers, command output, and full error descriptions.
The generic summarizer reads at most 16 MiB and 2,000 records
by default and omits team IDs, team names, prompts, raw error descriptions, and full
logs. If the export format is not recognized, share only a screenshot of the log
format or a few manually redacted structural lines so the parser can be adapted.

## Current Unverified Boundary

The returned v0.3 run confirms that the legal-ring repair enabled three weapons
and ten walls by the first night. It also exposes blocked controller access on the
third night, no successful task income, single-item sales, no upgrades, and base
loss in that night. Successful construction is not evidence of competitive strength.
Side/rear robots were observed, so a one-direction-only threat assumption is invalid.
The two fixed rear gates remain an experiment requiring route and exposure checks.

Two returned v0.4 runs confirm three rear weapons and third-night staffing, but
only 4/8 first-night walls, zero completed task income, and no weapon/base upgrades.
Their final supplied records show scores 107/112 and base health 30/45; the base
is still present, so these are not confirmed final scores or destruction turns.
Visible local ore was ignored in favor of remote copper. Global recall froze
nearby work, and cross-day carrier ownership stranded purchased repairs.

The v0.5 candidate addresses these scheduling and funding failures, and permits
local cd/multiline task solvers with bounded execution. The private v0.4 telemetry
does not contain command text, so individual task failures cannot all be attributed
to command filtering. New telemetry emits categories without command contents.
Its task-income integration supplies prescribed synthetic LLM replies: it tests
cash-to-upgrade scheduling, not real solving ability. Its combat harness is not an
engine model and cannot establish survival or score.

For the next platform run, retain artifact hash and collect bounded evidence for:

1. third weapon completion, each controller's position and wall count at turns 70/71;
2. task accepts, checked-command/result/submission sequence, success, errors and elapsed turns;
3. first rocket upgrade and second-day weapon/base levels;
4. local mine selection, mine depletion/respawn, per-role recall, sale batches,
   actual gold changes, purchase-to-use delays and stranded items;
5. third-night unstaffed weapons, cooldown recovery and side/rear intrusions;
6. per-night base/critical-wall health, repair/upgrade uses and replacement construction;
7. live prices versus news-derived windows and treasure result codes without raw clues/answers.

Real robot routing, settlement, rear-gate safety, projectile interactions,
night activity, LLM/task judging, treasure interpretation, and score/win rate
remain unverified for v0.5. Run both map sides and more than one match before
promoting the candidate to a stronger-strategy claim. Exact Python 3.11.10 runtime
verification is also required.

## v0.6 Returned Evidence and v0.7 Boundary

Four v0.6 telemetry sequences contain 633/485/489/481 turns. Their last recorded
scores are 505/282/393/265, with bases still present; these are not confirmed final
match scores. Each run upgrades one rocket before the first night, and successful
task completions are 2/1/2/1 from six accepts per run. No local validation drops or
planner fallbacks were recorded. Task timeout/wrong-answer codes are separate from
competition-level response exceptions.

The mirrored opening has a legitimate one-turn builder wait when the pioneer
occupies the intended building cell. More damaging is a delivery goal occupied by
an idle role: one base voucher is bought at turn 290 and used at 432. A frozen local
scene from that interval reproduces the courier blockage. v0.7 yields the idle role;
with other scene elements frozen, the courier reaches use after 16 movement turns.
This is a diagnostic counterfactual, not an official replay or new match outcome.

The new release also changes upgrade saving and task execution/submission handling.
Typed Python, workspace-relative repair and final-JSON transport are tested locally;
real LLM accuracy, next-wave survival and any score increase remain unverified.
