"""Tests for Agent 4: Cardiac State Builder Agent.

Coverage:
- valid EDV/ESV derives SV/EF deterministically
- HR + SV derives CO
- SBP/DBP derives MAP
- missing EDV/ESV does not invent SV
- priors are labelled default_model_prior with capped confidence and warnings
- derived values have source map entries with method=deterministic_formula
- user-provided values are never overwritten by priors
- operating environment defaults are applied when not supplied
- output validates against CardiacTwinState schema
- agent_id / agent_name are correct
- data_quality_score is produced
- source_map is non-empty
"""

from __future__ import annotations

import pytest
import pytest_asyncio

from python.hearttwin.agents.state_builder_agent import (
    _AGENT_ID,
    _AGENT_NAME,
    _PRIOR_CONFIDENCE_CAP,
    run_state_builder_agent,
)
from python.hearttwin.schemas import (
    AgentStatus,
    CardiacTwinState,
    SafetyLevel,
    ValueSource,
)


# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------

_FULL_VITALS: dict = {
    "heart_rate_bpm": {"value": 72, "unit": "bpm", "source": "user_input", "confidence": 0.9},
    "systolic_bp_mmhg": {"value": 130, "unit": "mmHg", "source": "user_input", "confidence": 0.85},
    "diastolic_bp_mmhg": {"value": 85, "unit": "mmHg", "source": "user_input", "confidence": 0.85},
    "edv_ml": {"value": 140, "unit": "mL", "source": "file_extraction", "confidence": 0.8},
    "esv_ml": {"value": 60, "unit": "mL", "source": "file_extraction", "confidence": 0.8},
    "age_years": {"value": 55, "unit": "years", "source": "user_input", "confidence": 0.9},
    "height_cm": {"value": 175, "unit": "cm", "source": "user_input", "confidence": 0.9},
    "weight_kg": {"value": 80, "unit": "kg", "source": "user_input", "confidence": 0.9},
    "sex": {"value": "male", "source": "user_input", "confidence": 0.9},
}

_MINIMAL_VITALS: dict = {
    "heart_rate_bpm": {"value": 68, "unit": "bpm", "source": "user_input", "confidence": 0.8},
    "systolic_bp_mmhg": {"value": 125, "unit": "mmHg", "source": "user_input", "confidence": 0.8},
    "diastolic_bp_mmhg": {"value": 80, "unit": "mmHg", "source": "user_input", "confidence": 0.8},
}


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------

def _source_map_entry(source_map, field: str):
    """Return the first source map entry for the given field, or None."""
    for entry in source_map:
        if entry.field == field:
            return entry
    return None


# ---------------------------------------------------------------------------
# Deterministic derivation tests
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_sv_ef_derived_from_edv_esv():
    """SV = EDV - ESV and EF = SV/EDV*100 when real EDV/ESV evidence is present."""
    resp, state = await run_state_builder_agent(
        validated_fields=_FULL_VITALS,
        case_id="test-sv-ef",
    )
    sv = state.measurements.stroke_volume_ml
    ef = state.measurements.ejection_fraction_pct

    assert sv is not None, "stroke_volume_ml must be derived"
    assert ef is not None, "ejection_fraction_pct must be derived"

    assert abs(sv.value - (140 - 60)) < 0.01, "SV = EDV - ESV = 80 mL"
    assert abs(ef.value - (80 / 140 * 100)) < 0.1, "EF = SV/EDV*100 ≈ 57.14%"

    assert sv.source == ValueSource.DERIVED
    assert ef.source == ValueSource.DERIVED
    assert sv.method == "deterministic_formula"
    assert ef.method == "deterministic_formula"


