#!/usr/bin/env python3
"""OpenAI-compatible proxy in front of a logged-in gemini.google.com session.

There is no API key for Gemini's consumer tiers, so this proxy drives the same
web session the browser uses. It reuses the `__Secure-1PSID` and
`__Secure-1PSIDTS` cookies of an account signed in to gemini.google.com and
re-exposes the conversation as `/v1/chat/completions`, which Cursor's
`openAIBaseUrl` setting understands.

The web UI speaks a chat transcript, not a message array, so every request is
flattened into one prompt. `temporary = true` keeps the generated chats out of
the account's Gemini history and leaves conversation state entirely with the
client, which is what Cursor already does.

Function calling is not a web-UI feature. `tool_mode = "prompt"` appends the
tool schemas to the prompt and parses a single JSON tool call back out of the
reply; it buffers the reply, because the decision to call a tool is only known
at the end. `tool_mode = "off"` drops the tools and streams normally.

Usage:
    ./gemini_web_proxy.py --config config.gemini.toml
    ./gemini_web_proxy.py --config config.gemini.toml --check

Then point Cursor's `openAIBaseUrl` at http://127.0.0.1:6969/v1, or chain it
behind cursor_effort_proxy.py (see config.chain.toml.example).
"""

from __future__ import annotations

import argparse
import asyncio
import json
import math
import os
import queue
import re
import sys
import threading
import time
import tomllib
import uuid
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Iterator

DEFAULT_PORT = 6969
DEFAULT_TIMEOUT = 300

_ROLE_LABELS = {
    "system": "SYSTEM",
    "developer": "SYSTEM",
    "user": "USER",
    "assistant": "ASSISTANT",
    "tool": "TOOL RESULT",
    "function": "TOOL RESULT",
}

# Effort values that switch Gemini's extended-thinking mode on.
_HIGH_EFFORT = {"high", "max", "xhigh"}

_TOOL_INSTRUCTION = (
    "You can call at most one function per reply. The functions available to "
    "you are listed as JSON schemas below. To call one, reply with a single "
    'JSON object and nothing else: {"tool_calls": [{"name": "<function '
    'name>", "arguments": {...}}]}. If no function is needed, answer '
    "normally in plain text and do not emit JSON."
)


# -- config -------------------------------------------------------------
@dataclass
class Config:
    listen_host: str = "127.0.0.1"
    listen_port: int = DEFAULT_PORT
    # Gemini model name, alias or hex id. Empty means the account default.
    model: str = ""
    # Credentials come from the config file only; it is git-ignored.
    secure_1psid: str = ""
    secure_1psidts: str = ""
    # Outbound HTTP proxy for reaching Google, if one is required.
    proxy: str = ""
    impersonate: str = "chrome145"
    timeout: int = DEFAULT_TIMEOUT
    # Keep generated chats out of the account's Gemini history.
    temporary: bool = True
    # Force extended thinking regardless of the request's reasoning_effort.
    extended_thinking: bool = False
    # "off" drops OpenAI tools; "prompt" emulates one call per reply.
    tool_mode: str = "off"
    # Where gemini-webapi caches rotated cookies. Defaults to the package's
    # own location; set explicitly so the file is not written world-readable
    # under the system temp directory.
    cookie_cache_dir: str = os.path.join(
        os.path.expanduser("~"), ".cache", "gemini-webkit-proxy"
    )
    log: bool = True


def _prepare_cookie_cache(path: str) -> None:
    """Create the cookie cache directory, private to the current user.

    gemini-webapi writes rotated `__Secure-1PSID` values there. The package
    defaults to the system temp directory, which every user on the host can
    read, so an explicit private directory is used instead. A failure is not fatal: the
    package then falls back to its own temp directory.
    """
    if not path:
        return
    try:
        os.makedirs(path, mode=0o700, exist_ok=True)
        os.chmod(path, 0o700)
    except OSError as exc:
        sys.stderr.write(
            f"[gemini] warning: cannot use cookie cache dir {path} ({exc});"
            " rotated cookies fall back to the system temp directory\n"
        )
        return
    os.environ["GEMINI_COOKIE_PATH"] = path


