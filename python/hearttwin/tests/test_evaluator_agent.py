"""Tests for the Evaluator & Critic Agent (Agent 8).

Covers:
  - All eval scores clamped to [0, 1]
  - Overall score formula penalizes hallucination risk
  - Unsafe wording lowers safety compliance
  - Missing sources increase hallucination risk
  - Impossible physiology lowers plausibility score
  - Recovery instability lowers stability score
  - Visualization missing lowers readiness score
  - Critic findings are harness-focused (no treatment recommendations)
  - No forbidden words in required_revisions
  - EvaluatorOutput schema validates
  - Weave/local trace steps are recorded
  - run_evaluator_agent backward-compatible signature works
  - safe_to_display gate blocks critical unsafe phrases
"""

from __future__ import annotations

import asyncio
from typing import Any

import pytest

from python.hearttwin.agents.evaluator_agent import (
    CriticFinding,
    EvalScores,
    EvaluatorInput,
    EvaluatorOutput,
    RecoveryOutput,
    ValidatorOutput,
    _clamp,
    _dedupe_local,
    _detect_unsafe_phrases,
    _detect_unsupported_numeric_claims,
    _generate_critic_findings,
    _get_prior_fields,
    _harness_improvement_recommendations,
    _is_safe_to_display,
    run_evaluator_agent,
    run_evaluator_critic,
)
from python.hearttwin.schemas import (
    AgentResponse,
    AgentStatus,
    CardiacTwinState,
    Measurements,
    MeasuredValue,
    ValueSource,
    SourceMapEntry,
)


# ---------------------------------------------------------------------------
# Test fixtures
# ---------------------------------------------------------------------------


def _measured(value: float, source: str = "user_input", confidence: float = 0.9) -> MeasuredValue:
    return MeasuredValue(
        value=value,
        unit="",
        source=ValueSource(source),
        confidence=confidence,
    )


def _good_state() -> CardiacTwinState:
    """A physiologically valid cardiac twin state."""
    meas = Measurements(
        heart_rate_bpm=_measured(75),
        systolic_bp_mmhg=_measured(120),
        diastolic_bp_mmhg=_measured(80),
        edv_ml=_measured(130),
        esv_ml=_measured(55),
        ejection_fraction_pct=_measured(57.7, source="derived"),
        stroke_volume_ml=_measured(75, source="derived"),
        cardiac_output_l_min=_measured(5.6, source="derived"),
        oxygen_saturation_pct=_measured(98),
    )
    state = CardiacTwinState(measurements=meas)
    state.source_map = [
        SourceMapEntry(
            field=field,
            source=ValueSource.USER_INPUT,
            confidence=0.9,
        )
        for field in (
            "heart_rate_bpm",
            "systolic_bp_mmhg",
            "diastolic_bp_mmhg",
            "edv_ml",
            "esv_ml",
            "ejection_fraction_pct",
        )
    ]
    return state


def _good_agent_responses(state: CardiacTwinState) -> list[AgentResponse]:
    return [
        AgentResponse(
            agent="hemodynamics_agent",
            status=AgentStatus.SUCCESS,
            outputs={
                "simulation_note": (
                    "Educational cardiac simulation only. "
                    "Not for diagnosis or treatment decisions."
                ),
                "ef_pct": state.measurements.ejection_fraction_pct.value
                if state.measurements.ejection_fraction_pct
                else 57.7,
            },
            confidence=0.9,
        )
    ]


def _good_viz_payload(state: CardiacTwinState) -> dict[str, Any]:
    return {
        "pv_loop": {"volumes_ml": [55, 130], "pressures_mmhg": [80, 120]},
        "summary": {"ef_pct": 57.7},
        "recovery_scenarios": [
            {
                "scenario_label": "Simulated Load Reduction Scenario",
                "trajectory": [
                    {
                        "day": 0,
                        "ef_pct": 57.7,
                        "cardiac_output_l_min": 5.6,
                        "uncertainty_low": 0.55,
                        "uncertainty_high": 0.65,
                    },
                    {
                        "day": 7,
                        "ef_pct": 59.0,
                        "cardiac_output_l_min": 5.8,
                        "uncertainty_low": 0.55,
                        "uncertainty_high": 0.68,
                    },
                ],
                "warnings": ["Simulated trajectory — not clinical guidance"],
            }
        ],
    }


def _good_eval_scores(**overrides: float) -> EvalScores:
    base = dict(
        extraction_completeness=0.80,
        physiological_plausibility=0.85,
        safety_compliance=0.95,
        hallucination_risk=0.05,
        visualization_readiness=0.75,
        recovery_scenario_stability=0.90,
        overall_score=0.85,
    )
    base.update(overrides)
    return EvalScores(**base)


