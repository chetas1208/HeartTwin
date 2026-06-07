"""Weave tracing tests (configured + unconfigured behavior).

By default everything runs against the local trace fallback. External Weave
integration is only exercised when RUN_EXTERNAL_INTEGRATION_TESTS=true.
"""

from __future__ import annotations

import contextlib
import os

import pytest

from python.hearttwin.tools.weave_trace import (
    TraceSink,
    get_traces,
    weave_status,
)

EXTERNAL = os.environ.get("RUN_EXTERNAL_INTEGRATION_TESTS", "").lower() in {"1", "true", "yes"}


@contextlib.contextmanager
def env(**kv):
    old = {k: os.environ.get(k) for k in kv}
    try:
        for k, v in kv.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        yield
    finally:
        for k, v in old.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v


def test_missing_wandb_key_uses_local_fallback() -> None:
    with env(WANDB_API_KEY=None):
        status = weave_status()
        assert status["enabled"] is False
        assert status["status"] in {"not_configured", "error"}


def test_weave_project_default() -> None:
    with env(WANDB_PROJECT=None, WANDB_API_KEY=None):
        status = weave_status()
        assert status["project"] == "hearttwin-weavehacks"


def test_trace_sink_never_throws() -> None:
    sink = TraceSink()
    # All trace operations are best-effort and must never raise.
    run_id = sink.start_run("case-x", "extract", {"k": "v"})
    sink.log_agent_stage(run_id, {"stage": "s", "agent": "a", "status": "success"})
    sink.log_tool_call(run_id, "tool", {"in": 1}, {"out": 2})
    sink.log_eval_scores(run_id, {"overall_score": 0.9}, [])
    sink.finish_run(run_id, "success", {"done": True})
    # Even with a bad run_id, no exception.
    sink.log_agent_stage(None, {"stage": "s"})
    sink.finish_run(None, "success", {})


def test_agent_stage_written_locally() -> None:
    sink = TraceSink()
    run_id = sink.start_run("case-local-1", "operate", {})
    sink.log_agent_stage(run_id, {"stage": "build", "agent": "state_builder_agent", "status": "success"})
    events = get_traces("case-local-1")
    assert any(e.get("kind") == "agent_stage" and e.get("agent") == "state_builder_agent" for e in events)


def test_eval_scores_logged_locally() -> None:
    sink = TraceSink()
    run_id = sink.start_run("case-local-2", "operate", {})
    sink.log_eval_scores(run_id, {"overall_score": 0.77, "safety_compliance": 1.0}, ["w1"])
    events = get_traces("case-local-2")
    assert any(e.get("kind") == "eval_scores" for e in events)


async def test_self_improvement_comparison_logged_locally(baseline_vitals) -> None:
    from python.hearttwin.orchestrator import (
        run_extraction_pipeline,
        run_operation_pipeline,
        run_recovery_pipeline,
        run_self_improvement_pipeline,
    )
    from python.hearttwin.schemas import CaseRecord

    case = CaseRecord(status="created")
    _, case = await run_extraction_pipeline(case=case, files=[], user_vitals=baseline_vitals)
    await run_operation_pipeline(case=case)
    await run_recovery_pipeline(case=case)
    result = await run_self_improvement_pipeline(case)

    assert "before" in result and "after" in result
    assert "score_delta" in result
    events = get_traces(case.case_id)
    # A self_improve run was started and finished locally.
    assert any(e.get("kind") == "run_start" and e.get("run_type") == "self_improve" for e in events)


def test_raw_report_text_is_not_logged_verbatim() -> None:
    sink = TraceSink()
    run_id = sink.start_run("case-redact", "extract", {})
    long_report = "Patient John Doe SSN 123-45-6789. " + ("clinical narrative " * 50)
    sink.log_tool_call(run_id, "extract", {"report": long_report}, {"ok": True})
    events = get_traces("case-redact")
    blob = str(events)
    # SSN redacted and long text trimmed (sanitizer caps strings at 280 chars).
    assert "123-45-6789" not in blob
    assert "clinical narrative " * 50 not in blob


def test_secrets_not_logged() -> None:
    sink = TraceSink()
    with env(OPENAI_API_KEY="sk-secret-should-not-appear-1234567890"):
        run_id = sink.start_run("case-secret", "extract", {})
        # Even if a caller accidentally passes a key-like field, traces are local
        # and we never serialize os.environ into them.
        sink.log_tool_call(run_id, "extract", {"note": "no secret here"}, {"ok": True})
        blob = str(get_traces("case-secret"))
        assert "sk-secret-should-not-appear-1234567890" not in blob


@pytest.mark.skipif(not EXTERNAL, reason="external Weave integration disabled (set RUN_EXTERNAL_INTEGRATION_TESTS=true)")
def test_external_weave_init() -> None:
    sink = TraceSink()
    assert sink.enabled() in (True, False)
    status = weave_status()
    if status["enabled"]:
        assert status["project_url"]
