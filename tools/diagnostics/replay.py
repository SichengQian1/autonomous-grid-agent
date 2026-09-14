#!/usr/bin/env python3
"""Read bounded JSONL turn requests and print aggregate, sanitized diagnostics.

No HTTP requests, task command execution, file writes, or raw payload output.
"""
from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
import logging
from pathlib import Path
import sys
import time

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from solution.configuration import load_config
from solution.engine import AgentEngine
from solution.models import Turn
from solution.actions import Decision
from solution.validation import ActionValidator


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path, help="local JSONL file, one request object per line")
    parser.add_argument("--limit", type=int, default=100, help="maximum records, capped at 1300")
    parser.add_argument("--config", help="optional local strategy JSON file")
    args = parser.parse_args()
    if not 1 <= args.limit <= 1300:
        parser.error("limit must be between 1 and 1300")
    logging.disable(logging.CRITICAL)
    counts, error_codes = Counter(), Counter()
    latencies, rounds = [], []
    digest = hashlib.sha256()
    invalid = failed = 0
    bytes_read = 0
    try:
        engine = AgentEngine(load_config(args.config))
        with args.input.open("rb") as stream:
            for _ in range(args.limit):
                line = stream.readline(8 * 1024 * 1024 + 1)
                if not line:
                    break
                if len(line) > 8 * 1024 * 1024:
                    raise ValueError("record too large")
                bytes_read += len(line)
                if bytes_read > 64 * 1024 * 1024:
                    break
                digest.update(line)
                raw = json.loads(line)
                if not isinstance(raw, dict):
                    raise ValueError("record must be an object")
                started = time.monotonic()
                try:
                    response = engine.decide(raw)
                    json.dumps(response)
                except Exception:
                    failed += 1
                    continue
                latencies.append((time.monotonic() - started) * 1000)
                turn = Turn.from_raw(raw)
                rounds.append(turn.round_no)
                actions = tuple(a for a in engine.state.previous_actions if str(a.actor_id) in response["roleCommandMap"])
                invalid += len(ActionValidator().validate(turn, Decision(actions)).issues)
                counts.update(a["action"] for a in response["roleCommandMap"].values())
                counts["llm_requests"] += bool(response.get("prompt"))
                counts["sandbox_requests"] += bool(response.get("executeCmd"))
                error_codes.update(e.error_code for e in turn.errors)
    except (OSError, ValueError, TypeError):
        print("Input/config could not be read as bounded JSON. No source content was printed.", file=sys.stderr)
        return 2
    ordered = sorted(latencies)
    report = {"python": sys.version.split()[0], "records": len(rounds), "processed_sha256": digest.hexdigest(),
              "round_min": min(rounds, default=0), "round_max": max(rounds, default=0),
              "actions": dict(counts), "input_error_codes": dict(error_codes),
              "validation_issues": invalid, "decision_failures": failed,
              "latency_ms": {"max": round(max(ordered, default=0), 3),
                             "p95": round(ordered[min(len(ordered)-1, int(len(ordered)*.95))], 3) if ordered else 0}}
    print(json.dumps(report, sort_keys=True))
    return 1 if invalid or failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
