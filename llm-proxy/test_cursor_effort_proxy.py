#!/usr/bin/env python3
"""Tests for cursor_effort_proxy.py.

Run with:  python3 -m unittest discover -s llm-proxy -v
"""

from __future__ import annotations

import json
import re
import unittest

from cursor_effort_proxy import Rule, transform


def rule(pattern: str, value: str, param: str = "reasoning_effort",
         force: bool = False, model: str = "", default: bool = False) -> Rule:
    return Rule(match=re.compile(pattern), param=param, value=value,
                force=force, model=model, default=default)


def body(model: str, **extra) -> bytes:
    return json.dumps({"model": model, "messages": [], **extra}).encode()


class TestTransform(unittest.TestCase):
    def test_injects_for_matching_model(self) -> None:
        out, note, headers = transform(body("vendor/model-a"), [rule("model-a", "high")])
        self.assertEqual(json.loads(out)["reasoning_effort"], "high")
        self.assertIn("injected", note)
        self.assertEqual(headers, {})

    def test_no_injection_for_non_matching_model(self) -> None:
        payload = body("gpt-5.4")
        out, note, headers = transform(payload, [rule("model-a", "high")])
        self.assertEqual(out, payload)
        self.assertIsNone(note)
        self.assertEqual(headers, {})

    def test_preserves_existing_value(self) -> None:
        payload = body("vendor/model-a", reasoning_effort="low")
        out, note, _ = transform(payload, [rule("model-a", "high")])
        self.assertEqual(json.loads(out)["reasoning_effort"], "low")
        self.assertIn("left alone", note)

    def test_force_overrides_existing_value(self) -> None:
        payload = body("vendor/model-a", reasoning_effort="low")
        out, _, _ = transform(payload, [rule("model-a", "high", force=True)])
        self.assertEqual(json.loads(out)["reasoning_effort"], "high")

    def test_first_matching_rule_wins(self) -> None:
        rules = [rule("model-a", "high"), rule(".*", "low")]
        out, _, _ = transform(body("vendor/model-a"), rules)
        self.assertEqual(json.loads(out)["reasoning_effort"], "high")

    def test_fallback_rule_catches_others(self) -> None:
        rules = [rule("model-a", "high"), rule(".*", "medium")]
        out, _, _ = transform(body("vendor/model-b"), rules)
        self.assertEqual(json.loads(out)["reasoning_effort"], "medium")

    def test_dotted_param_creates_nested_object(self) -> None:
        out, _, _ = transform(
            body("claude-opus-5-5"),
            [rule("claude-opus", "xhigh", param="output_config.effort")],
        )
        self.assertEqual(json.loads(out)["output_config"]["effort"], "xhigh")

    def test_dotted_param_preserved_when_present(self) -> None:
        payload = body("claude-opus-5-5", output_config={"effort": "low"})
        out, _, _ = transform(payload, [rule("claude-opus", "max", param="output_config.effort")])
        self.assertEqual(json.loads(out)["output_config"]["effort"], "low")

    def test_dotted_param_merges_into_existing_object(self) -> None:
        payload = body("claude-opus-5-5", output_config={"other": 1})
        out, _, _ = transform(payload, [rule("claude-opus", "high", param="output_config.effort")])
        cfg = json.loads(out)["output_config"]
        self.assertEqual(cfg["effort"], "high")
        self.assertEqual(cfg["other"], 1)

    def test_empty_body_passthrough(self) -> None:
        out, note, headers = transform(b"", [rule(".*", "high")])
        self.assertEqual(out, b"")
        self.assertIsNone(note)
        self.assertEqual(headers, {})

    def test_invalid_json_passthrough(self) -> None:
        out, note, headers = transform(b"{not json", [rule(".*", "high")])
        self.assertEqual(out, b"{not json")
        self.assertIsNone(note)
        self.assertEqual(headers, {})

    def test_non_object_json_passthrough(self) -> None:
        payload = b'["a"]'
        out, note, headers = transform(payload, [rule(".*", "high")])
        self.assertEqual(out, payload)
        self.assertIsNone(note)
        self.assertEqual(headers, {})

    def test_missing_model_passthrough(self) -> None:
        payload = json.dumps({"messages": []}).encode()
        out, note, headers = transform(payload, [rule(".*", "high")])
        self.assertEqual(out, payload)
        self.assertIsNone(note)
        self.assertEqual(headers, {})

    def test_preserves_unrelated_fields(self) -> None:
        payload = body("vendor/model-a", temperature=0.2, max_tokens=64)
        out, _, _ = transform(payload, [rule("model-a", "high")])
        data = json.loads(out)
        self.assertEqual(data["temperature"], 0.2)
        self.assertEqual(data["max_tokens"], 64)
        self.assertEqual(data["messages"], [])


