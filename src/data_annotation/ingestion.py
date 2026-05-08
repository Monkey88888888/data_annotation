from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import struct
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from data_annotation.archetypes import Archetype, bipolar_vector_sample, default_archetype_path


@dataclass(frozen=True)
class AuthorityScore:
    value: float
    rubric: str
    checks: dict[str, bool]


@dataclass(frozen=True)
class IngestedAsset:
    asset_id: str
    source: str
    dataset_id: str
    path: str
    archetype_id: str
    dimension: int
    raw_hypervector_seed: str
    raw_hypervector_preview: list[int]
    authority_score: float
    authority_rubric: str
    authority_checks: dict[str, bool]
    local_evidence: dict[str, Any]
    authority_vector_seed: str
    authority_vector_magnitude: float
    authority_vector_preview: list[float]
    faceted_matrix: dict[str, dict[str, Any]]


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if line:
                records.append(json.loads(line))
    return records


def write_jsonl(path: Path, records: list[IngestedAsset]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for record in records:
            handle.write(json.dumps(asdict(record), sort_keys=True) + "\n")


def ingest_manifest(
    manifest_path: Path,
    archetype: Archetype,
    output_path: Path,
    preview_size: int = 8,
    dataset_root: Path | None = None,
) -> list[IngestedAsset]:
    manifest_records = read_jsonl(manifest_path)
    ingested = [ingest_asset(record, archetype, preview_size, dataset_root) for record in manifest_records]
    write_jsonl(output_path, ingested)
    return ingested


def ingest_asset(
    asset: dict[str, Any],
    archetype: Archetype,
    preview_size: int = 8,
    dataset_root: Path | None = None,
) -> IngestedAsset:
    if asset.get("archetype_id") != archetype.id:
        raise ValueError(f"asset archetype {asset.get('archetype_id')} does not match {archetype.id}")

    local_evidence = inspect_local_fmri_evidence(asset, dataset_root) if dataset_root else {}
    score = score_authority(asset, archetype, local_evidence)
    raw_seed = raw_hypervector_seed(asset)
    authority_seed = authority_vector_seed(asset, score)
    authority_preview = [
        round(value * score.value, 6)
        for value in bipolar_vector_sample(authority_seed, archetype.dimension, preview_size)
    ]

    matrix = build_faceted_matrix(
        archetype=archetype,
        asset=asset,
        score=score,
        authority_seed=authority_seed,
        authority_preview=authority_preview,
        preview_size=preview_size,
    )

    return IngestedAsset(
        asset_id=asset_identifier(asset),
        source=str(asset["source"]),
        dataset_id=str(asset["dataset_id"]),
        path=str(asset["path"]),
        archetype_id=archetype.id,
        dimension=archetype.dimension,
        raw_hypervector_seed=raw_seed,
        raw_hypervector_preview=bipolar_vector_sample(raw_seed, archetype.dimension, preview_size),
        authority_score=score.value,
        authority_rubric=score.rubric,
        authority_checks=score.checks,
        local_evidence=local_evidence,
        authority_vector_seed=authority_seed,
        authority_vector_magnitude=score.value,
        authority_vector_preview=authority_preview,
        faceted_matrix=matrix,
    )


def score_authority(
    asset: dict[str, Any],
    archetype: Archetype,
    local_evidence: dict[str, Any] | None = None,
) -> AuthorityScore:
    modality = facet_value(archetype, "modality")
    if modality != "fMRI_NIfTI_BIDS":
        raise ValueError(f"no authority rubric for modality {modality}")

    return score_fmri_authority(asset, local_evidence)


def score_fmri_authority(
    asset: dict[str, Any],
    local_evidence: dict[str, Any] | None = None,
) -> AuthorityScore:
    checks = {
        "openneuro_source": asset.get("source") == "OpenNeuro",
        "dataset_accession": str(asset.get("dataset_id", "")).startswith("ds"),
        "versioned_snapshot": bool(asset.get("snapshot_tag")),
        "dataset_doi": str(asset.get("dataset_doi", "")).startswith("10."),
        "open_license": asset.get("license") in {"CC0", "PDDL"},
        "bids_func_path": "/func/" in str(asset.get("path", "")),
        "nifti_payload": str(asset.get("path", "")).endswith((".nii", ".nii.gz")),
        "annexed_payload": bool(asset.get("annexed")),
        "nonzero_size": int(asset.get("size") or 0) > 0,
    }
    if local_evidence:
        checks.update(
            {
                "local_payload_present": bool(local_evidence.get("payload_present")),
                "nifti_header_valid": bool(local_evidence.get("nifti_header", {}).get("valid")),
                "nifti_is_4d": int(local_evidence.get("nifti_header", {}).get("dimensions", [0])[0]) >= 4,
                "sidecar_json_present": bool(local_evidence.get("sidecar_present")),
                "repetition_time_present": "RepetitionTime" in local_evidence.get("sidecar_json", {}),
            }
        )
    value = round(sum(checks.values()) / len(checks), 6)
    return AuthorityScore(value=value, rubric="fmri_openneuro_bids_metadata_v0", checks=checks)


def inspect_local_fmri_evidence(asset: dict[str, Any], dataset_root: Path | None) -> dict[str, Any]:
    if dataset_root is None:
        return {}

    asset_path = dataset_root / str(asset["path"])
    sidecar_path = resolve_bids_sidecar_path(asset_path, dataset_root)
    evidence: dict[str, Any] = {
        "payload_path": str(asset_path),
        "payload_present": asset_path.exists(),
        "sidecar_path": str(sidecar_path),
        "sidecar_present": sidecar_path.exists(),
        "nifti_header": {},
        "sidecar_json": {},
    }

    if asset_path.exists():
        evidence["nifti_header"] = read_nifti_header(asset_path)
    if sidecar_path.exists():
        evidence["sidecar_json"] = read_json_file(sidecar_path)
    return evidence


def bids_sidecar_path(asset_path: Path) -> Path:
    name = asset_path.name
    if name.endswith(".nii.gz"):
        return asset_path.with_name(name[:-7] + ".json")
    if name.endswith(".nii"):
        return asset_path.with_suffix(".json")
    return asset_path.with_suffix(asset_path.suffix + ".json")


def resolve_bids_sidecar_path(asset_path: Path, dataset_root: Path) -> Path:
    exact = bids_sidecar_path(asset_path)
    if exact.exists():
        return exact

    task_name = bids_entity(asset_path.name, "task")
    suffix = bids_suffix(asset_path.name)
    if task_name and suffix:
        inherited = dataset_root / f"task-{task_name}_{suffix}.json"
        if inherited.exists():
            return inherited
    return exact


def bids_entity(filename: str, entity: str) -> str | None:
    prefix = f"{entity}-"
    for part in filename.split("_"):
        if part.startswith(prefix):
            return part[len(prefix) :]
    return None


def bids_suffix(filename: str) -> str | None:
    base = filename
    if base.endswith(".nii.gz"):
        base = base[:-7]
    else:
        base = Path(base).stem
    if "_" not in base:
        return None
    return base.rsplit("_", 1)[1]


def read_json_file(path: Path) -> dict[str, Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}


def read_nifti_header(path: Path) -> dict[str, Any]:
    opener = gzip.open if path.name.endswith(".gz") else open
    with opener(path, "rb") as handle:
        header = handle.read(348)
    if len(header) < 348:
        return {"valid": False, "reason": "short_header"}

    sizeof_hdr = struct.unpack("<i", header[0:4])[0]
    dimensions = list(struct.unpack("<8h", header[40:56]))
    datatype = struct.unpack("<h", header[70:72])[0]
    pixdim = [round(value, 6) for value in struct.unpack("<8f", header[76:108])]
    vox_offset = round(struct.unpack("<f", header[108:112])[0], 6)
    magic = header[344:348].rstrip(b"\x00").decode("ascii", errors="replace")

    return {
        "valid": sizeof_hdr == 348 and magic in {"n+1", "ni1"},
        "sizeof_hdr": sizeof_hdr,
        "magic": magic,
        "dimensions": dimensions,
        "datatype": datatype,
        "pixdim": pixdim,
        "vox_offset": vox_offset,
    }


def build_faceted_matrix(
    archetype: Archetype,
    asset: dict[str, Any],
    score: AuthorityScore,
    authority_seed: str,
    authority_preview: list[float],
    preview_size: int,
) -> dict[str, dict[str, Any]]:
    columns: dict[str, dict[str, Any]] = {}
    for facet in archetype.facets:
        if facet.name == "authority_base":
            columns["authority"] = {
                "seed": authority_seed,
                "magnitude": score.value,
                "preview": authority_preview,
                "source": "asset_authority_score",
            }
            continue

        columns[facet.name] = {
            "seed": facet.seed,
            "value": facet.value,
            "preview": bipolar_vector_sample(facet.seed, archetype.dimension, preview_size),
        }
    return columns


def facet_value(archetype: Archetype, name: str) -> str | None:
    for facet in archetype.facets:
        if facet.name == name:
            return facet.value
    return None


def asset_identifier(asset: dict[str, Any]) -> str:
    source = f"{asset.get('source')}:{asset.get('dataset_id')}:{asset.get('snapshot_tag')}:{asset.get('path')}"
    return hashlib.sha256(source.encode("utf-8")).hexdigest()


def raw_hypervector_seed(asset: dict[str, Any]) -> str:
    return "raw:" + asset_identifier(asset)


def authority_vector_seed(asset: dict[str, Any], score: AuthorityScore) -> str:
    return f"authority:{asset_identifier(asset)}:{score.rubric}:{score.value}"


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run Step 2 ingestion and authority axis swap.")
    parser.add_argument("--manifest", type=Path, default=Path("manifests/openneuro_ds000001_fmri.jsonl"))
    parser.add_argument("--output", type=Path, default=Path("manifests/openneuro_ds000001_ingested.jsonl"))
    parser.add_argument("--archetype", type=Path, default=default_archetype_path("fmri_scan"))
    parser.add_argument("--preview-size", type=int, default=8)
    parser.add_argument(
        "--dataset-root",
        type=Path,
        default=None,
        help="Optional local BIDS dataset root containing downloaded payloads.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv or sys.argv[1:])
    archetype = Archetype.from_file(args.archetype)
    records = ingest_manifest(args.manifest, archetype, args.output, args.preview_size, args.dataset_root)
    print(f"wrote {len(records)} ingested {archetype.id} records to {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