@pytest.mark.asyncio
async def test_co_derived_from_hr_and_sv():
    """CO = HR * SV / 1000 when real HR and derived SV are available."""
    resp, state = await run_state_builder_agent(
        validated_fields=_FULL_VITALS,
        case_id="test-co",
    )
    co = state.measurements.cardiac_output_l_min
    assert co is not None, "cardiac_output_l_min must be derived"
    expected_co = 72 * 80 / 1000
    assert abs(co.value - expected_co) < 0.05, f"CO should be ~{expected_co} L/min"
    assert co.source == ValueSource.DERIVED


@pytest.mark.asyncio
async def test_map_derived_from_bp():
    """MAP = DBP + (SBP - DBP)/3 is recorded in the source map."""
    resp, state = await run_state_builder_agent(
        validated_fields=_FULL_VITALS,
        case_id="test-map",
    )
    map_entry = _source_map_entry(state.source_map, "map_mmhg")
    assert map_entry is not None, "map_mmhg must appear in source map"
    expected_map = 85 + (130 - 85) / 3
    assert abs(map_entry.value - expected_map) < 0.5
    assert map_entry.source == ValueSource.DERIVED
    assert map_entry.method == "deterministic_formula"


@pytest.mark.asyncio
async def test_rr_interval_derived_from_hr():
    """RR interval = 60000 / HR is derived when HR is known."""
    resp, state = await run_state_builder_agent(
        validated_fields=_FULL_VITALS,
        case_id="test-rr",
    )
    rr = state.electrophysiology.rr_interval_ms
    assert rr is not None
    expected_rr = 60000 / 72
    assert abs(rr.value - expected_rr) < 1.0
    assert rr.source == ValueSource.DERIVED


# ---------------------------------------------------------------------------
# Missing EDV/ESV — no SV invented
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_missing_edv_esv_does_not_invent_sv():
    """Without real EDV/ESV evidence, stroke volume must not be derived or guessed."""
    resp, state = await run_state_builder_agent(
        validated_fields=_MINIMAL_VITALS,
        case_id="test-no-sv",
    )
    sv = state.measurements.stroke_volume_ml
    # SV may be filled from a population prior but must NOT be source=DERIVED
    if sv is not None:
        assert sv.source != ValueSource.DERIVED, (
            "SV must not be marked as DERIVED when EDV/ESV are absent"
        )
    # Warning must mention the absence
    full_text = " ".join(resp.warnings)
    assert "edv" in full_text.lower() or "stroke volume" in full_text.lower(), (
        "A warning must acknowledge that SV could not be derived"
    )


@pytest.mark.asyncio
async def test_invalid_edv_esv_does_not_derive_sv():
    """When ESV >= EDV (physiologically impossible), SV must not be derived."""
    bad_volumes = {
        **_MINIMAL_VITALS,
        "edv_ml": {"value": 60, "unit": "mL", "source": "file_extraction", "confidence": 0.8},
        "esv_ml": {"value": 90, "unit": "mL", "source": "file_extraction", "confidence": 0.8},
    }
    resp, state = await run_state_builder_agent(
        validated_fields=bad_volumes,
        case_id="test-bad-volumes",
    )
    sv = state.measurements.stroke_volume_ml
    if sv is not None:
        assert sv.source != ValueSource.DERIVED
    warning_text = " ".join(resp.warnings).lower()
    assert "invalid" in warning_text or "not greater" in warning_text or "esv" in warning_text


# ---------------------------------------------------------------------------
# Prior labelling
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_priors_are_labelled_default_model_prior():
    """Any field filled from population priors must have source=default_model_prior."""
    resp, state = await run_state_builder_agent(
        validated_fields={},
        case_id="test-priors",
    )
    prior_fields = [p for p in resp.outputs["prior_fields"]]
    assert len(prior_fields) > 0, "At least some priors should be applied"

    for entry in state.source_map:
        if entry.source == ValueSource.DEFAULT_MODEL_PRIOR:
            assert entry.confidence <= _PRIOR_CONFIDENCE_CAP, (
                f"Prior confidence for {entry.field} must be capped at {_PRIOR_CONFIDENCE_CAP}"
            )

    # Warnings must mention default_model_prior
    warning_text = " ".join(resp.warnings).lower()
    assert "default_model_prior" in warning_text or "population prior" in warning_text


