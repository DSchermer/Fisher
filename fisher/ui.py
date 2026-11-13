"""A small local web UI for the lookups and sizing tools.

    python -m fisher.ui            # then open http://127.0.0.1:8000
    python -m fisher.ui --port 9000

Standard library only. The page sends each form to /api/<command>, which runs the same code
as the command-line interface (fisher/__main__.py), so the UI and CLI always agree.
"""
from __future__ import annotations

import argparse
import contextlib
import io
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qsl, urlparse

from .__main__ import run

PAGE = Path(__file__).with_name("ui.html")
POSITIONAL = {"show", "size-valve"}  # commands whose first argument is a config id


def to_argv(command: str, params: dict[str, str]) -> list[str]:
    argv = [command]
    if command in POSITIONAL:
        argv.append(params.pop("config_id", ""))
    for key, value in params.items():
        if value == "":
            continue
        flag = "--" + key.replace("_", "-")
        if value in ("on", "true"):
            argv.append(flag)
        else:
            argv += [flag, value]
    return argv


def call(command: str, params: dict[str, str]) -> tuple[int, object]:
    err = io.StringIO()
    try:
        with contextlib.redirect_stderr(err):
            return 200, run(to_argv(command, params))
    except SystemExit:  # argparse rejected the input
        msg = err.getvalue().strip().splitlines()
        return 400, {"error": msg[-1] if msg else "invalid input"}
    except KeyError as e:
        return 400, {"error": f"not found: {e.args[0] if e.args else ''}"}
    except (ValueError, IndexError) as e:
        return 400, {"error": str(e)}


class Handler(BaseHTTPRequestHandler):
    def _send(self, status: int, body: bytes, ctype: str) -> None:
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:  # noqa: N802
        url = urlparse(self.path)
        if url.path in ("/", "/index.html"):
            self._send(200, PAGE.read_bytes(), "text/html; charset=utf-8")
        elif url.path.startswith("/api/"):
            status, out = call(url.path[len("/api/"):], dict(parse_qsl(url.query, keep_blank_values=True)))
            self._send(status, json.dumps(out, default=str).encode(), "application/json")
        else:
            self._send(404, b"not found", "text/plain")

    def log_message(self, fmt, *args) -> None:  # keep the console quiet
        pass


def main() -> None:
    ap = argparse.ArgumentParser(description="Local web UI for the Fisher Catalog 12 tools")
    ap.add_argument("--port", type=int, default=8000)
    ap.add_argument("--host", default="127.0.0.1")
    a = ap.parse_args()
    server = ThreadingHTTPServer((a.host, a.port), Handler)
    print(f"Fisher Catalog 12 tools: http://{a.host}:{server.server_address[1]}  (Ctrl+C to stop)")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
