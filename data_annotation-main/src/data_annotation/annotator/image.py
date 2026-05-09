from __future__ import annotations

import base64
from pathlib import Path
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


ARCHETYPE_ID = "image_asset"
ANNOTATOR_VERSION = "image/v0.1"
DEFAULT_MODEL = "claude-sonnet-4-6"

IMAGE_FACETS = (
    "type_image",
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
Given a business image (ad, slide, screenshot, infographic), you record its
facet values via the `record_facets` tool.

Read both visual structure (composition, color palette, typography) and any
text the image contains. The facet definitions are the same as for text:

- strict_regulatory: legal/compliance copy density in the image (0..1).
- strict_technicality: density of domain-specific terminology (0..1).
- tone_formality: 0 = casual/playful, 1 = corporate/austere.
- tone_aggressiveness: 0 = soft/measured, 1 = urgent CTA / shock copy.
- tone_creativity: 0 = stock/literal, 1 = bold/metaphorical visual concept.

Booleans:
- type_image: always true for this annotator.
- modality_b2b_email: the image is an email banner/header for B2B outbound.
- modality_landing_page: the image is hero/section art for a landing page.

Pick the single best modality_* if both fit; set the other to false.
Return only the tool call.
"""

# Anthropic image input MIME type whitelist.
_SUPPORTED_MEDIA_TYPES = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".gif": "image/gif",
    ".webp": "image/webp",
}


def _media_type_for(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix not in _SUPPORTED_MEDIA_TYPES:
        raise ValueError(f"unsupported image extension {suffix!r}")
    return _SUPPORTED_MEDIA_TYPES[suffix]


def annotate_image(
    payload: bytes | Path | str,
    *,
    media_type: str | None = None,
    client: LLMClient | None = None,
    model: str = DEFAULT_MODEL,
) -> AnnotationResult:
    """Run the image annotator. ``payload`` is either raw bytes (with
    ``media_type`` set) or a filesystem path."""
    if isinstance(payload, (str, Path)):
        path = Path(payload)
        media_type = media_type or _media_type_for(path)
        data = path.read_bytes()
    else:
        data = payload
        if media_type is None:
            raise ValueError("media_type is required when passing raw bytes")

    client = client or AnthropicLLMClient()
    tool = build_facet_tool_schema(ARCHETYPE_ID, IMAGE_FACETS)
    facets = client.call_with_tool(
        model=model,
        system=SYSTEM_PROMPT,
        tool=tool,
        content=[
            {
                "type": "image",
                "source": {
                    "type": "base64",
                    "media_type": media_type,
                    "data": base64.standard_b64encode(data).decode("ascii"),
                },
            },
            {"type": "text", "text": "Annotate the image."},
        ],
        max_tokens=512,
    )

    return AnnotationResult(
        asset_hash=hash_payload(data),
        annotator_version=ANNOTATOR_VERSION,
        archetype_id=ARCHETYPE_ID,
        annotator_kind="image",
        model=model,
        facets=jsonable(facets),
        raw_response={"tool_input": jsonable(facets), "media_type": media_type},
    )


annotator_registry.register(ARCHETYPE_ID, annotate_image)
