#!/usr/bin/env python3
"""Decode bounded AGLOG2 records from a .log or user-compressed .log.xz file."""

from __future__ import annotations

import argparse
import json
import lzma
import sys
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


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("log", type=Path)
    parser.add_argument("--limit", type=int, default=2000)
    parser.add_argument("--max-bytes", type=int, default=16 * 1024 * 1024)
    args = parser.parse_args()
    if not args.log.is_file():
        raise SystemExit(f"log not found: {args.log}")
    limit = min(max(args.limit, 1), 10000)
    max_bytes = min(max(args.max_bytes, 1024), 64 * 1024 * 1024)
    decoded = 0
    failed = 0
    for line in iter_lines(args.log, max_bytes):
        if PREFIX not in line:
            continue
        try:
            event = decode_event(line)
        except ValueError:
            failed += 1
            continue
        print(json.dumps(event, ensure_ascii=False, sort_keys=True))
        decoded += 1
        if decoded >= limit:
            break
    print(json.dumps({"summary": {"decoded": decoded, "failed": failed}}), file=sys.stderr)


if __name__ == "__main__":
    main()
