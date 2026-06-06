"""Structured eval score tests."""

from __future__ import annotations

from python.hearttwin.tools.scoring import (
    evaluate_run,
    score_hallucination_risk,
    score_physiological_plausibility,
    score_safety_compliance,
)


def _state() -> dict:
    return {
        "measurements": {
            "heart_rate_bpm": {"value": 80, "source": "user_input", "confidence": 0.95},
            "systolic_bp_mmhg": {"value": 120, "source": "user_input", "confidence": 0.95},
            "diastolic_bp_mmhg": {"value": 80, "source": "user_input", "confidence": 0.95},
            "edv_ml": {"value": 130, "source": "user_input", "confidence": 0.95},
            "esv_ml": {"value": 60, "source": "user_input", "confidence": 0.95},
            "ejection_fraction_pct": {"value": 53.8, "source": "derived", "confidence": 0.95},
            "stroke_volume_ml": {"value": 70, "source": "derived", "confidence": 0.95},
            "cardiac_output_l_min": {"value": 5.6, "source": "derived", "confidence": 0.9},
            "oxygen_saturation_pct": {"value": 98, "source": "user_input", "confidence": 0.95},
        },
        "electrophysiology": {
            "rr_interval_ms": {"value": 750, "source": "derived", "confidence": 0.9}
        },
        "hemodynamics": {},
        "tissue_state": {},
        "source_map": [
            {"field": field, "source": value["source"], "confidence": value["confidence"]}
            for field, value in {
                "heart_rate_bpm": {"source": "user_input", "confidence": 0.95},
                "systolic_bp_mmhg": {"source": "user_input", "confidence": 0.95},
                "diastolic_bp_mmhg": {"source": "user_input", "confidence": 0.95},
                "edv_ml": {"source": "user_input", "confidence": 0.95},
                "esv_ml": {"source": "user_input", "confidence": 0.95},
                "ejection_fraction_pct": {"source": "derived", "confidence": 0.95},
            }.items()
        ],
    }


def test_scores_are_clamped_between_zero_and_one():
    result = evaluate_run(
        _state(),
        [{"agent": "evaluator_agent", "outputs": {"simulation_note": "not for diagnosis or treatment decisions"}}],
        {},
    )
    for key, value in result.items():
        if isinstance(value, float):
            assert 0.0 <= value <= 1.0, key


def test_overall_score_penalizes_hallucination_risk():
    safe = evaluate_run(_state(), [{"agent": "a", "outputs": {"simulation_note": "not for diagnosis or treatment decisions"}}])
    risky = evaluate_run(
        _state(),
        [{"agent": "a", "outputs": {"summary": "diagnosis cured prescription 999 888 777 666"}}],
    )
    assert risky["hallucination_risk"] > safe["hallucination_risk"]
    assert risky["overall_score"] < safe["overall_score"]


def test_unsafe_wording_reduces_safety_score():
    score = score_safety_compliance({"text": "you have a diagnosis and treatment plan"})
    assert score < 0.8


def test_impossible_physiology_reduces_plausibility_score():
    state = _state()
    state["measurements"]["edv_ml"]["value"] = 60
    state["measurements"]["esv_ml"]["value"] = 90
    assert score_physiological_plausibility(state) < 0.8


def test_missing_source_increases_hallucination_risk():
    sourced = _state()
    missing = _state()
    missing["source_map"] = []
    assert score_hallucination_risk([], missing) > score_hallucination_risk([], sourced)
