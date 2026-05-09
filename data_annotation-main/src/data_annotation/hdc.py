from __future__ import annotations

import hashlib
import math
import random


FACET_ORDER = ("authority", "type", "modality", "strictness", "tone")


def stable_bipolar_vector(seed: str, dimension: int) -> list[float]:
    digest = hashlib.sha256(seed.encode("utf-8")).digest()
    rng = random.Random(digest)
    return [1.0 if rng.getrandbits(1) else -1.0 for _ in range(dimension)]


def bind(left: list[float], right: list[float], scale: float = 1.0) -> list[float]:
    if len(left) != len(right):
        raise ValueError("vectors must have the same length")
    return [left[index] * right[index] * scale for index in range(len(left))]


def add_vectors(vectors: list[list[float]]) -> list[float]:
    if not vectors:
        return []
    dimension = len(vectors[0])
    totals = [0.0] * dimension
    for vector in vectors:
        if len(vector) != dimension:
            raise ValueError("vectors must have the same length")
        for index, value in enumerate(vector):
            totals[index] += value
    return totals


def block_project(seed: str, vector: list[float], target_dimension: int) -> list[float]:
    """Project a high-dimensional vector into a deterministic low-rank sector."""
    if target_dimension <= 0:
        raise ValueError("target_dimension must be positive")

    digest = hashlib.sha256(seed.encode("utf-8")).digest()
    rng = random.Random(digest)
    output: list[float] = []
    source_dimension = len(vector)
    sample_size = min(64, source_dimension)
    for _ in range(target_dimension):
        total = 0.0
        for _ in range(sample_size):
            source_index = rng.randrange(source_dimension)
            sign = 1.0 if rng.getrandbits(1) else -1.0
            total += vector[source_index] * sign
        output.append(total / math.sqrt(sample_size))
    return output


def cosine_similarity(left: list[float], right: list[float]) -> float:
    if len(left) != len(right):
        raise ValueError("vectors must have the same length")
    dot = sum(a * b for a, b in zip(left, right))
    left_norm = math.sqrt(sum(value * value for value in left))
    right_norm = math.sqrt(sum(value * value for value in right))
    if left_norm == 0.0 or right_norm == 0.0:
        return 0.0
    return dot / (left_norm * right_norm)


def normalize_weights(weights: dict[str, float]) -> dict[str, float]:
    normalized = {facet: float(weights.get(facet, 1.0)) for facet in FACET_ORDER}
    return {facet: max(0.0, value) for facet, value in normalized.items()}

