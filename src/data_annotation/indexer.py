"""Tier-2 indexer: push annotated documents_raw rows into Pinecone.

Loop:
1. Pull rows where ``is_processed = TRUE AND is_indexed = FALSE``.
2. For each row, build the asset dict shape that ``pipeline.py`` expects.
3. Call ``pipeline.build_manifold_record`` to project the HDC vector down
   to the manifold dimension (256D, matches the live Pinecone index).
4. Push ``(row_id, manifold_vector, metadata)`` to Pinecone.
5. Flip ``is_indexed = TRUE``.

Annotation is *not* re-run here; the LLM-attested facets in
``documents_raw`` are the input. That is why this is a separate stage from
``runner.py`` -- you can re-index (different manifold dim, different
weighting) without re-billing the annotator.

Usage::

    python -m data_annotation.indexer
    python -m data_annotation.indexer --batch-size 10
    python -m data_annotation.indexer --dry-run
    python -m data_annotation.indexer --manifold-dimension 256
"""

from __future__ import annotations

import argparse
import os
import statistics
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from dotenv import load_dotenv

from data_annotation.archetypes import Archetype, default_archetype_path
from data_annotation.db import SupabaseClient
from data_annotation.hdc import FACET_ORDER
from data_annotation.pipeline import build_manifold_record


DEFAULT_MANIFOLD_DIMENSION = 256
SKIP_ARCHETYPES = {"fmri_scan"}     # has its own ingestion + indexing path


# ---------------------------------------------------------------------------
# Per-row outcomes
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class IndexOutcome:
    document_id: str
    status: str           # 'indexed' | 'skipped' | 'error'
    archetype_id: str | None = None
    detail: str | None = None


# ---------------------------------------------------------------------------
# Protocols (narrow surfaces so tests can inject fakes)
# ---------------------------------------------------------------------------

class IndexerClient(Protocol):
    def fetch_processed_unindexed(self, limit: int = ...) -> list[dict[str, Any]]: ...
    def mark_indexed(self, row_id: str) -> dict[str, Any]: ...


class PineconeIndex(Protocol):
    def upsert(self, vectors: list[dict[str, Any]]) -> Any: ...


# ---------------------------------------------------------------------------
# documents_raw row -> asset dict (compatible with pipeline.build_manifold_record)
# ---------------------------------------------------------------------------

_AUTH_COLS = ("auth_domain", "auth_author", "auth_institution")
_TYPE_COLS = ("type_text", "type_image", "type_timeseries")
_MODALITY_COLS = (
    "modality_b2b_email",
    "modality_landing_page",
    "modality_fmri_t1",
    "modality_fmri_bold",
)
_STRICT_COLS = ("strict_regulatory", "strict_technicality")
_TONE_COLS = ("tone_formality", "tone_aggressiveness", "tone_creativity")


def _mean(values: list[float]) -> float:
    return statistics.fmean(values) if values else 0.0


def _bool_any(row: dict[str, Any], cols: tuple[str, ...]) -> float:
    return 1.0 if any(row.get(col) for col in cols) else 0.0


def _facet_magnitudes(row: dict[str, Any]) -> dict[str, float]:
    """Aggregate the documents_raw column values into one magnitude per facet."""
    return {
        "authority": _mean([float(row.get(c) or 0.0) for c in _AUTH_COLS]),
        "type": _bool_any(row, _TYPE_COLS),
        "modality": _bool_any(row, _MODALITY_COLS),
        "strictness": _mean([float(row.get(c) or 0.0) for c in _STRICT_COLS]),
        "tone": _mean([float(row.get(c) or 0.0) for c in _TONE_COLS]),
    }


def row_to_asset(row: dict[str, Any], archetype: Archetype) -> dict[str, Any]:
    """Build the asset-dict shape that ``pipeline.build_manifold_record`` consumes.

    Maps documents_raw column values onto the archetype's facet structure,
    using a per-facet magnitude aggregated from the relevant columns. The
    archetype's facet seeds are reused, so two rows of the same archetype
    share their bipolar bases and only the magnitudes differ.
    """
    asset_id = str(row["id"])
    magnitudes = _facet_magnitudes(row)
    preview_size = 8

    matrix: dict[str, dict[str, Any]] = {}
    for facet in archetype.facets:
        if facet.name == "authority_base":
            matrix["authority"] = {
                "seed": f"authority:{asset_id}",
                "magnitude": magnitudes["authority"],
                "preview": [],
                "source": "documents_raw_authority_columns",
            }
            continue
        matrix[facet.name] = {
            "seed": facet.seed,
            "magnitude": magnitudes[facet.name],
            "value": facet.value,
            "preview": [],
        }

    # Backfill any facet pipeline expects but that the archetype config didn't
    # name (defensive — keeps build_manifold_record from KeyError'ing).
    for facet_name in FACET_ORDER:
        matrix.setdefault(facet_name, {
            "seed": f"{facet_name}:default",
            "magnitude": magnitudes.get(facet_name, 1.0),
            "preview": [],
        })

    return {
        "asset_id": asset_id,
        "source": row.get("source_name") or "documents_raw",
        "dataset_id": "documents_raw",
        "path": row.get("content_payload") or "",
        "archetype_id": archetype.id,
        "dimension": archetype.dimension,
        "raw_hypervector_seed": f"raw:{asset_id}",
        "authority_score": magnitudes["authority"],
        "authority_checks": {},
        "local_evidence": {},
        "faceted_matrix": matrix,
    }


# ---------------------------------------------------------------------------
# Pinecone glue
# ---------------------------------------------------------------------------

