"""Tests for the Recovery Orchestration Agent.

All tests run fully offline: no OpenAI key, no Redis credentials.
They assert the deterministic orchestration contract — scenario generation,
safety labels, forbidden-content absence, schema validation, memory fallbacks,
uncertainty bands, and Weave/local trace — without any network calls.
"""

from __future__ import annotations

import pytest

from python.hearttwin.agents.recovery_agent import (
    SIMULATION_LABEL,
    AgentStageResult,
    RecoveryOutput,
    RecoveryScenario,
    _classify_uncertainty,
    _compute_confidence,
    _compute_scenario_tradeoffs,
    _compute_tradeoffs,
    _validate_scenario_config,
    run_recovery_agent,
)
from python.hearttwin.schemas import (
    AgentStatus,
    CardiacTwinState,
    RecoveryConfig,
    RecoveryScenarioType,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _no_external_services(monkeypatch):
    """Isolate every test from OpenAI and Redis."""
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("UPSTASH_REDIS_REST_URL", raising=False)
    monkeypatch.delenv("UPSTASH_REDIS_REST_TOKEN", raising=False)
    yield


def _make_state(
    edv: float = 130.0,
    esv: float = 50.0,
    hr: float = 72.0,
    data_quality: float = 0.7,
) -> CardiacTwinState:
    """Build a minimal CardiacTwinState with the given values."""
    from python.hearttwin.schemas import (
        Hemodynamics,
        Measurements,
        MeasuredValue,
        TissueState,
        ValueSource,
    )

    def mv(val: float, unit: str) -> MeasuredValue:
        return MeasuredValue(value=val, unit=unit, source=ValueSource.USER_INPUT, confidence=0.9)

    return CardiacTwinState(
        case_id="test-recovery-001",
        data_quality_score=data_quality,
        measurements=Measurements(
            edv_ml=mv(edv, "mL"),
            esv_ml=mv(esv, "mL"),
            heart_rate_bpm=mv(hr, "bpm"),
            systolic_bp_mmhg=mv(120.0, "mmHg"),
            diastolic_bp_mmhg=mv(80.0, "mmHg"),
        ),
        hemodynamics=Hemodynamics(
            contractility_index=mv(0.65, "index"),
            afterload_index=mv(0.50, "index"),
            preload_index=mv(0.55, "index"),
        ),
        tissue_state=TissueState(
            inflammation_index=mv(0.25, "index"),
            oxygen_delivery_index=mv(0.80, "index"),
            stiffness_index=mv(0.30, "index"),
            scar_fraction=mv(0.05, "index"),
        ),
    )


# ---------------------------------------------------------------------------
# Agent creates 2–4 scenarios
# ---------------------------------------------------------------------------


async def test_agent_creates_at_least_two_scenarios():
    state = _make_state()
    response, payloads = await run_recovery_agent(state, None, "case-count")

    stage = AgentStageResult.model_validate(response.outputs["agent_stage_result"])
    assert stage.scenario_count >= 2
    assert len(payloads) >= 2


async def test_agent_creates_at_most_four_scenarios():
    state = _make_state()
    response, payloads = await run_recovery_agent(state, None, "case-max")

    stage = AgentStageResult.model_validate(response.outputs["agent_stage_result"])
    assert stage.scenario_count <= 4
    assert len(payloads) <= 4


async def test_agent_with_provided_configs_respects_count():
    state = _make_state()
    configs = [
        RecoveryConfig(scenario_type=RecoveryScenarioType.LOAD_REDUCTION),
        RecoveryConfig(scenario_type=RecoveryScenarioType.CONDITIONING),
        RecoveryConfig(scenario_type=RecoveryScenarioType.CONTRACTILITY_SUPPORT),
    ]
    response, payloads = await run_recovery_agent(state, configs, "case-provided")

    assert len(payloads) == 3


# ---------------------------------------------------------------------------
# Simulation label is present on every scenario
# ---------------------------------------------------------------------------


async def test_every_scenario_has_simulation_label():
    state = _make_state()
    _, payloads = await run_recovery_agent(state, None, "case-label")

    for payload in payloads:
        assert payload.get("simulation_label") == SIMULATION_LABEL, (
            f"Scenario missing simulation_label: {payload.get('simulation_label')!r}"
        )


async def test_simulation_label_not_medical():
    label = SIMULATION_LABEL.lower()
    # These affirm clinical action — must be absent.
    assert "therapy" not in label
    assert "prescription" not in label
    assert "medication" not in label
    assert "prescribe" not in label
    # Label must contain simulation and explicitly disclaim treatment.
    assert "simulation" in label
    # "treatment recommendation" must appear only in a negated phrase.
    assert "not a treatment recommendation" in label or "not a clinical" in label


# ---------------------------------------------------------------------------
# No forbidden medical language anywhere in output
# ---------------------------------------------------------------------------

# Affirmative forbidden phrases — these must never appear in any output.
# Note: "clinical recommendation" and "treatment recommendation" appear in
# DISCLAIMERS only in the negated form ("not a clinical recommendation"),
# so we check for the *positive* affirmations instead.
_FORBIDDEN_AFFIRM = [
    "medication", "dosage", "dose", "drug", "mg", "tablet", "pill",
    "prescribe", "prescription",
    "recommended therapy",
    "treatment plan",
    "healed", "cured",
    "the patient will recover",
    "is a clinical recommendation",
    "is a treatment recommendation",
]


async def test_no_forbidden_content_in_payloads():
    state = _make_state()
    response, payloads = await run_recovery_agent(state, None, "case-safe")

    full_text = str(payloads).lower()
    for term in _FORBIDDEN_AFFIRM:
        assert term not in full_text, f"Forbidden affirmative term '{term}' found in payloads"


async def test_no_forbidden_content_in_response_outputs():
    state = _make_state()
    response, _ = await run_recovery_agent(state, None, "case-safe-resp")

    full_text = str(response.outputs).lower()
    for term in _FORBIDDEN_AFFIRM:
        assert term not in full_text, f"Forbidden term '{term}' found in response outputs"


# ---------------------------------------------------------------------------
# Scenario types are valid
# ---------------------------------------------------------------------------


async def test_all_scenario_types_are_valid():
    from python.hearttwin.agents.recovery_agent import _VALID_SCENARIO_TYPES

    state = _make_state()
    _, payloads = await run_recovery_agent(state, None, "case-types")

    for payload in payloads:
        st = payload.get("scenario_type")
        assert st in _VALID_SCENARIO_TYPES, f"Invalid scenario_type: {st!r}"


# ---------------------------------------------------------------------------
# Bounded parameter changes
# ---------------------------------------------------------------------------


def test_validate_scenario_config_clamps_large_delta():
    cfg = {
        "scenario_type": "load_reduction",
        "contractility_delta_per_day": 0.99,  # far above 0.30 max
        "afterload_delta_per_day": -0.50,
        "preload_delta_per_day": 0.0,
        "inflammation_decay_rate": 0.02,
        "oxygen_delivery_delta_per_day": 0.003,
        "stiffness_delta_per_day": -0.002,
        "scar_remodeling_rate": 0.001,
        "heart_rate_adaptation_rate": 0.002,
        "arrhythmia_stability_delta": 0.004,
        "max_safe_parameter_shift": 0.20,
        "uncertainty_penalty_weight": 0.2,
    }
    sanitized, warnings = _validate_scenario_config(cfg, horizon=30)

    assert abs(sanitized["contractility_delta_per_day"]) <= 0.20
    assert abs(sanitized["afterload_delta_per_day"]) <= 0.20
    assert any("contractility_delta_per_day" in w or "afterload_delta_per_day" in w
               for w in warnings)


def test_validate_scenario_config_rejects_forbidden_type():
    cfg = {
        "scenario_type": "medication_support",  # invalid
        "contractility_delta_per_day": 0.003,
        "afterload_delta_per_day": -0.005,
        "preload_delta_per_day": -0.003,
        "inflammation_decay_rate": 0.025,
        "oxygen_delivery_delta_per_day": 0.003,
        "stiffness_delta_per_day": -0.002,
        "scar_remodeling_rate": 0.001,
        "heart_rate_adaptation_rate": 0.002,
        "arrhythmia_stability_delta": 0.004,
        "max_safe_parameter_shift": 0.20,
        "uncertainty_penalty_weight": 0.2,
    }
    sanitized, warnings = _validate_scenario_config(cfg, horizon=30)

    assert sanitized["scenario_type"] == "custom"
    assert any("scenario_type" in w.lower() or "unknown" in w.lower() for w in warnings)


def test_validate_scenario_config_sanitizes_forbidden_name():
    cfg = {
        "scenario_type": "load_reduction",
        "scenario_name": "diuretic_dose_reduction",  # forbidden term
        "contractility_delta_per_day": 0.003,
        "afterload_delta_per_day": -0.005,
        "preload_delta_per_day": -0.003,
        "inflammation_decay_rate": 0.025,
        "oxygen_delivery_delta_per_day": 0.003,
        "stiffness_delta_per_day": -0.002,
        "scar_remodeling_rate": 0.001,
        "heart_rate_adaptation_rate": 0.002,
        "arrhythmia_stability_delta": 0.004,
        "max_safe_parameter_shift": 0.20,
        "uncertainty_penalty_weight": 0.2,
    }
    sanitized, warnings = _validate_scenario_config(cfg, horizon=30)

    assert "dose" not in sanitized.get("scenario_name", "").lower()


def test_max_safe_parameter_shift_capped_at_0_30():
    cfg = {
        "scenario_type": "custom",
        "contractility_delta_per_day": 0.005,
        "afterload_delta_per_day": -0.005,
        "preload_delta_per_day": -0.003,
        "inflammation_decay_rate": 0.025,
        "oxygen_delivery_delta_per_day": 0.003,
        "stiffness_delta_per_day": -0.002,
        "scar_remodeling_rate": 0.001,
        "heart_rate_adaptation_rate": 0.002,
        "arrhythmia_stability_delta": 0.004,
        "max_safe_parameter_shift": 9.99,  # way too high
        "uncertainty_penalty_weight": 0.2,
    }
    sanitized, _ = _validate_scenario_config(cfg, horizon=30)

    assert sanitized["max_safe_parameter_shift"] <= 0.30


# ---------------------------------------------------------------------------
# Uncertainty bands exist
# ---------------------------------------------------------------------------


async def test_uncertainty_bands_exist_in_every_trajectory():
    state = _make_state()
    _, payloads = await run_recovery_agent(state, None, "case-unc")

    for payload in payloads:
        trajectory = payload.get("trajectory") or []
        assert len(trajectory) > 0, "Empty trajectory"
        for point in trajectory:
            assert "uncertainty_low" in point, "Missing uncertainty_low"
            assert "uncertainty_high" in point, "Missing uncertainty_high"
            assert point["uncertainty_low"] <= point.get("cardiac_output_l_min", 0) + 1e-6
            assert point["uncertainty_high"] >= point.get("cardiac_output_l_min", 0) - 1e-6


async def test_uncertainty_status_is_classified():
    state = _make_state()
    response, _ = await run_recovery_agent(state, None, "case-unc-status")

    status = response.outputs.get("uncertainty_status")
    assert status in ("narrow", "moderate", "wide", "unknown"), f"Unexpected: {status!r}"


def test_classify_uncertainty_uses_band_width():
    from python.hearttwin.tools.recovery_sim import build_default_scenarios

    results = build_default_scenarios(
        {
            "edv_ml": 130.0, "esv_ml": 50.0, "heart_rate_bpm": 72.0,
            "contractility_index": 0.65, "afterload_index": 0.5,
            "preload_index": 0.55, "inflammation_index": 0.25,
            "oxygen_delivery_index": 0.80, "stiffness_index": 0.30,
            "scar_fraction": 0.05, "arrhythmia_instability_score": 0.10,
        },
        recovery_horizon_days=14,
        random_seed=0,
    )
    status = _classify_uncertainty(results)
    assert status in ("narrow", "moderate", "wide")


# ---------------------------------------------------------------------------
# Missing data produces warnings
# ---------------------------------------------------------------------------


async def test_missing_measurements_produce_warnings():
    """Agent must not crash on a sparse state (all measurements are None)."""
    state = CardiacTwinState(case_id="sparse-case", data_quality_score=0.0)
    response, payloads = await run_recovery_agent(state, None, "case-sparse")

    # Must still produce scenarios
    assert len(payloads) >= 2
    # Response must not be FAILED
    assert response.status != AgentStatus.FAILED


# ---------------------------------------------------------------------------
# Redis fallback (unavailable)
# ---------------------------------------------------------------------------


async def test_redis_unavailable_produces_safe_fallback():
    """When Redis is not configured, memory_patterns_used should be empty but
    the agent must still run without error."""
    state = _make_state()
    response, payloads = await run_recovery_agent(state, None, "case-no-redis")

    assert len(payloads) >= 2
    stage = AgentStageResult.model_validate(response.outputs["agent_stage_result"])
    assert stage.memory_patterns_used == []
    assert response.status != AgentStatus.FAILED


# ---------------------------------------------------------------------------
# OpenAI unavailable → deterministic fallback
# ---------------------------------------------------------------------------


async def test_openai_missing_falls_back_to_deterministic():
    state = _make_state()
    response, payloads = await run_recovery_agent(state, None, "case-no-llm")

    stage = AgentStageResult.model_validate(response.outputs["agent_stage_result"])
    assert stage.model_used is None, "model_used should be None when no API key"
    assert stage.deterministic_tool_calls >= 2
    assert len(payloads) >= 2


async def test_deterministic_fallback_still_labels_scenarios():
    state = _make_state()
    _, payloads = await run_recovery_agent(state, None, "case-fallback-label")

    for payload in payloads:
        assert payload.get("simulation_label") == SIMULATION_LABEL


# ---------------------------------------------------------------------------
# Output schema validates
# ---------------------------------------------------------------------------


async def test_output_schema_validates():
    state = _make_state()
    response, _ = await run_recovery_agent(state, None, "case-schema")

    stage_dict = response.outputs["agent_stage_result"]
    stage = AgentStageResult.model_validate(stage_dict)
    assert stage.agent_id == "recovery_orchestration"
    assert stage.agent_name == "Recovery Orchestration Agent"
    assert 0.0 <= stage.confidence <= 1.0

    recovery_out = RecoveryOutput.model_validate(stage.structured_output)
    assert len(recovery_out.scenarios) >= 2
    assert 0.0 <= recovery_out.confidence <= 1.0
    assert recovery_out.comparison_summary.get("scenario_count", 0) >= 2


async def test_recovery_scenario_schema_validates():
    state = _make_state()
    response, _ = await run_recovery_agent(state, None, "case-rs-schema")

    stage = AgentStageResult.model_validate(response.outputs["agent_stage_result"])
    recovery_out = RecoveryOutput.model_validate(stage.structured_output)

    for scenario in recovery_out.scenarios:
        rs = RecoveryScenario.model_validate(scenario.model_dump())
        assert rs.simulation_label == SIMULATION_LABEL
        assert len(rs.days) > 0
        assert len(rs.ef_pct) == len(rs.days)
        assert len(rs.uncertainty_lower) == len(rs.days)
        assert len(rs.uncertainty_upper) == len(rs.days)
        assert all(lo <= hi for lo, hi in zip(rs.uncertainty_lower, rs.uncertainty_upper))


# ---------------------------------------------------------------------------
# Agent metadata fields
# ---------------------------------------------------------------------------


async def test_agent_id_and_name():
    state = _make_state()
    response, _ = await run_recovery_agent(state, None, "case-meta")

    # AgentResponse.agent is the frontend/orchestrator key; the internal id
    # lives on stage_result.agent_id.
    assert response.agent == "recovery_agent"
    stage = AgentStageResult.model_validate(response.outputs["agent_stage_result"])
    assert stage.agent_id == "recovery_orchestration"
    assert stage.agent_name == "Recovery Orchestration Agent"


async def test_response_confidence_is_bounded():
    state = _make_state()
    response, _ = await run_recovery_agent(state, None, "case-conf")

    assert 0.0 <= response.confidence <= 1.0
    stage = AgentStageResult.model_validate(response.outputs["agent_stage_result"])
    assert 0.0 <= stage.confidence <= 1.0


async def test_tools_called_list_populated():
    state = _make_state()
    response, _ = await run_recovery_agent(state, None, "case-tools")

    stage = AgentStageResult.model_validate(response.outputs["agent_stage_result"])
    assert "hearttwin.redis_memory_read" in stage.tools_called
    assert "hearttwin.simulate_recovery_scenarios" in stage.tools_called
    assert "hearttwin.redis_memory_write" in stage.tools_called


async def test_weave_trace_steps_present():
    state = _make_state()
    response, _ = await run_recovery_agent(state, None, "case-weave")

    assert len(response.trace) >= 3, "Expected ≥3 trace steps"
    tool_names = [step.tool for step in response.trace]
    assert "hearttwin.redis_memory_read" in tool_names
    assert "hearttwin.simulate_recovery_scenarios" in tool_names
    assert "hearttwin.redis_memory_write" in tool_names


# ---------------------------------------------------------------------------
# Tradeoff analysis
# ---------------------------------------------------------------------------


def test_tradeoffs_present_with_multiple_scenarios():
    from python.hearttwin.tools.recovery_sim import build_default_scenarios

    state_params = {
        "edv_ml": 130.0, "esv_ml": 50.0, "heart_rate_bpm": 72.0,
        "contractility_index": 0.65, "afterload_index": 0.5,
        "preload_index": 0.55, "inflammation_index": 0.25,
        "oxygen_delivery_index": 0.80, "stiffness_index": 0.30,
        "scar_fraction": 0.05, "arrhythmia_instability_score": 0.10,
    }
    results = build_default_scenarios(state_params, recovery_horizon_days=14, random_seed=0)
    ids = [f"id{i}" for i in range(len(results))]
    tradeoff_map = _compute_scenario_tradeoffs(results, ids)

    assert len(tradeoff_map) == len(results)
    for sid, trades in tradeoff_map.items():
        assert len(trades) >= 1, f"No tradeoffs for scenario {sid}"
        full_text = " ".join(trades).lower()
        for term in _FORBIDDEN_AFFIRM:
            assert term not in full_text, f"Forbidden term '{term}' in tradeoffs"


async def test_tradeoffs_in_payload():
    state = _make_state()
    _, payloads = await run_recovery_agent(state, None, "case-tradeoffs")

    for payload in payloads:
        tradeoffs = payload.get("tradeoffs")
        assert isinstance(tradeoffs, list), "tradeoffs should be a list"


# ---------------------------------------------------------------------------
# Confidence scoring unit tests
# ---------------------------------------------------------------------------


def test_confidence_clamped_to_0_1():
    from python.hearttwin.tools.recovery_sim import build_default_scenarios

    state = _make_state(data_quality=0.0)
    state_params = {
        "edv_ml": 130.0, "esv_ml": 50.0, "heart_rate_bpm": 72.0,
        "contractility_index": 0.65, "afterload_index": 0.5,
        "preload_index": 0.55, "inflammation_index": 0.25,
        "oxygen_delivery_index": 0.80, "stiffness_index": 0.30,
        "scar_fraction": 0.05, "arrhythmia_instability_score": 0.10,
    }
    scenarios = build_default_scenarios(state_params, recovery_horizon_days=7, random_seed=0)
    conf = _compute_confidence(state, scenarios, ["w"] * 20, priors_used=10, model_used=None)
    assert 0.0 <= conf <= 1.0


def test_confidence_higher_with_good_data():
    from python.hearttwin.tools.recovery_sim import build_default_scenarios

    state_good = _make_state(data_quality=1.0)
    state_bad = _make_state(data_quality=0.0)
    state_params = {
        "edv_ml": 130.0, "esv_ml": 50.0, "heart_rate_bpm": 72.0,
        "contractility_index": 0.65, "afterload_index": 0.5,
        "preload_index": 0.55, "inflammation_index": 0.10,
        "oxygen_delivery_index": 0.90, "stiffness_index": 0.25,
        "scar_fraction": 0.0, "arrhythmia_instability_score": 0.05,
    }
    scenarios = build_default_scenarios(state_params, recovery_horizon_days=14, random_seed=0)
    conf_good = _compute_confidence(state_good, scenarios, [], priors_used=0, model_used="gpt-5.5")
    conf_bad = _compute_confidence(state_bad, scenarios, ["w"] * 5, priors_used=5, model_used=None)
    assert conf_good > conf_bad


# ---------------------------------------------------------------------------
# Backward-compatible payload structure
# ---------------------------------------------------------------------------


async def test_payload_has_expected_keys_for_orchestrator():
    """The orchestrator accesses specific keys; verify they are always present."""
    state = _make_state()
    _, payloads = await run_recovery_agent(state, None, "case-compat")

    for payload in payloads:
        assert "scenario_type" in payload
        assert "scenario_label" in payload
        assert "summary_metrics" in payload
        assert "trajectory" in payload
        assert "warnings" in payload
        assert "simulation_disclaimer" in payload
        horizon = payload["summary_metrics"].get("horizon_days")
        assert horizon is not None and isinstance(horizon, int)


async def test_trajectory_has_uncertainty_fields_for_orchestrator():
    """_uncertainty_expands in orchestrator uses uncertainty_high / uncertainty_low."""
    state = _make_state()
    _, payloads = await run_recovery_agent(state, None, "case-unc-compat")

    for payload in payloads:
        traj = payload.get("trajectory") or []
        assert len(traj) > 0
        first = traj[0]
        assert "uncertainty_high" in first
        assert "uncertainty_low" in first
        assert first["uncertainty_high"] >= first["uncertainty_low"]
