"""Indexer tests with mocked Supabase + Pinecone. No network calls."""

from __future__ import annotations

import unittest
from typing import Any

from data_annotation.indexer import (
    DEFAULT_MANIFOLD_DIMENSION,
    index_batch,
    index_row,
    row_to_asset,
)


# ---------------------------------------------------------------------------
# Fakes
# ---------------------------------------------------------------------------

class FakeIndexerClient:
    def __init__(self, rows: list[dict[str, Any]] | None = None):
        self.rows = list(rows or [])
        self.marked_indexed: list[str] = []

    def fetch_processed_unindexed(self, limit: int = 50) -> list[dict[str, Any]]:
        ready = [
            row for row in self.rows
            if row.get("is_processed") and not row.get("is_indexed")
        ]
        return ready[:limit]

    def mark_indexed(self, row_id: str) -> dict[str, Any]:
        self.marked_indexed.append(row_id)
        for row in self.rows:
            if str(row["id"]) == row_id:
                row["is_indexed"] = True
                return row
        raise KeyError(row_id)


class FakePineconeIndex:
    def __init__(self) -> None:
        self.upserts: list[dict[str, Any]] = []

    def upsert(self, vectors: list[dict[str, Any]]) -> None:
        self.upserts.extend(vectors)


def make_text_row(rid: str = "doc-1", **overrides: Any) -> dict[str, Any]:
    base = {
        "id": rid,
        "archetype_id": "text_document",
        "source_name": "smoke",
        "content_payload": "Q3 outbound — SOC2 audited.",
        "is_processed": True,
        "is_indexed": False,
        "auth_domain": 0.6,
        "auth_author": 0.4,
        "auth_institution": 0.5,
        "type_text": True,
        "type_image": False,
        "type_timeseries": False,
        "modality_b2b_email": True,
        "modality_landing_page": False,
        "modality_fmri_t1": False,
        "modality_fmri_bold": False,
        "strict_regulatory": 0.3,
        "strict_technicality": 0.5,
        "tone_formality": 0.7,
        "tone_aggressiveness": 0.6,
        "tone_creativity": 0.2,
    }
    base.update(overrides)
    return base


# ---------------------------------------------------------------------------
# row_to_asset
# ---------------------------------------------------------------------------

class RowToAssetTests(unittest.TestCase):
    def test_authority_magnitude_is_mean_of_auth_columns(self) -> None:
        from data_annotation.archetypes import Archetype, default_archetype_path
        archetype = Archetype.from_file(default_archetype_path("text_document"))
        asset = row_to_asset(make_text_row(), archetype)

        # Mean of 0.6, 0.4, 0.5 = 0.5
        self.assertAlmostEqual(
            asset["faceted_matrix"]["authority"]["magnitude"],
            0.5,
            places=6,
        )

    def test_facet_seeds_come_from_archetype_config(self) -> None:
        from data_annotation.archetypes import Archetype, default_archetype_path
        archetype = Archetype.from_file(default_archetype_path("text_document"))
        asset = row_to_asset(make_text_row(), archetype)

        # Authority seed is per-asset; other facets reuse archetype seeds.
        self.assertTrue(asset["faceted_matrix"]["authority"]["seed"].startswith("authority:"))
        for facet in archetype.facets:
            if facet.name == "authority_base":
                continue
            self.assertEqual(
                asset["faceted_matrix"][facet.name]["seed"],
                facet.seed,
            )


# ---------------------------------------------------------------------------
# Per-row dispatch
# ---------------------------------------------------------------------------

class IndexRowTests(unittest.TestCase):
    def test_text_row_pushes_to_pinecone_and_marks_indexed(self) -> None:
        client = FakeIndexerClient([make_text_row("doc-1")])
        pc = FakePineconeIndex()

        outcome = index_row(client.rows[0], client=client, pinecone_index=pc)

        self.assertEqual(outcome.status, "indexed")
        self.assertEqual(client.marked_indexed, ["doc-1"])
        self.assertEqual(len(pc.upserts), 1)
        upsert = pc.upserts[0]
        self.assertEqual(upsert["id"], "doc-1")
        self.assertEqual(len(upsert["values"]), DEFAULT_MANIFOLD_DIMENSION)
        self.assertEqual(upsert["metadata"]["archetype_id"], "text_document")
        self.assertTrue(upsert["metadata"]["is_text"])

    def test_dry_run_skips_pinecone_and_db(self) -> None:
        client = FakeIndexerClient([make_text_row("doc-2")])
        pc = FakePineconeIndex()
        outcome = index_row(
            client.rows[0],
            client=client,
            pinecone_index=pc,
            dry_run=True,
        )
        self.assertEqual(outcome.status, "indexed")
        self.assertEqual(pc.upserts, [])
        self.assertEqual(client.marked_indexed, [])

    def test_row_without_archetype_skipped(self) -> None:
        row = make_text_row("doc-3", archetype_id=None)
        outcome = index_row(row, client=FakeIndexerClient(), pinecone_index=FakePineconeIndex())
        self.assertEqual(outcome.status, "skipped")
        self.assertIn("no archetype_id", outcome.detail or "")

    def test_fmri_archetype_skipped(self) -> None:
        row = make_text_row("doc-4", archetype_id="fmri_scan")
        outcome = index_row(row, client=FakeIndexerClient(), pinecone_index=FakePineconeIndex())
        self.assertEqual(outcome.status, "skipped")

    def test_unknown_archetype_skipped_safely(self) -> None:
        row = make_text_row("doc-5", archetype_id="not_a_real_archetype")
        outcome = index_row(row, client=FakeIndexerClient(), pinecone_index=FakePineconeIndex())
        self.assertEqual(outcome.status, "skipped")
        self.assertIn("config not found", outcome.detail or "")


# ---------------------------------------------------------------------------
# Batch
# ---------------------------------------------------------------------------

class IndexBatchTests(unittest.TestCase):
    def test_only_processed_unindexed_rows_are_picked(self) -> None:
        rows = [
            make_text_row("ready", is_processed=True, is_indexed=False),
            make_text_row("already-indexed", is_processed=True, is_indexed=True),
            make_text_row("not-yet-processed", is_processed=False, is_indexed=False),
        ]
        client = FakeIndexerClient(rows)
        pc = FakePineconeIndex()
        outcomes = index_batch(client=client, pinecone_index=pc)
        ids = [o.document_id for o in outcomes]
        self.assertEqual(ids, ["ready"])
        self.assertEqual(client.marked_indexed, ["ready"])

    def test_empty_queue_does_nothing(self) -> None:
        outcomes = index_batch(
            client=FakeIndexerClient(),
            pinecone_index=FakePineconeIndex(),
        )
        self.assertEqual(outcomes, [])


if __name__ == "__main__":
    unittest.main()