def _vector_metadata(row: dict[str, Any]) -> dict[str, Any]:
    """Compact metadata stored alongside the manifold vector. Pinecone caps
    metadata size; keep this small."""
    return {
        "archetype_id": row.get("archetype_id") or "",
        "source_name": (row.get("source_name") or "")[:128],
        "is_text": bool(row.get("type_text")),
        "is_image": bool(row.get("type_image")),
        "is_timeseries": bool(row.get("type_timeseries")),
    }


def build_pinecone_index() -> PineconeIndex:
    """Construct the live Pinecone index handle from env vars. Public so
    other modules (pinecone_search) can reuse it."""
    api_key = os.environ.get("PINECONE_API_KEY")
    index_name = os.environ.get("PINECONE_INDEX") or "annotation"
    if not api_key:
        raise RuntimeError("PINECONE_API_KEY not set")
    from pinecone import Pinecone  # local import — soft dependency
    return Pinecone(api_key=api_key).Index(index_name)


# Backwards-compat alias kept private name working in case anyone imported it.
_build_pinecone_index = build_pinecone_index


# ---------------------------------------------------------------------------
# Per-row processing
# ---------------------------------------------------------------------------

_ARCHETYPE_CACHE: dict[str, Archetype] = {}


def _load_archetype(archetype_id: str) -> Archetype:
    if archetype_id not in _ARCHETYPE_CACHE:
        _ARCHETYPE_CACHE[archetype_id] = Archetype.from_file(default_archetype_path(archetype_id))
    return _ARCHETYPE_CACHE[archetype_id]


def index_row(
    row: dict[str, Any],
    *,
    client: IndexerClient,
    pinecone_index: PineconeIndex,
    manifold_dimension: int = DEFAULT_MANIFOLD_DIMENSION,
    dry_run: bool = False,
) -> IndexOutcome:
    document_id = str(row["id"])
    archetype_id = row.get("archetype_id")

    if not archetype_id:
        return IndexOutcome(document_id, "skipped", None, "no archetype_id")
    if archetype_id in SKIP_ARCHETYPES:
        return IndexOutcome(document_id, "skipped", archetype_id, "non-LLM archetype")

    try:
        archetype = _load_archetype(archetype_id)
    except FileNotFoundError:
        return IndexOutcome(document_id, "skipped", archetype_id, "archetype config not found")

    asset = row_to_asset(row, archetype)
    record = build_manifold_record(asset, manifold_dimension)

    if dry_run:
        return IndexOutcome(document_id, "indexed", archetype_id, "dry-run (no Pinecone write, no DB update)")

    pinecone_index.upsert(vectors=[{
        "id": document_id,
        "values": list(record.manifold_vector),
        "metadata": _vector_metadata(row),
    }])
    client.mark_indexed(document_id)
    return IndexOutcome(document_id, "indexed", archetype_id)


def index_batch(
    *,
    client: IndexerClient,
    pinecone_index: PineconeIndex,
    batch_size: int = 50,
    manifold_dimension: int = DEFAULT_MANIFOLD_DIMENSION,
    dry_run: bool = False,
) -> list[IndexOutcome]:
    rows = client.fetch_processed_unindexed(limit=batch_size)
    outcomes: list[IndexOutcome] = []
    for row in rows:
        outcome = index_row(
            row,
            client=client,
            pinecone_index=pinecone_index,
            manifold_dimension=manifold_dimension,
            dry_run=dry_run,
        )
        outcomes.append(outcome)
        print(_format_outcome(outcome, dry_run))
    return outcomes


def _format_outcome(outcome: IndexOutcome, dry_run: bool) -> str:
    prefix = "[DRY] " if dry_run else ""
    base = f"{prefix}{outcome.status:>9}  {outcome.document_id}"
    if outcome.archetype_id:
        base += f"  ({outcome.archetype_id})"
    if outcome.detail:
        base += f"  -- {outcome.detail}"
    return base


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--batch-size", type=int, default=50)
    parser.add_argument("--manifold-dimension", type=int, default=DEFAULT_MANIFOLD_DIMENSION,
                        help="Must match the dimension of the live Pinecone index.")
    parser.add_argument("--dry-run", action="store_true",
                        help="Build manifolds but skip Pinecone writes and DB flags.")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    load_dotenv()
    args = parse_args(argv or sys.argv[1:])

    if not (os.environ.get("SUPABASE_URL") and os.environ.get("SUPABASE_SERVICE_KEY")):
        print("SUPABASE_URL / SUPABASE_SERVICE_KEY not set", file=sys.stderr)
        return 2
    if not args.dry_run and not os.environ.get("PINECONE_API_KEY"):
        print("PINECONE_API_KEY not set (use --dry-run to skip Pinecone)", file=sys.stderr)
        return 2

    client = SupabaseClient()
    pinecone_index = build_pinecone_index() if not args.dry_run else _NoopPineconeIndex()

    outcomes = index_batch(
        client=client,
        pinecone_index=pinecone_index,
        batch_size=args.batch_size,
        manifold_dimension=args.manifold_dimension,
        dry_run=args.dry_run,
    )
    counts: dict[str, int] = {}
    for outcome in outcomes:
        counts[outcome.status] = counts.get(outcome.status, 0) + 1
    print(f"\nindexed {len(outcomes)} row(s): {counts}")
    return 0


class _NoopPineconeIndex:
    """Stand-in for dry-run mode so we don't need the Pinecone SDK loaded."""

    def upsert(self, vectors: list[dict[str, Any]]) -> None:
        return None


if __name__ == "__main__":
    raise SystemExit(main())