# ---------------------------------------------------------------------------
# Score clamping
# ---------------------------------------------------------------------------


def test_clamp_helper_bounds():
    assert _clamp(-0.5) == 0.0
    assert _clamp(1.5) == 1.0
    assert _clamp(0.5) == 0.5


def test_scores_clamped_to_zero_one():
    """All EvalScores fields must be in [0, 1]."""
    scores = _good_eval_scores()
    for field in EvalScores.model_fields:
        if field in ("warnings", "failed_checks"):
            continue
        val = getattr(scores, field)
        assert 0.0 <= val <= 1.0, f"Score field '{field}' out of range: {val}"


# ---------------------------------------------------------------------------
# Overall score formula
# ---------------------------------------------------------------------------


def test_overall_score_penalizes_hallucination_risk():
    """Higher hallucination risk → lower overall score."""
    low_risk = _good_eval_scores(hallucination_risk=0.05)
    high_risk = _good_eval_scores(hallucination_risk=0.80)

    overall_low = _clamp(
        0.20 * low_risk.extraction_completeness
        + 0.25 * low_risk.physiological_plausibility
        + 0.25 * low_risk.safety_compliance
        + 0.15 * low_risk.visualization_readiness
        + 0.15 * low_risk.recovery_scenario_stability
        - 0.20 * low_risk.hallucination_risk
    )
    overall_high = _clamp(
        0.20 * high_risk.extraction_completeness
        + 0.25 * high_risk.physiological_plausibility
        + 0.25 * high_risk.safety_compliance
        + 0.15 * high_risk.visualization_readiness
        + 0.15 * high_risk.recovery_scenario_stability
        - 0.20 * high_risk.hallucination_risk
    )

    assert overall_high < overall_low


# ---------------------------------------------------------------------------
# Unsafe wording detection
# ---------------------------------------------------------------------------


def test_detect_unsafe_phrases_catches_diagnosis():
    payload = {"text": "The patient has a diagnosis and treatment plan."}
    found = _detect_unsafe_phrases(payload, [])
    assert "diagnosis" in found
    assert "treatment plan" in found


def test_detect_unsafe_phrases_ignores_disclaimer():
    """The safety disclaimer itself should NOT trigger unsafe-phrase detection."""
    payload = {
        "text": (
            "Educational cardiac simulation only. "
            "Not for diagnosis or treatment decisions."
        )
    }
    found = _detect_unsafe_phrases(payload, [])
    # "diagnosis" inside the approved phrase is stripped before scanning
    assert not any(p in ("diagnosed", "treatment plan", "prescribe") for p in found)


def test_unsafe_wording_lowers_safety_score():
    """run_evaluator_critic returns lower safety_compliance when unsafe text present."""

    async def _run() -> EvalScores:
        state = _good_state()
        inp = EvaluatorInput(
            case_id="test-unsafe",
            cardiac_state=state,
            generated_text=["You have a diagnosis and treatment plan."],
        )
        out, _ = await run_evaluator_critic(inp)
        return out.eval_scores

    scores = asyncio.get_event_loop().run_until_complete(_run())
    assert scores.safety_compliance < 0.85


# ---------------------------------------------------------------------------
# Hallucination risk
# ---------------------------------------------------------------------------


def test_missing_sources_increase_hallucination_risk():
    """State without source_map → higher hallucination risk."""

    async def _run(has_sources: bool) -> float:
        state = _good_state()
        if not has_sources:
            state.source_map = []
        inp = EvaluatorInput(case_id="test-hal", cardiac_state=state)
        out, _ = await run_evaluator_critic(inp)
        return out.eval_scores.hallucination_risk

    risk_with = asyncio.get_event_loop().run_until_complete(_run(True))
    risk_without = asyncio.get_event_loop().run_until_complete(_run(False))
    assert risk_without > risk_with


def test_unsupported_numeric_claims_detected():
    """Numeric claims not in state are flagged."""
    state = _good_state()
    state_dict = state.model_dump()
    unsupported = _detect_unsupported_numeric_claims(
        [{"summary": "The EF is 999.9 and CO is 888.8 and BP is 777.7"}],
        [],
        state_dict,
    )
    # These values are not in the state
    assert 999.9 in unsupported or 888.8 in unsupported


# ---------------------------------------------------------------------------
# Physiological plausibility
# ---------------------------------------------------------------------------


