#!/usr/bin/env python3
"""Tests for gemini_web_proxy.py.

Run with:  python3 -m unittest discover -s llm-proxy -v

Only the pure request/response translation is covered here; the Gemini
backend needs live cookies and is exercised by `--check`.
"""

from __future__ import annotations

import json
import unittest

from gemini_web_proxy import (
    build_prompt,
    build_tool_prompt,
    completion_payload,
    error_status,
    parse_tool_calls,
    stream_chunk,
)


def user(text: str) -> dict:
    return {"role": "user", "content": text}


class TestBuildPrompt(unittest.TestCase):
    def test_lone_user_message_is_verbatim(self) -> None:
        self.assertEqual(build_prompt([user("hello there")]), "hello there")

    def test_system_message_comes_first(self) -> None:
        prompt = build_prompt(
            [{"role": "system", "content": "be terse"}, user("hi")]
        )
        self.assertEqual(prompt, "SYSTEM: be terse\n\nUSER: hi")

    def test_multi_turn_is_labelled(self) -> None:
        prompt = build_prompt(
            [
                user("one"),
                {"role": "assistant", "content": "two"},
                user("three"),
            ]
        )
        self.assertEqual(prompt, "USER: one\n\nASSISTANT: two\n\nUSER: three")

    def test_content_parts_are_flattened(self) -> None:
        msg = {
            "role": "user",
            "content": [
                {"type": "text", "text": "first"},
                {"type": "image_url", "image_url": {"url": "http://x"}},
                {"type": "text", "text": "second"},
            ],
        }
        self.assertEqual(build_prompt([msg]), "first\nsecond")

    def test_tool_result_is_labelled(self) -> None:
        prompt = build_prompt(
            [
                user("q"),
                {"role": "tool", "content": "42", "tool_call_id": "c1"},
            ]
        )
        self.assertEqual(prompt, "USER: q\n\nTOOL RESULT: 42")

    def test_assistant_tool_call_is_rendered(self) -> None:
        msg = {
            "role": "assistant",
            "content": "",
            "tool_calls": [
                {
                    "id": "c1",
                    "type": "function",
                    "function": {"name": "ls", "arguments": '{"p": 1}'},
                }
            ],
        }
        prompt = build_prompt([user("q"), msg])
        self.assertIn("[called ls with ", prompt)

    def test_empty_messages_produce_empty_prompt(self) -> None:
        self.assertEqual(build_prompt([]), "")

    def test_extra_system_is_appended(self) -> None:
        prompt = build_prompt([user("hi")], "extra rules")
        self.assertEqual(prompt, "SYSTEM: extra rules\n\nUSER: hi")

    def test_malformed_messages_are_skipped(self) -> None:
        prompt = build_prompt(["nope", None, {"role": "user", "content": "ok"}])
        self.assertEqual(prompt, "ok")


class TestBuildToolPrompt(unittest.TestCase):
    def test_includes_schema_and_instruction(self) -> None:
        tools = [
            {
                "type": "function",
                "function": {
                    "name": "read_file",
                    "description": "read a file",
                    "parameters": {"type": "object"},
                },
            }
        ]
        prompt = build_tool_prompt(tools)
        self.assertIn("tool_calls", prompt)
        self.assertIn("read_file", prompt)
        self.assertIn('"parameters"', prompt)

    def test_no_tools_means_no_prompt(self) -> None:
        self.assertEqual(build_tool_prompt(None), "")
        self.assertEqual(build_tool_prompt([]), "")
        self.assertEqual(build_tool_prompt([{"type": "function"}]), "")

    def test_unnamed_tool_is_ignored(self) -> None:
        self.assertEqual(
            build_tool_prompt([{"function": {"description": "x"}}]), ""
        )


class TestParseToolCalls(unittest.TestCase):
    def test_parses_plain_json_call(self) -> None:
        text = json.dumps(
            {"tool_calls": [{"name": "ls", "arguments": {"path": "/"}}]}
        )
        calls = parse_tool_calls(text)
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0]["function"]["name"], "ls")
        self.assertEqual(json.loads(calls[0]["function"]["arguments"]), {
            "path": "/",
        })
        self.assertEqual(calls[0]["type"], "function")
        self.assertTrue(calls[0]["id"].startswith("call_"))

    def test_parses_fenced_json(self) -> None:
        text = 'Sure:\n```json\n{"tool_calls": [{"name": "ls"}]}\n```'
        self.assertEqual(parse_tool_calls(text)[0]["function"]["name"], "ls")

    def test_parses_openai_shaped_function_key(self) -> None:
        text = json.dumps(
            {"tool_calls": [{"function": {"name": "ls", "arguments": "{}"}}]}
        )
        calls = parse_tool_calls(text)
        self.assertEqual(calls[0]["function"]["name"], "ls")
        self.assertEqual(calls[0]["function"]["arguments"], "{}")

    def test_accepts_single_object_without_list(self) -> None:
        text = json.dumps({"tool_calls": {"name": "ls"}})
        self.assertEqual(len(parse_tool_calls(text)), 1)

    def test_plain_text_yields_no_calls(self) -> None:
        self.assertEqual(parse_tool_calls("just an answer"), [])
        self.assertEqual(parse_tool_calls(""), [])

    def test_json_without_tool_calls_is_ignored(self) -> None:
        self.assertEqual(parse_tool_calls('{"answer": "hi"}'), [])

    def test_unnamed_call_is_dropped(self) -> None:
        text = json.dumps({"tool_calls": [{"arguments": {}}]})
        self.assertEqual(parse_tool_calls(text), [])

    def test_braces_inside_prose_still_parse(self) -> None:
        text = 'steps {a, b} then {"tool_calls": [{"name": "ls"}]}'
        self.assertEqual(parse_tool_calls(text)[0]["function"]["name"], "ls")


class TestResponseShapes(unittest.TestCase):
    def test_plain_completion(self) -> None:
        payload = completion_payload("gemini-3-flash", "hi", None, 40)
        choice = payload["choices"][0]
        self.assertEqual(payload["object"], "chat.completion")
        self.assertEqual(choice["message"]["content"], "hi")
        self.assertEqual(choice["finish_reason"], "stop")
        self.assertNotIn("tool_calls", choice["message"])
        self.assertEqual(payload["usage"]["prompt_tokens"], 10)

    def test_tool_completion_sets_finish_reason(self) -> None:
        calls = [{"id": "c1", "type": "function",
                  "function": {"name": "ls", "arguments": "{}"}}]
        payload = completion_payload("m", "", calls, 0)
        choice = payload["choices"][0]
        self.assertEqual(choice["finish_reason"], "tool_calls")
        self.assertEqual(choice["message"]["tool_calls"], calls)

    def test_stream_chunk_shape(self) -> None:
        chunk = stream_chunk("id1", "m", 7, {"content": "a"})
        self.assertEqual(chunk["object"], "chat.completion.chunk")
        self.assertEqual(chunk["choices"][0]["delta"], {"content": "a"})
        self.assertIsNone(chunk["choices"][0]["finish_reason"])


class TestErrorStatus(unittest.TestCase):
    def test_unknown_exception_is_bad_gateway(self) -> None:
        self.assertEqual(error_status(ValueError("x")), 502)


if __name__ == "__main__":
    unittest.main()
