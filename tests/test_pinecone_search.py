"""pinecone_search tests with a fake Pinecone index + fake fetcher.
No network required."""

from __future__ import annotations

import unittest
from typing import Any

from data_annotation.pinecone_search import (
    DEFAULT_MANIFOLD_DIMENSION,
    SearchMatch,
    build_query_vector,
    search,
)


# ---------------------------------------------------------------------------
# Fakes
# ---------------------------------------------------------------------------

class _FakeMatch:
    def __init__(self, mid: str, score: float, metadata: dict[str, Any] | None = None):
        self.id = mid
        self.score = score
        self.metadata = metadata or {}


class _FakeQueryResponse:
    def __init__(self, matches: list[_FakeMatch]):
        self.matches = matches


class FakePineconeIndex:
    def __init__(self, matches: list[_FakeMatch]):
        self.matches = matches
        self.calls: list[dict[str, Any]] = []

    def query(self, **kwargs) -> _FakeQueryResponse:
        self.calls.append(kwargs)
        return _FakeQueryResponse(self.matches)


class FakeFetcher:
    def __init__(self, rows: dict[str, dict[str, Any]]):
        self.rows = rows
        self.calls: list[list[str]] = []

    def fetch_by_ids(self, ids: list[str]) -> dict[str, dict[str, Any]]:
        self.calls.append(list(ids))
        return {k: v for k, v in self.rows.items() if k in ids}


# ---------------------------------------------------------------------------
# build_query_vector
# ---------------------------------------------------------------------------

class BuildQueryVectorTests(unittest.TestCase):
    def test_dimension_matches_requested(self) -> None:
        v = build_query_vector("hello", {"authority": 1.0}, manifold_dimension=256)
        self.assertEqual(len(v), 256)

    def test_deterministic_for_same_inputs(self) -> None:
        weights = {"authority": 1.0, "type": 1.0, "modality": 1.0,
                   "strictness": 1.0, "tone": 0.2}
        a = build_query_vector("seek", weights)
        b = build_query_vector("seek", weights)
        self.assertEqual(a, b)

    def test_different_prompts_yield_different_vectors(self) -> None:
        weights = {f: 1.0 for f in ("authority", "type", "modality",
                                     "strictness", "tone")}
        a = build_query_vector("alpha", weights)
        b = build_query_vector("beta", weights)
        self.assertNotEqual(a, b)

    def test_zero_weight_zeros_facet_segment(self) -> None:
        # If a facet weight is 0 the corresponding sector contribution is 0.
        weights = {"authority": 0.0, "type": 1.0, "modality": 1.0,
                   "strictness": 1.0, "tone": 1.0}
        v = build_query_vector("anything", weights, manifold_dimension=256)
        # Authority is the first sector. With 256D and 5 facets the first sector
        # is 52 long (256/5=51, remainder 1 spills into the first).
        first_segment = v[:52]
        self.assertTrue(all(value == 0.0 for value in first_segment),
                        "zero authority weight should zero the authority segment")


# ---------------------------------------------------------------------------
# search
# ---------------------------------------------------------------------------

class SearchTests(unittest.TestCase):
    def test_returns_matches_with_document_ids(self) -> None:
        pc = FakePineconeIndex([
            _FakeMatch("doc-a", 0.91, {"archetype_id": "text_document"}),
            _FakeMatch("doc-b", 0.83, {"archetype_id": "text_document"}),
        ])
        results = search("buying intent", top_k=2, pinecone_index=pc)
        self.assertEqual([m.document_id for m in results], ["doc-a", "doc-b"])
        self.assertAlmostEqual(results[0].score, 0.91)
        self.assertEqual(results[0].metadata["archetype_id"], "text_document")

    def test_query_vector_passed_to_pinecone_has_manifold_dimension(self) -> None:
        pc = FakePineconeIndex([])
        search("anything", top_k=3, pinecone_index=pc, manifold_dimension=256)
        self.assertEqual(len(pc.calls[0]["vector"]), 256)
        self.assertEqual(pc.calls[0]["top_k"], 3)
        self.assertTrue(pc.calls[0]["include_metadata"])
        self.assertNotIn("filter", pc.calls[0])

    def test_archetype_filter_passes_through(self) -> None:
        pc = FakePineconeIndex([])
        search("anything", pinecone_index=pc, archetype_filter="image_asset")
        self.assertEqual(pc.calls[0]["filter"], {"archetype_id": "image_asset"})

    def test_enrich_false_skips_fetcher(self) -> None:
        pc = FakePineconeIndex([_FakeMatch("doc-x", 0.5)])
        fetcher = FakeFetcher({"doc-x": {"id": "doc-x", "source_name": "X"}})
        results = search("q", pinecone_index=pc, document_fetcher=fetcher, enrich=False)
        self.assertEqual(fetcher.calls, [])
        self.assertIsNone(results[0].document)

    def test_enrich_true_fetches_and_attaches_documents(self) -> None:
        pc = FakePineconeIndex([
            _FakeMatch("doc-x", 0.7),
            _FakeMatch("doc-y", 0.6),
        ])
        fetcher = FakeFetcher({
            "doc-x": {"id": "doc-x", "source_name": "X email"},
            "doc-y": {"id": "doc-y", "source_name": "Y page"},
        })
        results = search("q", pinecone_index=pc, document_fetcher=fetcher, enrich=True)
        self.assertEqual(fetcher.calls, [["doc-x", "doc-y"]])
        self.assertEqual(results[0].document["source_name"], "X email")
        self.assertEqual(results[1].document["source_name"], "Y page")

    def test_enrich_with_no_matches_skips_fetch(self) -> None:
        pc = FakePineconeIndex([])
        fetcher = FakeFetcher({})
        results = search("q", pinecone_index=pc, document_fetcher=fetcher, enrich=True)
        self.assertEqual(results, [])
        self.assertEqual(fetcher.calls, [])

    def test_handles_pinecone_dict_response_shape(self) -> None:
        # Some Pinecone client paths return dicts instead of objects.
        class _DictResponseIndex:
            def query(self, **kwargs):
                return {"matches": [{"id": "doc-d", "score": 0.42, "metadata": {"archetype_id": "text_document"}}]}

        results = search("q", pinecone_index=_DictResponseIndex())
        self.assertEqual(results[0].document_id, "doc-d")
        self.assertAlmostEqual(results[0].score, 0.42)
        self.assertEqual(results[0].metadata["archetype_id"], "text_document")


if __name__ == "__main__":
    unittest.main()
