"""Case memory + similar-case retrieval (Redis-backed, in-memory fallback).

Gives HeartTwin a real memory layer for the "Best Use of Redis" track:

  * a deterministic cardiac *profile vector* per case (pure function),
  * brute-force cosine KNN retrieval of similar prior cases,
  * Redis (Upstash REST) persistence with a transparent in-memory fallback,
  * prior *suggestions* derived from neighbours — clearly labelled as priors.

This mirrors ``tools/storage.py``: every Redis call is env-gated and wrapped in
``try/except`` so the module runs fully offline for local dev and tests.

Safety boundary
---------------
Retrieval produces *suggestions* with source ``similar_case_prior`` and low
confidence. It never invents measurements, diagnoses, or changes deterministic
formulas, and it never overwrites extracted or user-provided evidence — the
state builder remains the only place evidence is assembled.

Roadmap (documented in docs/PLANNING.md): swap the brute-force KNN for
Upstash Vector / RediSearch ``FT.SEARCH`` and add Redis Streams for the live
agent-trace event log. The pure functions below stay the stable seam.
"""

from __future__ import annotations

import json
import math
import os
import statistics
from typing import Any, Optional

# In-memory fallback store (module-level, like tools/storage.py).
_MEMORY_INDEX: dict[str, dict[str, Any]] = {}

# Ordered feature space for the cardiac profile vector.
# (group, field, typical, scale) — values are centred on a population typical
# and scaled, so a missing field contributes 0.0 (i.e. "behaves as typical")
# rather than skewing distance. Order is fixed and must not be reordered.
PROFILE_FEATURES: list[tuple[str, str, float, float]] = [
    ("measurements", "heart_rate_bpm", 70.0, 30.0),
    ("measurements", "systolic_bp_mmhg", 120.0, 30.0),
    ("measurements", "diastolic_bp_mmhg", 80.0, 20.0),
    ("measurements", "ejection_fraction_pct", 60.0, 15.0),
    ("measurements", "stroke_volume_ml", 80.0, 30.0),
    ("measurements", "cardiac_output_l_min", 5.0, 2.0),
    ("measurements", "edv_ml", 130.0, 40.0),
    ("measurements", "esv_ml", 50.0, 30.0),
    ("measurements", "oxygen_saturation_pct", 97.0, 5.0),
    ("electrophysiology", "qtc_ms", 430.0, 40.0),
    ("electrophysiology", "qrs_duration_ms", 95.0, 25.0),
]

# Stable dotted field keys, e.g. "measurements.edv_ml".
PROFILE_FIELDS: list[str] = [f"{group}.{field}" for group, field, _, _ in PROFILE_FEATURES]


# ---------------------------------------------------------------------------
# Pure functions (no IO) — fully unit-tested
# ---------------------------------------------------------------------------


def _measured_value(state: Any, group: str, field: str) -> Optional[float]:
    """Read a nested ``MeasuredValue.value`` off the state, or None if absent."""
    section = getattr(state, group, None)
    if section is None:
        return None
    measured = getattr(section, field, None)
    if measured is None:
        return None
    value = getattr(measured, "value", None)
    return None if value is None else float(value)


def build_profile_vector(state: Any) -> list[float]:
    """Deterministic normalized cardiac feature vector for a CardiacTwinState.

    Missing fields map to 0.0 (population typical). Pure and order-stable.
    """
    vector: list[float] = []
    for group, field, typical, scale in PROFILE_FEATURES:
        value = _measured_value(state, group, field)
        if value is None:
            vector.append(0.0)
        else:
            vector.append(round((value - typical) / scale, 6))
    return vector


def summarize_state(state: Any) -> dict[str, float]:
    """Compact {dotted_field: value} summary of the profile fields present."""
    summary: dict[str, float] = {}
    for group, field, _, _ in PROFILE_FEATURES:
        value = _measured_value(state, group, field)
        if value is not None:
            summary[f"{group}.{field}"] = round(value, 4)
    return summary


def cosine_similarity(a: list[float], b: list[float]) -> float:
    """Cosine similarity in [-1, 1]. Returns 0.0 if either vector is all-zero."""
    if len(a) != len(b):
        raise ValueError("Vectors must be equal length")
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(y * y for y in b))
    if norm_a == 0.0 or norm_b == 0.0:
        return 0.0
    return dot / (norm_a * norm_b)


