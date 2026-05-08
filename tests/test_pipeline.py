import tempfile
import unittest
from pathlib import Path

from data_annotation.pipeline import (
    build_manifold_record,
    execute_retrieval,
    facet_alignment_score,
    facet_sector_lengths,
    score_record,
    search_index,
    write_jsonl,
)
from tests.test_ingestion import ASSET
from data_annotation.archetypes import Archetype, default_archetype_path
from data_annotation.ingestion import ingest_asset


class PipelineTests(unittest.TestCase):
    def test_facet_sector_lengths_preserve_dimension(self):
        sectors = facet_sector_lengths(256)

        self.assertEqual(sum(sectors.values()), 256)
        self.assertEqual(set(sectors), {"authority", "type", "modality", "strictness", "tone"})

    def test_build_manifold_record_creates_block_projected_vector(self):
        archetype = Archetype.from_file(default_archetype_path("fmri_scan"))
        ingested = ingest_asset(ASSET, archetype)
        record = build_manifold_record(ingested.__dict__, 64)

        self.assertEqual(record.manifold_dimension, 64)
        self.assertEqual(len(record.manifold_vector), 64)
        self.assertEqual(sum(len(values) for values in record.facet_sectors.values()), 64)

    def test_score_record_returns_retrieval_route(self):
        archetype = Archetype.from_file(default_archetype_path("fmri_scan"))
        ingested = ingest_asset(ASSET, archetype)
        record = build_manifold_record(ingested.__dict__, 64)

        result = score_record(record.__dict__, "balloon risk fMRI", {"authority": 1, "type": 1, "modality": 1, "strictness": 1, "tone": 0})

        self.assertEqual(result.terminal_route, "retrieval")
        self.assertEqual(result.path, ASSET["path"])

    def test_facet_alignment_prefers_verified_authority(self):
        archetype = Archetype.from_file(default_archetype_path("fmri_scan"))
        high_authority = ingest_asset(ASSET, archetype).__dict__
        high_authority["local_evidence"] = {"payload_present": True}
        low_authority = dict(high_authority)
        low_authority["authority_score"] = 0.5
        low_authority["local_evidence"] = {}

        weights = {"authority": 1, "type": 1, "modality": 1, "strictness": 1, "tone": 0}

        self.assertGreater(
            facet_alignment_score(high_authority, weights),
            facet_alignment_score(low_authority, weights),
        )

    def test_search_and_execute_retrieval_package(self):
        archetype = Archetype.from_file(default_archetype_path("fmri_scan"))
        ingested = ingest_asset(ASSET, archetype)
        record = build_manifold_record(ingested.__dict__, 64)

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            index_path = root / "index.jsonl"
            results_path = root / "results.jsonl"
            package_path = root / "package.json"
            dataset_root = root / "dataset"
            payload = dataset_root / ASSET["path"]
            payload.parent.mkdir(parents=True)
            payload.write_bytes(b"payload")
            write_jsonl(index_path, [record])

            results = search_index(
                index_path,
                "balloon risk fMRI",
                {"authority": 1, "type": 1, "modality": 1, "strictness": 1, "tone": 0},
                1,
                results_path,
            )
            package = execute_retrieval(results_path, package_path, dataset_root)

        self.assertEqual(len(results), 1)
        self.assertEqual(package["count"], 1)
        self.assertTrue(package["assets"][0]["local_payload_present"])


if __name__ == "__main__":
    unittest.main()
