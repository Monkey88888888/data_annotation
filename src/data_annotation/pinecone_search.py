"""Pinecone-backed faceted search for the Tier-2 vector store.

Builds the per-facet weighted query vector that mirrors
``pipeline.score_record``'s query construction, sends it to Pinecone, and
returns matches keyed on ``documents_raw.id`` (which is also the vector
id used by ``indexer.py``). Optionally enriches each match with the full
``documents_raw`` row.

Usage as a library::

    from data_annotation.pinecone_search import search

    matches = search(
        prompt="high authority B2B sales email",
        weights={"authority": 1.0, "type": 1.0, "modality": 1.0,
                 "strictness": 0.5, "tone": 0.2},
        top_k=5,
        archetype_filter="text_document",
        enrich=True,
    )
    for match in matches:
        print(match.document_id, match.score, match.document.get("source_name"))

Usage as a CLI::

    python -m data_annotation.pinecone_search "high authority B2B email" --top-k 5
    python -m data_annotation.pinecone_search "..." --archetype-filter text_document --enrich

Note on weighting math: ``pipeline.score_record`` weights *both* the query
and the stored vector by the same per-facet weight, so the effective
contribution of a facet to cosine is weight^2. Pinecone holds the raw
manifold vector (no per-facet scaling), so here the query is weighted
once -- effective contribution is weight^1. Ranking still favours
high-weight facets; the curve is just less aggressive.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import dataclass, field
from typing import Any, Protocol

from dotenv import load_dotenv

from data_annotation.hdc import (
    FACET_ORDER,
    block_project,
    normalize_weights,
    stable_bipolar_vector,
)
from data_annotation.pipeline import facet_sector_lengths


DEFAULT_MANIFOLD_DIMENSION = 256
RAW_VECTOR_DIMENSION = 10000


# ---------------------------------------------------------------------------
# Types
# ---------------------------------------------------------------------------

@dataclass
class SearchMatch:
    document_id: str
    score: float
    metadata: dict[str, Any] = field(default_factory=dict)
    document: dict[str, Any] | None = None      # populated by enrich=True


class PineconeIndex(Protocol):
    def query(self, **kwargs) -> Any: ...


class DocumentFetcher(Protocol):
    def fetch_by_ids(self, ids: list[str]) -> dict[str, dict[str, Any]]: ...


# ---------------------------------------------------------------------------
# Query vector construction (mirrors pipeline.score_record's per-facet build)
# ---------------------------------------------------------------------------

def build_query_vector(
    prompt: str,
    weights: dict[str, float],
    manifold_dimension: int = DEFAULT_MANIFOLD_DIMENSION,
) -> list[float]:
    sectors = facet_sector_lengths(manifold_dimension)
    normalized = normalize_weights(weights)
    semantic_base = stable_bipolar_vector(f"semantic:{prompt}", RAW_VECTOR_DIMENSION)

    query_vector: list[float] = []
    for facet in FACET_ORDER:
        sector_len = sectors[facet]
        semantic_sector = block_project(
            seed=f"query:{prompt}:{facet}:{sector_len}",
            vector=semantic_base,
            target_dimension=sector_len,
        )
        weight = normalized[facet]
        query_vector.extend(value * weight for value in semantic_sector)
    return query_vector


# ---------------------------------------------------------------------------
# Search
# ---------------------------------------------------------------------------

def search(
    prompt: str,
    *,
    weights: dict[str, float] | None = None,
    plan_prompt: bool = False,
    top_k: int = 10,
    manifold_dimension: int = DEFAULT_MANIFOLD_DIMENSION,
    archetype_filter: str | None = None,
    enrich: bool = False,
    pinecone_index: PineconeIndex | None = None,
    document_fetcher: DocumentFetcher | None = None,
    planner_client: Any = None,
) -> list[SearchMatch]:
    if plan_prompt and weights is None:
        from data_annotation.query_planner import plan_query
        weights = plan_query(prompt, client=planner_client) if planner_client else plan_query(prompt)
    weights = weights or {f: 1.0 for f in FACET_ORDER}
    query_vector = build_query_vector(prompt, weights, manifold_dimension)

    pinecone_index = pinecone_index or _build_default_index()
    query_kwargs: dict[str, Any] = {
        "vector": query_vector,
        "top_k": top_k,
        "include_metadata": True,
    }
    if archetype_filter:
        query_kwargs["filter"] = {"archetype_id": archetype_filter}

    response = pinecone_index.query(**query_kwargs)
    if hasattr(response, "matches"):
        raw_matches = response.matches or []
    elif isinstance(response, dict):
        raw_matches = response.get("matches", [])
    else:
        raw_matches = []
    matches = [
        SearchMatch(
            document_id=str(_attr(match, "id")),
            score=float(_attr(match, "score") or 0.0),
            metadata=dict(_attr(match, "metadata") or {}),
        )
        for match in raw_matches
    ]

    if enrich and matches:
        document_fetcher = document_fetcher or _build_default_fetcher()
        rows = document_fetcher.fetch_by_ids([m.document_id for m in matches])
        for match in matches:
            match.document = rows.get(match.document_id)

    return matches


def _attr(match: Any, name: str) -> Any:
    """Pinecone match objects sometimes use attributes, sometimes dict keys."""
    if hasattr(match, name):
        return getattr(match, name)
    if isinstance(match, dict):
        return match.get(name)
    return None


def _build_default_index() -> PineconeIndex:
    from data_annotation.indexer import build_pinecone_index
    return build_pinecone_index()


def _build_default_fetcher() -> DocumentFetcher:
    from data_annotation.db import SupabaseClient
    return SupabaseClient()


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("prompt", help="Free-text search prompt.")
    parser.add_argument("--top-k", type=int, default=5)
    parser.add_argument("--manifold-dimension", type=int, default=DEFAULT_MANIFOLD_DIMENSION)
    parser.add_argument("--archetype-filter", default=None,
                        help="Restrict to one archetype id (e.g. text_document).")
    parser.add_argument("--enrich", action="store_true",
                        help="Fetch the documents_raw row for each match.")
    parser.add_argument("--plan", action="store_true",
                        help="Use Claude to translate the prompt into per-facet weights "
                             "(overrides the --*-weight flags).")
    parser.add_argument("--authority-weight", type=float, default=1.0)
    parser.add_argument("--type-weight", type=float, default=1.0)
    parser.add_argument("--modality-weight", type=float, default=1.0)
    parser.add_argument("--strictness-weight", type=float, default=1.0)
    parser.add_argument("--tone-weight", type=float, default=0.2)
    parser.add_argument("--json", action="store_true",
                        help="Emit JSON instead of the human-readable table.")
    return parser.parse_args(argv)


def _weights_from_args(args: argparse.Namespace) -> dict[str, float]:
    return {
        "authority": args.authority_weight,
        "type": args.type_weight,
        "modality": args.modality_weight,
        "strictness": args.strictness_weight,
        "tone": args.tone_weight,
    }


def main(argv: list[str] | None = None) -> int:
    load_dotenv()
    args = parse_args(argv or sys.argv[1:])
    if not os.environ.get("PINECONE_API_KEY"):
        print("PINECONE_API_KEY not set", file=sys.stderr)
        return 2
    if args.enrich and not (
        os.environ.get("SUPABASE_URL") and os.environ.get("SUPABASE_SERVICE_KEY")
    ):
        print("SUPABASE creds required for --enrich", file=sys.stderr)
        return 2

    matches = search(
        args.prompt,
        weights=None if args.plan else _weights_from_args(args),
        plan_prompt=args.plan,
        top_k=args.top_k,
        manifold_dimension=args.manifold_dimension,
        archetype_filter=args.archetype_filter,
        enrich=args.enrich,
    )

    if args.json:
        print(json.dumps([_match_to_jsonable(m) for m in matches], indent=2))
        return 0

    print(f"top {len(matches)} match(es) for: {args.prompt!r}")
    for rank, match in enumerate(matches, start=1):
        line = f"{rank:>2}.  score={match.score:.4f}  id={match.document_id}"
        if match.metadata.get("archetype_id"):
            line += f"  ({match.metadata['archetype_id']})"
        if match.document:
            source = match.document.get("source_name") or "?"
            payload = (match.document.get("content_payload") or "")[:80]
            line += f"  source={source}  payload={payload!r}"
        print(line)
    return 0


def _match_to_jsonable(match: SearchMatch) -> dict[str, Any]:
    return {
        "document_id": match.document_id,
        "score": match.score,
        "metadata": match.metadata,
        "document": match.document,
    }


if __name__ == "__main__":
    raise SystemExit(main())