def suggest_priors_from_neighbors(
    neighbors: list[dict[str, Any]],
    fields: list[str],
    *,
    min_neighbors: int = 1,
) -> list[dict[str, Any]]:
    """Derive *labelled prior suggestions* (medians) from retrieved neighbours.

    Only emits a suggestion for a requested field when at least ``min_neighbors``
    neighbours actually carry it — it never fabricates absent fields. Output is
    advisory metadata, not a MeasuredValue: the state builder decides whether to
    use it, and any value it adopts stays a low-confidence model prior.
    """
    suggestions: list[dict[str, Any]] = []
    for field in fields:
        values: list[float] = []
        contributors: list[str] = []
        for neighbor in neighbors:
            summary = neighbor.get("summary") or {}
            if field in summary and summary[field] is not None:
                values.append(float(summary[field]))
                contributors.append(neighbor.get("case_id"))
        if len(values) < min_neighbors:
            continue
        suggestions.append(
            {
                "field": field,
                "suggested_value": round(statistics.median(values), 4),
                "source": "similar_case_prior",
                "confidence": 0.3,
                "n_contributing_cases": len(values),
                "contributing_case_ids": contributors,
                "note": (
                    "Suggestion only — labelled prior, not evidence. Does not "
                    "overwrite extracted or user values."
                ),
            }
        )
    return suggestions


# ---------------------------------------------------------------------------
# Persistence (Upstash Redis REST, with in-memory fallback)
# ---------------------------------------------------------------------------


def _redis_config() -> Optional[tuple[str, str]]:
    url = os.environ.get("UPSTASH_REDIS_REST_URL", "")
    token = os.environ.get("UPSTASH_REDIS_REST_TOKEN", "")
    if url and token:
        return url, token
    return None


async def index_case(
    case_id: str,
    vector: list[float],
    summary: dict[str, Any],
    *,
    namespace: str = "casemem",
) -> bool:
    """Store a case profile for later retrieval.

    Always writes to the in-memory index. When Upstash is configured, also
    best-effort persists to Redis. Returns True iff the Redis write succeeded.
    """
    record = {"case_id": case_id, "vector": list(vector), "summary": dict(summary)}
    _MEMORY_INDEX[case_id] = record

    config = _redis_config()
    if config is None:
        return False

    url, token = config
    try:
        import httpx

        headers = {"Authorization": f"Bearer {token}"}
        async with httpx.AsyncClient() as client:
            await client.post(
                f"{url}/set/{namespace}:{case_id}",
                headers=headers,
                json=json.dumps(record),
                timeout=10.0,
            )
            await client.post(
                f"{url}/sadd/{namespace}:index/{case_id}",
                headers=headers,
                timeout=10.0,
            )
        return True
    except Exception:
        return False


async def _hydrate_from_redis(namespace: str) -> dict[str, dict[str, Any]]:
    """Best-effort pull of all indexed case records from Redis. Never raises."""
    config = _redis_config()
    if config is None:
        return {}

    url, token = config
    hydrated: dict[str, dict[str, Any]] = {}
    try:
        import httpx

        headers = {"Authorization": f"Bearer {token}"}
        async with httpx.AsyncClient() as client:
            members_resp = await client.get(
                f"{url}/smembers/{namespace}:index", headers=headers, timeout=10.0
            )
            case_ids = members_resp.json().get("result") or []
            for case_id in case_ids:
                if case_id in _MEMORY_INDEX:
                    continue
                value_resp = await client.get(
                    f"{url}/get/{namespace}:{case_id}", headers=headers, timeout=10.0
                )
                raw = value_resp.json().get("result")
                if raw:
                    hydrated[case_id] = json.loads(raw)
    except Exception:
        return hydrated
    return hydrated


async def retrieve_similar(
    vector: list[float],
    k: int = 3,
    *,
    exclude_case_id: Optional[str] = None,
    namespace: str = "casemem",
) -> list[dict[str, Any]]:
    """Return the top-``k`` most similar prior cases by cosine similarity.

    Reads the in-memory index, plus (best-effort) any Redis-only records. Pure
    ranking; safe and deterministic offline.
    """
    candidates: dict[str, dict[str, Any]] = dict(_MEMORY_INDEX)
    candidates.update(await _hydrate_from_redis(namespace))

    scored: list[dict[str, Any]] = []
    for case_id, record in candidates.items():
        if exclude_case_id is not None and case_id == exclude_case_id:
            continue
        candidate_vector = record.get("vector") or []
        if len(candidate_vector) != len(vector):
            continue
        scored.append(
            {
                "case_id": case_id,
                "similarity": round(cosine_similarity(vector, candidate_vector), 6),
                "summary": record.get("summary", {}),
            }
        )

    scored.sort(key=lambda row: row["similarity"], reverse=True)
    return scored[:k]
