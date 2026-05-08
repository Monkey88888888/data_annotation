from __future__ import annotations

import hashlib
import json
import random
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class Facet:
    name: str
    seed: str
    value: str | None = None
    role: str | None = None


@dataclass(frozen=True)
class Archetype:
    id: str
    version: str
    dimension: int
    facets: tuple[Facet, ...]
    raw: dict[str, Any]

    @classmethod
    def from_file(cls, path: Path) -> "Archetype":
        data = json.loads(path.read_text())
        facets = tuple(Facet(**facet) for facet in data["facets"])
        return cls(
            id=data["id"],
            version=data["version"],
            dimension=int(data["dimension"]),
            facets=facets,
            raw=data,
        )

    def master_matrix_preview(self, sample_size: int = 8) -> dict[str, list[int]]:
        """Return deterministic bipolar vector samples for each archetype facet.

        This is a lightweight Step 1 representation. We keep full 10k-dimensional
        vectors implicit until ingestion needs numeric HDC operations.
        """
        return {
            facet.name: bipolar_vector_sample(facet.seed, self.dimension, sample_size)
            for facet in self.facets
        }


def bipolar_vector_sample(seed: str, dimension: int, sample_size: int) -> list[int]:
    if sample_size > dimension:
        raise ValueError("sample_size cannot exceed dimension")
    digest = hashlib.sha256(seed.encode("utf-8")).digest()
    rng = random.Random(digest)
    return [1 if rng.getrandbits(1) else -1 for _ in range(sample_size)]


def default_archetype_path(name: str) -> Path:
    return Path(__file__).resolve().parents[2] / "configs" / "archetypes" / f"{name}.json"

