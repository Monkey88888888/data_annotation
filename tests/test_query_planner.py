"""Query planner tests with a stubbed Anthropic client."""

from __future__ import annotations

import unittest
from typing import Any

from data_annotation.query_planner import FACET_NAMES, plan_query


class _StubClient:
    def __init__(self, response: dict[str, Any]):
        self.response = response
        self.calls: list[dict[str, Any]] = []

    def call_with_tool(self, **kwargs: Any) -> dict[str, Any]:
        self.calls.append(kwargs)
        return dict(self.response)


class PlanQueryTests(unittest.TestCase):
    def test_returns_full_facet_weights(self) -> None:
        stub = _StubClient({
            "authority": 0.9,
            "type": 0.4,
            "modality": 0.6,
            "strictness": 0.85,
            "tone": 0.3,
        })
        weights = plan_query("compliance proof from Big Four", client=stub)

        self.assertEqual(set(weights.keys()), set(FACET_NAMES))
        self.assertAlmostEqual(weights["authority"], 0.9)
        self.assertAlmostEqual(weights["strictness"], 0.85)
        # Single LLM call per query.
        self.assertEqual(len(stub.calls), 1)
        # Tool was named correctly so the model is forced into structured output.
        self.assertEqual(stub.calls[0]["tool"]["name"], "facet_weights")

    def test_tool_schema_clamps_each_facet_between_zero_and_one(self) -> None:
        stub = _StubClient({f: 0.5 for f in FACET_NAMES})
        plan_query("anything", client=stub)
        properties = stub.calls[0]["tool"]["input_schema"]["properties"]
        for facet in FACET_NAMES:
            self.assertEqual(properties[facet]["type"], "number")
            self.assertEqual(properties[facet]["minimum"], 0.0)
            self.assertEqual(properties[facet]["maximum"], 1.0)


if __name__ == "__main__":
    unittest.main()
