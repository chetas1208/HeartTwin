"""Tests for the Redis-backed case-memory + similar-case retrieval tool.

All tests run fully offline against the in-memory fallback — no network, no
Upstash credentials. They assert the pure vector/similarity functions, the
KNN ranking, the safe prior-suggestion behaviour, and the graceful no-Redis
fallback.
"""

import pytest

from python.hearttwin.schemas import (
    CardiacTwinState,
    Electrophysiology,
    MeasuredValue,
    Measurements,
    ValueSource,
)
from python.hearttwin.tools.case_memory import (
    _MEMORY_INDEX,
    PROFILE_FIELDS,
    build_profile_vector,
    cosine_similarity,
    index_case,
    retrieve_similar,
    suggest_priors_from_neighbors,
    summarize_state,
)


@pytest.fixture(autouse=True)
def _clear_memory(monkeypatch):
    """Isolate each test: no Redis env, empty in-memory index."""
    monkeypatch.delenv("UPSTASH_REDIS_REST_URL", raising=False)
    monkeypatch.delenv("UPSTASH_REDIS_REST_TOKEN", raising=False)
    _MEMORY_INDEX.clear()
    yield
    _MEMORY_INDEX.clear()


def _mv(value, unit="", source=ValueSource.FILE_EXTRACTION, confidence=0.9):
    return MeasuredValue(value=value, unit=unit, source=source, confidence=confidence)


def _state(case_id, *, hr=70, ef=60, sv=80, co=5.0, qtc=None):
    return CardiacTwinState(
        case_id=case_id,
        measurements=Measurements(
            heart_rate_bpm=_mv(hr, "bpm"),
            ejection_fraction_pct=_mv(ef, "%"),
            stroke_volume_ml=_mv(sv, "mL"),
            cardiac_output_l_min=_mv(co, "L/min"),
        ),
        electrophysiology=Electrophysiology(qtc_ms=_mv(qtc, "ms")) if qtc else Electrophysiology(),
    )


# ---------------------------------------------------------------------------
# Profile vector
# ---------------------------------------------------------------------------


class TestProfileVector:
    def test_length_matches_feature_space(self):
        vec = build_profile_vector(_state("a"))
        assert len(vec) == len(PROFILE_FIELDS)

    def test_deterministic(self):
        state = _state("a", hr=88, ef=47, sv=62, co=3.6)
        assert build_profile_vector(state) == build_profile_vector(state)

    def test_missing_fields_are_neutral_zero(self):
        # Empty state → every feature falls back to its population typical → 0.0
        vec = build_profile_vector(CardiacTwinState(case_id="empty"))
        assert vec == [0.0] * len(PROFILE_FIELDS)

    def test_typical_values_center_to_zero(self):
        # All-typical inputs should also produce the zero vector.
        vec = build_profile_vector(_state("typ", hr=70, ef=60, sv=80, co=5.0))
        assert vec == [0.0] * len(PROFILE_FIELDS)

    def test_qtc_feature_populates_electrophysiology_slot(self):
        idx = PROFILE_FIELDS.index("electrophysiology.qtc_ms")
        vec = build_profile_vector(_state("a", qtc=510))
        assert vec[idx] != 0.0


# ---------------------------------------------------------------------------
# Cosine similarity
# ---------------------------------------------------------------------------


class TestCosineSimilarity:
    def test_identity_is_one(self):
        v = [0.5, -0.3, 1.2, 0.0]
        assert abs(cosine_similarity(v, v) - 1.0) < 1e-9

    def test_opposite_is_minus_one(self):
        v = [1.0, 2.0, -1.0]
        w = [-1.0, -2.0, 1.0]
        assert abs(cosine_similarity(v, w) + 1.0) < 1e-9

    def test_zero_vector_is_zero(self):
        assert cosine_similarity([0.0, 0.0], [1.0, 1.0]) == 0.0

    def test_length_mismatch_raises(self):
        with pytest.raises(ValueError):
            cosine_similarity([1.0], [1.0, 2.0])


# ---------------------------------------------------------------------------
# Indexing + retrieval
# ---------------------------------------------------------------------------


class TestIndexAndRetrieve:
    async def test_index_without_redis_returns_false_but_stores_in_memory(self):
        state = _state("c1", hr=90, ef=45)
        persisted = await index_case("c1", build_profile_vector(state), summarize_state(state))
        assert persisted is False
        assert "c1" in _MEMORY_INDEX

    async def test_retrieve_empty_returns_empty_list(self):
        assert await retrieve_similar(build_profile_vector(_state("q"))) == []

    async def test_retrieve_ranks_nearest_first(self):
        low = _state("low", hr=115, ef=32, sv=48, co=2.4)
        normal = _state("normal", hr=64, ef=63, sv=86, co=5.3)
        mid = _state("mid", hr=86, ef=50, sv=70, co=4.0)
        for cid, st in [("low", low), ("normal", normal), ("mid", mid)]:
            await index_case(cid, build_profile_vector(st), summarize_state(st))

        query = build_profile_vector(_state("q", hr=116, ef=31, sv=47, co=2.3))
        results = await retrieve_similar(query, k=3)

        assert [r["case_id"] for r in results][0] == "low"
        assert results[0]["similarity"] >= results[-1]["similarity"]

    async def test_retrieve_excludes_self(self):
        st = _state("self", hr=92, ef=44)
        await index_case("self", build_profile_vector(st), summarize_state(st))
        results = await retrieve_similar(build_profile_vector(st), exclude_case_id="self")
        assert all(r["case_id"] != "self" for r in results)

    async def test_retrieve_respects_k(self):
        for i in range(5):
            st = _state(f"c{i}", hr=70 + i * 8, ef=60 - i * 4)
            await index_case(f"c{i}", build_profile_vector(st), summarize_state(st))
        results = await retrieve_similar(build_profile_vector(_state("q", hr=95, ef=48)), k=2)
        assert len(results) == 2


# ---------------------------------------------------------------------------
# Prior suggestions (safety-critical: must stay labelled and never fabricate)
# ---------------------------------------------------------------------------


class TestSuggestPriors:
    def _neighbors(self):
        return [
            {"case_id": "n1", "similarity": 0.98, "summary": {"measurements.edv_ml": 120.0}},
            {"case_id": "n2", "similarity": 0.95, "summary": {"measurements.edv_ml": 140.0}},
        ]

    def test_median_suggestion_is_labelled_prior(self):
        out = suggest_priors_from_neighbors(self._neighbors(), ["measurements.edv_ml"])
        assert len(out) == 1
        s = out[0]
        assert s["suggested_value"] == 130.0
        assert s["source"] == "similar_case_prior"
        assert s["confidence"] < 1.0
        assert s["n_contributing_cases"] == 2

    def test_absent_field_is_not_fabricated(self):
        out = suggest_priors_from_neighbors(self._neighbors(), ["measurements.bnp_pg_ml"])
        assert out == []

    def test_min_neighbors_threshold(self):
        out = suggest_priors_from_neighbors(
            self._neighbors(), ["measurements.edv_ml"], min_neighbors=3
        )
        assert out == []
