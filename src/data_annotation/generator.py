"""LLM-backed generation from retrieved context.

Two surfaces:

- ``generate_text_from_context(prompt, examples)`` -- given a user prompt
  and a list of retrieved documents (from ``pinecone_search.search``),
  asks Claude to write new text that fulfils the prompt while adopting
  the voice/style of the examples. Used by ``/api/text/generate``.

- ``generate_image_brief_from_context(prompt, examples)`` -- same idea
  for visuals: given retrieved image rows (with their facet annotations),
  produces a written creative brief describing what a *new* image in
  this space should look like. Image *synthesis* (an actual pixel
  generator) is out of scope; the brief is what couples to a designer
  or a separate image-generation model downstream.
"""

from __future__ import annotations

import json
import os
from typing import Any, Protocol


DEFAULT_TEXT_MODEL = "claude-sonnet-4-6"
DEFAULT_BRIEF_MODEL = "claude-haiku-4-5-20251001"

TEXT_GEN_SYSTEM = """\
You are a copywriter for a B2B SaaS team. Given the user's request and
example documents that match the desired style and intent, write new
text that:

- Fulfils the user's request literally
- Adopts the voice, tone, and structural choices of the examples
- Stays roughly the same length as the examples (do not pad)

Return only the new text. No preamble, no explanation, no headers.
"""

IMAGE_BRIEF_SYSTEM = """\
You are a creative director writing a brief for a designer (or a
downstream image-generation model). Given the user's prompt and the
facet annotations of retrieved example images, write a short brief
(2-4 sentences) describing what a new image in this space should look
like. Cover composition, color, mood, and any text/typography.

Return only the brief. No preamble, no headers.
"""


# ---------------------------------------------------------------------------
# Generator protocol (lets tests inject a stub instead of the real SDK)
# ---------------------------------------------------------------------------

class TextGenerator(Protocol):
    def generate(self, *, system: str, user: str, model: str, max_tokens: int) -> str: ...


class AnthropicTextGenerator:
    def __init__(self, client: Any | None = None):
        if client is None:
            from anthropic import Anthropic
            api_key = os.environ.get("ANTHROPIC_API_KEY")
            if not api_key:
                raise RuntimeError("ANTHROPIC_API_KEY not set")
            client = Anthropic(api_key=api_key)
        self._client = client

    def generate(self, *, system: str, user: str, model: str, max_tokens: int) -> str:
        response = self._client.messages.create(
            model=model,
            max_tokens=max_tokens,
            system=system,
            messages=[{"role": "user", "content": user}],
        )
        chunks: list[str] = []
        for block in response.content:
            text = getattr(block, "text", None)
            if text:
                chunks.append(text)
        return "".join(chunks).strip()


# ---------------------------------------------------------------------------
# Text generation
# ---------------------------------------------------------------------------

def _format_text_examples(examples: list[dict[str, Any]], char_budget: int = 1500) -> str:
    blocks: list[str] = []
    for index, example in enumerate(examples, start=1):
        source = example.get("source_name") or f"example-{index}"
        payload = (example.get("content_payload") or "")[:char_budget]
        blocks.append(f"Example {index} ({source}):\n{payload}".strip())
    return "\n\n".join(blocks) if blocks else "(none)"


def generate_text_from_context(
    prompt: str,
    examples: list[dict[str, Any]],
    *,
    generator: TextGenerator | None = None,
    model: str = DEFAULT_TEXT_MODEL,
    max_tokens: int = 800,
) -> str:
    """Return new text for ``prompt`` styled after ``examples``.

    ``examples`` is a list of dicts with at least ``content_payload`` and
    optionally ``source_name``. ``pinecone_search.search(..., enrich=True)``
    matches expose this shape via ``match.document``."""
    generator = generator or AnthropicTextGenerator()
    user_msg = (
        f"User request: {prompt}\n\n"
        f"Style examples:\n{_format_text_examples(examples)}\n\n"
        "Write the new text now."
    )
    return generator.generate(
        system=TEXT_GEN_SYSTEM,
        user=user_msg,
        model=model,
        max_tokens=max_tokens,
    )


# ---------------------------------------------------------------------------
# Image-brief generation
# ---------------------------------------------------------------------------

_FACET_KEYS_FOR_BRIEF = (
    "modality_b2b_email", "modality_landing_page",
    "strict_regulatory", "strict_technicality",
    "tone_formality", "tone_aggressiveness", "tone_creativity",
)


def _format_image_examples(examples: list[dict[str, Any]]) -> str:
    blocks: list[str] = []
    for index, example in enumerate(examples, start=1):
        source = example.get("source_name") or f"image-{index}"
        facets = {k: example.get(k) for k in _FACET_KEYS_FOR_BRIEF if k in example}
        blocks.append(
            f"Reference {index} ({source}):\n{json.dumps(facets, indent=2, sort_keys=True)}"
        )
    return "\n\n".join(blocks) if blocks else "(none)"


def generate_image_brief_from_context(
    prompt: str,
    examples: list[dict[str, Any]],
    *,
    generator: TextGenerator | None = None,
    model: str = DEFAULT_BRIEF_MODEL,
    max_tokens: int = 400,
) -> str:
    """Return a written creative brief for an image matching ``prompt``,
    informed by ``examples`` (retrieved image rows with their facet
    annotations)."""
    generator = generator or AnthropicTextGenerator()
    user_msg = (
        f"User request: {prompt}\n\n"
        f"Reference image annotations:\n{_format_image_examples(examples)}\n\n"
        "Write the brief now."
    )
    return generator.generate(
        system=IMAGE_BRIEF_SYSTEM,
        user=user_msg,
        model=model,
        max_tokens=max_tokens,
    )