@pytest.mark.asyncio
async def test_prior_confidence_never_exceeds_cap():
    """No prior entry may have confidence > _PRIOR_CONFIDENCE_CAP."""
    resp, state = await run_state_builder_agent(
        validated_fields={},
        case_id="test-prior-cap",
    )
    for entry in state.source_map:
        if entry.source == ValueSource.DEFAULT_MODEL_PRIOR:
            assert entry.confidence <= _PRIOR_CONFIDENCE_CAP, (
                f"{entry.field}: prior confidence {entry.confidence} exceeds cap {_PRIOR_CONFIDENCE_CAP}"
            )


# ---------------------------------------------------------------------------
# User values are not overwritten
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_user_ef_not_overwritten_by_derived():
    """A user-reported EF must survive even when EDV/ESV would produce a different derived value."""
    user_ef_vitals = {
        **_FULL_VITALS,
        "ejection_fraction_pct": {
            "value": 65.0,
            "unit": "%",
            "source": "user_input",
            "confidence": 0.95,
        },
    }
    resp, state = await run_state_builder_agent(
        validated_fields=user_ef_vitals,
        case_id="test-ef-no-overwrite",
    )
    ef = state.measurements.ejection_fraction_pct
    assert ef is not None
    # The user-provided value is 65; derived would be ~57.14 — must keep 65
    assert abs(ef.value - 65.0) < 0.01, (
        f"User-provided EF (65.0) must not be overwritten; got {ef.value}"
    )
    warning_text = " ".join(resp.warnings)
    assert "kept as reported" in warning_text or "not used to overwrite" in warning_text


@pytest.mark.asyncio
async def test_user_co_not_overwritten_by_derived():
    """A user-supplied cardiac output must not be overwritten by the HR×SV formula."""
    user_co_vitals = {
        **_FULL_VITALS,
        "cardiac_output_l_min": {
            "value": 6.5,
            "unit": "L/min",
            "source": "file_extraction",
            "confidence": 0.9,
        },
    }
    resp, state = await run_state_builder_agent(
        validated_fields=user_co_vitals,
        case_id="test-co-no-overwrite",
    )
    co = state.measurements.cardiac_output_l_min
    assert co is not None
    assert abs(co.value - 6.5) < 0.01, (
        f"User-provided CO (6.5) must not be overwritten; got {co.value}"
    )


# ---------------------------------------------------------------------------
# Source map integrity
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_derived_values_have_source_map_entries():
    """Every derived metric must appear in the source map with source=DERIVED."""
    resp, state = await run_state_builder_agent(
        validated_fields=_FULL_VITALS,
        case_id="test-source-map-derived",
    )
    derived_fields = resp.outputs["derived_fields"]
    assert len(derived_fields) > 0

    source_map_fields = {e.field for e in state.source_map}
    for field in derived_fields:
        assert field in source_map_fields, f"Derived field '{field}' not found in source_map"

    for entry in state.source_map:
        if entry.source == ValueSource.DERIVED:
            assert entry.method == "deterministic_formula", (
                f"{entry.field}: derived entry must have method=deterministic_formula"
            )


@pytest.mark.asyncio
async def test_all_source_map_entries_have_required_fields():
    """Every source map entry must have field, unit, source, and confidence set."""
    resp, state = await run_state_builder_agent(
        validated_fields=_FULL_VITALS,
        case_id="test-source-map-completeness",
    )
    assert len(state.source_map) > 0
    for entry in state.source_map:
        assert entry.field, "source_map entry must have a non-empty field name"
        assert entry.source is not None, f"source_map entry for {entry.field} missing source"
        assert entry.confidence is not None, f"source_map entry for {entry.field} missing confidence"
        assert entry.unit is not None, f"source_map entry for {entry.field} missing unit"


