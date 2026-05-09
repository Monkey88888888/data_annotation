from __future__ import annotations

import os
from dataclasses import dataclass, field, asdict
from typing import Any

from supabase import Client, create_client


TABLE = "documents_raw"
ANNOTATIONS_TABLE = "annotations"


@dataclass
class DocumentRow:
    """Mirror of the documents_raw schema. Defaults match db/schema.sql."""

    source_name: str | None = None
    content_payload: str | None = None
    archetype_id: str | None = None     # routes the annotator runner
    is_processed: bool = False
    is_indexed: bool = False

    auth_domain: float = 0.0
    auth_author: float = 0.0
    auth_institution: float = 0.0

    type_text: bool = False
    type_image: bool = False
    type_timeseries: bool = False

    modality_b2b_email: bool = False
    modality_landing_page: bool = False
    modality_fmri_t1: bool = False
    modality_fmri_bold: bool = False

    strict_regulatory: float = 0.0
    strict_technicality: float = 0.0

    tone_formality: float = 0.0
    tone_aggressiveness: float = 0.0
    tone_creativity: float = 0.0

    id: str | None = field(default=None)
    created_at: str | None = field(default=None)

    def to_insert_payload(self) -> dict[str, Any]:
        payload = asdict(self)
        # Let Postgres assign id + created_at on insert.
        payload.pop("id", None)
        payload.pop("created_at", None)
        # archetype_id is nullable — drop it from the payload when unset
        # so the column default (NULL) applies cleanly.
        if payload.get("archetype_id") is None:
            payload.pop("archetype_id", None)
        return payload


class SupabaseClient:
    """Thin wrapper for the Tier-1 ingestion surface area.

    Reads SUPABASE_URL and SUPABASE_SERVICE_KEY from the environment unless
    explicit values are supplied. Use the service-role key for ingestion
    workers; the anon key is read-only against RLS-protected tables.
    """

    def __init__(self, url: str | None = None, key: str | None = None):
        url = url or os.environ.get("SUPABASE_URL")
        key = key or os.environ.get("SUPABASE_SERVICE_KEY")
        if not url or not key:
            raise RuntimeError(
                "SUPABASE_URL and SUPABASE_SERVICE_KEY must be set "
                "(see docs/setup_supabase_pinecone.md)."
            )
        self._client: Client = create_client(url, key)

    def insert(self, row: DocumentRow) -> dict[str, Any]:
        result = self._client.table(TABLE).insert(row.to_insert_payload()).execute()
        return result.data[0]

    def fetch_unprocessed(self, limit: int = 50) -> list[dict[str, Any]]:
        result = (
            self._client.table(TABLE)
            .select("*")
            .eq("is_processed", False)
            .limit(limit)
            .execute()
        )
        return result.data

    def fetch_processed_unindexed(self, limit: int = 50) -> list[dict[str, Any]]:
        """Rows ready for the Tier-2 indexer: facets filled, not yet pushed to Pinecone."""
        result = (
            self._client.table(TABLE)
            .select("*")
            .eq("is_processed", True)
            .eq("is_indexed", False)
            .limit(limit)
            .execute()
        )
        return result.data

    def mark_processed(self, row_id: str) -> dict[str, Any]:
        result = (
            self._client.table(TABLE)
            .update({"is_processed": True})
            .eq("id", row_id)
            .execute()
        )
        return result.data[0]

    def mark_indexed(self, row_id: str) -> dict[str, Any]:
        result = (
            self._client.table(TABLE)
            .update({"is_indexed": True})
            .eq("id", row_id)
            .execute()
        )
        return result.data[0]

    def delete(self, row_id: str) -> None:
        self._client.table(TABLE).delete().eq("id", row_id).execute()

    # ------------------------------------------------------------------
    # Annotation cache
    # ------------------------------------------------------------------

    def upsert_annotation(self, row: dict[str, Any]) -> dict[str, Any]:
        """Insert or replace an annotation keyed on (asset_hash, annotator_version)."""
        result = (
            self._client.table(ANNOTATIONS_TABLE)
            .upsert(row, on_conflict="asset_hash,annotator_version")
            .execute()
        )
        return result.data[0]

    def fetch_annotation(
        self,
        asset_hash: str,
        annotator_version: str,
    ) -> dict[str, Any] | None:
        result = (
            self._client.table(ANNOTATIONS_TABLE)
            .select("*")
            .eq("asset_hash", asset_hash)
            .eq("annotator_version", annotator_version)
            .limit(1)
            .execute()
        )
        return result.data[0] if result.data else None

    def merge_annotation_into_document(
        self,
        document_id: str,
        facets: dict[str, Any],
    ) -> dict[str, Any]:
        """Copy facet values from an annotation row into the matching documents_raw row."""
        result = (
            self._client.table(TABLE)
            .update(facets)
            .eq("id", document_id)
            .execute()
        )
        return result.data[0]
