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
    first_three = None
    first_wall = None
    first_night = None
    builds = []
    last = {}
    for e in events:
        if e.get("event") != "turn":
            continue
        r = e.get("r")
        counts = Counter(u[1] for u in e.get("roles", []))
        weapons = sum(counts[k] for k in ("rocket","railgun","gatling"))
        if weapons == 3 and first_three is None:
            first_three = r
        if counts["wall"] and first_wall is None:
            first_wall = r
        if e.get("phase") == "night" and first_night is None:
            first_night = {"round":r,"weapons":weapons,"walls":counts["wall"],"base":e.get("station")}
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
        errors.update(str(code) for code in e.get("errors", []))
        previous = {str(cmd[0]):cmd for cmd in commands}
        last = {"round":r,"score":e.get("score"),"gold":e.get("gold"),"base":e.get("station"),
                "weapons":weapons,"walls":counts["wall"]}
    return {"firstThreeWeaponsRound":first_three,"firstWallRound":first_wall,
            "firstNight":first_night,"last":last,"actions":dict(actions),
            "failedActions":dict(failures),"errorCodes":dict(errors),"buildResults":builds}


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
        if PREFIX not in line:
            continue
        try:
            event = decode_event(line)
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
