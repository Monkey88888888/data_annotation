"""LLM annotator stage.

For unstructured assets (text, image) we cannot read facet values out of a
struct-packed header the way `ingestion.py` reads NIfTI. Instead, an LLM
fills in the facet row deterministically via tool_use with a JSON schema.

The HDC pipeline downstream is unchanged — it consumes facet values, which
can come from a human operator (Supabase Table Editor) or from this
annotator. Same destination, two writers.
"""

from .base import (
    AnnotationResult,
    AnnotatorRegistry,
    AnnotatorVersionError,
    annotator_registry,
)

# Import the per-archetype modules for their side-effect: each one registers
# itself with annotator_registry on import.
from . import image as _image  # noqa: F401
from . import text as _text  # noqa: F401

__all__ = [
    "AnnotationResult",
    "AnnotatorRegistry",
    "AnnotatorVersionError",
    "annotator_registry",
]
