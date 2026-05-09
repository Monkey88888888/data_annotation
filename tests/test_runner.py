"""Runner tests with a fake Supabase client and a fake Anthropic client.
No live API or DB required."""

from __future__ import annotations

import unittest
from pathlib import Path
from typing import Any

from data_annotation.annotator import annotator_registry
from data_annotation.annotator.base import hash_payload
from data_annotation.annotator.image import (
    ANNOTATOR_VERSION as IMAGE_ANNOTATOR_VERSION,
)
from data_annotation.annotator.text import (
    ANNOTATOR_VERSION as TEXT_ANNOTATOR_VERSION,
)
from data_annotation.runner import process_row, run_batch


# ---------------------------------------------------------------------------
# Fakes
# ---------------------------------------------------------------------------

class FakeSupabaseClient:
    """In-memory stand-in for SupabaseClient. Records calls so tests can
    assert on order + arguments."""

    def __init__(self, rows: list[dict[str, Any]] | None = None,
                 cached_annotations: dict[tuple[str, str], dict[str, Any]] | None = None):
        self.rows = list(rows or [])
        self.cached = dict(cached_annotations or {})
        self.upserts: list[dict[str, Any]] = []
        self.merges: list[tuple[str, dict[str, Any]]] = []
        self.marked_processed: list[str] = []

    def fetch_unprocessed(self, limit: int = 50) -> list[dict[str, Any]]:
        return [row for row in self.rows if not row.get("is_processed")][:limit]

    def fetch_annotation(self, asset_hash: str, annotator_version: str):
        return self.cached.get((asset_hash, annotator_version))

    def upsert_annotation(self, row: dict[str, Any]) -> dict[str, Any]:
        self.upserts.append(row)
        # Mirror the upsert into the cache so subsequent rows in the same
        # batch with the same payload are cache hits.
        self.cached[(row["asset_hash"], row["annotator_version"])] = row
        return row

    def merge_annotation_into_document(self, document_id: str,
                                       facets: dict[str, Any]) -> dict[str, Any]:
        self.merges.append((document_id, facets))
        for row in self.rows:
            if row["id"] == document_id:
                row.update(facets)
                return row
        raise KeyError(document_id)

    def mark_processed(self, row_id: str) -> dict[str, Any]:
        self.marked_processed.append(row_id)
        for row in self.rows:
            if row["id"] == row_id:
                row["is_processed"] = True
                return row
        raise KeyError(row_id)


class StubAnthropicClient:
    """Returns a canned tool_use payload, so the registered annotators
    never reach the real network."""

    def __init__(self, response: dict[str, Any]):
        self.response = response
        self.calls: list[dict[str, Any]] = []

    def call_with_tool(self, **kwargs):
        self.calls.append(kwargs)
        return dict(self.response)


def _patch_text_default_client(stub: StubAnthropicClient):
    """The registered text annotator builds its own AnthropicLLMClient
    when ``client`` is omitted. Patch the import so it grabs our stub."""
    import data_annotation.annotator.text as text_mod
    original = text_mod.AnthropicLLMClient
    text_mod.AnthropicLLMClient = lambda: stub  # type: ignore
    return lambda: setattr(text_mod, "AnthropicLLMClient", original)


def _patch_image_default_client(stub: StubAnthropicClient):
    import data_annotation.annotator.image as image_mod
    original = image_mod.AnthropicLLMClient
    image_mod.AnthropicLLMClient = lambda: stub  # type: ignore
    return lambda: setattr(image_mod, "AnthropicLLMClient", original)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

TEXT_FACETS_OK = {
    "type_text": True,
    "modality_b2b_email": True,
    "modality_landing_page": False,
    "strict_regulatory": 0.1,
    "strict_technicality": 0.5,
    "tone_formality": 0.6,
    "tone_aggressiveness": 0.4,
    "tone_creativity": 0.3,
}

IMAGE_FACETS_OK = {
    "type_image": True,
    "modality_b2b_email": False,
    "modality_landing_page": True,
    "strict_regulatory": 0.0,
    "strict_technicality": 0.2,
    "tone_formality": 0.3,
    "tone_aggressiveness": 0.6,
    "tone_creativity": 0.9,
}


def make_text_row(rid: str = "doc-1", payload: str = "hello buyer") -> dict[str, Any]:
    return {
        "id": rid,
        "archetype_id": "text_document",
        "content_payload": payload,
        "is_processed": False,
    }


def make_image_row(rid: str, payload_path: str) -> dict[str, Any]:
    return {
        "id": rid,
        "archetype_id": "image_asset",
        "content_payload": payload_path,
        "is_processed": False,
    }


# ---------------------------------------------------------------------------
# Routing / skip cases
# ---------------------------------------------------------------------------

class RoutingTests(unittest.TestCase):
    def test_empty_queue_does_nothing(self) -> None:
        client = FakeSupabaseClient()
        outcomes = run_batch(client)
        self.assertEqual(outcomes, [])
        self.assertEqual(client.marked_processed, [])

    def test_row_without_archetype_id_is_skipped(self) -> None:
        row = {"id": "x", "content_payload": "hi", "is_processed": False}
        outcomes = run_batch(FakeSupabaseClient([row]))
        self.assertEqual(outcomes[0].status, "skipped")
        self.assertIn("no archetype_id", outcomes[0].detail or "")

    def test_fmri_archetype_is_skipped(self) -> None:
        row = {"id": "f", "archetype_id": "fmri_scan", "is_processed": False}
        outcomes = run_batch(FakeSupabaseClient([row]))
        self.assertEqual(outcomes[0].status, "skipped")
        self.assertEqual(outcomes[0].archetype_id, "fmri_scan")

    def test_unknown_archetype_is_skipped(self) -> None:
        row = {"id": "u", "archetype_id": "made_up", "is_processed": False}
        outcomes = run_batch(FakeSupabaseClient([row]))
        self.assertEqual(outcomes[0].status, "skipped")


