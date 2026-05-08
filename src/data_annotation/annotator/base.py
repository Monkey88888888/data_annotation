from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass, field
from typing import Any, Callable, Protocol


# ---------------------------------------------------------------------------
# Facet column lists. Mirror documents_raw -- if you add a column there,
# add it here so the LLM tool_use schema covers it.
# ---------------------------------------------------------------------------

CONTINUOUS_FACETS = (
    "auth_domain",
    "auth_author",
    "auth_institution",
    "strict_regulatory",
    "strict_technicality",
    "tone_formality",
    "tone_aggressiveness",
    "tone_creativity",
)

BOOLEAN_FACETS = (
    "type_text",
    "type_image",
    "type_timeseries",
    "modality_b2b_email",
    "modality_landing_page",
    "modality_fmri_t1",
    "modality_fmri_bold",
)


# ---------------------------------------------------------------------------
# Annotation result
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class AnnotationResult:
    asset_hash: str
    annotator_version: str
    archetype_id: str
    annotator_kind: str           # 'text' | 'image'
    model: str
    facets: dict[str, Any]        # subset of CONTINUOUS_FACETS + BOOLEAN_FACETS
    raw_response: dict[str, Any] = field(default_factory=dict)

    def to_db_row(self, document_id: str | None = None) -> dict[str, Any]:
        return {
            "asset_hash": self.asset_hash,
            "annotator_version": self.annotator_version,
            "document_id": document_id,
            "archetype_id": self.archetype_id,
            "annotator_kind": self.annotator_kind,
            "model": self.model,
            "facets": self.facets,
            "raw_response": self.raw_response,
        }


# ---------------------------------------------------------------------------
# Hashing
# ---------------------------------------------------------------------------

def hash_payload(payload: bytes | str) -> str:
    """Stable cache key for an asset payload.

    For text we hash the UTF-8 bytes; for images the file bytes. Same payload
    + same annotator version = cache hit, no second LLM call.
    """
    if isinstance(payload, str):
        payload = payload.encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


# ---------------------------------------------------------------------------
# Tool schema
# ---------------------------------------------------------------------------

def build_facet_tool_schema(
    archetype_id: str,
    facet_names: tuple[str, ...],
) -> dict[str, Any]:
    """Anthropic tool_use schema that forces the model to fill in named facets.

    We pass only the facets that make sense for the given archetype rather
    than the union -- a text annotator should not be invited to set
    `modality_fmri_bold`.
    """
    properties: dict[str, Any] = {}
    for name in facet_names:
        if name in BOOLEAN_FACETS:
            properties[name] = {"type": "boolean"}
        elif name in CONTINUOUS_FACETS:
            properties[name] = {"type": "number", "minimum": 0.0, "maximum": 1.0}
        else:
            raise ValueError(f"unknown facet {name!r}")

    return {
        "name": "record_facets",
        "description": (
            f"Record the faceted annotation for an asset of archetype {archetype_id!r}. "
            "All listed facets must be present."
        ),
        "input_schema": {
            "type": "object",
            "properties": properties,
            "required": list(facet_names),
            "additionalProperties": False,
        },
    }


# ---------------------------------------------------------------------------
# LLM client protocol
# ---------------------------------------------------------------------------

class LLMClient(Protocol):
    """Abstraction over the Anthropic SDK so we can mock in tests."""

    def call_with_tool(
        self,
        *,
        model: str,
        system: str,
        tool: dict[str, Any],
        content: list[dict[str, Any]],
        max_tokens: int,
    ) -> dict[str, Any]:
        """Invoke the model and return the parsed tool_use input dict."""


class AnthropicLLMClient:
    """Real client. Lazy-imports anthropic so the package stays importable
    without the dependency installed (relevant for unit tests)."""

    def __init__(self, api_key: str | None = None):
        api_key = api_key or os.environ.get("ANTHROPIC_API_KEY")
        if not api_key:
            raise RuntimeError("ANTHROPIC_API_KEY not set")
        from anthropic import Anthropic  # local import — soft dependency
        self._client = Anthropic(api_key=api_key)

    def call_with_tool(
        self,
        *,
        model: str,
        system: str,
        tool: dict[str, Any],
        content: list[dict[str, Any]],
        max_tokens: int,
    ) -> dict[str, Any]:
        response = self._client.messages.create(
            model=model,
            max_tokens=max_tokens,
            system=system,
            tools=[tool],
            tool_choice={"type": "tool", "name": tool["name"]},
            messages=[{"role": "user", "content": content}],
        )
        for block in response.content:
            if block.type == "tool_use" and block.name == tool["name"]:
                return dict(block.input)
        raise RuntimeError("model did not return the expected tool_use block")


# ---------------------------------------------------------------------------
# Registry (Option A)
# ---------------------------------------------------------------------------

AnnotateFn = Callable[..., AnnotationResult]


class AnnotatorVersionError(RuntimeError):
    pass


class AnnotatorRegistry:
    """Maps archetype_id -> annotate function. Mirrors the rubric registry
    pattern from ingestion.py (Option A)."""

    def __init__(self) -> None:
        self._fns: dict[str, AnnotateFn] = {}

    def register(self, archetype_id: str, fn: AnnotateFn) -> None:
        if archetype_id in self._fns:
            raise AnnotatorVersionError(
                f"annotator already registered for archetype {archetype_id!r}"
            )
        self._fns[archetype_id] = fn

    def get(self, archetype_id: str) -> AnnotateFn:
        if archetype_id not in self._fns:
            raise KeyError(f"no annotator registered for archetype {archetype_id!r}")
        return self._fns[archetype_id]

    def __contains__(self, archetype_id: str) -> bool:
        return archetype_id in self._fns


annotator_registry = AnnotatorRegistry()


# ---------------------------------------------------------------------------
# JSON helpers (raw_response is JSONB-bound on the DB side)
# ---------------------------------------------------------------------------

def jsonable(value: Any) -> Any:
    """Coerce to a JSON-serialisable shape so raw_response always round-trips."""
    return json.loads(json.dumps(value, default=str))
