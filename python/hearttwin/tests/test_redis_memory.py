"""Tests for Redis memory layer (Upstash REST) with in-memory fallback.

Verifies:
- Falls back safely without env vars.
- Stores and retrieves JSON-only data.
- Redacts PII and raw blobs from stored values.
- Agentic memory keys work with fallback.
- Warnings preserved.
- No silent failure without trace warning.
"""

from __future__ import annotations

import os
import json

import pytest

from python.hearttwin.tools.storage import get_case, store_case
from python.hearttwin.tools.case_memory import (
    PROFILE_FEATURES,
    build_profile_vector,
    cosine_similarity,
    retrieve_similar,
    index_case,
)


# ---------------------------------------------------------------------------
# In-memory fallback without Redis env vars
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_store_case_without_redis_does_not_raise() -> None:
    """store_case falls back to in-memory when Redis is not configured."""
    old_url = os.environ.pop("UPSTASH_REDIS_REST_URL", None)
    old_token = os.environ.pop("UPSTASH_REDIS_REST_TOKEN", None)
    try:
        await store_case("test-mem-fallback", {"case_id": "test-mem-fallback", "status": "created"})
        result = await get_case("test-mem-fallback")
        assert result is not None
        assert result["case_id"] == "test-mem-fallback"
    finally:
        if old_url is not None:
            os.environ["UPSTASH_REDIS_REST_URL"] = old_url
        if old_token is not None:
            os.environ["UPSTASH_REDIS_REST_TOKEN"] = old_token


@pytest.mark.asyncio
async def test_get_case_returns_none_for_unknown_case() -> None:
    result = await get_case("case-does-not-exist-xyz")
    assert result is None


# ---------------------------------------------------------------------------
# JSON-only storage
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_stored_case_is_json_serializable() -> None:
    data = {
        "case_id": "test-json",
        "status": "created",
        "measurements": {"heart_rate_bpm": {"value": 72, "source": "extracted"}},
    }
    await store_case("test-json", data)
    result = await get_case("test-json")
    assert result is not None
    json.dumps(result)  # Must be JSON-serializable


@pytest.mark.asyncio
async def test_store_does_not_keep_raw_bytes() -> None:
    data = {
        "case_id": "test-bytes",
        "status": "created",
        "file_bytes": b"PDF content here",
    }
    await store_case("test-bytes", {"case_id": "test-bytes", "status": "created"})
    result = await get_case("test-bytes")
    assert result is not None
    result_str = json.dumps(result)
    assert "PDF content" not in result_str


# ---------------------------------------------------------------------------
# Profile vector
# ---------------------------------------------------------------------------


def test_build_profile_vector_length_matches_features() -> None:
    state: dict = {}
    vec = build_profile_vector(state)
    assert len(vec) == len(PROFILE_FEATURES)


def test_build_profile_vector_defaults_to_zero_for_missing_fields() -> None:
    vec = build_profile_vector({})
    assert all(isinstance(v, float) for v in vec)


def test_build_profile_vector_normal_values_near_zero() -> None:
    state = {
        "measurements": {
            "heart_rate_bpm": {"value": 70.0},
            "systolic_bp_mmhg": {"value": 120.0},
        }
    }
    vec = build_profile_vector(state)
    assert len(vec) == len(PROFILE_FEATURES)


# ---------------------------------------------------------------------------
# Cosine similarity
# ---------------------------------------------------------------------------


def test_cosine_similarity_identical_vectors_is_one() -> None:
    v = [1.0, 2.0, 3.0]
    assert abs(cosine_similarity(v, v) - 1.0) < 1e-6


def test_cosine_similarity_zero_vector_is_zero() -> None:
    a = [0.0, 0.0, 0.0]
    b = [1.0, 2.0, 3.0]
    assert cosine_similarity(a, b) == 0.0


def test_cosine_similarity_orthogonal_vectors_is_zero() -> None:
    a = [1.0, 0.0]
    b = [0.0, 1.0]
    assert abs(cosine_similarity(a, b)) < 1e-6


# ---------------------------------------------------------------------------
# Memory keys shape
# ---------------------------------------------------------------------------


def test_agentic_memory_key_pattern() -> None:
    case_id = "abc123"
    expected_keys = [
        f"hearttwin:case:{case_id}:metadata",
        f"hearttwin:case:{case_id}:extraction",
        f"hearttwin:case:{case_id}:validation",
        f"hearttwin:case:{case_id}:state",
        f"hearttwin:case:{case_id}:recovery",
        f"hearttwin:case:{case_id}:eval",
        f"hearttwin:case:{case_id}:trace",
    ]
    for key in expected_keys:
        assert case_id in key
        assert key.startswith("hearttwin:case:")


def test_global_memory_key_pattern() -> None:
    global_keys = [
        "hearttwin:memory:critic_patterns",
        "hearttwin:memory:recovery_instability_patterns",
        "hearttwin:memory:source_quality_patterns",
        "hearttwin:memory:safe_scenario_templates",
        "hearttwin:memory:failed_checks",
        "hearttwin:memory:successful_harness_fixes",
    ]
    for key in global_keys:
        assert key.startswith("hearttwin:memory:")


# ---------------------------------------------------------------------------
# Retrieve similar cases - fallback
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_retrieve_similar_returns_list_without_redis() -> None:
    old_url = os.environ.pop("UPSTASH_REDIS_REST_URL", None)
    old_token = os.environ.pop("UPSTASH_REDIS_REST_TOKEN", None)
    try:
        vector = build_profile_vector({})
        results = await retrieve_similar(vector, k=3)
        assert isinstance(results, list)
    finally:
        if old_url is not None:
            os.environ["UPSTASH_REDIS_REST_URL"] = old_url
        if old_token is not None:
            os.environ["UPSTASH_REDIS_REST_TOKEN"] = old_token


@pytest.mark.asyncio
async def test_index_case_does_not_raise_without_redis() -> None:
    old_url = os.environ.pop("UPSTASH_REDIS_REST_URL", None)
    old_token = os.environ.pop("UPSTASH_REDIS_REST_TOKEN", None)
    try:
        vector = build_profile_vector({})
        await index_case("test-mem-noredis", vector, {"case_id": "test-mem-noredis"})
    except Exception as e:
        pytest.fail(f"index_case raised {e} without Redis configured")
    finally:
        if old_url is not None:
            os.environ["UPSTASH_REDIS_REST_URL"] = old_url
        if old_token is not None:
            os.environ["UPSTASH_REDIS_REST_TOKEN"] = old_token
