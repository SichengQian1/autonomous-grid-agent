from __future__ import annotations

import json
import logging
import socket
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

if sys.version_info < (3, 11):
    raise SystemExit("Python 3.11 or newer is required")

from .engine import decide_payload
from .protocol import safe_response


LOGGER = logging.getLogger(__name__)
MAX_REQUEST_BYTES = 8 * 1024 * 1024
SOCKET_READ_TIMEOUT_SECONDS = 4.5


def decide(payload: dict[str, Any]) -> dict[str, Any]:
    return decide_payload(payload)


class RequestHandler(BaseHTTPRequestHandler):
    def do_POST(self) -> None:
        response = safe_response()
        try:
            self.connection.settimeout(SOCKET_READ_TIMEOUT_SECONDS)
            content_length = int(self.headers.get("Content-Length", "0"))
            if content_length < 0 or content_length > MAX_REQUEST_BYTES:
                raise ValueError("request body size is invalid")
            raw_body = self.rfile.read(content_length)
            payload = json.loads(raw_body.decode("utf-8"))
            if not isinstance(payload, dict):
                raise TypeError("request body must be a JSON object")
            candidate = decide(payload)
            if (
                isinstance(candidate, dict)
                and isinstance(candidate.get("roleCommandMap"), dict)
            ):
                response = candidate
        except (BrokenPipeError, ConnectionResetError, socket.timeout):
            LOGGER.warning("request connection ended before a response was sent")
        except (TypeError, ValueError, UnicodeDecodeError) as error:
            LOGGER.warning("rejected request: %s", type(error).__name__)
        except Exception:
            LOGGER.exception("request processing failed")

        self._write_json(response)

    def _write_json(self, response: dict[str, Any]) -> None:
        try:
            body = json.dumps(
                response,
                ensure_ascii=False,
                separators=(",", ":"),
            ).encode("utf-8")
        except Exception:
            body = b'{"roleCommandMap":{}}'
        try:
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError, socket.timeout):
            LOGGER.warning("response connection closed")
        except Exception:
            LOGGER.exception("response write failed")

    def log_message(self, format: str, *args: Any) -> None:
        del format, args


class AgentServer(ThreadingHTTPServer):
    allow_reuse_address = True
    daemon_threads = True


def parse_port(arguments: list[str]) -> int:
    if len(arguments) != 2:
        raise SystemExit("usage: main.py <port>")
    port = int(arguments[1])
    if not 1 <= port <= 65535:
        raise SystemExit("port must be between 1 and 65535")
    return port


def serve(port: int) -> None:
    LOGGER.info("agent v0.12 listening on port %d; detailed records use AGLOG3", port)
    with AgentServer(("0.0.0.0", port), RequestHandler) as server:
        server.serve_forever()


def main() -> None:
    logging.basicConfig(
        stream=sys.stderr,
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )
    try:
        serve(parse_port(sys.argv))
    except KeyboardInterrupt:
        LOGGER.info("server stopped")


if __name__ == "__main__":
    main()
