"""OpenAI fallback tests.

With OPENAI_API_KEY removed, every agent must fall back to deterministic logic:
- no crash
- no FAILED status purely due to a missing key
- LLM-backed stages report model_used=None (fallback active) in the trace

The deterministic core never depends on OpenAI.
"""

from __future__ import annotations

import contextlib
import os

import pytest

from python.hearttwin.agents.evaluator_agent import run_evaluator_agent
from python.hearttwin.agents.extraction_agent import run_extraction_agent
from python.hearttwin.agents.intake_agent import run_intake_agent
from python.hearttwin.agents.recovery_agent import run_recovery_agent
from python.hearttwin.agents.state_builder_agent import run_state_builder_agent
from python.hearttwin.agents.validator_agent import run_validator_agent
from python.hearttwin.orchestrator import (
    run_extraction_pipeline,
    run_operation_pipeline,
    run_recovery_pipeline,
)
from python.hearttwin.schemas import AgentStatus, CaseRecord
from python.hearttwin.tools.weave_trace import get_traces


@contextlib.contextmanager
def no_openai_key():
    old = os.environ.get("OPENAI_API_KEY")
    os.environ.pop("OPENAI_API_KEY", None)
    try:
        yield
    finally:
        if old is not None:
            os.environ["OPENAI_API_KEY"] = old


async def test_intake_fallback_allows_simulation() -> None:
    with no_openai_key():
        resp, _ = await run_intake_agent(
            files=[],
            patient_notes="Educational simulation of baseline cardiac function.",
            user_request_text="Run an educational cardiac simulation.",
        )
        assert resp.status != AgentStatus.FAILED


async def test_extraction_fallback_parses_vitals() -> None:
    with no_openai_key():
        resp = await run_extraction_agent(
            files=[],
            user_vitals={"heart_rate_bpm": 72, "edv_ml": 120, "esv_ml": 50},
            case_id="t-ext",
        )
        assert resp.status != AgentStatus.FAILED
        assert resp.outputs.get("extracted_fields")


async def test_validator_fallback_runs_deterministic_checks() -> None:
    with no_openai_key():
        resp = await run_validator_agent(
            extracted_fields={
                "heart_rate_bpm": {"value": 72, "source": "user_input"},
                "edv_ml": {"value": 120, "source": "user_input"},
                "esv_ml": {"value": 50, "source": "user_input"},
            },
            case_id="t-val",
        )
        assert resp.status != AgentStatus.FAILED


async def test_state_builder_fallback_builds_state(baseline_vitals) -> None:
    with no_openai_key():
        case = CaseRecord(status="created")
        _, case = await run_extraction_pipeline(case=case, files=[], user_vitals=baseline_vitals)
        resp, state = await run_state_builder_agent(
            validated_fields=case.validated_fields,
            case_id=case.case_id,
            simulation_config=None,
        )
        assert resp.status != AgentStatus.FAILED
        assert state is not None


async def test_recovery_fallback_uses_templates(baseline_vitals) -> None:
    with no_openai_key():
        case = CaseRecord(status="created")
        _, case = await run_extraction_pipeline(case=case, files=[], user_vitals=baseline_vitals)
        await run_operation_pipeline(case=case)
        resp, scenarios = await run_recovery_agent(
            state=case.state, recovery_configs=None, case_id=case.case_id
        )
        assert resp.status != AgentStatus.FAILED
        assert 2 <= len(scenarios) <= 4


async def test_evaluator_fallback_scores(baseline_vitals) -> None:
    with no_openai_key():
        case = CaseRecord(status="created")
        _, case = await run_extraction_pipeline(case=case, files=[], user_vitals=baseline_vitals)
        _, viz, _ = await run_operation_pipeline(case=case)
        resp, report = await run_evaluator_agent(
            state=case.state,
            all_agent_responses=case.stage_results,
            visualization_payload=viz,
            case_id=case.case_id,
        )
        assert resp.status != AgentStatus.FAILED
        assert "eval_scores" in report
        assert "overall_score" in report["eval_scores"]


async def test_full_pipeline_no_crash_without_key(baseline_vitals) -> None:
    with no_openai_key():
        case = CaseRecord(status="created")
        _, case = await run_extraction_pipeline(case=case, files=[], user_vitals=baseline_vitals)
        _, viz, report = await run_operation_pipeline(case=case)
        _, scenarios, _ = await run_recovery_pipeline(case=case)

        # Pipeline produced real outputs deterministically.
        assert viz["pv_loop"]
        assert 2 <= len(scenarios) <= 4
        assert report["eval_scores"]["overall_score"] is not None

        # LLM-backed stages report fallback (model_used None) in tool traces.
        events = [e for e in get_traces(case.case_id) if isinstance(e, dict)]
        assert any(e.get("kind") == "tool_call" for e in events), "expected tool calls in trace"
        reported_models = [
            e.get("outputs", {}).get("model_used")
            for e in events
            if e.get("kind") == "tool_call" and "model_used" in (e.get("outputs") or {})
        ]
        # When the key is absent, no tool should report a live OpenAI model name.
        assert all(m is None for m in reported_models), (
            f"tools reported live models without an API key: {reported_models}"
        )