def load_config(path: str | None) -> Config:
    cfg = Config()
    if not path:
        return cfg
    with open(path, "rb") as fh:
        raw = tomllib.load(fh)
    cfg.listen_host = str(raw.get("listen_host", cfg.listen_host))
    cfg.listen_port = int(raw.get("listen_port", cfg.listen_port))
    cfg.model = str(raw.get("model", cfg.model))
    cfg.secure_1psid = str(raw.get("secure_1psid", cfg.secure_1psid))
    cfg.secure_1psidts = str(raw.get("secure_1psidts", cfg.secure_1psidts))
    cfg.proxy = str(raw.get("proxy", cfg.proxy))
    cfg.impersonate = str(raw.get("impersonate", cfg.impersonate))
    cfg.timeout = int(raw.get("timeout", cfg.timeout))
    cfg.temporary = bool(raw.get("temporary", cfg.temporary))
    cfg.extended_thinking = bool(
        raw.get("extended_thinking", cfg.extended_thinking)
    )
    cfg.tool_mode = str(raw.get("tool_mode", cfg.tool_mode))
    cfg.cookie_cache_dir = str(
        raw.get("cookie_cache_dir", cfg.cookie_cache_dir)
    )
    cfg.log = bool(raw.get("log", cfg.log))
    return cfg


# -- request translation ------------------------------------------------
def _content_text(content: Any) -> str:
    """Flatten an OpenAI message `content` (string or parts) to plain text."""
    if isinstance(content, str):
        return content
    if not isinstance(content, list):
        return ""
    parts = []
    for part in content:
        if isinstance(part, str):
            parts.append(part)
        elif isinstance(part, dict) and part.get("type") == "text":
            text = part.get("text")
            if isinstance(text, str):
                parts.append(text)
    return "\n".join(parts)


def _render_body(msg: dict[str, Any], role: str) -> str:
    """Render one non-system message, including any assistant tool calls."""
    text = _content_text(msg.get("content"))
    parts = [text] if text else []
    if role == "assistant":
        for call in msg.get("tool_calls") or []:
            fn = (call or {}).get("function") or {}
            parts.append(
                f"[called {fn.get('name', '')} "
                f"with {fn.get('arguments', '')}]"
            )
    return "\n".join(part for part in parts if part)


def build_prompt(messages: list[Any], extra_system: str = "") -> str:
    """Flatten a full OpenAI message array into a single Gemini prompt."""
    systems: list[str] = []
    turns: list[str] = []
    for msg in messages or []:
        if not isinstance(msg, dict):
            continue
        role = str(msg.get("role", "user")).lower()
        if role in ("system", "developer"):
            text = _content_text(msg.get("content"))
            if text:
                systems.append(text)
            continue
        body = _render_body(msg, role)
        if body:
            turns.append(f"{_ROLE_LABELS.get(role, role.upper())}: {body}")
    if extra_system:
        systems.append(extra_system)
    # A lone user message needs no labels: pass it through verbatim so the
    # model sees exactly what the user typed.
    if not systems and len(turns) == 1 and turns[0].startswith("USER: "):
        return turns[0][len("USER: "):]
    blocks = []
    if systems:
        blocks.append("SYSTEM: " + "\n\n".join(systems))
    blocks.extend(turns)
    return "\n\n".join(blocks)


def build_tool_prompt(tools: Any) -> str:
    """Describe OpenAI tools in prose so the web model can call one."""
    specs = []
    for tool in tools if isinstance(tools, list) else []:
        fn = (tool or {}).get("function") or {}
        if fn.get("name"):
            specs.append(json.dumps(fn, sort_keys=True))
    if not specs:
        return ""
    return "\n".join([_TOOL_INSTRUCTION, "Functions:", *specs])


_FENCE_RE = re.compile(r"```(?:json)?\s*(\{.*?\})\s*```", re.DOTALL)


def _iter_json_objects(text: str) -> Iterator[Any]:
    """Yield every JSON value that decode cleanly out of a reply.

    Prose can contain stray braces (`steps {a, b} then {...}`), so each `{` is
    tried in turn instead of taking the span from the first brace to the last.
    """
    decoder = json.JSONDecoder()
    for fenced in _FENCE_RE.finditer(text):
        try:
            yield json.loads(fenced.group(1))
        except (json.JSONDecodeError, TypeError):
            pass
    idx = text.find("{")
    while idx != -1:
        try:
            obj, _ = decoder.raw_decode(text, idx)
        except json.JSONDecodeError:
            idx = text.find("{", idx + 1)
            continue
        yield obj
        idx = text.find("{", idx + 1)


def _tool_calls_payload(text: str) -> Any:
    """Return the first decoded object that carries a `tool_calls` key."""
    for obj in _iter_json_objects(text or ""):
        if isinstance(obj, dict) and "tool_calls" in obj:
            return obj
    return None


