#!/usr/bin/env python3
"""Decode bounded AGLOG2 records from a .log or user-compressed .log.xz file."""

from __future__ import annotations

import argparse
import json
import lzma
import sys
from collections import Counter
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from solution.telemetry import PREFIX, decode_event  # noqa: E402


def iter_lines(path: Path, max_bytes: int):
    opener = lzma.open if path.suffix.lower() == ".xz" else open
    total = 0
    with opener(path, mode="rt", encoding="utf-8", errors="replace") as source:
        for line in source:
            total += len(line.encode("utf-8", errors="replace"))
            if total > max_bytes:
                break
            yield line


def summarize_events(events):
    """Bounded, identifier-free incident summary; compatible with v0.2 records."""
    actions, failures, errors = Counter(), Counter(), Counter()
    previous = {}
    previous_round = None
    first_three = None
    first_wall = None
    first_night = None
    builds = []
    last = {}
    boundaries, weapon_activity, commerce, task_reasons = [], Counter(), Counter(), Counter()
    command_categories, rejection_reasons, economy_activity = Counter(), Counter(), Counter()
    for e in events:
        if e.get("event") != "turn":
            continue
        r = e.get("r")
        counts = Counter(u[1] for u in e.get("roles", []))
        weapons = e.get("readiness",{}).get("weapons",sum(counts[k] for k in ("rocket","railgun","gatling")))
        walls = e.get("readiness",{}).get("walls",counts["wall"])
        if weapons == 3 and first_three is None:
            first_three = r
        if walls and first_wall is None:
            first_wall = r
        if e.get("phase") == "night" and first_night is None:
            first_night = {"round":r,"weapons":weapons,"walls":walls,"base":e.get("station")}
        if isinstance(r,int) and (r-1)%130+1 in (70,71) and len(boundaries)<20:
            boundaries.append({"round":r,"base":e.get("station"),"walls":walls,"gold":e.get("gold"),
                               "units":[[u[1],u[2],u[3],u[4],u[7]] for u in e.get("roles",[]) if len(u)>=8 and u[1]!='wall']})
        diagnostics=e.get("diagnostics",{})
        command_categories.update([diagnostics["taskCommandCategory"]] if diagnostics.get("taskCommandCategory") not in (None,"none") else [])
        rejection_reasons.update([diagnostics["taskRejectReason"]] if diagnostics.get("taskRejectReason") not in (None,"none") else [])
        economy_activity.update(diagnostics.get("economy",{}).values())
        task_reasons.update([diagnostics["taskReason"]] if diagnostics.get("taskReason") else [])
        for item in diagnostics.get("weapons",[]):
            if isinstance(item,list) and len(item)==3:
                weapon_activity[str(item[0])+":"+str(item[1])+":"+str(item[2])] += 1
        if previous_round is None or r != previous_round+1:
            previous = {}  # Never pair feedback across missing telemetry turns.
        for actor, ok in e.get("results", {}).items():
            cmd = previous.get(str(actor))
            if cmd is None:
                continue
            if not ok:
                failures[cmd[1]+":"+cmd[2]] += 1
            if cmd[1] == "build" and len(builds) < 32:
                builds.append({"resultRound":r,"name":cmd[2],"target":cmd[4],"ok":ok})
        commands = e.get("commands", [])
        for cmd in commands:
            actions[cmd[1]] += 1
            if cmd[1] in ("sell","buy","use"):
                commerce[cmd[1]+":"+cmd[2]] += max(cmd[3],1)
        errors.update(str(code) for code in e.get("errors", []))
        previous = {str(cmd[0]):cmd for cmd in commands}
        previous_round = r
        last = {"round":r,"score":e.get("score"),"gold":e.get("gold"),"base":e.get("station"),
                "weapons":weapons,"walls":walls}
    return {"firstThreeWeaponsRound":first_three,"firstWallRound":first_wall,
            "firstNight":first_night,"last":last,"actions":dict(actions),
            "failedActions":dict(failures),"errorCodes":dict(errors),"buildResults":builds,
            "dayNightBoundaries":boundaries,"weaponActivity":dict(weapon_activity),
            "requestedCommerceQuantities":dict(commerce),"taskReasons":dict(task_reasons),
            "taskCommandCategoryTurns":dict(command_categories),"taskRejectReasonTurns":dict(rejection_reasons),
            "economyActivityTurns":dict(economy_activity),"taskOutcomes":task_outcomes(events)}


def task_outcomes(events):
    """Report end-of-task credits, including timeout settlement, without answers.

    Concurrent economic actions or missing turns prevent reward attribution.
    Score changes may include combat; only matching gold/score gains indicate a
    partial settlement. This is observational accounting, not judge feedback.
    """
    previous=None; start=None; submissions=0; result=[]
    for event in events:
        if event.get('event')!='turn': continue
        if previous and event.get('r')==previous.get('r',-2)+1:
            now=event.get('diagnostics',{}); old=previous.get('diagnostics',{})
            full=now.get('taskCompleted',0)-old.get('taskCompleted',0)
            failed=now.get('taskFailed',0)-old.get('taskFailed',0)
            if full+failed>0:
                gold=event.get('gold',0)-previous.get('gold',0)
                score=event.get('score',0)-previous.get('score',0)
                mixed=any(c[1] in ('sell','buy','summonTreasure') or
                          (c[1]=='build' and c[2]!='wall') for c in previous.get('commands',[]))
                outcome='full' if full>0 else 'unresolved'
                if not full and not mixed:
                    if gold>0 and score==gold: outcome='partial_observed'
                    elif gold==0 and score==0: outcome='zero_observed'
                if len(result)<64:
                    result.append({'start':start,'end':event['r'],'outcome':outcome,
                        'submissions':submissions,'goldDelta':gold,'scoreDelta':score,'mixedIncome':mixed})
                start=None;submissions=0
        elif previous:
            start=None;submissions=0
        for command in event.get('commands',[]):
            if command[1]=='acceptTask':start=event.get('r');submissions=0
            elif command[1]=='submitAnswer':submissions+=1
        previous=event
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("log", type=Path)
    parser.add_argument("--limit", type=int, default=2000)
    parser.add_argument("--max-bytes", type=int, default=16 * 1024 * 1024)
    parser.add_argument("--summary", action="store_true", help="print only a bounded identifier-free diagnostic summary")
    args = parser.parse_args()
    if not args.log.is_file():
        raise SystemExit(f"log not found: {args.log}")
    limit = min(max(args.limit, 1), 10000)
    max_bytes = min(max(args.max_bytes, 1024), 64 * 1024 * 1024)
    decoded = 0
    failed = 0
    events = []
    for line in iter_lines(args.log, max_bytes):
        try:
            if PREFIX in line:
                event = decode_event(line)
            elif line.lstrip().startswith("{"):
                event = json.loads(line)
                if not isinstance(event,dict) or event.get("event") not in {"turn","checkpoint"}:
                    continue
            else:
                continue
        except ValueError:
            failed += 1
            continue
        if args.summary:
            events.append(event)
        else:
            print(json.dumps(event, ensure_ascii=False, sort_keys=True))
        decoded += 1
        if decoded >= limit:
            break
    if args.summary:
        print(json.dumps(summarize_events(events), ensure_ascii=False, sort_keys=True))
    print(json.dumps({"summary": {"decoded": decoded, "failed": failed}}), file=sys.stderr)


if __name__ == "__main__":
    main()