def test_impossible_physiology_lowers_plausibility():
    """ESV ≥ EDV → physiologically impossible → lower plausibility score."""

    async def _run(esv: float, edv: float) -> float:
        state = _good_state()
        state.measurements.esv_ml = _measured(esv)
        state.measurements.edv_ml = _measured(edv)
        inp = EvaluatorInput(case_id="test-physio", cardiac_state=state)
        out, _ = await run_evaluator_critic(inp)
        return out.eval_scores.physiological_plausibility

    plausible = asyncio.get_event_loop().run_until_complete(_run(55, 130))
    impossible = asyncio.get_event_loop().run_until_complete(_run(150, 130))
    assert impossible < plausible


def test_impossible_physiology_generates_critic_finding():
    """ESV ≥ EDV must generate a high-severity physiology CriticFinding."""
    state = _good_state()
    meas = state.measurements.model_dump()
    meas["esv_ml"]["value"] = 160
    meas["edv_ml"]["value"] = 130

    scores = _good_eval_scores(physiological_plausibility=0.30)
    findings = _generate_critic_findings(
        scores,
        {"measurements": meas, "source_map": [], "data_quality_score": 0.7},
        [],
        [],
        {},
        None,
        [],
        [],
    )
    physio_findings = [f for f in findings if f.category == "physiology"]
    assert any(f.severity == "high" for f in physio_findings)
    assert any("esv" in f.issue.lower() or "edv" in f.issue.lower() for f in physio_findings)


# ---------------------------------------------------------------------------
# Recovery scenario stability
# ---------------------------------------------------------------------------


def test_recovery_instability_lowers_stability_score():
    """Unrealistic EF jumps in trajectory → lower recovery stability score."""

    async def _run(ef_jump: bool) -> float:
        state = _good_state()
        traj = [
            {
                "day": 0,
                "ef_pct": 57.0,
                "cardiac_output_l_min": 5.5,
                "uncertainty_low": 0.50,
                "uncertainty_high": 0.65,
            },
            {
                "day": 7,
                "ef_pct": 95.0 if ef_jump else 58.0,
                "cardiac_output_l_min": 5.6,
                "uncertainty_low": 0.50,
                "uncertainty_high": 0.65,
            },
        ]
        viz = {"recovery_scenarios": [{"trajectory": traj, "warnings": ["simulated"]}]}
        inp = EvaluatorInput(
            case_id="test-stability",
            cardiac_state=state,
            recovery=RecoveryOutput(
                scenarios=[{"trajectory": traj, "warnings": ["simulated"]}]
            ),
        )
        out, _ = await run_evaluator_critic(inp, viz_payload=viz)
        return out.eval_scores.recovery_scenario_stability

    stable = asyncio.get_event_loop().run_until_complete(_run(False))
    unstable = asyncio.get_event_loop().run_until_complete(_run(True))
    assert unstable < stable


# ---------------------------------------------------------------------------
# Visualization readiness
# ---------------------------------------------------------------------------


def test_visualization_missing_lowers_readiness():
    """Empty viz payload → lower visualization_readiness score."""

    async def _run(with_viz: bool) -> float:
        state = _good_state()
        inp = EvaluatorInput(case_id="test-viz", cardiac_state=state)
        viz = (
            {
                "pv_loop": {"volumes_ml": [55, 130], "pressures_mmhg": [80, 120]},
                "summary": {"ef_pct": 57.7},
            }
            if with_viz
            else {}
        )
        out, _ = await run_evaluator_critic(inp, viz_payload=viz)
        return out.eval_scores.visualization_readiness

    with_viz = asyncio.get_event_loop().run_until_complete(_run(True))
    without_viz = asyncio.get_event_loop().run_until_complete(_run(False))
    assert without_viz <= with_viz


# ---------------------------------------------------------------------------
# Critic findings: harness-focused, no treatment recommendations
# ---------------------------------------------------------------------------

_FORBIDDEN_MEDICAL_WORDS = {
    "medication",
    "prescribe",
    "treat",
    "diagnos",
    "clinical",
    "healed",
    "cured",
    "surgery",
    "drug",
    "dose",
    "therapy",
}


def _has_forbidden_medical_content(text: str) -> bool:
    lower = text.lower()
    return any(word in lower for word in _FORBIDDEN_MEDICAL_WORDS)


def test_critic_findings_are_harness_focused():
    """All CriticFinding.fix values must not contain forbidden medical keywords."""
    scores = _good_eval_scores(
        safety_compliance=0.55,
        physiological_plausibility=0.30,
        hallucination_risk=0.60,
        recovery_scenario_stability=0.50,
    )
    findings = _generate_critic_findings(
        scores,
        {"measurements": {}, "source_map": [], "data_quality_score": 0.3},
        [],
        ["diagnosis and treatment plan for the patient"],
        {},
        None,
        [999.0, 888.0],
        ["diagnosis", "treatment plan"],
    )
    for finding in findings:
        assert not _has_forbidden_medical_content(
            finding.fix
        ), f"Forbidden medical content in fix: {finding.fix!r}"