# ---------------------------------------------------------------------------
# Operating environment defaults
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_operating_environment_defaults_applied():
    """When no operating_environment is supplied, safe simulation defaults are set."""
    resp, state = await run_state_builder_agent(
        validated_fields=_MINIMAL_VITALS,
        case_id="test-op-defaults",
    )
    op = state.operating_environment
    assert op is not None
    assert op.simulation_duration_seconds == 10.0
    assert op.time_step_ms == 20.0
    assert abs(op.activity_level_mets - 1.0) < 0.01
    assert abs(op.hydration_index - 0.7) < 0.01
    assert abs(op.oxygen_fraction - 0.2095) < 0.0001
    assert op.altitude_m == 0.0


@pytest.mark.asyncio
async def test_operating_environment_provided_values_respected():
    """When operating_environment is explicitly provided, its values are used."""
    custom_env = {
        "simulation_duration_seconds": 30.0,
        "activity_level_mets": 3.5,
        "altitude_m": 1500.0,
    }
    resp, state = await run_state_builder_agent(
        validated_fields=_MINIMAL_VITALS,
        case_id="test-op-provided",
        operating_environment=custom_env,
    )
    op = state.operating_environment
    assert op.simulation_duration_seconds == 30.0
    assert abs(op.activity_level_mets - 3.5) < 0.01
    assert op.altitude_m == 1500.0


# ---------------------------------------------------------------------------
# Output schema validation
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_output_validates_against_cardiac_twin_state_schema():
    """run_state_builder_agent must return a valid CardiacTwinState."""
    resp, state = await run_state_builder_agent(
        validated_fields=_FULL_VITALS,
        case_id="test-schema-valid",
    )
    assert isinstance(state, CardiacTwinState)
    assert state.case_id == "test-schema-valid"
    assert state.data_quality_score is not None
    assert 0.0 <= state.data_quality_score <= 1.0
    assert isinstance(state.safety_level, SafetyLevel)
    assert state.measurements is not None
    assert state.electrophysiology is not None
    assert state.hemodynamics is not None
    assert state.tissue_state is not None
    assert state.operating_environment is not None
    assert state.simulation_config is not None
    assert state.patient_context is not None
    assert isinstance(state.source_map, list)
    assert isinstance(state.warnings, list)


@pytest.mark.asyncio
async def test_agent_response_metadata():
    """AgentResponse must carry the correct agent identity and structured outputs."""
    resp, state = await run_state_builder_agent(
        validated_fields=_FULL_VITALS,
        case_id="test-agent-meta",
    )
    assert resp.agent == "state_builder_agent"
    assert resp.status in (AgentStatus.SUCCESS, AgentStatus.WARNING)

    stage = resp.outputs.get("agent_stage_result", {})
    assert stage.get("agent_id") == _AGENT_ID
    assert stage.get("agent_name") == _AGENT_NAME

    assert "data_quality_score" in resp.outputs
    assert "derived_fields" in resp.outputs
    assert "prior_fields" in resp.outputs
    assert "missing_values" in resp.outputs
    assert "source_coverage" in resp.outputs


# ---------------------------------------------------------------------------
# Data quality score
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_data_quality_score_higher_with_more_evidence():
    """Full vitals should produce a higher quality score than minimal vitals."""
    _, state_full = await run_state_builder_agent(
        validated_fields=_FULL_VITALS,
        case_id="test-dqs-full",
    )
    _, state_min = await run_state_builder_agent(
        validated_fields=_MINIMAL_VITALS,
        case_id="test-dqs-min",
    )
    assert state_full.data_quality_score >= state_min.data_quality_score, (
        "More evidence should yield a higher data quality score"
    )


