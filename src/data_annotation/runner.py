"""Annotation runner: pull unprocessed documents_raw rows, dispatch to the
right annotator by ``archetype_id``, cache to ``annotations``, merge facets
back into ``documents_raw``, flip ``is_processed``.

Usage::

    python -m data_annotation.runner                  # processes up to 50 rows
    python -m data_annotation.runner --batch-size 10
    python -m data_annotation.runner --dry-run        # logs only, no DB writes

Routing:
    archetype_id='text_document'  -> annotator.text   (Haiku 4.5)
    archetype_id='image_asset'    -> annotator.image  (Sonnet 4.6, native vision)
    archetype_id='fmri_scan'      -> skipped (handled by ingestion.py)
    archetype_id missing/unknown  -> skipped (logged)

Image rows: ``content_payload`` must be a local filesystem path. Remote
fetching (s3://, https://) is left for a later iteration.
"""

from __future__ import annotations

import argparse
import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from dotenv import load_dotenv

from data_annotation.annotator import (
    AnnotationResult,
    annotator_registry,
)
from data_annotation.annotator.base import hash_payload
from data_annotation.annotator.image import (
    ANNOTATOR_VERSION as IMAGE_ANNOTATOR_VERSION,
    _media_type_for as image_media_type_for,
)
from data_annotation.annotator.text import (
    ANNOTATOR_VERSION as TEXT_ANNOTATOR_VERSION,
)
from data_annotation.db import SupabaseClient


SKIP_ARCHETYPES = {"fmri_scan"}  # handled by ingestion.py, not the annotator


# ---------------------------------------------------------------------------
# Per-row outcomes
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class RowOutcome:
    document_id: str
    status: str           # 'annotated' | 'cache_hit' | 'skipped' | 'error'
    archetype_id: str | None = None
    detail: str | None = None


# ---------------------------------------------------------------------------
# Client protocol — narrowed surface area lets tests inject a fake.
# ---------------------------------------------------------------------------

class RunnerClient(Protocol):
    def fetch_unprocessed(self, limit: int = ...) -> list[dict[str, Any]]: ...
    def fetch_annotation(
        self, asset_hash: str, annotator_version: str
    ) -> dict[str, Any] | None: ...
    def upsert_annotation(self, row: dict[str, Any]) -> dict[str, Any]: ...
    def merge_annotation_into_document(
        self, document_id: str, facets: dict[str, Any]
    ) -> dict[str, Any]: ...
    def mark_processed(self, row_id: str) -> dict[str, Any]: ...


# ---------------------------------------------------------------------------
# Per-archetype handlers. Adding a third archetype = one new branch.
# ---------------------------------------------------------------------------

def _prepare_text_call(row: dict[str, Any]) -> tuple[bytes, str, dict[str, Any]]:
    """Returns (payload_bytes_for_hash, annotator_version, kwargs_for_annotator)."""
    payload = row.get("content_payload") or ""
    return payload.encode("utf-8"), TEXT_ANNOTATOR_VERSION, {"payload": payload}


def _prepare_image_call(row: dict[str, Any]) -> tuple[bytes, str, dict[str, Any]]:
    payload_path = row.get("content_payload") or ""
    if not payload_path:
        raise ValueError("content_payload is empty for image row")
    path = Path(payload_path)
    if not path.exists():
        raise FileNotFoundError(f"image not found at {path}")
    data = path.read_bytes()
    media_type = image_media_type_for(path)
    return data, IMAGE_ANNOTATOR_VERSION, {"payload": data, "media_type": media_type}


_PREPARE: dict[str, Any] = {
    "text_document": _prepare_text_call,
    "image_asset": _prepare_image_call,
}


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------

def process_row(
    row: dict[str, Any],
    client: RunnerClient,
    *,
    dry_run: bool = False,
) -> RowOutcome:
    document_id = row["id"]
    archetype_id = row.get("archetype_id")

    if not archetype_id:
        return RowOutcome(document_id, "skipped", None, "no archetype_id")
    if archetype_id in SKIP_ARCHETYPES:
        return RowOutcome(document_id, "skipped", archetype_id, "handled by ingestion.py")
    if archetype_id not in _PREPARE or archetype_id not in annotator_registry:
        return RowOutcome(document_id, "skipped", archetype_id, "no annotator registered")

    try:
        payload_bytes, annotator_version, call_kwargs = _PREPARE[archetype_id](row)
    except (FileNotFoundError, ValueError) as exc:
        return RowOutcome(document_id, "error", archetype_id, str(exc))

    asset_hash = hash_payload(payload_bytes)
    cached = client.fetch_annotation(asset_hash, annotator_version)
    if cached is not None:
        facets = cached["facets"]
        status = "cache_hit"
    else:
        annotate_fn = annotator_registry.get(archetype_id)
        result: AnnotationResult = annotate_fn(**call_kwargs)
        if not dry_run:
            client.upsert_annotation(result.to_db_row(document_id=document_id))
        facets = result.facets
        status = "annotated"

    if not dry_run:
        client.merge_annotation_into_document(document_id, facets)
        client.mark_processed(document_id)

    return RowOutcome(document_id, status, archetype_id)


def run_batch(
    client: RunnerClient,
    *,
    batch_size: int = 50,
    dry_run: bool = False,
) -> list[RowOutcome]:
    rows = client.fetch_unprocessed(limit=batch_size)
    outcomes: list[RowOutcome] = []
    for row in rows:
        outcome = process_row(row, client, dry_run=dry_run)
        outcomes.append(outcome)
        print(_format_outcome(outcome, dry_run))
    return outcomes


def _format_outcome(outcome: RowOutcome, dry_run: bool) -> str:
    prefix = "[DRY] " if dry_run else ""
    base = f"{prefix}{outcome.status:>10}  {outcome.document_id}"
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
    parser.add_argument("--dry-run", action="store_true",
                        help="Run annotators but skip every DB write.")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    load_dotenv()
    args = parse_args(argv or sys.argv[1:])
    if not (os.environ.get("SUPABASE_URL") and os.environ.get("SUPABASE_SERVICE_KEY")):
        print("SUPABASE_URL / SUPABASE_SERVICE_KEY not set", file=sys.stderr)
        return 2

    client = SupabaseClient()
    outcomes = run_batch(client, batch_size=args.batch_size, dry_run=args.dry_run)
    counts: dict[str, int] = {}
    for outcome in outcomes:
        counts[outcome.status] = counts.get(outcome.status, 0) + 1
    print(f"\nprocessed {len(outcomes)} row(s): {counts}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
