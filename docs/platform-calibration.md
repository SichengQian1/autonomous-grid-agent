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

Paste only the bounded JSON summary. The tool reads at most 16 MiB and 2,000 records
by default and omits team IDs, team names, prompts, raw error descriptions, and full
logs. If the export format is not recognized, share only a screenshot of the log
format or a few manually redacted structural lines so the parser can be adapted.

## Current Unverified Boundary

The following remain `UNVERIFIED_PLATFORM_BEHAVIOR`: exact build cells; real robot
routing and settlement order; rear-exit safety; weapon/wall projectile interaction;
rocket overlap; night economy; exact wave/Boss schedule; cross-map kill ownership;
summon timing/stacking; task, LLM, sandbox, and treasure judging; and whether current
defense margins/loadouts improve real match results.
