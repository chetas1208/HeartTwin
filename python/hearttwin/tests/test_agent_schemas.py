"""Tests for the shared AgentStageResult and ToolCallRecord schemas.

Verifies:
- Common contract fields exist and validate.
- Recovery-specific optional fields have safe defaults.
- ToolCallRecord validates strictly.
- No duplicate class definitions across agents (import from schemas).
"""

from __future__ import annotations

import pytest

from python.hearttwin.schemas import AgentStageResult, ToolCallRecord


# ---------------------------------------------------------------------------
# AgentStageResult
# ---------------------------------------------------------------------------


def _minimal_stage() -> dict:
    return {
        "agent_id": "test_agent",
        "agent_name": "Test Agent",
        "status": "success",
        "started_at": "2026-01-01T00:00:00+00:00",
        "finished_at": "2026-01-01T00:00:01+00:00",
        "latency_ms": 1000.0,
    }


def test_agent_stage_result_minimal_valid() -> None:
    r = AgentStageResult(**_minimal_stage())
    assert r.agent_id == "test_agent"
    assert r.confidence == 0.0
    assert r.inputs_used == []
    assert r.tools_called == []
    assert r.source_refs == []
    assert r.safety_flags == []
    assert r.weave_call_id is None
    assert r.local_trace_id is None


def test_agent_stage_result_all_common_fields() -> None:
    data = {
        **_minimal_stage(),
        "model_used": "gpt-5.5",
        "inputs_used": ["case_id", "cardiac_state"],
        "tools_called": ["compute_sv", "compute_ef"],
        "output_summary": "Built cardiac state successfully.",
        "structured_output": {"sv_ml": 60.0},
        "warnings": ["Using prior for weight."],
        "confidence": 0.85,
        "source_refs": [{"field": "heart_rate_bpm", "source": "extracted"}],
        "safety_flags": [],
        "weave_call_id": "weave-abc123",
        "local_trace_id": "local-xyz",
    }
    r = AgentStageResult(**data)
    assert r.model_used == "gpt-5.5"
    assert r.confidence == 0.85
    assert r.weave_call_id == "weave-abc123"


def test_agent_stage_result_invalid_status() -> None:
    with pytest.raises(Exception):
        AgentStageResult(**{**_minimal_stage(), "status": "bogus_status"})


def test_agent_stage_result_confidence_clamped_by_validation() -> None:
    with pytest.raises(Exception):
        AgentStageResult(**{**_minimal_stage(), "confidence": 1.5})


def test_agent_stage_result_recovery_specific_fields_optional() -> None:
    r = AgentStageResult(**_minimal_stage())
    assert r.scenario_count == 0
    assert r.scenario_types == []
    assert r.deterministic_tool_calls == 0
    assert r.memory_patterns_used == []
    assert r.uncertainty_status == ""


def test_agent_stage_result_recovery_fields_can_be_set() -> None:
    r = AgentStageResult(**{
        **_minimal_stage(),
        "agent_id": "recovery_orchestration",
        "scenario_count": 3,
        "scenario_types": ["load_reduction", "contractility_support", "rest"],
        "deterministic_tool_calls": 9,
        "memory_patterns_used": ["instability_v1"],
        "uncertainty_status": "moderate",
    })
    assert r.scenario_count == 3
    assert len(r.scenario_types) == 3
    assert r.deterministic_tool_calls == 9


def test_agent_stage_result_statuses() -> None:
    for status in ("success", "warning", "failed", "skipped"):
        r = AgentStageResult(**{**_minimal_stage(), "status": status})
        assert r.status == status


def test_agent_stage_result_model_used_optional_none() -> None:
    r = AgentStageResult(**_minimal_stage())
    assert r.model_used is None


# ---------------------------------------------------------------------------
# ToolCallRecord
# ---------------------------------------------------------------------------


def test_tool_call_record_defaults() -> None:
    t = ToolCallRecord(tool_name="compute_stroke_volume")
    assert t.deterministic is True
    assert t.input_keys == []
    assert t.output_keys == []
    assert t.latency_ms == 0.0
    assert t.status == "success"
    assert t.warnings == []


def test_tool_call_record_full() -> None:
    t = ToolCallRecord(
        tool_name="compute_map",
        deterministic=True,
        input_keys=["sbp_mmhg", "dbp_mmhg"],
        output_keys=["map_mmhg"],
        latency_ms=0.5,
        status="success",
        warnings=[],
    )
    assert t.tool_name == "compute_map"
    assert t.latency_ms == 0.5


def test_tool_call_record_invalid_status() -> None:
    with pytest.raises(Exception):
        ToolCallRecord(tool_name="foo", status="running")


def test_tool_call_record_warning_status() -> None:
    t = ToolCallRecord(tool_name="foo", status="warning", warnings=["clamped input"])
    assert t.status == "warning"
    assert len(t.warnings) == 1


# ---------------------------------------------------------------------------
# No duplicate class in agent files
# ---------------------------------------------------------------------------


def test_agent_stage_result_import_is_from_schemas() -> None:
    """All agents must import AgentStageResult from schemas, not redefine it."""
    import python.hearttwin.agents.intake_agent as ia
    import python.hearttwin.agents.validator_agent as va
    import python.hearttwin.agents.electrophysiology_agent as ep
    import python.hearttwin.agents.recovery_agent as ra
    import python.hearttwin.agents.evaluator_agent as ev

    for module in (ia, va, ep, ra, ev):
        assert module.AgentStageResult is AgentStageResult, (
            f"{module.__name__} defines its own AgentStageResult instead of importing from schemas"
        )


def test_tool_call_record_import_is_from_schemas() -> None:
    from python.hearttwin.schemas import ToolCallRecord as TCR
    assert TCR is ToolCallRecord
