"""Translate a free-text search prompt into per-facet retrieval weights.

The Tier-2 manifold has five facets (authority, type, modality, strictness,
tone). A naive search uses uniform weights, which means the prompt's intent
does not steer ranking. This planner asks Claude (tool_use, structured
output) to score each facet 0..1 based on what the prompt is *asking for*.

Examples of how the planner should behave:

- "compliance proof from Big Four" -> high authority, high strictness
- "casual lifestyle blog post"     -> low strictness, low formality bias
- "B2B sales email with urgency"   -> high modality, high tone (aggressive)
"""

from __future__ import annotations

from typing import Any

from .annotator.base import AnthropicLLMClient, LLMClient


FACET_NAMES = ("authority", "type", "modality", "strictness", "tone")
PLANNER_VERSION = "planner/v0.1"
DEFAULT_MODEL = "claude-haiku-4-5-20251001"

SYSTEM_PROMPT = """\
You translate user search prompts into facet weights for a faceted retrieval
system. Output a number between 0.0 and 1.0 per facet via the
`facet_weights` tool. 1.0 = the prompt strongly prioritises this facet.
0.0 = the prompt is indifferent to it.

Facet meanings:
- authority    : source credibility, institutional weight, expert provenance
- type         : asset type (text vs image vs timeseries) — high if the
                 prompt restricts type, low if any type is fine
- modality     : specific format (B2B email, landing page, fMRI scan)
- strictness   : regulatory / technical / compliance density
- tone         : formality, aggressiveness, creativity

Default unspecified facets to 0.5. Do not invert: a prompt asking for
"low strictness" still produces a HIGH strictness weight, because the
facet is salient to the ranking. Weights express salience, not direction.
Return only the tool call.
"""


_TOOL: dict[str, Any] = {
    "name": "facet_weights",
    "description": "Per-facet 0..1 salience weights for the search prompt.",
    "input_schema": {
        "type": "object",
        "properties": {
            facet: {"type": "number", "minimum": 0.0, "maximum": 1.0}
            for facet in FACET_NAMES
        },
        "required": list(FACET_NAMES),
        "additionalProperties": False,
    },
}


def plan_query(
    prompt: str,
    *,
    client: LLMClient | None = None,
    model: str = DEFAULT_MODEL,
) -> dict[str, float]:
    """Return ``{facet: 0..1}`` weights for the five facets, derived from the
    user's prompt by Claude. The keys exactly match
    ``data_annotation.hdc.FACET_ORDER``."""
    client = client or AnthropicLLMClient()
    raw = client.call_with_tool(
        model=model,
        system=SYSTEM_PROMPT,
        tool=_TOOL,
        content=[{"type": "text", "text": prompt}],
        max_tokens=256,
    )
    return {facet: float(raw[facet]) for facet in FACET_NAMES}
