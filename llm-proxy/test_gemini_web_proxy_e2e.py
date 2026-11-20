#!/usr/bin/env python3
"""End-to-end test: real socket, fake Gemini backend, SSE streaming intact.

A fake backend replaces the Gemini client so the HTTP layer, the prompt
translation and the SSE framing are exercised without cookies.
"""

from __future__ import annotations

import json
import threading
import unittest
import urllib.request
from http.server import ThreadingHTTPServer
from types import SimpleNamespace

import gemini_web_proxy as proxy


class FakeOutput:
    def __init__(self, text: str):
        self.text = text
        self.text_delta = text
        self.usage = {}


class FakeBackend:
    """Stands in for GeminiBackend; records the prompts it receives."""

    def __init__(self, reply: str = "hello from gemini"):
        self.reply = reply
        self.prompts: list[str] = []
        self.thinking: list[bool] = []
        self.ready_flag = True

    def ready(self) -> bool:
        return self.ready_flag

    def models(self):
        return ["gemini-3-flash", "gemini-3-pro"]

    def connect(self):
        return self

    def invalidate(self) -> None:
        self.ready_flag = False

    def complete(self, prompt, model_name, extended_thinking):
        self.prompts.append(prompt)
        self.thinking.append(extended_thinking)
        return FakeOutput(self.reply)

    def stream(self, prompt, model_name, extended_thinking):
        self.prompts.append(prompt)
        self.thinking.append(extended_thinking)
        parts = [self.reply[:5], self.reply[5:]]

        def gen():
            for part in parts:
                if part:
                    yield ("delta", FakeOutput(part))
            yield ("end", None)

        return gen()


class ProxyTestCase(unittest.TestCase):
    reply = "hello from gemini"
    tool_mode = "off"

    def setUp(self) -> None:
        cfg = proxy.Config(tool_mode=self.tool_mode, log=False)
        proxy.Handler.cfg = cfg
        self.backend = FakeBackend(self.reply)
        proxy.Handler.backend = self.backend
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), proxy.Handler)
        self.server.daemon_threads = True
        self.port = self.server.server_address[1]
        self.thread = threading.Thread(
            target=self.server.serve_forever, daemon=True
        )
        self.thread.start()

    def tearDown(self) -> None:
        self.server.shutdown()
        self.server.server_close()

    def url(self, path: str) -> str:
        return f"http://127.0.0.1:{self.port}{path}"

    def post(self, payload: dict):
        req = urllib.request.Request(
            self.url("/v1/chat/completions"),
            data=json.dumps(payload).encode(),
            headers={"Content-Type": "application/json"},
        )
        return self._send(req)

    def _send(self, req):
        """Return (status, body) for both success and error responses."""
        try:
            with urllib.request.urlopen(req, timeout=10) as resp:
                return resp.status, resp.read()
        except urllib.error.HTTPError as exc:
            with exc:
                return exc.code, exc.read()

    def get(self, path: str):
        return self._send(urllib.request.Request(self.url(path)))


