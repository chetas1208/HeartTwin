"""Weave tracing fallback tests."""

from __future__ import annotations

from python.hearttwin.tools.weave_trace import get_trace_sink, get_traces


def test_weave_wrapper_does_not_throw_when_env_missing(monkeypatch):
    monkeypatch.delenv("WANDB_API_KEY", raising=False)
    sink = get_trace_sink()
    run_id = sink.start_run("case-fallback", "test", {"patient_name": "Jane Doe"})
    sink.log_agent_stage(run_id, {"stage": "extract_evidence", "status": "success"})
    sink.log_tool_call(run_id, "compute_map", {"systolic": 120}, {"map": 93.3})
    sink.log_eval_scores(run_id, {"overall_score": 0.9}, [])
    sink.finish_run(run_id, "success", {"done": True})

    traces = get_traces("case-fallback")
    assert traces
    assert sink.weave_info(run_id)["status"] == "not_configured"


def test_weave_trace_redacts_obvious_pii(monkeypatch):
    monkeypatch.delenv("WANDB_API_KEY", raising=False)
    sink = get_trace_sink()
    run_id = sink.start_run(
        "case-redact",
        "test",
        {"email": "person@example.com", "files": [{"filename": "report.pdf", "bytes": b"secret"}]},
    )
    sink.finish_run(run_id, "success", {})
    text = str(get_traces("case-redact"))
    assert "person@example.com" not in text
    assert "secret" not in text
