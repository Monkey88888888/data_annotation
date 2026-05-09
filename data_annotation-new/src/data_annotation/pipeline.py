from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from data_annotation.hdc import (
    FACET_ORDER,
    add_vectors,
    bind,
    block_project,
    cosine_similarity,
    normalize_weights,
    stable_bipolar_vector,
)
from data_annotation.ingestion import read_jsonl


@dataclass(frozen=True)
class ManifoldRecord:
    asset_id: str
    source: str
    dataset_id: str
    path: str
    archetype_id: str
    authority_score: float
    authority_checks: dict[str, bool]
    local_evidence: dict[str, Any]
    trusted_hypervector_seed: str
    trusted_hypervector_preview: list[float]
    manifold_dimension: int
    manifold_vector: list[float]
    facet_sectors: dict[str, list[float]]


@dataclass(frozen=True)
class SearchResult:
    asset_id: str
    score: float
    source: str
    dataset_id: str
    path: str
    archetype_id: str
    authority_score: float
    local_payload_present: bool
    terminal_route: str


def write_jsonl(path: Path, records: list[Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for record in records:
            if hasattr(record, "__dataclass_fields__"):
                payload = asdict(record)
            else:
                payload = record
            handle.write(json.dumps(payload, sort_keys=True) + "\n")


def build_manifold_index(
    ingested_path: Path,
    output_path: Path,
    manifold_dimension: int = 256,
) -> list[ManifoldRecord]:
    records = [build_manifold_record(record, manifold_dimension) for record in read_jsonl(ingested_path)]
    write_jsonl(output_path, records)
    return records


def build_manifold_record(asset: dict[str, Any], manifold_dimension: int) -> ManifoldRecord:
    sectors = facet_sector_lengths(manifold_dimension)
    raw_vector = stable_bipolar_vector(asset["raw_hypervector_seed"], int(asset["dimension"]))
    facet_vectors: dict[str, list[float]] = {}

    for facet in FACET_ORDER:
        facet_column = asset["faceted_matrix"][facet]
        scale = float(facet_column.get("magnitude", 1.0))
        facet_vector = stable_bipolar_vector(facet_column["seed"], int(asset["dimension"]))
        facet_vectors[facet] = bind(raw_vector, facet_vector, scale)

    trusted = add_vectors([facet_vectors[facet] for facet in FACET_ORDER])
    facet_sectors = {
        facet: block_project(
            seed=f"project:{asset['asset_id']}:{facet}:{manifold_dimension}",
            vector=facet_vectors[facet],
            target_dimension=sectors[facet],
        )
        for facet in FACET_ORDER
    }
    manifold_vector = [value for facet in FACET_ORDER for value in facet_sectors[facet]]
    local_evidence = asset.get("local_evidence") or {}

    return ManifoldRecord(
        asset_id=asset["asset_id"],
        source=asset["source"],
        dataset_id=asset["dataset_id"],
        path=asset["path"],
        archetype_id=asset["archetype_id"],
        authority_score=float(asset["authority_score"]),
        authority_checks=asset["authority_checks"],
        local_evidence=local_evidence,
        trusted_hypervector_seed=f"trusted:{asset['asset_id']}",
        trusted_hypervector_preview=[round(value, 6) for value in trusted[:8]],
        manifold_dimension=manifold_dimension,
        manifold_vector=[round(value, 6) for value in manifold_vector],
        facet_sectors={facet: [round(value, 6) for value in values] for facet, values in facet_sectors.items()},
    )


def facet_sector_lengths(manifold_dimension: int) -> dict[str, int]:
    if manifold_dimension < len(FACET_ORDER):
        raise ValueError("manifold_dimension must be at least the number of facets")
    base = manifold_dimension // len(FACET_ORDER)
    remainder = manifold_dimension % len(FACET_ORDER)
    return {
        facet: base + (1 if index < remainder else 0)
        for index, facet in enumerate(FACET_ORDER)
    }


def search_index(
    index_path: Path,
    prompt: str,
    weights: dict[str, float],
    top_k: int,
    output_path: Path | None = None,
) -> list[SearchResult]:
    records = read_jsonl(index_path)
    normalized_weights = normalize_weights(weights)
    results = [
        score_record(record, prompt, normalized_weights)
        for record in records
    ]
    results.sort(key=lambda result: result.score, reverse=True)
    top_results = results[:top_k]
    if output_path:
        write_jsonl(output_path, top_results)
    return top_results


def score_record(record: dict[str, Any], prompt: str, weights: dict[str, float]) -> SearchResult:
    query_vector: list[float] = []
    active_vector: list[float] = []
    for facet in FACET_ORDER:
        sector = record["facet_sectors"][facet]
        semantic_sector = block_project(
            seed=f"query:{prompt}:{facet}:{len(sector)}",
            vector=stable_bipolar_vector(f"semantic:{prompt}", 10000),
            target_dimension=len(sector),
        )
        weight = weights[facet]
        query_vector.extend([value * weight for value in semantic_sector])
        active_vector.extend([value * weight for value in sector])

    vector_score = cosine_similarity(query_vector, active_vector)
    alignment_score = facet_alignment_score(record, weights)
    score = (0.35 * vector_score) + (0.65 * alignment_score)
    local_evidence = record.get("local_evidence") or {}
    return SearchResult(
        asset_id=record["asset_id"],
        score=round(score, 6),
        source=record["source"],
        dataset_id=record["dataset_id"],
        path=record["path"],
        archetype_id=record["archetype_id"],
        authority_score=float(record["authority_score"]),
        local_payload_present=bool(local_evidence.get("payload_present")),
        terminal_route="retrieval",
    )


def facet_alignment_score(record: dict[str, Any], weights: dict[str, float]) -> float:
    total_weight = sum(weights.values())
    if total_weight == 0.0:
        return 0.0

    local_evidence = record.get("local_evidence") or {}
    authority = float(record.get("authority_score", 0.0))
    if local_evidence.get("payload_present"):
        authority = min(1.0, authority + 0.05)

    facet_scores = {
        "authority": authority,
        "type": 1.0,
        "modality": 1.0,
        "strictness": 1.0 if record.get("archetype_id") == "fmri_scan" else 0.0,
        "tone": 1.0,
    }
    return sum(facet_scores[facet] * weights[facet] for facet in FACET_ORDER) / total_weight


def execute_retrieval(
    results_path: Path,
    output_path: Path,
    dataset_root: Path | None = None,
) -> dict[str, Any]:
    results = read_jsonl(results_path)
    package = {
        "intent": "retrieval",
        "count": len(results),
        "assets": [retrieval_asset(result, dataset_root) for result in results],
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(package, indent=2, sort_keys=True), encoding="utf-8")
    return package


def retrieval_asset(result: dict[str, Any], dataset_root: Path | None) -> dict[str, Any]:
    local_path = str(dataset_root / result["path"]) if dataset_root else None
    return {
        "asset_id": result["asset_id"],
        "score": result["score"],
        "source": result["source"],
        "dataset_id": result["dataset_id"],
        "path": result["path"],
        "local_path": local_path,
        "local_payload_present": bool(local_path and Path(local_path).exists()),
        "authority_score": result["authority_score"],
        "route": "pure_retrieval",
    }


def run_end_to_end(args: argparse.Namespace) -> None:
    build_manifold_index(args.ingested, args.index, args.manifold_dimension)
    search_index(args.index, args.prompt, cli_weights(args), args.top_k, args.results)
    execute_retrieval(args.results, args.retrieval_package, args.dataset_root)
    print(f"wrote index to {args.index}")
    print(f"wrote search results to {args.results}")
    print(f"wrote retrieval package to {args.retrieval_package}")


def cli_weights(args: argparse.Namespace) -> dict[str, float]:
    return {
        "authority": args.authority_weight,
        "type": args.type_weight,
        "modality": args.modality_weight,
        "strictness": args.strictness_weight,
        "tone": args.tone_weight,
    }


def add_common_search_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--prompt", default="high authority fMRI balloon risk task")
    parser.add_argument("--top-k", type=int, default=3)
    parser.add_argument("--authority-weight", type=float, default=1.0)
    parser.add_argument("--type-weight", type=float, default=1.0)
    parser.add_argument("--modality-weight", type=float, default=1.0)
    parser.add_argument("--strictness-weight", type=float, default=1.0)
    parser.add_argument("--tone-weight", type=float, default=0.2)


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run Steps 3-6 of the local faceted HDC pipeline.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    build = subparsers.add_parser("build-index")
    build.add_argument("--ingested", type=Path, default=Path("manifests/openneuro_ds000001_ingested.jsonl"))
    build.add_argument("--output", type=Path, default=Path("manifests/openneuro_ds000001_manifold.jsonl"))
    build.add_argument("--manifold-dimension", type=int, default=256)

    search = subparsers.add_parser("search")
    search.add_argument("--index", type=Path, default=Path("manifests/openneuro_ds000001_manifold.jsonl"))
    search.add_argument("--output", type=Path, default=Path("manifests/openneuro_ds000001_search.jsonl"))
    add_common_search_args(search)

    execute = subparsers.add_parser("execute")
    execute.add_argument("--results", type=Path, default=Path("manifests/openneuro_ds000001_search.jsonl"))
    execute.add_argument("--output", type=Path, default=Path("manifests/openneuro_ds000001_retrieval_package.json"))
    execute.add_argument("--dataset-root", type=Path, default=Path("data/openneuro/ds000001"))

    run = subparsers.add_parser("run")
    run.add_argument("--ingested", type=Path, default=Path("manifests/openneuro_ds000001_ingested.jsonl"))
    run.add_argument("--index", type=Path, default=Path("manifests/openneuro_ds000001_manifold.jsonl"))
    run.add_argument("--results", type=Path, default=Path("manifests/openneuro_ds000001_search.jsonl"))
    run.add_argument("--retrieval-package", type=Path, default=Path("manifests/openneuro_ds000001_retrieval_package.json"))
    run.add_argument("--dataset-root", type=Path, default=Path("data/openneuro/ds000001"))
    run.add_argument("--manifold-dimension", type=int, default=256)
    add_common_search_args(run)

    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv or sys.argv[1:])
    if args.command == "build-index":
        records = build_manifold_index(args.ingested, args.output, args.manifold_dimension)
        print(f"wrote {len(records)} manifold records to {args.output}")
    elif args.command == "search":
        results = search_index(args.index, args.prompt, cli_weights(args), args.top_k, args.output)
        print(f"wrote {len(results)} search results to {args.output}")
    elif args.command == "execute":
        package = execute_retrieval(args.results, args.output, args.dataset_root)
        print(f"wrote {package['count']} retrieval assets to {args.output}")
    elif args.command == "run":
        run_end_to_end(args)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