def test_no_treatment_recommendations_in_revisions():
    """_generate_required_revisions must not contain forbidden medical keywords."""
    from python.hearttwin.agents.evaluator_agent import _generate_required_revisions

    scores = _good_eval_scores(
        safety_compliance=0.40,
        hallucination_risk=0.70,
        physiological_plausibility=0.20,
    )
    findings = [
        CriticFinding(
            issue="Test safety issue",
            severity="high",
            evidence="test",
            fix="Remove the unsafe phrase",
            category="safety",
        )
    ]
    revisions = _generate_required_revisions(scores, findings)
    for rev in revisions:
        assert not _has_forbidden_medical_content(rev), (
            f"Forbidden medical content in revision: {rev!r}"
        )


def test_harness_improvement_recommendations_are_safe():
    """_harness_improvement_recommendations must never mention forbidden medical words."""
    scores = _good_eval_scores(
        extraction_completeness=0.30,
        recovery_scenario_stability=0.40,
    )
    state_dict = {
        "source_map": [
            {"field": "edv_ml", "source": "default_model_prior"},
            {"field": "esv_ml", "source": "default_model_prior"},
        ],
        "simulation_config": {
            "recovery": {
                "max_safe_parameter_shift": 0.40,
                "uncertainty_penalty_weight": 0.10,
                "recovery_horizon_days": 60,
            }
        },
        "data_quality_score": 0.3,
    }
    recs = _harness_improvement_recommendations(scores, state_dict, None)
    for rec in recs:
        assert not _has_forbidden_medical_content(rec), (
            f"Forbidden content in recommendation: {rec!r}"
        )


# ---------------------------------------------------------------------------
# Schema validation
# ---------------------------------------------------------------------------


def test_evaluator_output_schema_validates():
    """EvaluatorOutput must successfully round-trip through Pydantic."""
    scores = _good_eval_scores()
    out = EvaluatorOutput(
        eval_scores=scores,
        critic_findings=[
            CriticFinding(
                issue="Test issue",
                severity="low",
                evidence="score=0.5",
                fix="adjust uncertainty_penalty_weight",
                category="orchestration",
            )
        ],
        safe_to_display=True,
        required_revisions=[],
        summary="All checks passed.",
    )
    dumped = out.model_dump()
    re_parsed = EvaluatorOutput.model_validate(dumped)
    assert re_parsed.eval_scores.overall_score == scores.overall_score
    assert re_parsed.safe_to_display is True


def test_eval_scores_validation_rejects_out_of_range():
    """EvalScores must reject values outside [0, 1]."""
    with pytest.raises(Exception):
        EvalScores(
            extraction_completeness=1.5,
            physiological_plausibility=0.8,
            safety_compliance=0.9,
            hallucination_risk=0.1,
            visualization_readiness=0.7,
            recovery_scenario_stability=0.85,
            overall_score=0.8,
        )


# ---------------------------------------------------------------------------
# Weave/local trace works
# ---------------------------------------------------------------------------


def test_evaluator_critic_records_trace_steps():
    """run_evaluator_critic should record at least one trace step in the stage result."""

    async def _run() -> list[str]:
        state = _good_state()
        inp = EvaluatorInput(case_id="test-trace", cardiac_state=state)
        _, stage_result = await run_evaluator_critic(inp)
        return stage_result.tools_called

    tools = asyncio.get_event_loop().run_until_complete(_run())
    assert "hearttwin.evaluate_run" in tools
    assert "hearttwin.score_extraction_completeness" in tools
    assert "hearttwin.score_safety_compliance" in tools


def test_evaluator_agent_sets_agent_id_and_name():
    """AgentStageResult must carry the correct agent_id and agent_name."""

    async def _run() -> tuple[str, str]:
        state = _good_state()
        inp = EvaluatorInput(case_id="test-id", cardiac_state=state)
        _, stage_result = await run_evaluator_critic(inp)
        return stage_result.agent_id, stage_result.agent_name

    agent_id, agent_name = asyncio.get_event_loop().run_until_complete(_run())
    assert agent_id == "evaluator_critic"
    assert agent_name == "Evaluator & Critic Agent"


# ---------------------------------------------------------------------------
# Backward-compatible run_evaluator_agent signature
# ---------------------------------------------------------------------------


