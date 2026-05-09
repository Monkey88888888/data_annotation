"""Generator tests with a stubbed text-generator."""

from __future__ import annotations

import unittest
from typing import Any

from data_annotation.generator import (
    generate_image_brief_from_context,
    generate_text_from_context,
)


class StubGenerator:
    def __init__(self, response: str = "GENERATED OUTPUT"):
        self.response = response
        self.calls: list[dict[str, Any]] = []

    def generate(self, *, system: str, user: str, model: str, max_tokens: int) -> str:
        self.calls.append({"system": system, "user": user, "model": model, "max_tokens": max_tokens})
        return self.response


class TextGenerationTests(unittest.TestCase):
    def test_returns_generator_output(self) -> None:
        stub = StubGenerator("Hello, Jordan! Quick demo this week?")
        out = generate_text_from_context(
            "B2B email about a 15-minute demo",
            [{"source_name": "demo-email", "content_payload": "Hi Jordan, our analytics..."}],
            generator=stub,
        )
        self.assertEqual(out, "Hello, Jordan! Quick demo this week?")
        self.assertEqual(len(stub.calls), 1)

    def test_user_message_includes_prompt_and_examples(self) -> None:
        stub = StubGenerator("ok")
        generate_text_from_context(
            "Q3 outbound about SOC2 compliance",
            [
                {"source_name": "soc2-email-1", "content_payload": "Lock in pricing now."},
                {"source_name": "soc2-email-2", "content_payload": "Compliance proof attached."},
            ],
            generator=stub,
        )
        sent = stub.calls[0]["user"]
        self.assertIn("Q3 outbound about SOC2 compliance", sent)
        self.assertIn("soc2-email-1", sent)
        self.assertIn("soc2-email-2", sent)
        self.assertIn("Lock in pricing now.", sent)

    def test_truncates_long_examples(self) -> None:
        long_payload = "x" * 5000
        stub = StubGenerator("ok")
        generate_text_from_context(
            "anything",
            [{"source_name": "huge", "content_payload": long_payload}],
            generator=stub,
        )
        sent = stub.calls[0]["user"]
        # 1500-char per-example budget keeps the prompt size bounded.
        self.assertLess(sent.count("x"), 1600)

    def test_no_examples_still_calls_model(self) -> None:
        stub = StubGenerator("written-from-scratch")
        out = generate_text_from_context("write a haiku", [], generator=stub)
        self.assertEqual(out, "written-from-scratch")
        self.assertIn("(none)", stub.calls[0]["user"])


class ImageBriefTests(unittest.TestCase):
    def test_returns_brief(self) -> None:
        stub = StubGenerator("A bright hero image with bold typography...")
        out = generate_image_brief_from_context(
            "landing page hero for SOC2 compliance",
            [{"source_name": "ad-1", "tone_formality": 0.7, "tone_aggressiveness": 0.4}],
            generator=stub,
        )
        self.assertEqual(out, "A bright hero image with bold typography...")

    def test_user_message_includes_facet_annotations(self) -> None:
        stub = StubGenerator("ok")
        generate_image_brief_from_context(
            "trustworthy banner",
            [{"source_name": "trust-banner",
              "tone_formality": 0.8,
              "strict_regulatory": 0.6}],
            generator=stub,
        )
        sent = stub.calls[0]["user"]
        self.assertIn("trust-banner", sent)
        self.assertIn("tone_formality", sent)
        self.assertIn("0.8", sent)


if __name__ == "__main__":
    unittest.main()
