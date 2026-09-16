#!/usr/bin/env python3
"""Decrypt an encrypted turn log to stdout. Read-only, bounded, no network.

The key comes from --key, the AGENT_TURN_LOG_KEY environment variable, or a
terminal prompt. Plaintext JSONL envelopes go to stdout; with --requests only
the original request objects are printed, matching the classic replay input.
"""
from __future__ import annotations

import argparse
import getpass
import json
import os
from pathlib import Path
import sys

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from solution.turncrypto import TurnLogCipher
from solution.turnlog import ENV_TURN_LOG_KEY

MAX_LINE_BYTES = 16 * 1024 * 1024
MAX_TOTAL_BYTES = 512 * 1024 * 1024


def _passphrase(provided: str | None) -> str:
    if provided:
        return provided
    from_env = os.environ.get(ENV_TURN_LOG_KEY, "").strip()
    if from_env:
        return from_env
    if sys.stdin.isatty():
        return getpass.getpass("Turn log passphrase: ")
    raise ValueError("no passphrase; set AGENT_TURN_LOG_KEY or pass --key")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path, help="encrypted turn log file")
    parser.add_argument("--key", help="log passphrase; prefer the environment variable on shared machines")
    parser.add_argument("--requests", action="store_true", help="print only the decrypted request objects")
    parser.add_argument("--limit", type=int, default=20000, help="maximum records, capped at 200000")
    args = parser.parse_args()
    if not 1 <= args.limit <= 200000:
        parser.error("limit must be between 1 and 200000")

    decrypted = skipped = failed = 0
    bytes_read = 0
    try:
        passphrase = _passphrase(args.key)
        cipher: TurnLogCipher | None = None
        with args.input.open("rb") as stream:
            while decrypted < args.limit:
                line = stream.readline(MAX_LINE_BYTES + 1)
                if not line:
                    break
                if len(line) > MAX_LINE_BYTES:
                    raise ValueError("record too large")
                bytes_read += len(line)
                if bytes_read > MAX_TOTAL_BYTES:
                    break
                record = json.loads(line)
                if not isinstance(record, dict):
                    skipped += 1
                    continue
                if cipher is None:
                    cipher = TurnLogCipher.from_header(passphrase, record)
                    continue
                if "ct" not in record:
                    skipped += 1
                    continue
                try:
                    plain = json.loads(cipher.decrypt(record))
                except (ValueError, TypeError):
                    failed += 1
                    continue
                decrypted += 1
                if args.requests and isinstance(plain, dict):
                    plain = plain.get("request", plain)
                print(json.dumps(plain, ensure_ascii=False, separators=(",", ":")), flush=True)
        if cipher is None:
            raise ValueError("input has no encrypted turn log header")
    except (OSError, ValueError, TypeError) as error:
        print(f"decryption failed: {type(error).__name__}: {error}", file=sys.stderr)
        return 2
    summary = {"decrypted": decrypted, "skipped": skipped, "failed": failed}
    print(json.dumps(summary, sort_keys=True), file=sys.stderr)
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
