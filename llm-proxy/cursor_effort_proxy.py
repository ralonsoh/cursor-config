#!/usr/bin/env python3
"""Effort-injection proxy for Cursor's custom OpenAI-compatible endpoint.

Cursor decides reasoning-effort support by hardcoded model-ID pattern matching
in `cursor-local-agent-runtime`. Model IDs that match nothing get no effort
parameter and no picker control.

This proxy sits between Cursor and the real gateway and injects the effort
parameter into the request body, so effort becomes a proxy-side decision.

Usage:
    ./cursor_effort_proxy.py --config config.toml
    ./cursor_effort_proxy.py --upstream https://host/v1 --effort high

Then point Cursor's `openAIBaseUrl` at http://127.0.0.1:8787/v1
"""

from __future__ import annotations

import argparse
import http.client
import json
import re
import sys
import tomllib
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.parse import urlsplit

# Headers that must not be copied across a proxy hop.
HOP_BY_HOP = {
    "connection",
    "keep-alive",
    "proxy-authenticate",
    "proxy-authorization",
    "te",
    "trailers",
    "transfer-encoding",
    "upgrade",
}


@dataclass
class Rule:
    """One model-ID pattern and the parameter it should carry."""

    match: re.Pattern[str]
    param: str
    value: str
    force: bool = False


@dataclass
class Config:
    listen_host: str = "127.0.0.1"
    listen_port: int = 8787
    # No default on purpose: the gateway URL is deployment-specific and must
    # come from the config file or --upstream, never from committed source.
    upstream: str = ""
    timeout: int = 600
    log: bool = True
    rules: list[Rule] = field(default_factory=list)
    # Credentials are resolved once at startup and never logged. `api_key`
    # holds the literal value read from the config file; the file itself is
    # git-ignored, so the secret is never committed.
    api_key: str = ""
    api_key_header: str = "Authorization"
    api_key_prefix: str = "Bearer"


def resolve_api_key(cfg: Config) -> str:
    """Return the API key to inject, or "" when none is configured."""
    return cfg.api_key.strip()


def _get_path(obj: dict[str, Any], dotted: str) -> Any:
    """Read a possibly dotted key, e.g. 'output_config.effort'."""
    cur: Any = obj
    for part in dotted.split("."):
        if not isinstance(cur, dict) or part not in cur:
            return None
        cur = cur[part]
    return cur


def _set_path(obj: dict[str, Any], dotted: str, value: Any) -> None:
    """Write a possibly dotted key, creating intermediate dicts."""
    parts = dotted.split(".")
    cur = obj
    for part in parts[:-1]:
        nxt = cur.get(part)
        if not isinstance(nxt, dict):
            nxt = {}
            cur[part] = nxt
        cur = nxt
    cur[parts[-1]] = value


def transform(body: bytes, rules: list[Rule]) -> tuple[bytes, str | None]:
    """Return (possibly rewritten body, log note)."""
    if not body:
        return body, None
    try:
        data = json.loads(body)
    except (json.JSONDecodeError, UnicodeDecodeError):
        return body, None
    if not isinstance(data, dict):
        return body, None

    model = data.get("model")
    # Skip when absent or empty: a catch-all rule would otherwise inject into
    # requests that have no model (and `.*` matches the empty string).
    if not isinstance(model, str) or not model:
        return body, None

    for rule in rules:
        if not rule.match.search(model):
            continue
        existing = _get_path(data, rule.param)
        if existing is not None and not rule.force:
            return body, f"{model}: {rule.param} already {existing!r}, left alone"
        _set_path(data, rule.param, rule.value)
        return json.dumps(data).encode(), f"{model}: injected {rule.param}={rule.value}"

    return body, None


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    server_version = "cursor-effort-proxy/1.0"

    cfg: Config  # set by main()
    api_key: str = ""  # resolved at startup; never logged

    # -- logging ---------------------------------------------------------
    def log_message(self, fmt: str, *args: Any) -> None:
        if self.cfg.log:
            sys.stderr.write(f"[proxy] {self.address_string()} {fmt % args}\n")

    def _note(self, msg: str) -> None:
        if self.cfg.log:
            sys.stderr.write(f"[proxy] {msg}\n")

    # -- verbs -----------------------------------------------------------
    def do_GET(self) -> None:
        if self.path.rstrip("/") == "/healthz":
            self._plain(200, b"ok\n")
            return
        self._forward("GET")

    def do_POST(self) -> None:
        self._forward("POST")

    def do_DELETE(self) -> None:
        self._forward("DELETE")

    def do_PUT(self) -> None:
        self._forward("PUT")

    # -- helpers ---------------------------------------------------------
    def _plain(self, status: int, payload: bytes) -> None:
        self.send_response(status)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)
        self.wfile.flush()

    def _read_body(self) -> bytes:
        length = self.headers.get("Content-Length")
        if not length:
            return b""
        try:
            n = int(length)
        except ValueError:
            return b""
        return self.rfile.read(n) if n > 0 else b""

    def _forward(self, method: str) -> None:
        body = self._read_body() if method in ("POST", "PUT", "DELETE") else b""

        if body:
            body, note = transform(body, self.cfg.rules)
            if note:
                self._note(note)

        url = urlsplit(self.cfg.upstream)
        target = url.path.rstrip("/") + self.path

        headers = {
            k: v
            for k, v in self.headers.items()
            if k.lower() not in HOP_BY_HOP
        }
        # Replace any client-supplied credential with the configured one, so
        # Cursor can be pointed at the proxy without holding the real key.
        if self.api_key:
            target_header = self.cfg.api_key_header.lower()
            headers = {
                k: v for k, v in headers.items() if k.lower() != target_header
            }
            headers[self.cfg.api_key_header] = (
                f"{self.cfg.api_key_prefix} {self.api_key}".strip()
                if self.cfg.api_key_prefix
                else self.api_key
            )
        if body:
            headers["Content-Length"] = str(len(body))
        else:
            headers.pop("Content-Length", None)
        headers["Host"] = url.netloc

        if url.scheme == "https":
            conn: http.client.HTTPConnection = http.client.HTTPSConnection(
                url.hostname, url.port, timeout=self.cfg.timeout
            )
        else:
            conn = http.client.HTTPConnection(
                url.hostname, url.port, timeout=self.cfg.timeout
            )

        try:
            conn.request(method, target, body=body or None, headers=headers)
            resp = conn.getresponse()
        except Exception as exc:  # noqa: BLE001 - surface upstream failure to client
            self._note(f"upstream error: {exc}")
            self._plain(502, f"proxy upstream error: {exc}\n".encode())
            conn.close()
            return

        try:
            self.send_response(resp.status)
            for key, val in resp.getheaders():
                low = key.lower()
                if low in HOP_BY_HOP or low == "content-length":
                    continue
                self.send_header(key, val)
            # We re-chunk every response, so streaming SSE stays incremental.
            self.send_header("Transfer-Encoding", "chunked")
            self.end_headers()

            if method != "HEAD" and resp.status not in (204, 304):
                self._stream(resp)
            else:
                self.wfile.write(b"0\r\n\r\n")
                self.wfile.flush()
        finally:
            conn.close()

    def _stream(self, resp: http.client.HTTPResponse) -> None:
        """Copy upstream bytes to the client using chunked encoding."""
        try:
            while True:
                chunk = resp.read1(8192)
                if not chunk:
                    break
                self.wfile.write(b"%x\r\n" % len(chunk))
                self.wfile.write(chunk)
                self.wfile.write(b"\r\n")
                self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError):
            return
        self.wfile.write(b"0\r\n\r\n")
        self.wfile.flush()


