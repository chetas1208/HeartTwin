"""Tests for the Hemodynamics Simulation Agent.

All tests use deterministic inputs and validate:
- Correct formula outputs (SV, EF, CO, MAP)
- Safe handling of missing EDV/ESV
- PV loop array generation
- Visualization payload field completeness
- Operating environment parameter bounding
- Confidence reduction when priors are used
- Impossible physiology clamping and warnings
- Absence of unsafe medical language in outputs
- Weave/local trace recording
"""

from __future__ import annotations

import pytest

from python.hearttwin.agents.hemodynamics_agent import (
    AGENT_ID,
    AGENT_NAME,
    HemodynamicsInput,
    HemodynamicsOutput,
    _bound_env,
    _compute_confidence,
    _compute_environment_effects,
    run_hemodynamics_agent,
)
from python.hearttwin.schemas import (
    AgentStatus,
    CardiacTwinState,
    Electrophysiology,
    Hemodynamics,
    Measurements,
    MeasuredValue,
    MissingValuePolicy,
    OperatingEnvironment,
    OperatingMode,
    SimulationConfig,
    TissueState,
    ValueSource,
)
from python.hearttwin.tools.hemodynamics import (
    compute_oxygen_demand_index,
    generate_3d_visual_payload,
    generate_cardiac_cycle,
    generate_pressure_volume_loop,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_SRC = ValueSource.FILE_EXTRACTION


def _mv(value: float, unit: str = "unit", confidence: float = 0.90) -> MeasuredValue:
    return MeasuredValue(value=value, unit=unit, source=_SRC, confidence=confidence)


def _make_state(
    edv: float | None = 130.0,
    esv: float | None = 50.0,
    hr: float | None = 72.0,
    sbp: float | None = 120.0,
    dbp: float | None = 80.0,
    scar: float = 0.0,
    inflammation: float = 0.0,
    mode: OperatingMode = OperatingMode.REST,
    missing_value_policy: MissingValuePolicy = MissingValuePolicy.PRIOR,
    data_quality_score: float = 0.70,
) -> CardiacTwinState:
    meas = Measurements(
        edv_ml=_mv(edv) if edv is not None else None,
        esv_ml=_mv(esv) if esv is not None else None,
        heart_rate_bpm=_mv(hr) if hr is not None else None,
        systolic_bp_mmhg=_mv(sbp) if sbp is not None else None,
        diastolic_bp_mmhg=_mv(dbp) if dbp is not None else None,
    )
    ts = TissueState(
        scar_fraction=_mv(scar, "fraction") if scar else None,
        inflammation_index=_mv(inflammation, "index") if inflammation else None,
        oxygen_delivery_index=_mv(0.85, "index"),
    )
    op_env = OperatingEnvironment(
        mode=mode,
        missing_value_policy=missing_value_policy,
        activity_level_mets=1.0,
    )
    sim_cfg = SimulationConfig(operating=op_env)
    return CardiacTwinState(
        case_id="test-case-001",
        data_quality_score=data_quality_score,
        measurements=meas,
        tissue_state=ts,
        simulation_config=sim_cfg,
    )


# ---------------------------------------------------------------------------
# Unit tests for new hemodynamics tool functions
# ---------------------------------------------------------------------------


class TestNewTools:
    def test_oxygen_demand_typical(self):
        val = compute_oxygen_demand_index(70.0, 1.0, 1.0, 1.0)
        # HR_norm=1, so result = 1.0*1.0*1.0*1.0 = 1.0
        assert abs(val - 1.0) < 0.01

    def test_oxygen_demand_high_activity(self):
        hi = compute_oxygen_demand_index(140.0, 1.2, 1.2, 5.0)
        lo = compute_oxygen_demand_index(70.0, 1.0, 1.0, 1.0)
        assert hi > lo

    def test_oxygen_demand_clamped_at_5(self):
        val = compute_oxygen_demand_index(300.0, 2.0, 2.0, 20.0)
        assert val <= 5.0

    def test_oxygen_demand_non_negative(self):
        val = compute_oxygen_demand_index(0.0, 0.0, 0.0, 0.0)
        assert val >= 0.0

    def test_generate_pv_loop_structure(self):
        result = generate_pressure_volume_loop(
            edv_ml=130, esv_ml=50, heart_rate_bpm=70,
            systolic_bp_mmhg=120, diastolic_bp_mmhg=80,
        )
        assert "volume_ml" in result
        assert "pressure_mmhg" in result
        assert "loop_area_index" in result
        assert result["model"] == "simplified_time_varying_elastance"
        assert result["simulation_label"] == "educational simulation"
        assert len(result["volume_ml"]) == 200
        assert result["loop_area_index"] > 0

    def test_generate_cardiac_cycle_structure(self):
        result = generate_cardiac_cycle(
            edv_ml=130, esv_ml=50, heart_rate_bpm=70,
            systolic_bp_mmhg=120, diastolic_bp_mmhg=80,
        )
        assert "time_ms" in result
        assert "volume_ml" in result
        assert "pressure_mmhg" in result
        assert "phase" in result
        assert len(result["time_ms"]) == len(result["phase"])
        assert len(result["time_ms"]) > 0
        phases = set(result["phase"])
        valid = {"isovolumetric_contraction", "ejection", "isovolumetric_relaxation", "filling"}
        assert phases.issubset(valid)

    def test_generate_3d_payload_fields(self):
        result = generate_3d_visual_payload(
            heart_rate_bpm=72.0,
            contractility_index=0.85,
            afterload_index=0.92,
            preload_index=1.00,
            oxygen_delivery_index=0.85,
            inflammation_index=0.05,
            scar_fraction=0.02,
            beat_amplitude=1.0,
            electrical_wave_speed=1.0,
        )
        required = [
            "heart_rate_bpm", "beat_interval_ms", "beat_amplitude",
            "contractility_index", "afterload_index", "preload_index",
            "oxygen_delivery_index", "inflammation_index", "scar_fraction",
            "stress_field_intensity", "blood_flow_particle_density",
            "electrical_wave_speed", "simulation_label",
        ]
        for field in required:
            assert field in result, f"Missing field: {field}"
        assert result["simulation_label"] == "educational visualization"
        assert abs(result["beat_interval_ms"] - 60000.0 / 72.0) < 1.0

    def test_generate_3d_payload_clamping(self):
        result = generate_3d_visual_payload(
            heart_rate_bpm=300.0,
            contractility_index=99.0,
            afterload_index=-5.0,
            preload_index=-1.0,
            oxygen_delivery_index=5.0,
            inflammation_index=-1.0,
            scar_fraction=2.0,
            beat_amplitude=10.0,
            electrical_wave_speed=100.0,
        )
        assert 0.0 <= result["oxygen_delivery_index"] <= 1.0
        assert 0.0 <= result["scar_fraction"] <= 1.0
        assert result["beat_amplitude"] <= 1.5
        assert result["electrical_wave_speed"] <= 2.0


# ---------------------------------------------------------------------------
# Environment bounding unit tests
# ---------------------------------------------------------------------------


class TestEnvBounding:
    def _make_env(self, **kwargs) -> OperatingEnvironment:
        return OperatingEnvironment(**kwargs)

    def test_nominal_env_no_warnings(self):
        env = self._make_env()
        bounded, warns = _bound_env(env)
        assert warns == []

    def test_activity_clamped_above_max(self):
        env = self._make_env(activity_level_mets=25.0)
        bounded, warns = _bound_env(env)
        assert bounded["activity_level_mets"] == 20.0
        assert any("activity_level_mets" in w for w in warns)

    def test_hydration_clamped_below_min(self):
        env = self._make_env(hydration_index=-1.0)
        bounded, warns = _bound_env(env)
        assert bounded["hydration_index"] == 0.0
        assert any("hydration_index" in w for w in warns)

    def test_altitude_clamped(self):
        env = self._make_env(altitude_m=9000.0)
        bounded, warns = _bound_env(env)
        assert bounded["altitude_m"] == 5500.0

    def test_oxygen_fraction_clamped(self):
        env = self._make_env(oxygen_fraction=0.01)
        bounded, warns = _bound_env(env)
        assert bounded["oxygen_fraction"] == 0.10

    def test_environment_effects_hr_increases_with_activity(self):
        env_low = self._make_env(activity_level_mets=1.0)
        env_high = self._make_env(activity_level_mets=8.0)
        low_bounded, _ = _bound_env(env_low)
        high_bounded, _ = _bound_env(env_high)
        low_eff = _compute_environment_effects(low_bounded)
        high_eff = _compute_environment_effects(high_bounded)
        assert high_eff["hr_modifier"] > low_eff["hr_modifier"]

    def test_altitude_reduces_o2_delivery(self):
        sea_level = self._make_env(altitude_m=0.0)
        altitude = self._make_env(altitude_m=4000.0)
        sea_b, _ = _bound_env(sea_level)
        alt_b, _ = _bound_env(altitude)
        sea_eff = _compute_environment_effects(sea_b)
        alt_eff = _compute_environment_effects(alt_b)
        assert alt_eff["o2_delivery_modifier"] < sea_eff["o2_delivery_modifier"]


# ---------------------------------------------------------------------------
# Agent integration tests
# ---------------------------------------------------------------------------


class TestHemodynamicsAgent:
    async def test_valid_state_computes_sv_ef_co_map(self):
        state = _make_state(edv=130.0, esv=50.0, hr=72.0, sbp=120.0, dbp=80.0)
        response, hd, viz = await run_hemodynamics_agent(state, "case-valid-001")

        # agent field is the backward-compatible orchestrator ID
        assert response.agent == "hemodynamics_agent"
        # AGENT_ID is the semantic identifier carried inside outputs
        assert response.outputs.get("agent_id") == AGENT_ID
        assert response.status in (AgentStatus.SUCCESS, AgentStatus.WARNING)
        assert response.confidence >= 0.0

        outputs = response.outputs
        # SV = 130 - 50 = 80 mL
        assert abs(outputs["stroke_volume_ml"] - 80.0) < 0.5
        # EF = 80/130 * 100 ≈ 61.5%
        assert 55.0 < outputs["ef_pct"] < 70.0
        # CO = HR * SV / 1000
        co_expected = 72.0 * 80.0 / 1000.0
        assert abs(outputs["cardiac_output_l_min"] - co_expected) < 0.5
        # MAP = DBP + (SBP-DBP)/3 = 80 + 40/3 ≈ 93.3
        assert abs(outputs["map_mmhg"] - 93.3) < 1.0

    async def test_hemodynamics_schema_populated(self):
        state = _make_state()
        _, hd, _ = await run_hemodynamics_agent(state, "case-hd-001")

        assert hd.preload_index is not None
        assert hd.afterload_index is not None
        assert hd.contractility_index is not None
        assert hd.systemic_vascular_resistance_index is not None
        assert hd.pv_loop_area_index is not None
        assert 0.0 < hd.preload_index.value < 5.0

    async def test_missing_edv_warns_but_does_not_crash(self):
        state = _make_state(edv=None)
        response, hd, viz = await run_hemodynamics_agent(state, "case-no-edv")

        # Should produce a warning, not a crash
        assert response.status in (AgentStatus.WARNING, AgentStatus.SUCCESS)
        assert any("EDV" in w for w in response.warnings)

    async def test_missing_esv_warns(self):
        state = _make_state(esv=None)
        response, _, _ = await run_hemodynamics_agent(state, "case-no-esv")
        assert any("ESV" in w for w in response.warnings)

    async def test_refuse_policy_blocks_when_missing(self):
        state = _make_state(edv=None, missing_value_policy=MissingValuePolicy.REFUSE)
        response, hd, viz = await run_hemodynamics_agent(state, "case-refuse")
        assert response.status == AgentStatus.FAILED
        assert response.confidence == 0.0
        assert viz.get("blocked") is True

    async def test_pv_loop_arrays_generated(self):
        state = _make_state()
        _, _, viz = await run_hemodynamics_agent(state, "case-pv-001")

        pv = viz["pv_loop"]
        assert "volume_ml" in pv
        assert "pressure_mmhg" in pv
        assert len(pv["volume_ml"]) > 0
        assert len(pv["volume_ml"]) == len(pv["pressure_mmhg"])
        assert pv["loop_area_index"] > 0
        assert pv["model"] == "simplified_time_varying_elastance"
        assert pv["simulation_label"] == "educational simulation"

    async def test_cardiac_cycle_generated(self):
        state = _make_state()
        _, _, viz = await run_hemodynamics_agent(state, "case-cc-001")

        cc = viz["cardiac_cycle"]
        assert "time_ms" in cc
        assert "volume_ml" in cc
        assert "pressure_mmhg" in cc
        assert "phase" in cc
        assert len(cc["time_ms"]) > 0
        assert len(cc["time_ms"]) == len(cc["phase"])

    async def test_visualization_payload_3d_fields(self):
        state = _make_state()
        _, _, viz = await run_hemodynamics_agent(state, "case-viz-001")

        heart_3d = viz["3d_heart"]
        required_3d = [
            "heart_rate_bpm", "beat_interval_ms", "beat_amplitude",
            "contractility_index", "afterload_index", "preload_index",
            "oxygen_delivery_index", "inflammation_index", "scar_fraction",
            "stress_field_intensity", "blood_flow_particle_density",
            "electrical_wave_speed", "simulation_label",
        ]
        for field in required_3d:
            assert field in heart_3d, f"3D payload missing field: {field}"
        assert heart_3d["simulation_label"] == "educational visualization"

    async def test_environment_effects_returned(self):
        state = _make_state()
        _, _, viz = await run_hemodynamics_agent(state, "case-env-001")
        assert "simulation_note" in viz
        assert "operation_summary" in viz

    async def test_priors_reduce_confidence(self):
        full_state = _make_state(edv=130.0, esv=50.0, data_quality_score=0.80)
        prior_state = _make_state(edv=None, esv=None, data_quality_score=0.80)

        full_response, _, _ = await run_hemodynamics_agent(full_state, "case-full")
        prior_response, _, _ = await run_hemodynamics_agent(prior_state, "case-prior")

        assert prior_response.confidence < full_response.confidence

    async def test_impossible_esv_gte_edv_warns_and_clamps(self):
        state = _make_state(edv=100.0, esv=110.0)
        response, _, viz = await run_hemodynamics_agent(state, "case-impossible-esv")

        assert response.status in (AgentStatus.WARNING, AgentStatus.SUCCESS)
        assert any("ESV" in w and "EDV" in w for w in response.warnings)
        # Despite impossible input, still produces a valid simulation
        assert response.outputs["ef_pct"] > 0

    async def test_impossible_dbp_gte_sbp_warns(self):
        state = _make_state(sbp=80.0, dbp=90.0)
        response, _, _ = await run_hemodynamics_agent(state, "case-impossible-bp")
        assert any("Diastolic" in w or "DBP" in w or "diastolic" in w for w in response.warnings)

    async def test_no_unsafe_medical_language_in_outputs(self):
        state = _make_state()
        response, _, viz = await run_hemodynamics_agent(state, "case-safety-001")

        from python.hearttwin.safety import strip_allowed_safety_phrases

        # Collect all string output values, then remove approved safety phrasing
        all_text = " ".join(
            str(v) for v in (list(response.outputs.values()) + response.warnings)
        )
        all_text += str(viz.get("simulation_note", ""))
        all_text += str(viz.get("operation_summary", ""))

        # Strip the required safety disclaimer before checking for blocked terms
        scrubbed = strip_allowed_safety_phrases(all_text)

        # "diagnosis", "treatment" etc. only blocked outside the approved disclaimer
        blocked = ["prescri", "you have", "you are", "take this", "triage", "emergenc", "ambulance"]
        for term in blocked:
            assert term.lower() not in scrubbed.lower(), (
                f"Unsafe medical language detected: '{term}' found in outputs"
            )

    async def test_weave_local_trace_records_steps(self):
        state = _make_state()
        response, _, _ = await run_hemodynamics_agent(state, "case-trace-001")

        # TraceContext should have recorded tool steps
        assert isinstance(response.trace, list)
        assert len(response.trace) > 0
        tool_names = [step.get("tool", step) if isinstance(step, dict) else step.tool
                      for step in response.trace]
        # At minimum, formula indices and PV loop should be traced
        assert any("hemodynamics" in str(t) or "pv_loop" in str(t) or "cardiac_cycle" in str(t)
                   or "llm" in str(t) for t in tool_names)

    async def test_agent_id_and_name_in_outputs(self):
        state = _make_state()
        response, _, _ = await run_hemodynamics_agent(state, "case-id-001")
        assert response.outputs.get("agent_id") == AGENT_ID
        assert response.outputs.get("agent_name") == AGENT_NAME

    async def test_tools_called_list_present(self):
        state = _make_state()
        response, _, _ = await run_hemodynamics_agent(state, "case-tools-001")
        tools = response.outputs.get("tools_called", [])
        assert isinstance(tools, list)
        assert len(tools) >= 7

    async def test_scar_reduces_contractility(self):
        clean = _make_state(scar=0.0)
        scarred = _make_state(scar=0.4)

        _, hd_clean, _ = await run_hemodynamics_agent(clean, "case-clean")
        _, hd_scarred, _ = await run_hemodynamics_agent(scarred, "case-scarred")

        # Contractility index should be lower with scar
        assert hd_scarred.contractility_index.value < hd_clean.contractility_index.value

    async def test_stress_mode_increases_hr(self):
        rest = _make_state(hr=70.0, mode=OperatingMode.REST)
        stress = _make_state(hr=70.0, mode=OperatingMode.STRESS)

        _, _, rest_viz = await run_hemodynamics_agent(rest, "case-rest")
        _, _, stress_viz = await run_hemodynamics_agent(stress, "case-stress")

        rest_hr = rest_viz["summary"]["heart_rate_bpm"]
        stress_hr = stress_viz["summary"]["heart_rate_bpm"]
        assert stress_hr > rest_hr

    async def test_pv_loop_point_count(self):
        state = _make_state()
        _, _, viz = await run_hemodynamics_agent(state, "case-pv-count")
        assert len(viz["pv_loop"]["volume_ml"]) == 200

    async def test_confidence_clamped_0_1(self):
        for dq in (0.0, 0.5, 1.0):
            state = _make_state(data_quality_score=dq)
            response, _, _ = await run_hemodynamics_agent(state, f"case-conf-{dq}")
            assert 0.0 <= response.confidence <= 1.0

    async def test_simulation_label_present(self):
        state = _make_state()
        response, _, viz = await run_hemodynamics_agent(state, "case-label-001")
        assert "simulation_label" in response.outputs.get("simulation_note", "")  \
            or "Educational" in str(viz.get("simulation_note", ""))


# ---------------------------------------------------------------------------
# Confidence scoring unit test
# ---------------------------------------------------------------------------


class TestConfidenceScoring:
    def _base_state(self) -> CardiacTwinState:
        return _make_state(data_quality_score=0.7)

    def test_all_fields_present_increases_confidence(self):
        state = self._base_state()
        fp = {f: True for f in ["edv_ml", "esv_ml", "heart_rate_bpm", "systolic_bp_mmhg", "diastolic_bp_mmhg"]}
        score_full = _compute_confidence(state, fp, [], [], [], True)

        fp_none = {f: False for f in fp}
        score_none = _compute_confidence(state, fp_none, [], [], [], True)

        assert score_full > score_none

    def test_priors_reduce_confidence(self):
        state = self._base_state()
        fp = {f: True for f in ["edv_ml", "esv_ml"]}
        score_no_prior = _compute_confidence(state, fp, [], [], [], False)
        score_with_prior = _compute_confidence(state, fp, ["edv_ml", "esv_ml"], [], [], False)
        assert score_with_prior < score_no_prior

    def test_impossible_states_reduce_confidence(self):
        state = self._base_state()
        fp = {f: True for f in ["edv_ml", "esv_ml"]}
        score_ok = _compute_confidence(state, fp, [], [], [], False)
        score_imp = _compute_confidence(state, fp, [], [], ["ESV >= EDV"], False)
        assert score_imp < score_ok

    def test_confidence_always_in_range(self):
        state = self._base_state()
        for dq in (0.0, 0.3, 0.7, 1.0):
            state.data_quality_score = dq
            score = _compute_confidence(state, {}, ["a", "b", "c", "d", "e"], ["x", "y"], ["z"], False)
            assert 0.0 <= score <= 1.0