# ---------------------------------------------------------------------------
# Text path
# ---------------------------------------------------------------------------

class TextRowTests(unittest.TestCase):
    def setUp(self) -> None:
        self.stub = StubAnthropicClient(TEXT_FACETS_OK)
        self.unpatch = _patch_text_default_client(self.stub)

    def tearDown(self) -> None:
        self.unpatch()

    def test_text_row_annotates_caches_merges_marks(self) -> None:
        row = make_text_row("doc-1", "Quick demo of our outbound sequence.")
        client = FakeSupabaseClient([row])

        outcomes = run_batch(client)

        self.assertEqual(len(outcomes), 1)
        self.assertEqual(outcomes[0].status, "annotated")
        # one upsert into annotations
        self.assertEqual(len(client.upserts), 1)
        upsert = client.upserts[0]
        self.assertEqual(upsert["asset_hash"], hash_payload("Quick demo of our outbound sequence."))
        self.assertEqual(upsert["annotator_version"], TEXT_ANNOTATOR_VERSION)
        self.assertEqual(upsert["document_id"], "doc-1")
        # merge happened with the same facets
        self.assertEqual(client.merges[0], ("doc-1", TEXT_FACETS_OK))
        # row marked processed
        self.assertEqual(client.marked_processed, ["doc-1"])
        # one LLM call
        self.assertEqual(len(self.stub.calls), 1)

    def test_cache_hit_does_not_call_llm(self) -> None:
        payload = "hello world"
        cache_key = (hash_payload(payload), TEXT_ANNOTATOR_VERSION)
        cached = {"asset_hash": cache_key[0], "annotator_version": cache_key[1],
                  "facets": TEXT_FACETS_OK}
        client = FakeSupabaseClient([make_text_row("doc-2", payload)],
                                    cached_annotations={cache_key: cached})

        outcomes = run_batch(client)

        self.assertEqual(outcomes[0].status, "cache_hit")
        self.assertEqual(self.stub.calls, [])
        # No re-upsert when cache hits.
        self.assertEqual(client.upserts, [])
        # Still merges + flips processed.
        self.assertEqual(client.merges[0], ("doc-2", TEXT_FACETS_OK))
        self.assertEqual(client.marked_processed, ["doc-2"])

    def test_dry_run_skips_writes(self) -> None:
        client = FakeSupabaseClient([make_text_row()])
        run_batch(client, dry_run=True)
        # LLM still called (so the operator sees what would happen)
        self.assertEqual(len(self.stub.calls), 1)
        # No DB writes
        self.assertEqual(client.upserts, [])
        self.assertEqual(client.merges, [])
        self.assertEqual(client.marked_processed, [])


# ---------------------------------------------------------------------------
# Image path
# ---------------------------------------------------------------------------

class ImageRowTests(unittest.TestCase):
    def setUp(self) -> None:
        self.stub = StubAnthropicClient(IMAGE_FACETS_OK)
        self.unpatch = _patch_image_default_client(self.stub)

    def tearDown(self) -> None:
        self.unpatch()

    def test_image_row_reads_bytes_and_annotates(self) -> None:
        # Write a fake PNG so _media_type_for accepts the suffix and the
        # bytes can be hashed. Annotator never actually parses them
        # because StubAnthropicClient short-circuits the network call.
        from tempfile import TemporaryDirectory
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "ad.png"
            path.write_bytes(b"\x89PNG\r\n\x1a\nfake-image-bytes")
            client = FakeSupabaseClient([make_image_row("img-1", str(path))])

            outcomes = run_batch(client)

        self.assertEqual(outcomes[0].status, "annotated")
        upsert = client.upserts[0]
        self.assertEqual(upsert["annotator_version"], IMAGE_ANNOTATOR_VERSION)
        self.assertEqual(upsert["asset_hash"], hash_payload(b"\x89PNG\r\n\x1a\nfake-image-bytes"))
        self.assertEqual(client.merges[0][1], IMAGE_FACETS_OK)
        self.assertEqual(client.marked_processed, ["img-1"])

    def test_image_row_with_missing_file_errors_without_marking(self) -> None:
        client = FakeSupabaseClient([make_image_row("img-2", "/nope/missing.png")])
        outcomes = run_batch(client)
        self.assertEqual(outcomes[0].status, "error")
        self.assertEqual(client.upserts, [])
        self.assertEqual(client.marked_processed, [])


# ---------------------------------------------------------------------------
# Sanity: registry is what runner expects
# ---------------------------------------------------------------------------

class RegistryWiringTests(unittest.TestCase):
    def test_text_and_image_both_registered(self) -> None:
        self.assertIn("text_document", annotator_registry)
        self.assertIn("image_asset", annotator_registry)


if __name__ == "__main__":
    unittest.main()