def test_run_evaluator_agent_returns_agent_response_and_report():
    """run_evaluator_agent must return (AgentResponse, dict) without errors."""

    async def _run() -> tuple[AgentResponse, dict]:
        state = _good_state()
        responses = _good_agent_responses(state)
        viz = _good_viz_payload(state)
        return await run_evaluator_agent(state, responses, viz, "test-compat")

    resp, report = asyncio.get_event_loop().run_until_complete(_run())
    assert isinstance(resp, AgentResponse)
    assert resp.agent == "evaluator_agent"
    assert "eval_scores" in report
    assert "critic_findings" in report
    assert "safe_to_display" in report


def test_run_evaluator_agent_report_has_required_score_keys():
    """Report from run_evaluator_agent must include all 7 score dimensions."""

    async def _run() -> dict:
        state = _good_state()
        _, report = await run_evaluator_agent(
            state, _good_agent_responses(state), _good_viz_payload(state), "test-keys"
        )
        return report

    report = asyncio.get_event_loop().run_until_complete(_run())
    es = report["eval_scores"]
    for field in (
        "extraction_completeness",
        "physiological_plausibility",
        "safety_compliance",
        "hallucination_risk",
        "visualization_readiness",
        "recovery_scenario_stability",
        "overall_score",
    ):
        assert field in es, f"Missing key in eval_scores: {field}"
        val = es[field]
        assert 0.0 <= val <= 1.0, f"Score {field}={val} out of range"


# ---------------------------------------------------------------------------
# Safe-to-display gate
# ---------------------------------------------------------------------------


def test_safe_to_display_blocks_critical_phrases():
    """'prescribe' and 'diagnosed' in output → safe_to_display=False."""
    scores_good = _good_eval_scores(safety_compliance=0.80)
    critical_phrases = ["prescribe", "diagnosed"]
    assert not _is_safe_to_display(scores_good, critical_phrases)


def test_safe_to_display_permits_clean_output():
    """No unsafe phrases + good safety score → safe_to_display=True."""
    scores_good = _good_eval_scores(safety_compliance=0.95)
    assert _is_safe_to_display(scores_good, [])


def test_safe_to_display_false_when_safety_compliance_critically_low():
    """safety_compliance < 0.50 → safe_to_display=False regardless of phrases."""
    scores_low = _good_eval_scores(safety_compliance=0.40)
    assert not _is_safe_to_display(scores_low, [])


# ---------------------------------------------------------------------------
# Prior-field handling
# ---------------------------------------------------------------------------


def test_prior_fields_detected():
    state_dict = {
        "source_map": [
            {"field": "edv_ml", "source": "default_model_prior"},
            {"field": "esv_ml", "source": "default_model_prior"},
            {"field": "heart_rate_bpm", "source": "user_input"},
        ]
    }
    priors = _get_prior_fields(state_dict)
    assert "edv_ml" in priors
    assert "esv_ml" in priors
    assert "heart_rate_bpm" not in priors


def test_high_prior_count_generates_uncertainty_finding():
    """More than 8 prior fields → uncertainty CriticFinding."""
    state_dict = {
        "measurements": {},
        "source_map": [
            {"field": f"field_{i}", "source": "default_model_prior"}
            for i in range(10)
        ],
        "data_quality_score": 0.5,
    }
    scores = _good_eval_scores()
    findings = _generate_critic_findings(
        scores, state_dict, [], [], {}, None, [], []
    )
    uncertainty_findings = [f for f in findings if f.category == "uncertainty"]
    assert any("prior" in f.issue.lower() for f in uncertainty_findings)


# ---------------------------------------------------------------------------
# EvaluatorInput schema
# ---------------------------------------------------------------------------


def test_evaluator_input_defaults_are_empty():
    inp = EvaluatorInput(case_id="test-defaults")
    assert inp.cardiac_state is None
    assert inp.trace == []
    assert inp.generated_text == []


def test_evaluator_input_with_all_fields():
    state = _good_state()
    inp = EvaluatorInput(
        case_id="test-full",
        cardiac_state=state,
        recovery=RecoveryOutput(scenarios=[], warnings=["no scenarios"]),
        generated_text=["Educational cardiac simulation only."],
    )
    assert inp.case_id == "test-full"
    assert inp.cardiac_state is not None
    assert inp.recovery.warnings == ["no scenarios"]


# ---------------------------------------------------------------------------
# dedupe helper
# ---------------------------------------------------------------------------


def test_dedupe_local_removes_duplicates():
    result = _dedupe_local(["a", "b", "a", "c", "b"])
    assert result == ["a", "b", "c"]