def load_config(path: str | None, upstream: str | None, effort: str | None) -> Config:
    cfg = Config()
    if path:
        with open(path, "rb") as fh:
            raw = tomllib.load(fh)
        cfg.listen_host = raw.get("listen_host", cfg.listen_host)
        cfg.listen_port = int(raw.get("listen_port", cfg.listen_port))
        cfg.upstream = raw.get("upstream", cfg.upstream)
        cfg.timeout = int(raw.get("timeout", cfg.timeout))
        cfg.log = bool(raw.get("log", cfg.log))
        cfg.api_key = str(raw.get("api_key", cfg.api_key))
        cfg.api_key_header = str(raw.get("api_key_header", cfg.api_key_header))
        cfg.api_key_prefix = str(raw.get("api_key_prefix", cfg.api_key_prefix))
        for entry in raw.get("rules", []):
            cfg.rules.append(
                Rule(
                    match=re.compile(entry["match"]),
                    param=entry.get("param", "reasoning_effort"),
                    value=str(entry["value"]),
                    force=bool(entry.get("force", False)),
                )
            )

    if upstream:
        cfg.upstream = upstream
    if effort:
        # Catch-all rule: apply to every model.
        cfg.rules = [Rule(match=re.compile(r".*"), param="reasoning_effort", value=effort)]

    return cfg


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", help="path to a TOML config file")
    parser.add_argument("--upstream", help="override upstream base URL")
    parser.add_argument("--effort", help="apply this effort to every model")
    parser.add_argument("--host", help="override listen host")
    parser.add_argument("--port", type=int, help="override listen port")
    parser.add_argument(
        "--api-key",
        help="upstream API key; overrides the value in the config file",
    )
    parser.add_argument("-q", "--quiet", action="store_true", help="no per-request logs")
    args = parser.parse_args(argv)

    if not args.config and not args.effort:
        parser.error("pass either --config or --effort")

    cfg = load_config(args.config, args.upstream, args.effort)
    if args.host:
        cfg.listen_host = args.host
    if args.port:
        cfg.listen_port = args.port
    if args.api_key:
        cfg.api_key = args.api_key
    if args.quiet:
        cfg.log = False

    if not cfg.rules:
        sys.stderr.write("error: no rules configured\n")
        return 2

    if not cfg.upstream:
        # Keep the gateway URL out of committed source: it must be configured.
        sys.stderr.write(
            "error: no upstream configured; pass --upstream or set `upstream`"
            " in the config file (see config.toml.example)\n"
        )
        return 2

    Handler.api_key = resolve_api_key(cfg)
    if not Handler.api_key:
        sys.stderr.write(
            "warning: no API key configured; requests are forwarded with the"
            " client-supplied Authorization header\n"
        )

    Handler.cfg = cfg
    server = ThreadingHTTPServer((cfg.listen_host, cfg.listen_port), Handler)
    server.daemon_threads = True

    sys.stderr.write(
        f"[proxy] listening on http://{cfg.listen_host}:{cfg.listen_port}/v1 "
        f"-> {cfg.upstream}\n"
    )
    for rule in cfg.rules:
        sys.stderr.write(
            f"[proxy]   {rule.match.pattern} -> {rule.param}={rule.value}"
            f"{' (force)' if rule.force else ''}\n"
        )
    sys.stderr.flush()

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        sys.stderr.write("\n[proxy] shutting down\n")
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
