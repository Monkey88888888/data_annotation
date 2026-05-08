from __future__ import annotations

from typing import Any

from .base import (
    AnnotationResult,
    AnthropicLLMClient,
    LLMClient,
    annotator_registry,
    build_facet_tool_schema,
    hash_payload,
    jsonable,
)


ARCHETYPE_ID = "text_document"
ANNOTATOR_VERSION = "text/v0.1"
DEFAULT_MODEL = "claude-haiku-4-5-20251001"

TEXT_FACETS = (
    "type_text",
    "modality_b2b_email",
    "modality_landing_page",
    "strict_regulatory",
    "strict_technicality",
    "tone_formality",
    "tone_aggressiveness",
    "tone_creativity",
)

SYSTEM_PROMPT = """\
You are a structured annotator for a faceted hyperdimensional retrieval system.
Given a piece of business text, you record its facet values via the
`record_facets` tool.

Definitions for continuous facets (0.0..1.0):
- strict_regulatory: how strongly the text is constrained by legal/compliance
  language (0 = casual marketing, 1 = SEC filing).
- strict_technicality: density of domain jargon and precise terminology
  (0 = elementary, 1 = expert-level).
- tone_formality: 0 = casual/conversational, 1 = formal/business.
- tone_aggressiveness: 0 = soft/measured, 1 = forceful/urgent CTA.
- tone_creativity: 0 = straight reportage, 1 = highly creative/metaphorical.

Definitions for booleans:
- type_text: always true for this annotator.
- modality_b2b_email: the text reads as a B2B sales/outbound email.
- modality_landing_page: the text reads as web landing-page copy.

Pick the single best modality_* if both fit; set the other to false. If
neither fits, set both to false. Always set type_text=true.
Return only the tool call.
"""


def annotate_text(
    payload: str,
    *,
    client: LLMClient | None = None,
    model: str = DEFAULT_MODEL,
) -> AnnotationResult:
    """Run the text annotator on a payload string and return facet values."""
    client = client or AnthropicLLMClient()
    tool = build_facet_tool_schema(ARCHETYPE_ID, TEXT_FACETS)
    facets = client.call_with_tool(
        model=model,
        system=SYSTEM_PROMPT,
        tool=tool,
        content=[{"type": "text", "text": payload}],
        max_tokens=512,
    )

    return AnnotationResult(
        asset_hash=hash_payload(payload),
        annotator_version=ANNOTATOR_VERSION,
        archetype_id=ARCHETYPE_ID,
        annotator_kind="text",
        model=model,
        facets=jsonable(facets),
        raw_response={"tool_input": jsonable(facets)},
    )


annotator_registry.register(ARCHETYPE_ID, annotate_text)
