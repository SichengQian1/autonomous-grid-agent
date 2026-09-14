#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.request


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Send one synthetic request to a running local agent.",
    )
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", required=True, type=int)
    parser.add_argument("--timeout", default=2.0, type=float)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    request_body = json.dumps({"roundNo": 1}).encode("utf-8")
    request = urllib.request.Request(
        f"http://{args.host}:{args.port}/",
        data=request_body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    try:
        with opener.open(request, timeout=args.timeout) as response:
            raw_body = response.read(64 * 1024)
    except (OSError, urllib.error.URLError) as error:
        print(f"smoke request failed: {error}", file=sys.stderr)
        return 1

    try:
        payload = json.loads(raw_body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        print(f"response is not valid JSON: {error}", file=sys.stderr)
        return 1

    if not isinstance(payload, dict) or not isinstance(
        payload.get("roleCommandMap"), dict
    ):
        print("response does not contain a roleCommandMap object", file=sys.stderr)
        return 1

    print(json.dumps(payload, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
