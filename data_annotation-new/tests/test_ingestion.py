import gzip
import json
import struct
import tempfile
import unittest
from pathlib import Path

from data_annotation.archetypes import Archetype, default_archetype_path
from data_annotation.ingestion import (
    bids_sidecar_path,
    ingest_asset,
    inspect_local_fmri_evidence,
    read_nifti_header,
    resolve_bids_sidecar_path,
    score_fmri_authority,
)


ASSET = {
    "annexed": True,
    "archetype_id": "fmri_scan",
    "dataset_doi": "10.18112/openneuro.ds000001.v1.0.0",
    "dataset_id": "ds000001",
    "dataset_name": "Balloon Analog Risk-taking Task",
    "file_id": "MD5E-s50489238--74cc94c18ee473ad8fb817a4d90ba0ea.nii.gz",
    "license": "CC0",
    "modality": "fMRI_NIfTI_BIDS",
    "path": "sub-16/func/sub-16_task-balloonanalogrisktask_run-01_bold.nii.gz",
    "size": 50489238,
    "snapshot_tag": "1.0.0",
    "source": "OpenNeuro",
}


class IngestionTests(unittest.TestCase):
    def test_fmri_authority_score_uses_metadata_checks(self):
        score = score_fmri_authority(ASSET)

        self.assertEqual(score.value, 1.0)
        self.assertEqual(score.rubric, "fmri_openneuro_bids_metadata_v0")
        self.assertTrue(all(score.checks.values()))

    def test_ingest_asset_swaps_authority_axis(self):
        archetype = Archetype.from_file(default_archetype_path("fmri_scan"))
        record = ingest_asset(ASSET, archetype)

        self.assertEqual(record.dimension, 10000)
        self.assertEqual(record.authority_vector_magnitude, 1.0)
        self.assertIn("authority", record.faceted_matrix)
        self.assertNotIn("authority_base", record.faceted_matrix)
        self.assertEqual(record.faceted_matrix["modality"]["value"], "fMRI_NIfTI_BIDS")
        self.assertEqual(len(record.raw_hypervector_preview), 8)

    def test_bids_sidecar_path_handles_nii_gz(self):
        path = Path("sub-16/func/sub-16_task-test_bold.nii.gz")

        self.assertEqual(
            bids_sidecar_path(path),
            Path("sub-16/func/sub-16_task-test_bold.json"),
        )

    def test_resolve_bids_sidecar_path_uses_root_task_inheritance(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            payload = root / "sub-16/func/sub-16_task-test_run-01_bold.nii.gz"
            inherited = root / "task-test_bold.json"
            payload.parent.mkdir(parents=True)
            inherited.write_text("{}", encoding="utf-8")

            self.assertEqual(resolve_bids_sidecar_path(payload, root), inherited)

    def test_local_nifti_and_sidecar_evidence_improves_rubric(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            payload = root / ASSET["path"]
            payload.parent.mkdir(parents=True)
            write_minimal_nifti_gz(payload)
            bids_sidecar_path(payload).write_text(json.dumps({"RepetitionTime": 2.0}), encoding="utf-8")

            evidence = inspect_local_fmri_evidence(ASSET, root)
            score = score_fmri_authority(ASSET, evidence)

        self.assertTrue(evidence["payload_present"])
        self.assertTrue(evidence["nifti_header"]["valid"])
        self.assertEqual(evidence["nifti_header"]["dimensions"][0], 4)
        self.assertTrue(evidence["sidecar_present"])
        self.assertEqual(score.value, 1.0)
        self.assertTrue(score.checks["nifti_header_valid"])
        self.assertTrue(score.checks["repetition_time_present"])

    def test_read_nifti_header_rejects_short_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "bad.nii"
            path.write_bytes(b"not a nifti")

            header = read_nifti_header(path)

        self.assertFalse(header["valid"])


def write_minimal_nifti_gz(path: Path) -> None:
    header = bytearray(348)
    header[0:4] = struct.pack("<i", 348)
    header[40:56] = struct.pack("<8h", 4, 64, 64, 32, 120, 1, 1, 1)
    header[70:72] = struct.pack("<h", 16)
    header[76:108] = struct.pack("<8f", 0.0, 3.0, 3.0, 3.5, 2.0, 0.0, 0.0, 0.0)
    header[108:112] = struct.pack("<f", 352.0)
    header[344:348] = b"n+1\x00"
    with gzip.open(path, "wb") as handle:
        handle.write(header)
        handle.write(b"\x00\x00\x00\x00")


if __name__ == "__main__":
    unittest.main()