def parse_tool_calls(text: str) -> list[dict[str, Any]]:
    """Extract OpenAI-shaped tool calls from a model reply, [] when none."""
    payload = _tool_calls_payload(text)
    if not isinstance(payload, dict):
        return []
    calls = payload.get("tool_calls")
    if isinstance(calls, dict):
        calls = [calls]
    if not isinstance(calls, list):
        return []
    out: list[dict[str, Any]] = []
    for call in calls:
        if not isinstance(call, dict):
            continue
        raw = call.get("function")
        fn = raw if isinstance(raw, dict) else call
        name = fn.get("name") or fn.get("tool")
        if not isinstance(name, str) or not name:
            continue
        args = fn.get("arguments", fn.get("args", {}))
        if not isinstance(args, str):
            args = json.dumps(args)
        out.append(
            {
                "id": f"call_{uuid.uuid4().hex[:24]}",
                "type": "function",
                "function": {"name": name, "arguments": args},
            }
        )
    return out


def _approx_tokens(chars: int) -> int:
    """Rough token estimate: about four characters per token."""
    return math.ceil(chars / 4) if chars else 0


def completion_payload(
    model: str,
    text: str,
    tool_calls: list[dict[str, Any]] | None = None,
    prompt_chars: int = 0,
) -> dict[str, Any]:
    """Build an OpenAI `chat.completion` response body."""
    message: dict[str, Any] = {"role": "assistant", "content": text or ""}
    finish = "stop"
    if tool_calls:
        message["tool_calls"] = tool_calls
        finish = "tool_calls"
    prompt_tokens = _approx_tokens(prompt_chars)
    reply_tokens = _approx_tokens(len(text or ""))
    return {
        "id": f"chatcmpl-{uuid.uuid4().hex[:24]}",
        "object": "chat.completion",
        "created": int(time.time()),
        "model": model,
        "choices": [
            {"index": 0, "message": message, "finish_reason": finish}
        ],
        "usage": {
            "prompt_tokens": prompt_tokens,
            "completion_tokens": reply_tokens,
            "total_tokens": prompt_tokens + reply_tokens,
        },
    }


def stream_chunk(
    chunk_id: str,
    model: str,
    created: int,
    delta: dict[str, Any],
    finish_reason: str | None = None,
) -> dict[str, Any]:
    """Build an OpenAI `chat.completion.chunk` response body."""
    return {
        "id": chunk_id,
        "object": "chat.completion.chunk",
        "created": created,
        "model": model,
        "choices": [
            {"index": 0, "delta": delta, "finish_reason": finish_reason}
        ],
    }


def error_payload(message: str, kind: str = "invalid_request_error") -> dict:
    return {"error": {"message": message, "type": kind}}


# -- gemini backend -----------------------------------------------------
def _load_package():
    """Import gemini_webapi lazily so the pure helpers stay importable."""
    import gemini_webapi
    from gemini_webapi import exceptions as gexc

    return gemini_webapi, gexc


class StreamBridge:
    """Adapt an async generator running on the proxy loop to a blocking one."""

    def __init__(self, loop: asyncio.AbstractEventLoop, agen, timeout: float):
        self._queue: queue.Queue = queue.Queue()
        self._timeout = timeout
        self._task = asyncio.run_coroutine_threadsafe(
            self._pump(agen), loop
        )

    async def _pump(self, agen) -> None:
        try:
            async for item in agen:
                self._queue.put(("delta", item))
            self._queue.put(("end", None))
        except Exception as exc:  # noqa: BLE001 - reported to the client
            self._queue.put(("error", exc))

    def __iter__(self) -> Iterator[tuple[str, Any]]:
        while True:
            try:
                kind, payload = self._queue.get(timeout=self._timeout)
            except queue.Empty:
                self._task.cancel()
                yield ("error", TimeoutError("gemini stream timed out"))
                return
            if kind == "delta":
                yield ("delta", payload)
            elif kind == "end":
                yield ("end", None)
                return
            else:
                yield ("error", payload)
                return


