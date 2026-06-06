"""Tests for bounded self-improvement reruns."""

from __future__ import annotations

import pytest

from python.hearttwin.orchestrator import (
    run_extraction_pipeline,
    run_operation_pipeline,
    run_recovery_pipeline,
    run_self_improvement_pipeline,
)
from python.hearttwin.schemas import CaseRecord

CASE_VITALS = {
    "heart_rate_bpm": 72.0,
    "systolic_bp_mmhg": 120.0,
    "diastolic_bp_mmhg": 80.0,
    "ejection_fraction_pct": 55.0,
}


async def _case_with_recovery() -> CaseRecord:
    case = CaseRecord(status="created")
    _, case = await run_extraction_pipeline(case=case, files=[], user_vitals=CASE_VITALS)
    _, _, _ = await run_operation_pipeline(case=case)
    assert case.state is not None
    case.state.warnings.append("pre-existing warning")
    _, _, _ = await run_recovery_pipeline(case=case)
    return case


@pytest.mark.asyncio
async def test_self_improvement_preserves_warnings():
    case = await _case_with_recovery()
    result = await run_self_improvement_pipeline(case)
    assert result["status"] in {"success", "warning"}
    assert "pre-existing warning" in result["after"]["warnings"]


@pytest.mark.asyncio
async def test_self_improvement_does_not_invent_missing_values():
    case = await _case_with_recovery()
    assert case.state is not None
    before = case.state.measurements.model_dump()
    await run_self_improvement_pipeline(case)
    after = case.state.measurements.model_dump()
    assert after == before


@pytest.mark.asyncio
async def test_self_improvement_improves_or_preserves_safety_compliance():
    case = await _case_with_recovery()
    result = await run_self_improvement_pipeline(case)
    before = result["before"]["eval_scores"]["safety_compliance"]
    after = result["after"]["eval_scores"]["safety_compliance"]
    assert after >= before