class TestDefaultModelRouting(unittest.TestCase):
    def setUp(self):
        # A default rule whose model is its literal match pattern.
        self.default_rule = rule("vendor/model-b", "high", default=True)

    def test_unmatched_model_routed_to_default(self) -> None:
        rules = [rule("model-a", "high"), self.default_rule]
        out, note, headers = transform(body("gpt-5.4"), rules,
                                       default_model="vendor/model-b")
        self.assertEqual(json.loads(out)["model"], "vendor/model-b")
        self.assertIn("default model", note)
        self.assertEqual(headers["x-cursor-model"], "vendor/model-b")

    def test_matched_model_not_routed_to_default(self) -> None:
        rules = [rule("model-a", "high"), self.default_rule]
        out, note, headers = transform(body("vendor/model-a"), rules,
                                       default_model="vendor/model-b")
        self.assertEqual(json.loads(out)["model"], "vendor/model-a")
        self.assertNotIn("default model", note)
        self.assertEqual(headers, {})

    def test_fallback_rule_is_not_default(self) -> None:
        # A catch-all rule without default=true injects its param but does
        # not rewrite the model.
        rules = [rule("model-a", "high"), rule(".*", "medium")]
        out, note, headers = transform(body("gpt-5.4"), rules)
        data = json.loads(out)
        self.assertEqual(data["model"], "gpt-5.4")
        self.assertEqual(data["reasoning_effort"], "medium")
        self.assertEqual(headers, {})

    def test_default_from_explicit_model_key(self) -> None:
        default = rule("fallback", "medium", model="vendor/model-b",
                       default=True)
        out, note, headers = transform(body("gpt-5.4"), [default],
                                       default_model="vendor/model-b")
        self.assertEqual(json.loads(out)["model"], "vendor/model-b")
        self.assertEqual(headers["x-cursor-model"], "vendor/model-b")

    def test_matched_rule_rewrites_model(self) -> None:
        out, note, headers = transform(
            body("alias-name"),
            [rule("alias", "high", model="vendor/model-b")],
        )
        self.assertEqual(json.loads(out)["model"], "vendor/model-b")
        self.assertIn("model alias-name -> vendor/model-b", note)
        self.assertEqual(headers["x-cursor-model"], "vendor/model-b")

    def test_matched_rule_model_rewrite_no_op_when_same(self) -> None:
        payload = body("vendor/model-b")
        out, note, headers = transform(
            payload, [rule("model-b", "medium", model="vendor/model-b")]
        )
        data = json.loads(out)
        self.assertEqual(data["model"], "vendor/model-b")
        self.assertIn("injected", note)
        self.assertNotIn("->", note)
        self.assertEqual(headers, {})

    def test_matched_rule_rewrites_model_and_injects(self) -> None:
        out, _, headers = transform(
            body("alias-name"),
            [rule("alias", "high", model="vendor/model-a")],
        )
        data = json.loads(out)
        self.assertEqual(data["model"], "vendor/model-a")
        self.assertEqual(data["reasoning_effort"], "high")
        self.assertEqual(headers["x-cursor-model"], "vendor/model-a")

    def test_missing_model_routed_to_default(self) -> None:
        payload = json.dumps({"messages": []}).encode()
        out, note, headers = transform(payload, [self.default_rule],
                                       default_model="vendor/model-b")
        self.assertEqual(json.loads(out)["model"], "vendor/model-b")
        self.assertIn("default model", note)
        self.assertEqual(headers["x-cursor-model"], "vendor/model-b")

    def test_no_default_model_passthrough(self) -> None:
        payload = body("gpt-5.4")
        out, note, headers = transform(payload, [rule("model-a", "high")])
        self.assertEqual(out, payload)
        self.assertIsNone(note)
        self.assertEqual(headers, {})

    def test_missing_model_no_default_passthrough(self) -> None:
        payload = json.dumps({"messages": []}).encode()
        out, note, headers = transform(payload, [rule(".*", "high")])
        self.assertEqual(out, payload)
        self.assertIsNone(note)
        self.assertEqual(headers, {})

    def test_default_model_applied_without_effort_injection(self) -> None:
        # No-model request routed to the default gets no effort param: the
        # default's rule params apply only to requests it matches.
        payload = json.dumps({"messages": []}).encode()
        out, _, _ = transform(payload, [self.default_rule],
                              default_model="vendor/model-b")
        self.assertNotIn("reasoning_effort", json.loads(out))


class TestResolvedModel(unittest.TestCase):
    def test_resolved_model_from_match_pattern(self) -> None:
        r = rule("vendor/model-b", "high", default=True)
        self.assertEqual(r.resolved_model(), "vendor/model-b")

    def test_resolved_model_from_model_key(self) -> None:
        r = rule("fallback", "medium", model="vendor/model-b", default=True)
        self.assertEqual(r.resolved_model(), "vendor/model-b")

    def test_resolved_model_empty_for_non_default_rule(self) -> None:
        r = rule(".*", "medium")
        self.assertEqual(r.resolved_model(), "")

    def test_resolved_model_prefers_model_key(self) -> None:
        r = rule("alias", "high", model="vendor/model-a", default=True)
        self.assertEqual(r.resolved_model(), "vendor/model-a")


if __name__ == "__main__":
    unittest.main()