class GeminiBackend:
    """Owns the event loop and the gemini-webapi client."""

    def __init__(self, cfg: Config):
        self.cfg = cfg
        self._loop = asyncio.new_event_loop()
        self._thread = threading.Thread(
            target=self._run_loop, name="gemini-loop", daemon=True
        )
        self._client = None
        self._connect_lock = threading.Lock()

    def _run_loop(self) -> None:
        asyncio.set_event_loop(self._loop)
        self._loop.run_forever()

    def start(self) -> None:
        self._thread.start()

    def _submit(self, coro):
        return asyncio.run_coroutine_threadsafe(coro, self._loop)

    def ready(self) -> bool:
        return self._client is not None

    def connect(self):
        """Return the initialized client, connecting on first use."""
        with self._connect_lock:
            if self._client is not None:
                return self._client
            future = self._submit(self._aconnect())
            self._client = future.result(timeout=120)
            return self._client

    async def _aconnect(self):
        gemini_webapi, gexc = _load_package()
        _prepare_cookie_cache(self.cfg.cookie_cache_dir)
        client = gemini_webapi.GeminiClient(
            self.cfg.secure_1psid,
            self.cfg.secure_1psidts,
            proxy=self.cfg.proxy or None,
        )
        await client.init(
            timeout=float(self.cfg.timeout),
            auto_refresh=True,
            impersonate=self.cfg.impersonate,
            verbose=self.cfg.log,
        )
        # init() succeeds even when the cookies are unusable: the session is
        # simply marked UNAUTHENTICATED. Checking here turns a proxy that
        # starts "healthy" but fails every request into an immediate error.
        status = getattr(client, "account_status", None)
        name = getattr(status, "name", "")
        if name and name != "AVAILABLE":
            description = getattr(status, "description", "account not available")
            if name == "UNAUTHENTICATED":
                raise gexc.AuthError(
                    f"gemini session is not authenticated ({name}):"
                    f" {description} - refresh the __Secure-1PSID cookie"
                )
            raise gexc.GeminiError(f"gemini account unusable ({name}): {description}")
        return client

    def invalidate(self) -> None:
        """Drop the session so the next request re-authenticates."""
        with self._connect_lock:
            client, self._client = self._client, None
        if client is not None:
            self._submit(client.close(delay=0))

    def models(self) -> list[str]:
        client = self.connect()
        listed = client.list_models() or []
        names = [m.model_name for m in listed if m.is_available]
        if names:
            return names
        return [self.cfg.model] if self.cfg.model else []

    def _resolve(self, model_name: str):
        """Map a requested model onto this account's registry."""
        client = self.connect()
        for name in (model_name, self.cfg.model):
            if not name:
                continue
            try:
                return client.resolve_model(name)
            except Exception:  # noqa: BLE001 - unknown model, try next
                continue
        return None

    def complete(
        self, prompt: str, model_name: str, extended_thinking: bool
    ):
        client = self.connect()
        future = self._submit(
            client.generate_content(
                prompt,
                model=self._resolve(model_name),
                temporary=self.cfg.temporary,
                extended_thinking=extended_thinking,
            )
        )
        return future.result(timeout=self.cfg.timeout)

    def stream(
        self, prompt: str, model_name: str, extended_thinking: bool
    ) -> StreamBridge:
        client = self.connect()
        agen = client.generate_content_stream(
            prompt,
            model=self._resolve(model_name),
            temporary=self.cfg.temporary,
            extended_thinking=extended_thinking,
        )
        return StreamBridge(self._loop, agen, self.cfg.timeout)


def error_status(exc: BaseException) -> int:
    """Map a gemini-webapi exception onto an HTTP status code."""
    try:
        _, gexc = _load_package()
    except Exception:  # noqa: BLE001 - package missing, generic failure
        return 502
    mapping = (
        ("AuthError", 401),
        ("UsageLimitExceededError", 429),
        ("TemporarilyBlockedError", 429),
        ("TimeoutError", 504),
        ("ModelInvalidError", 400),
    )
    for name, status in mapping:
        cls = getattr(gexc, name, None)
        if cls is not None and isinstance(exc, cls):
            return status
    return 502