class TestBuffered(ProxyTestCase):
    def test_plain_completion(self) -> None:
        status, raw = self.post(
            {"model": "gemini-3-flash", "messages": [
                {"role": "user", "content": "hi"}]}
        )
        self.assertEqual(status, 200)
        body = json.loads(raw)
        self.assertEqual(body["choices"][0]["message"]["content"],
                         "hello from gemini")
        self.assertEqual(body["choices"][0]["finish_reason"], "stop")
        self.assertEqual(self.backend.prompts, ["hi"])

    def test_system_and_history_reach_the_backend(self) -> None:
        self.post({"messages": [
            {"role": "system", "content": "be terse"},
            {"role": "user", "content": "q1"},
            {"role": "assistant", "content": "a1"},
            {"role": "user", "content": "q2"},
        ]})
        prompt = self.backend.prompts[0]
        self.assertIn("SYSTEM: be terse", prompt)
        self.assertIn("ASSISTANT: a1", prompt)
        self.assertTrue(prompt.endswith("USER: q2"))

    def test_high_effort_enables_thinking(self) -> None:
        self.post({"messages": [{"role": "user", "content": "x"}],
                   "reasoning_effort": "high"})
        self.assertEqual(self.backend.thinking, [True])

    def test_default_effort_leaves_thinking_off(self) -> None:
        self.post({"messages": [{"role": "user", "content": "x"}]})
        self.assertEqual(self.backend.thinking, [False])

    def test_stream_replayed_as_sse(self) -> None:
        status, raw = self.post({"messages": [
            {"role": "user", "content": "x"}], "stream": True})
        self.assertEqual(status, 200)
        text = raw.decode()
        chunks = [
            json.loads(line[len("data: "):])
            for line in text.splitlines()
            if line.startswith("data: {")
        ]
        self.assertEqual(chunks[0]["object"], "chat.completion.chunk")
        self.assertEqual(chunks[-1]["choices"][0]["finish_reason"], "stop")
        # OpenAI ends a stream with a bare sentinel, not a JSON string.
        self.assertIn("data: [DONE]", text)
        self.assertNotIn('"[DONE]"', text)

    def test_native_stream_accumulates_content(self) -> None:
        status, raw = self.post({"messages": [
            {"role": "user", "content": "x"}], "stream": True})
        contents = []
        for line in raw.decode().splitlines():
            if line.startswith("data: {"):
                delta = json.loads(line[6:])["choices"][0]["delta"]
                contents.append(delta.get("content", ""))
        self.assertEqual("".join(contents), "hello from gemini")

    def test_empty_messages_rejected(self) -> None:
        status, raw = self.post({"messages": []})
        self.assertEqual(status, 400)
        self.assertIn("error", json.loads(raw))

    def test_bad_json_rejected(self) -> None:
        req = urllib.request.Request(
            self.url("/v1/chat/completions"),
            data=b"not json",
            headers={"Content-Type": "application/json"},
        )
        status, raw = self._send(req)
        self.assertEqual(status, 400)
        self.assertIn("invalid JSON", json.loads(raw)["error"]["message"])

    def test_tools_dropped_when_mode_off(self) -> None:
        self.post({
            "messages": [{"role": "user", "content": "x"}],
            "tools": [{"type": "function", "function": {"name": "ls"}}],
        })
        self.assertNotIn("tool_calls", self.backend.prompts[0])

    def test_models_listing(self) -> None:
        status, raw = self.get("/v1/models")
        self.assertEqual(status, 200)
        ids = [m["id"] for m in json.loads(raw)["data"]]
        self.assertEqual(ids, ["gemini-3-flash", "gemini-3-pro"])

    def test_v1_prefix_is_accepted_once(self) -> None:
        # Cursor's base URL ends in /v1, so the request path is /v1/... and the
        # proxy must not expect or add a second prefix.
        status, _ = self.post({"messages": [
            {"role": "user", "content": "x"}]})
        self.assertEqual(status, 200)

    def test_unknown_path_is_404(self) -> None:
        status, raw = self.get("/v1/bogus")
        self.assertEqual(status, 404)
        self.assertIn("error", json.loads(raw))

    def test_healthz_when_connected(self) -> None:
        status, _ = self.get("/healthz")
        self.assertEqual(status, 200)


class TestToolMode(ProxyTestCase):
    reply = json.dumps({"tool_calls": [{"name": "ls",
                                        "arguments": {"path": "/"}}]})
    tool_mode = "prompt"

    def test_tool_schema_reaches_prompt(self) -> None:
        self.post({
            "messages": [{"role": "user", "content": "list root"}],
            "tools": [{"type": "function", "function": {"name": "ls"}}],
        })
        self.assertIn("tool_calls", self.backend.prompts[0])
        self.assertIn("ls", self.backend.prompts[0])

    def test_tool_call_is_parsed(self) -> None:
        _, raw = self.post({
            "messages": [{"role": "user", "content": "list root"}],
            "tools": [{"type": "function", "function": {"name": "ls"}}],
        })
        choice = json.loads(raw)["choices"][0]
        self.assertEqual(choice["finish_reason"], "tool_calls")
        call = choice["message"]["tool_calls"][0]
        self.assertEqual(call["function"]["name"], "ls")
        self.assertEqual(json.loads(call["function"]["arguments"]),
                         {"path": "/"})

    def test_tool_call_streams_as_single_chunk(self) -> None:
        _, raw = self.post({
            "messages": [{"role": "user", "content": "list root"}],
            "tools": [{"type": "function", "function": {"name": "ls"}}],
            "stream": True,
        })
        text = raw.decode()
        chunks = [json.loads(line[6:]) for line in text.splitlines()
                  if line.startswith("data: {")]
        # Buffered: one delta carrying the call, then the terminal chunk.
        self.assertEqual(len(chunks), 2)
        self.assertIn("tool_calls", chunks[0]["choices"][0]["delta"])
        self.assertEqual(chunks[-1]["choices"][0]["finish_reason"],
                         "tool_calls")


if __name__ == "__main__":
    unittest.main()
