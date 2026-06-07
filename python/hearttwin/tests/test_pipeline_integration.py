"""Full pipeline integration tests against synthetic fixtures.

Proves the pipeline does real work (not static placeholders): extraction →
validation → state build → electrophysiology → hemodynamics → PV loop →
recovery → evaluation → trace. Runs deterministically without OpenAI.
"""

from __future__ import annotations

import pytest

from python.hearttwin.orchestrator import (
    run_extraction_pipeline,
    run_operation_pipeline,
    run_recovery_pipeline,
)
from python.hearttwin.schemas import CaseRecord
from python.hearttwin.tools.weave_trace import get_traces

_UNSAFE = [
    "you have", "you should take", "healed", "cured", "treatment plan",
    "prescribe", "dosage", "recommend medication", "patient improved medically",
    "recovery guaranteed",
]


def _distinct_stage_agents(case_id: str) -> set[str]:
    return {
        e.get("agent")
        for e in get_traces(case_id)
        if isinstance(e, dict) and e.get("kind") == "agent_stage" and e.get("agent")
    }


def _no_unsafe_language(text: str) -> bool:
    low = text.lower()
    return not any(p in low for p in _UNSAFE)


async def _run_all(vitals: dict):
    case = CaseRecord(status="created")
    _, case = await run_extraction_pipeline(case=case, files=[], user_vitals=vitals)
    op_resp, viz, report = await run_operation_pipeline(case=case)
    rec_resp, scenarios, rec_report = await run_recovery_pipeline(case=case)
    return case, viz, report, scenarios, rec_report


# ---------------------------------------------------------------------------
# Baseline
# ---------------------------------------------------------------------------


async def test_baseline_full_pipeline(baseline_vitals) -> None:
    case, viz, report, scenarios, _ = await _run_all(baseline_vitals)

    # Extraction produced validated evidence
    assert case.validated_fields
    for key in ("heart_rate_bpm", "systolic_bp_mmhg", "diastolic_bp_mmhg", "edv_ml", "esv_ml"):
        assert key in case.validated_fields, f"missing validated field {key}"

    # State built with a source map
    assert case.state is not None
    assert case.state.source_map

    # Operation metrics
    summary = viz["summary"]
    assert summary["stroke_volume_ml"] == pytest.approx(70.0, abs=0.5)
    assert summary["ef_pct"] == pytest.approx(58.33, abs=0.5)
    assert summary["cardiac_output_l_min"] == pytest.approx(5.04, abs=0.05)
    assert summary["map_mmhg"] == pytest.approx(93.33, abs=0.5)

    # PV loop and 3D payload non-empty
    assert viz["pv_loop"]
    assert viz["3d_heart"]
    assert viz["electrophysiology"]["rr_interval_ms"] == pytest.approx(833.33, abs=1.0)

    # Recovery: 2-4 scenarios with non-empty trajectories + uncertainty bands
    assert 2 <= len(scenarios) <= 4
    for sc in scenarios:
        assert sc["trajectory"], "scenario trajectory is empty"
        first = sc["trajectory"][0]
        assert "uncertainty_low" in first and "uncertainty_high" in first
        assert "simulation_label" in sc

    # Evaluator scores
    eval_scores = report["eval_scores"]
    for key in (
        "extraction_completeness", "physiological_plausibility", "safety_compliance",
        "hallucination_risk", "overall_score",
    ):
        assert key in eval_scores
    assert "warnings" in report

    # Trace: 8 distinct agent stage records
    agents = _distinct_stage_agents(case.case_id)
    assert len(agents) == 8, f"expected 8 distinct agent stages, got {sorted(agents)}"


# ---------------------------------------------------------------------------
# Reduced function
# ---------------------------------------------------------------------------


async def test_reduced_function_full_pipeline(reduced_function_vitals) -> None:
    case, viz, report, scenarios, _ = await _run_all(reduced_function_vitals)

    summary = viz["summary"]
    assert summary["stroke_volume_ml"] == pytest.approx(55.0, abs=0.5)
    assert summary["ef_pct"] == pytest.approx(36.67, abs=0.5)
    assert summary["cardiac_output_l_min"] == pytest.approx(4.84, abs=0.05)

    assert 2 <= len(scenarios) <= 4

    # No diagnosis/treatment language anywhere user-facing
    blobs = [str(viz), str(report), str(scenarios), str([r.model_dump() for r in case.stage_results])]
    for blob in blobs:
        assert _no_unsafe_language(blob), "unsafe medical language found in reduced-function output"


# ---------------------------------------------------------------------------
# Partial data
# ---------------------------------------------------------------------------


async def test_partial_data_pipeline_does_not_crash_and_warns(partial_vitals) -> None:
    case = CaseRecord(status="created")
    _, case = await run_extraction_pipeline(case=case, files=[], user_vitals=partial_vitals)

    # Operation may run with labeled priors or block — either way no crash.
    op_resp, viz, report = await run_operation_pipeline(case=case)
    assert case.state is not None

    # EDV/ESV were not provided. They must come from labeled priors, never silently invented.
    prior_fields = [
        entry.field for entry in case.state.source_map
        if entry.source.value == "default_model_prior"
    ]
    # At least one of EDV/ESV should be flagged as a prior (not user-provided).
    assert any(f in prior_fields for f in ("edv_ml", "esv_ml")), (
        "missing EDV/ESV should be sourced from labeled model priors"
    )

    # There must be warnings somewhere about missing/low-confidence data.
    all_warnings = list(case.state.warnings)
    for r in case.stage_results:
        all_warnings.extend(r.warnings)
    eval_warnings = report.get("warnings", []) if isinstance(report, dict) else []
    all_warnings.extend(eval_warnings)
    assert all_warnings, "partial data must surface warnings"

    # Recovery still runs safely (uncertainty handled, no crash).
    _, scenarios, rec_report = await run_recovery_pipeline(case=case)
    assert isinstance(scenarios, list)

    # No unsafe medical language.
    blob = str(viz) + str(report) + str(scenarios)
    assert _no_unsafe_language(blob)


async def test_partial_data_increases_hallucination_or_uncertainty(partial_vitals, baseline_vitals) -> None:
    # Compare hallucination risk: partial (prior-reliant) >= baseline (fully sourced).
    case_b, _, report_b, _, _ = await _run_all(baseline_vitals)

    case_p = CaseRecord(status="created")
    _, case_p = await run_extraction_pipeline(case=case_p, files=[], user_vitals=partial_vitals)
    _, _, report_p = await run_operation_pipeline(case=case_p)

    h_base = report_b["eval_scores"]["hallucination_risk"]
    h_partial = report_p["eval_scores"]["hallucination_risk"]
    assert h_partial >= h_base, (
        f"partial-data hallucination risk ({h_partial}) should be >= baseline ({h_base})"
    )