# -- HTTP layer ---------------------------------------------------------
class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    server_version = "gemini-web-proxy/1.0"
    # Set once a response line has been written; reset per request.
    _sent: bool = False

    cfg: Config  # set by main()
    backend: GeminiBackend  # set by main()

    def log_message(self, fmt: str, *args: Any) -> None:
        if self.cfg.log:
            sys.stderr.write(
                f"[gemini] {self.address_string()} {fmt % args}\n"
            )

    def _note(self, msg: str) -> None:
        if self.cfg.log:
            sys.stderr.write(f"[gemini] {msg}\n")

    # -- verbs ----------------------------------------------------------
    def do_GET(self) -> None:
        self._sent = False
        path = self.path.split("?", 1)[0].rstrip("/")
        if path in ("/healthz", "/health"):
            if self.backend.ready():
                self._json(200, {"status": "ok"})
            else:
                self._json(503, {"status": "not connected"})
            return
        if path.endswith("/models"):
            self._models()
            return
        self._json(404, error_payload(f"unknown path {path}"))

    def do_POST(self) -> None:
        self._sent = False
        path = self.path.split("?", 1)[0].rstrip("/")
        body = self._read_body()
        if path.endswith("/chat/completions"):
            self._chat(body)
            return
        self._json(404, error_payload(f"unknown path {path}"))

    # -- helpers --------------------------------------------------------
    def _read_body(self) -> bytes:
        length = self.headers.get("Content-Length")
        if not length:
            return b""
        try:
            n = int(length)
        except ValueError:
            return b""
        return self.rfile.read(n) if n > 0 else b""

    def _json(self, status: int, payload: Any) -> None:
        data = json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)
        self.wfile.flush()

    def _sse_start(self) -> None:
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Transfer-Encoding", "chunked")
        self.end_headers()

    def _sse_write(self, payload: Any) -> None:
        self._raw_data(f"data: {json.dumps(payload)}\n\n")

    def _raw_data(self, text: str) -> None:
        data = text.encode()
        self.wfile.write(b"%x\r\n" % len(data))
        self.wfile.write(data)
        self.wfile.write(b"\r\n")
        self.wfile.flush()

    def _sse_done(self) -> None:
        # OpenAI terminates a stream with a bare `data: [DONE]` sentinel, not a
        # JSON string, so this cannot go through _sse_write.
        self._raw_data("data: [DONE]\n\n")

    def _sse_end(self) -> None:
        self.wfile.write(b"0\r\n\r\n")
        self.wfile.flush()

    def _models(self) -> None:
        try:
            names = self.backend.models()
        except Exception as exc:  # noqa: BLE001 - surfaced to the client
            self._note(f"model listing failed: {exc}")
            names = [self.cfg.model] if self.cfg.model else []
        payload = {
            "object": "list",
            "data": [
                {
                    "id": name,
                    "object": "model",
                    "created": 0,
                    "owned_by": "google-gemini-web",
                }
                for name in names
            ],
        }
        self._json(200, payload)

    def _chat(self, body: bytes) -> None:
        try:
            req = json.loads(body or b"{}")
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            self._json(400, error_payload(f"invalid JSON body: {exc}"))
            return
        if not isinstance(req, dict):
            self._json(400, error_payload("body must be a JSON object"))
            return

        model_name = str(req.get("model") or self.cfg.model)
        tools = req.get("tools")
        tool_prompt = ""
        if self.cfg.tool_mode == "prompt":
            tool_prompt = build_tool_prompt(tools)
        elif tools:
            self._note("dropping tools: tool_mode is off")

        prompt = build_prompt(req.get("messages") or [], tool_prompt)
        if not prompt.strip():
            self._json(400, error_payload("no prompt content"))
            return

        effort = str(req.get("reasoning_effort") or "").lower()
        thinking = self.cfg.extended_thinking or effort in _HIGH_EFFORT
        wants_stream = bool(req.get("stream"))
        # A tool call is only known once the reply is complete, so a prompt
        # tool mode cannot stream: buffer and replay the result instead.
        buffered = wants_stream and bool(tool_prompt)

        try:
            if wants_stream and not buffered:
                self._stream_completion(prompt, model_name, thinking)
            else:
                self._buffered_completion(
                    prompt, model_name, thinking, wants_stream, bool(tool_prompt)
                )
        except Exception as exc:  # noqa: BLE001 - surfaced to the client
            status = error_status(exc)
            self._note(f"request failed ({status}): {exc}")
            if status == 401:
                self.backend.invalidate()
            if not self._headers_sent():
                self._json(status, error_payload(str(exc), "upstream_error"))

    def _headers_sent(self) -> bool:
        # Reset per request in do_GET/do_POST: a keep-alive connection reuses
        # this handler instance, so a stale flag would suppress real errors.
        return getattr(self, "_sent", False)

    def _stream_completion(
        self, prompt: str, model_name: str, thinking: bool
    ) -> None:
        bridge = self.backend.stream(prompt, model_name, thinking)
        chunk_id = f"chatcmpl-{uuid.uuid4().hex[:24]}"
        created = int(time.time())
        self._sse_start()
        self._sent = True

        usage: dict[str, Any] = {}
        for kind, payload in bridge:
            if kind == "delta":
                text = getattr(payload, "text_delta", "") or ""
                if text:
                    self._sse_write(
                        stream_chunk(
                            chunk_id,
                            model_name,
                            created,
                            {"content": text},
                        )
                    )
                if getattr(payload, "usage", None):
                    usage = payload.usage
            elif kind == "end":
                self._sse_write(
                    stream_chunk(
                        chunk_id, model_name, created, {}, "stop"
                    )
                )
                self._sse_done()
                break
            else:
                self._note(f"stream error: {payload}")
                break
        if usage:
            self._note(f"usage: {usage}")
        self._sse_end()

    def _buffered_completion(
        self,
        prompt: str,
        model_name: str,
        thinking: bool,
        wants_stream: bool,
        parse_tools: bool,
    ) -> None:
        output = self.backend.complete(prompt, model_name, thinking)
        text = getattr(output, "text", "") or ""
        calls = parse_tool_calls(text) if parse_tools else []
        if calls:
            self._note(f"tool call: {calls[0]['function']['name']}")
        payload = completion_payload(model_name, text, calls, len(prompt))

        if not wants_stream:
            self._json(200, payload)
            return

        chunk_id = payload["id"]
        created = payload["created"]
        self._sse_start()
        self._sent = True
        message = payload["choices"][0]["message"]
        if calls:
            delta = {"tool_calls": [
                {**call, "index": idx} for idx, call in enumerate(calls)
            ]}
        else:
            delta = {"content": text}
        self._sse_write(stream_chunk(chunk_id, model_name, created, delta))
        self._sse_write(
            stream_chunk(
                chunk_id,
                model_name,
                created,
                {},
                payload["choices"][0]["finish_reason"],
            )
        )
        self._sse_done()
        self._sse_end()
        self._note(f"replayed buffered {len(text)} chars")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--config", help="path to a TOML config file")
    parser.add_argument("--host", help="override listen host")
    parser.add_argument("--port", type=int, help="override listen port")
    parser.add_argument("--model", help="override the default model")
    parser.add_argument(
        "--tool-mode",
        choices=("off", "prompt"),
        help="override the tool emulation mode",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="connect, print the account's models and exit",
    )
    parser.add_argument(
        "-q", "--quiet", action="store_true", help="no per-request logs"
    )
    args = parser.parse_args(argv)

    cfg = load_config(args.config)
    if args.host:
        cfg.listen_host = args.host
    if args.port:
        cfg.listen_port = args.port
    if args.model:
        cfg.model = args.model
    if args.tool_mode:
        cfg.tool_mode = args.tool_mode
    if args.quiet:
        cfg.log = False

    if not cfg.secure_1psid:
        sys.stderr.write(
            "error: no `secure_1psid` configured; copy"
            " config.gemini.toml.example to config.gemini.toml and paste the"
            " __Secure-1PSID cookie of a gemini.google.com session\n"
        )
        return 2

    backend = GeminiBackend(cfg)
    backend.start()
    Handler.cfg = cfg
    Handler.backend = backend

    if args.check:
        try:
            names = backend.models()
        except Exception as exc:  # noqa: BLE001 - reported to the user
            sys.stderr.write(f"error: {type(exc).__name__}: {exc}\n")
            return 1
        sys.stderr.write("[gemini] account models:\n")
        for name in names:
            sys.stderr.write(f"[gemini]   {name}\n")
        return 0

    try:
        backend.connect()
    except Exception as exc:  # noqa: BLE001 - reported to the user
        sys.stderr.write(
            f"error: could not connect to gemini.google.com:"
            f" {type(exc).__name__}: {exc}\n"
        )
        return 1

    server = ThreadingHTTPServer(
        (cfg.listen_host, cfg.listen_port), Handler
    )
    server.daemon_threads = True

    sys.stderr.write(
        f"[gemini] listening on"
        f" http://{cfg.listen_host}:{cfg.listen_port}/v1\n"
    )
    sys.stderr.write(
        f"[gemini] default model: {cfg.model or '<account default>'}"
        f", tool_mode={cfg.tool_mode}"
        f", temporary={cfg.temporary}"
    )
    for name in backend.models():
        sys.stderr.write(f"\n[gemini]   {name}")
    sys.stderr.write("\n")
    sys.stderr.flush()

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        sys.stderr.write("\n[gemini] shutting down\n")
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