@pytest.mark.asyncio
async def test_empty_fields_produces_valid_state():
    """Even with zero validated fields the builder must return a valid state (all priors)."""
    resp, state = await run_state_builder_agent(
        validated_fields={},
        case_id="test-empty",
    )
    assert isinstance(state, CardiacTwinState)
    assert state.data_quality_score >= 0.0
    assert len(state.source_map) > 0
    assert len(resp.warnings) > 0


# ---------------------------------------------------------------------------
# Tissue state conservative priors
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_tissue_state_initialized_with_conservative_priors():
    """Tissue state fields must be set to conservative defaults, never imply disease."""
    resp, state = await run_state_builder_agent(
        validated_fields=_MINIMAL_VITALS,
        case_id="test-tissue",
    )
    ts = state.tissue_state
    assert ts.scar_fraction is not None
    assert ts.scar_fraction.value == 0.0, "Conservative scar_fraction prior must be 0.0"
    assert ts.scar_fraction.source == ValueSource.DEFAULT_MODEL_PRIOR
    assert ts.scar_fraction.confidence <= _PRIOR_CONFIDENCE_CAP
    assert ts.inflammation_index is not None
    assert ts.inflammation_index.source == ValueSource.DEFAULT_MODEL_PRIOR

    warning_text = " ".join(resp.warnings).lower()
    assert "conservative" in warning_text or "tissue_state" in warning_text


# ---------------------------------------------------------------------------
# BSA derivation
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_bsa_derived_from_height_weight():
    """BSA (Mosteller) is derived only when real height and weight evidence exists."""
    resp, state = await run_state_builder_agent(
        validated_fields=_FULL_VITALS,
        case_id="test-bsa",
    )
    bsa = state.patient_context.bsa_m2
    assert bsa is not None
    # Mosteller: sqrt(175 * 80 / 3600) ≈ 1.972
    assert abs(bsa.value - 1.972) < 0.01
    assert bsa.source == ValueSource.DERIVED

    bsa_entry = _source_map_entry(state.source_map, "bsa_m2")
    assert bsa_entry is not None
    assert bsa_entry.source == ValueSource.DERIVED


@pytest.mark.asyncio
async def test_bsa_not_derived_without_height_weight():
    """BSA must not be derived when height/weight are absent."""
    resp, state = await run_state_builder_agent(
        validated_fields=_MINIMAL_VITALS,
        case_id="test-no-bsa",
    )
    bsa = state.patient_context.bsa_m2
    if bsa is not None:
        assert bsa.source != ValueSource.DERIVED


# ---------------------------------------------------------------------------
# Source coverage
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_source_coverage_sums_to_one():
    """Source coverage fractions must sum to approximately 1.0."""
    resp, state = await run_state_builder_agent(
        validated_fields=_FULL_VITALS,
        case_id="test-coverage",
    )
    coverage = resp.outputs["source_coverage"]
    assert isinstance(coverage, dict)
    assert len(coverage) > 0
    total = sum(coverage.values())
    assert abs(total - 1.0) < 0.01, f"Source coverage fractions should sum to 1.0, got {total}"


# ---------------------------------------------------------------------------
# Redis state memory (in-memory fallback path)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_state_memory_written(monkeypatch):
    """The in-memory fallback store must be populated after the agent runs."""
    import python.hearttwin.agents.state_builder_agent as sba

    monkeypatch.delenv("UPSTASH_REDIS_REST_URL", raising=False)
    monkeypatch.delenv("UPSTASH_REDIS_REST_TOKEN", raising=False)

    test_case_id = "test-memory-write"
    await run_state_builder_agent(
        validated_fields=_FULL_VITALS,
        case_id=test_case_id,
    )
    key = f"hearttwin:case:{test_case_id}:state"
    assert key in sba._STATE_MEMORY, "In-memory state store must contain the written key"
    payload = sba._STATE_MEMORY[key]
    assert payload["case_id"] == test_case_id
    assert "state" in payload
    assert "source_map" in payload
    assert "data_quality_score" in payload
    assert "warnings" in payload
