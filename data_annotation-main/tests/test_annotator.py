"""Annotator tests with a mocked LLM client. No live API key required."""

from __future__ import annotations

import unittest
from typing import Any

from data_annotation.annotator import annotator_registry
from data_annotation.annotator.base import (
    AnnotationResult,
    LLMClient,
    build_facet_tool_schema,
    hash_payload,
)
from data_annotation.annotator.image import IMAGE_FACETS, annotate_image
from data_annotation.annotator.text import TEXT_FACETS, annotate_text


class FakeLLMClient:
    """Records calls and returns a canned tool_use payload."""

    def __init__(self, response: dict[str, Any]):
        self.response = response
        self.calls: list[dict[str, Any]] = []

    def call_with_tool(
        self,
        *,
        model: str,
        system: str,
        tool: dict[str, Any],
        content: list[dict[str, Any]],
        max_tokens: int,
    ) -> dict[str, Any]:
        self.calls.append(
            {
                "model": model,
                "system": system,
                "tool": tool,
                "content": content,
                "max_tokens": max_tokens,
            }
        )
        return dict(self.response)


class HashingTests(unittest.TestCase):
    def test_text_hash_is_stable(self) -> None:
        h1 = hash_payload("hello world")
        h2 = hash_payload("hello world")
        self.assertEqual(h1, h2)
        self.assertEqual(len(h1), 64)

    def test_text_and_bytes_match_on_utf8(self) -> None:
        self.assertEqual(hash_payload("hi"), hash_payload(b"hi"))


class FacetToolSchemaTests(unittest.TestCase):
    def test_continuous_facet_gets_number_with_bounds(self) -> None:
        schema = build_facet_tool_schema("text_document", ("tone_formality",))
        prop = schema["input_schema"]["properties"]["tone_formality"]
        self.assertEqual(prop["type"], "number")
        self.assertEqual(prop["minimum"], 0.0)
        self.assertEqual(prop["maximum"], 1.0)

    def test_boolean_facet_gets_bool(self) -> None:
        schema = build_facet_tool_schema("text_document", ("type_text",))
        self.assertEqual(
            schema["input_schema"]["properties"]["type_text"]["type"],
            "boolean",
        )

    def test_unknown_facet_raises(self) -> None:
        with self.assertRaises(ValueError):
            build_facet_tool_schema("x", ("not_a_facet",))


class TextAnnotatorTests(unittest.TestCase):
    def _full_payload(self) -> dict[str, Any]:
        return {
            "type_text": True,
            "modality_b2b_email": True,
            "modality_landing_page": False,
            "strict_regulatory": 0.1,
            "strict_technicality": 0.6,
            "tone_formality": 0.7,
            "tone_aggressiveness": 0.8,
            "tone_creativity": 0.4,
        }

    def test_annotate_text_returns_facets_and_hash(self) -> None:
        client = FakeLLMClient(self._full_payload())
        result = annotate_text("Quick demo of our outbound sequence.", client=client)

        self.assertIsInstance(result, AnnotationResult)
        self.assertEqual(result.archetype_id, "text_document")
        self.assertEqual(result.annotator_kind, "text")
        self.assertEqual(result.facets, self._full_payload())
        self.assertEqual(
            result.asset_hash,
            hash_payload("Quick demo of our outbound sequence."),
        )

    def test_annotate_text_passes_payload_as_text_content(self) -> None:
        client = FakeLLMClient(self._full_payload())
        annotate_text("payload-X", client=client)
        call = client.calls[-1]
        self.assertEqual(call["content"][0]["type"], "text")
        self.assertEqual(call["content"][0]["text"], "payload-X")
        self.assertEqual(
            sorted(call["tool"]["input_schema"]["required"]),
            sorted(TEXT_FACETS),
        )


class ImageAnnotatorTests(unittest.TestCase):
    def _full_payload(self) -> dict[str, Any]:
        return {
            "type_image": True,
            "modality_b2b_email": False,
            "modality_landing_page": True,
            "strict_regulatory": 0.0,
            "strict_technicality": 0.2,
            "tone_formality": 0.3,
            "tone_aggressiveness": 0.6,
            "tone_creativity": 0.9,
        }

    def test_annotate_image_with_raw_bytes(self) -> None:
        client = FakeLLMClient(self._full_payload())
        result = annotate_image(b"\x89PNG\r\n\x1a\nfake", media_type="image/png", client=client)

        self.assertEqual(result.archetype_id, "image_asset")
        self.assertEqual(result.annotator_kind, "image")
        self.assertEqual(result.facets, self._full_payload())

    def test_annotate_image_sends_base64_image_block(self) -> None:
        client = FakeLLMClient(self._full_payload())
        annotate_image(b"abc", media_type="image/png", client=client)
        block = client.calls[-1]["content"][0]
        self.assertEqual(block["type"], "image")
        self.assertEqual(block["source"]["media_type"], "image/png")
        self.assertEqual(block["source"]["type"], "base64")

    def test_unsupported_media_type_raises_for_path(self) -> None:
        from pathlib import Path
        with self.assertRaises(ValueError):
            annotate_image(Path("not_real.bmp"), client=FakeLLMClient(self._full_payload()))

    def test_raw_bytes_without_media_type_raises(self) -> None:
        with self.assertRaises(ValueError):
            annotate_image(b"abc", client=FakeLLMClient(self._full_payload()))


class RegistryTests(unittest.TestCase):
    def test_text_and_image_archetypes_registered(self) -> None:
        self.assertIn("text_document", annotator_registry)
        self.assertIn("image_asset", annotator_registry)

    def test_to_db_row_has_expected_keys(self) -> None:
        client = FakeLLMClient(
            {
                "type_text": True,
                "modality_b2b_email": True,
                "modality_landing_page": False,
                "strict_regulatory": 0.0,
                "strict_technicality": 0.0,
                "tone_formality": 0.5,
                "tone_aggressiveness": 0.5,
                "tone_creativity": 0.5,
            }
        )
        result = annotate_text("hello", client=client)
        row = result.to_db_row(document_id="00000000-0000-0000-0000-000000000000")
        self.assertEqual(
            set(row.keys()),
            {
                "asset_hash",
                "annotator_version",
                "document_id",
                "archetype_id",
                "annotator_kind",
                "model",
                "facets",
                "raw_response",
            },
        )


if __name__ == "__main__":
    unittest.main()
