#!/usr/bin/env python3
"""Tests for cursor_effort_proxy.py.

Run with:  python3 -m unittest discover -s llm-proxy -v
"""

from __future__ import annotations

import json
import re
import unittest

from cursor_effort_proxy import Rule, transform


def rule(pattern: str, value: str, param: str = "reasoning_effort", force: bool = False) -> Rule:
    return Rule(match=re.compile(pattern), param=param, value=value, force=force)


def body(model: str, **extra) -> bytes:
    return json.dumps({"model": model, "messages": [], **extra}).encode()


class TestTransform(unittest.TestCase):
    def test_injects_for_matching_model(self) -> None:
        out, note = transform(body("vendor/model-a"), [rule("model-a", "high")])
        self.assertEqual(json.loads(out)["reasoning_effort"], "high")
        self.assertIn("injected", note)

    def test_no_injection_for_non_matching_model(self) -> None:
        payload = body("gpt-5.4")
        out, note = transform(payload, [rule("model-a", "high")])
        self.assertEqual(out, payload)
        self.assertIsNone(note)

    def test_preserves_existing_value(self) -> None:
        payload = body("vendor/model-a", reasoning_effort="low")
        out, note = transform(payload, [rule("model-a", "high")])
        self.assertEqual(json.loads(out)["reasoning_effort"], "low")
        self.assertIn("left alone", note)

    def test_force_overrides_existing_value(self) -> None:
        payload = body("vendor/model-a", reasoning_effort="low")
        out, _ = transform(payload, [rule("model-a", "high", force=True)])
        self.assertEqual(json.loads(out)["reasoning_effort"], "high")

    def test_first_matching_rule_wins(self) -> None:
        rules = [rule("model-a", "high"), rule(".*", "low")]
        out, _ = transform(body("vendor/model-a"), rules)
        self.assertEqual(json.loads(out)["reasoning_effort"], "high")

    def test_fallback_rule_catches_others(self) -> None:
        rules = [rule("model-a", "high"), rule(".*", "medium")]
        out, _ = transform(body("vendor/model-b"), rules)
        self.assertEqual(json.loads(out)["reasoning_effort"], "medium")

    def test_dotted_param_creates_nested_object(self) -> None:
        out, _ = transform(
            body("claude-opus-5-5"),
            [rule("claude-opus", "xhigh", param="output_config.effort")],
        )
        self.assertEqual(json.loads(out)["output_config"]["effort"], "xhigh")

    def test_dotted_param_preserved_when_present(self) -> None:
        payload = body("claude-opus-5-5", output_config={"effort": "low"})
        out, _ = transform(payload, [rule("claude-opus", "max", param="output_config.effort")])
        self.assertEqual(json.loads(out)["output_config"]["effort"], "low")

    def test_dotted_param_merges_into_existing_object(self) -> None:
        payload = body("claude-opus-5-5", output_config={"other": 1})
        out, _ = transform(payload, [rule("claude-opus", "high", param="output_config.effort")])
        cfg = json.loads(out)["output_config"]
        self.assertEqual(cfg["effort"], "high")
        self.assertEqual(cfg["other"], 1)

    def test_empty_body_passthrough(self) -> None:
        out, note = transform(b"", [rule(".*", "high")])
        self.assertEqual(out, b"")
        self.assertIsNone(note)

    def test_invalid_json_passthrough(self) -> None:
        out, note = transform(b"{not json", [rule(".*", "high")])
        self.assertEqual(out, b"{not json")
        self.assertIsNone(note)

    def test_non_object_json_passthrough(self) -> None:
        payload = b'["a"]'
        out, note = transform(payload, [rule(".*", "high")])
        self.assertEqual(out, payload)
        self.assertIsNone(note)

    def test_missing_model_passthrough(self) -> None:
        payload = json.dumps({"messages": []}).encode()
        out, note = transform(payload, [rule(".*", "high")])
        self.assertEqual(out, payload)
        self.assertIsNone(note)

    def test_preserves_unrelated_fields(self) -> None:
        payload = body("vendor/model-a", temperature=0.2, max_tokens=64)
        out, _ = transform(payload, [rule("model-a", "high")])
        data = json.loads(out)
        self.assertEqual(data["temperature"], 0.2)
        self.assertEqual(data["max_tokens"], 64)
        self.assertEqual(data["messages"], [])


if __name__ == "__main__":
    unittest.main()
