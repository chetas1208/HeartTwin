"""FastAPI application for HeartTwin Lab.

All routes are under /api/v1.
Python functions are the source of truth for numeric outputs.

Pipeline per spec:
  POST /extract          → stages 1 (Intake) + 2 (Extraction) + 3 (Validator)
  POST /operate          → stages 4 (State Builder) + 5a/5b (EP + Hemodynamics) + 7 (Evaluator)
  POST /simulate-recovery → stages 6 (Recovery) + 7 (Evaluator)
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from typing import Any

from copilotkit.integrations.fastapi import add_fastapi_endpoint
from fastapi import FastAPI, File, HTTPException, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse

from python.hearttwin.copilot import build_sdk
from python.hearttwin.orchestrator import (
    run_extraction_pipeline,
    run_operation_pipeline,
    run_recovery_pipeline,
    run_self_improvement_pipeline,
)
from python.hearttwin.safety import (
    CORE_SAFETY_PHRASE,
    DISCLAIMER,
    SafetyViolation,
    add_disclaimer,
    check_request_safety,
)
from python.hearttwin.schemas import (
    CardiacTwinState,
    CaseRecord,
    CreateCaseRequest,
    ExtractRequest,
    HealthResponse,
    OperateRequest,
    SimulateRecoveryRequest,
    UploadedFile,
)
from python.hearttwin.tools.storage import get_case, get_file, store_case, store_file
from python.hearttwin.tools.env_config import validate_environment
from python.hearttwin.tools.model_config import (
    get_intake_model,
    get_extraction_model,
    get_validator_model,
    get_state_builder_model,
    get_electrophysiology_model,
    get_hemodynamics_model,
    get_recovery_model,
    get_evaluator_model,
)
from python.hearttwin.tools.weave_trace import get_latest_run, get_traces, weave_status
from python.hearttwin.tools.cardiac_findings import derive_findings

app = FastAPI(
    title="HeartTwin Lab API",
    description="Agentic cardiac digital twin simulator. Educational use only.",
    version="0.1.0",
    docs_url="/api/v1/docs",
    openapi_url="/api/v1/openapi.json",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ---------------------------------------------------------------------------
# CopilotKit (AG-UI) endpoint  — "Best Use of CopilotKit"
# ---------------------------------------------------------------------------
# Mounts the deterministic HeartTwin pipeline as CopilotKit server-side
# actions at /copilotkit. The CopilotKit runtime handshakes against
# /copilotkit/info; actions execute at /copilotkit/actions/execute.
_copilot_sdk = build_sdk()
add_fastapi_endpoint(app, _copilot_sdk, "/copilotkit")


# ---------------------------------------------------------------------------
# Health
# ---------------------------------------------------------------------------


@app.get("/api/v1/health", response_model=HealthResponse)
async def health() -> HealthResponse:
    return HealthResponse(environment=validate_environment())


# ---------------------------------------------------------------------------
# Config — safe public metadata (no secrets)
# ---------------------------------------------------------------------------


@app.get("/api/v1/config")
async def get_config() -> dict:
    """Return non-secret system configuration for UI/harness introspection.

    Never exposes API keys, tokens, or credentials.
    """
    import os

    wandb_key = os.environ.get("WANDB_API_KEY", "")
    upstash_url = os.environ.get("UPSTASH_REDIS_REST_URL", "")
    upstash_token = os.environ.get("UPSTASH_REDIS_REST_TOKEN", "")
    vista_enabled = os.environ.get("VISTA3D_ENABLED", "false").lower() == "true"
    vista_base = os.environ.get("VISTA3D_API_BASE", "")

    return {
        "app_name": "HeartTwin Lab",
        "api_base": "/api/v1",
        "weave": {
            "configured": bool(wandb_key),
            "project": os.environ.get("WANDB_PROJECT", "hearttwin-weavehacks"),
            "entity": os.environ.get("WANDB_ENTITY", ""),
        },
        "redis": {
            "configured": bool(upstash_url and upstash_token),
        },
        "vista3d": {
            "enabled": vista_enabled,
            "configured": bool(vista_base),
        },
        "models": {
            "intake": get_intake_model(),
            "extraction": get_extraction_model(),
            "validator": get_validator_model(),
            "state_builder": get_state_builder_model(),
            "electrophysiology": get_electrophysiology_model(),
            "hemodynamics": get_hemodynamics_model(),
            "recovery": get_recovery_model(),
            "evaluator": get_evaluator_model(),
        },
    }


# ---------------------------------------------------------------------------
# System check  — golden case A validation
# ---------------------------------------------------------------------------

_GOLDEN_VITALS = {
    "heart_rate_bpm": 88.0,
    "systolic_bp_mmhg": 135.0,
    "diastolic_bp_mmhg": 85.0,
    "edv_ml": 130.0,
    "esv_ml": 70.0,
}

_GOLDEN_EXPECTED = {
    "sv_ml": 60.0,
    "ef_pct": 46.15,
    "co_l_min": 5.28,
    "map_mmhg": 101.67,
}


def _scan_for_secrets(payload: Any) -> list[str]:
    """Return the names of any secret env vars whose real value leaks in payload.

    Used to assert that public responses never expose configured secrets. Only
    flags secrets that actually have a non-trivial value set in the environment.
    """
    import json as _json
    import os

    from python.hearttwin.tools.env_spec import SECRET_ENV_VARS

    try:
        blob = _json.dumps(payload, default=str)
    except Exception:  # noqa: BLE001
        blob = str(payload)

    leaked: list[str] = []
    for name in SECRET_ENV_VARS:
        value = os.environ.get(name, "")
        if value and len(value) >= 8 and value in blob:
            leaked.append(name)
    return leaked


def _integration_status() -> dict[str, str]:
    """Map current env to honest integration status strings (no secrets)."""
    import os

    openai_status = "configured" if os.environ.get("OPENAI_API_KEY") else "fallback"

    weave_configured = bool(os.environ.get("WANDB_API_KEY"))
    weave_status_str = "configured" if weave_configured else "local_fallback"

    redis_configured = bool(
        os.environ.get("UPSTASH_REDIS_REST_URL") and os.environ.get("UPSTASH_REDIS_REST_TOKEN")
    )
    redis_status_str = "configured" if redis_configured else "memory_fallback"

    vista_enabled = os.environ.get("VISTA3D_ENABLED", "false").strip().lower() in {
        "1", "true", "yes", "on", "enabled"
    }
    vista_base = os.environ.get("VISTA3D_API_BASE")
    if not vista_enabled:
        vista_status_str = "disabled"
    elif vista_base:
        vista_status_str = "configured"
    else:
        vista_status_str = "warning"

    return {
        "openai": openai_status,
        "weave": weave_status_str,
        "redis": redis_status_str,
        "vista3d": vista_status_str,
    }


@app.get("/api/v1/system-check")
async def system_check() -> dict:
    """End-to-end deterministic health check using golden case vitals.

    Creates an ephemeral (not persisted) case, runs the full pipeline with
    known inputs, and validates outputs against expected values. Reports honest
    fallback states for optional integrations — never fakes success.
    """
    from python.hearttwin.tools.cardiac_state import (
        compute_cardiac_output,
        compute_ejection_fraction,
        compute_map,
        compute_rr_from_hr,
        compute_stroke_volume,
    )

    checks: list[dict] = []
    warnings: list[str] = []
    metrics: dict = {}

    def _add(name: str, status: str, message: str) -> None:
        checks.append({"name": name, "status": status, "message": message})

    # --- 0. API health & config safety ---
    _add("api_health", "ok", "API reachable")
    try:
        cfg = await get_config()
        leaked = _scan_for_secrets(cfg)
        if leaked:
            _add("config_safe", "failed", f"config exposed secret-like values: {leaked}")
        else:
            _add("config_safe", "ok", "config endpoint exposes no secrets")
    except Exception as exc:  # noqa: BLE001
        _add("config_safe", "failed", f"config check error: {exc}")

    # --- 1. Formula layer ---
    try:
        hr = _GOLDEN_VITALS["heart_rate_bpm"]
        edv = _GOLDEN_VITALS["edv_ml"]
        esv = _GOLDEN_VITALS["esv_ml"]
        sbp = _GOLDEN_VITALS["systolic_bp_mmhg"]
        dbp = _GOLDEN_VITALS["diastolic_bp_mmhg"]

        sv = compute_stroke_volume(edv, esv)
        ef = compute_ejection_fraction(edv, esv)
        co = compute_cardiac_output(hr, sv)
        map_val = compute_map(sbp, dbp)
        rr = compute_rr_from_hr(hr)

        metrics = {
            "sv_ml": round(sv, 2),
            "ef_pct": round(ef, 2),
            "co_l_min": round(co, 2),
            "map_mmhg": round(map_val, 2),
            "rr_interval_ms": round(rr, 2),
        }
        formula_ok = (
            abs(sv - _GOLDEN_EXPECTED["sv_ml"]) < 0.1
            and abs(ef - _GOLDEN_EXPECTED["ef_pct"]) < 0.1
            and abs(co - _GOLDEN_EXPECTED["co_l_min"]) < 0.05
            and abs(map_val - _GOLDEN_EXPECTED["map_mmhg"]) < 0.1
        )
        _add(
            "formulas",
            "ok" if formula_ok else "failed",
            f"SV={metrics['sv_ml']} EF={metrics['ef_pct']} CO={metrics['co_l_min']} "
            f"MAP={metrics['map_mmhg']} RR={metrics['rr_interval_ms']}",
        )
    except Exception as exc:  # noqa: BLE001
        _add("formulas", "failed", f"formula error: {exc}")

    # --- 2. Full pipeline (ephemeral, not persisted) ---
    case = None
    try:
        case = CaseRecord(status="created")
        _, case = await run_extraction_pipeline(case=case, files=[], user_vitals=_GOLDEN_VITALS)
        _add(
            "extraction",
            "ok" if case.validated_fields else "failed",
            f"{len(case.validated_fields)} validated fields",
        )
    except Exception as exc:  # noqa: BLE001
        _add("extraction", "failed", f"extraction error: {exc}")

    try:
        if case is None:
            raise RuntimeError("no case from extraction")
        _, viz_payload, eval_report = await run_operation_pipeline(case=case)
        summary = (viz_payload or {}).get("summary", {})
        sim_ok = bool(viz_payload and summary and viz_payload.get("pv_loop"))
        _add(
            "operation",
            "ok" if sim_ok else "failed",
            f"EF={summary.get('ef_pct')} CO={summary.get('cardiac_output_l_min')} "
            f"pv_loop={bool(viz_payload.get('pv_loop'))}",
        )
        eval_scores = eval_report.get("eval_scores", {}) if isinstance(eval_report, dict) else {}
        _add(
            "evaluation",
            "ok" if "overall_score" in eval_scores else "failed",
            f"overall_score={eval_scores.get('overall_score')}",
        )
    except Exception as exc:  # noqa: BLE001
        _add("operation", "failed", f"operation error: {exc}")
        _add("evaluation", "failed", "evaluation skipped (operation failed)")

    try:
        if case is None or not case.state:
            raise RuntimeError("no state for recovery")
        _, scenarios, _ = await run_recovery_pipeline(case=case)
        ok = bool(scenarios and 2 <= len(scenarios) <= 4)
        _add("recovery", "ok" if ok else "warning", f"{len(scenarios)} scenarios")
    except Exception as exc:  # noqa: BLE001
        _add("recovery", "failed", f"recovery error: {exc}")

    # --- 3. Trace / integrations (honest fallback reporting) ---
    integrations = _integration_status()
    _add("trace", "ok", f"weave={integrations['weave']}")
    if integrations["weave"] == "local_fallback":
        warnings.append("Weave not configured; using local trace fallback")
    if integrations["redis"] == "memory_fallback":
        warnings.append("Redis not configured; using in-memory fallback")
    if integrations["openai"] == "fallback":
        warnings.append("OpenAI not configured; deterministic fallbacks active")
    if integrations["vista3d"] == "warning":
        warnings.append("VISTA3D enabled but VISTA3D_API_BASE missing")

    # --- 4. Safety layer ---
    try:
        from python.hearttwin.safety import check_request_safety

        blocked = False
        try:
            check_request_safety("what diagnosis do I have and what treatment should I take?")
        except Exception:  # noqa: BLE001
            blocked = True
        _add(
            "safety",
            "ok" if blocked else "failed",
            "blocks diagnosis/treatment requests" if blocked else "failed to block unsafe request",
        )
    except Exception as exc:  # noqa: BLE001
        _add("safety", "failed", f"safety error: {exc}")

    _add("safety_phrase", "ok", DISCLAIMER)

    statuses = [c["status"] for c in checks]
    if any(s == "failed" for s in statuses):
        overall = "failed"
    elif any(s == "warning" for s in statuses):
        overall = "warning"
    else:
        overall = "ok"
    failed = [c["name"] for c in checks if c["status"] == "failed"]

    return {
        "status": overall,
        "checks": checks,
        "metrics": metrics,
        "integrations": integrations,
        "warnings": warnings,
        "failed_checks": failed,
        "golden_inputs": _GOLDEN_VITALS,
        "safety_disclaimer": DISCLAIMER,
    }


# ---------------------------------------------------------------------------
# Cases
# ---------------------------------------------------------------------------


@app.post("/api/v1/cases")
async def create_case(request: CreateCaseRequest) -> dict:
    """Create a new cardiac twin case."""
    if request.patient_notes:
        try:
            check_request_safety(request.patient_notes)
        except SafetyViolation as e:
            raise HTTPException(status_code=422, detail=str(e))

    case = CaseRecord(patient_notes=request.patient_notes, status="created")
    if request.simulation_config:
        case.state = CardiacTwinState(
            case_id=case.case_id, simulation_config=request.simulation_config
        )

    await store_case(case.case_id, case.model_dump(mode="json"))
    return add_disclaimer({
        "case_id": case.case_id,
        "created_at": case.created_at.isoformat(),
        "status": case.status,
    })


@app.get("/api/v1/cases/{case_id}")
async def get_case_detail(case_id: str) -> dict:
    case_data = await get_case(case_id)
    if not case_data:
        raise HTTPException(status_code=404, detail=f"Case {case_id} not found")
    return add_disclaimer(case_data)


@app.get("/api/v1/cases/{case_id}/trace")
async def get_trace(case_id: str) -> dict:
    case_data = await get_case(case_id)
    if not case_data:
        raise HTTPException(status_code=404, detail=f"Case {case_id} not found")
    latest = get_latest_run(case_id)
    run_id = latest.get("run_id") if latest else None
    traces = get_traces(case_id)
    return {
        "case_id": case_id,
        "traces": traces,
        "weave": {
            **weave_status(run_id),
            "latest_run_id": run_id,
            "traced_stages_count": sum(1 for t in traces if t.get("kind") == "agent_stage"),
            "traced_tool_calls_count": sum(1 for t in traces if t.get("kind") == "tool_call"),
        },
        "safety_disclaimer": DISCLAIMER,
    }


# ---------------------------------------------------------------------------
# Live trace stream (SSE)
# ---------------------------------------------------------------------------
#
# The web frontend (useTraceStream) opens an EventSource here to render the
# agent pipeline live. HeartTwin keeps traces in-process via
# weave_trace.get_traces (the same source as GET /trace), so the stream polls
# that list and emits each new entry. Every event is sent under the SSE event
# name "trace"; the real kind travels in the JSON payload so a single browser
# listener receives all of them. There is no polling fallback — this endpoint
# is the single live transport.

_TRACE_STREAM_POLL_SECONDS = 1.0


@app.get("/api/v1/cases/{case_id}/trace/stream")
async def stream_trace(
    case_id: str, request: Request, last_id: str | None = None
) -> StreamingResponse:
    case_data = await get_case(case_id)
    if not case_data:
        raise HTTPException(status_code=404, detail=f"Case {case_id} not found")

    resume_from = last_id or request.headers.get("Last-Event-ID")
    return StreamingResponse(
        _trace_stream_events(case_id, request, resume_from),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


async def _trace_stream_events(
    case_id: str,
    request: Request,
    last_id: str | None,
) -> AsyncIterator[str]:
    yield _sse_event(
        event_id=f"setup:{case_id}",
        kind="stream_setup",
        payload={
            "case_id": case_id,
            "source": "local",
            "last_id": last_id,
            "poll_seconds": _TRACE_STREAM_POLL_SECONDS,
            "safety_disclaimer": DISCLAIMER,
        },
    )

    next_index = _local_resume_index(last_id)
    while not await request.is_disconnected():
        traces = get_traces(case_id)
        while next_index < len(traces):
            trace = traces[next_index]
            kind = str(
                trace.get("kind")
                or trace.get("event")
                or trace.get("agent")
                or "trace"
            )
            yield _sse_event(
                event_id=f"local-{next_index + 1}",
                kind=kind,
                payload={
                    "case_id": case_id,
                    "source": "local",
                    "local_index": next_index,
                    "payload": trace,
                    "safety_disclaimer": DISCLAIMER,
                },
            )
            next_index += 1
        # Comment line doubles as a keep-alive ping; EventSource ignores it.
        yield ": ping\n\n"
        await asyncio.sleep(_TRACE_STREAM_POLL_SECONDS)


def _sse_event(event_id: str, kind: str, payload: dict[str, Any]) -> str:
    # A single stable SSE event name ("trace") so the browser EventSource
    # delivers every event to one listener regardless of kind. The real kind
    # (and original event name) travel in the data payload.
    data = {"kind": kind, "event": kind, **payload}
    body = json.dumps(data, default=str, sort_keys=True)
    return f"id: {event_id}\nevent: trace\ndata: {body}\n\n"


def _local_resume_index(last_id: str | None) -> int:
    if not last_id or not last_id.startswith("local-"):
        return 0
    try:
        return max(0, int(last_id.removeprefix("local-")))
    except ValueError:
        return 0


@app.get("/api/v1/cases/{case_id}/harness")
async def get_harness(case_id: str) -> dict:
    """Return harness metadata for a case: agent stage results, eval scores, Weave/Redis status."""
    case_data = await get_case(case_id)
    if not case_data:
        raise HTTPException(status_code=404, detail=f"Case {case_id} not found")
    latest = get_latest_run(case_id)
    run_id = latest.get("run_id") if latest else None
    traces = get_traces(case_id)
    wv = weave_status(run_id)

    stage_results = case_data.get("stage_results", [])
    eval_scores = case_data.get("eval_scores") or case_data.get("evaluation", {})
    self_improve = case_data.get("self_improvement")

    return add_disclaimer({
        "case_id": case_id,
        "stage_results": stage_results,
        "eval_scores": eval_scores,
        "self_improvement": self_improve,
        "weave": {
            **wv,
            "latest_run_id": run_id,
            "traced_stages_count": sum(1 for t in traces if t.get("kind") == "agent_stage"),
            "traced_tool_calls_count": sum(1 for t in traces if t.get("kind") == "tool_call"),
        },
        "redis": {
            "configured": bool(
                __import__("os").environ.get("UPSTASH_REDIS_REST_URL")
                and __import__("os").environ.get("UPSTASH_REDIS_REST_TOKEN")
            ),
        },
    })


# ---------------------------------------------------------------------------
# File upload
# ---------------------------------------------------------------------------


_ALLOWED_TYPES = {
    "application/pdf",
    "text/csv",
    "text/plain",
    "application/json",
    "application/octet-stream",
}


@app.post("/api/v1/cases/{case_id}/files")
async def upload_file(case_id: str, file: UploadFile = File(...)) -> dict:
    """Upload a PDF, image, CSV, TXT, or JSON to a case."""
    case_data = await get_case(case_id)
    if not case_data:
        raise HTTPException(status_code=404, detail=f"Case {case_id} not found")

    case = CaseRecord(**case_data)
    content_type = file.content_type or "application/octet-stream"

    if content_type not in _ALLOWED_TYPES and not content_type.startswith("image/"):
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported file type '{content_type}'. Accepted: PDF, image, CSV, TXT, JSON.",
        )

    file_bytes = await file.read()
    if len(file_bytes) > 50 * 1024 * 1024:
        raise HTTPException(status_code=400, detail="File exceeds 50 MB limit")

    file_id, storage_url = await store_file(file_bytes, file.filename or "upload", content_type)

    uploaded = UploadedFile(
        file_id=file_id,
        filename=file.filename or "upload",
        content_type=content_type,
        size_bytes=len(file_bytes),
        storage_url=storage_url,
    )
    case.files.append(uploaded)
    await store_case(case_id, case.model_dump(mode="json"))

    return add_disclaimer({
        "file_id": file_id,
        "filename": uploaded.filename,
        "content_type": content_type,
        "size_bytes": len(file_bytes),
        "storage_url": storage_url,
    })


# ---------------------------------------------------------------------------
# Stage 1-3: Extract
# ---------------------------------------------------------------------------


@app.post("/api/v1/cases/{case_id}/extract")
async def extract(case_id: str, request: ExtractRequest) -> dict:
    """Run stages 1 (Intake), 2 (Extraction), 3 (Validation).

    Stores validated evidence in case. Does NOT build the cardiac state yet.
    Call /operate after this to build the state and run the simulation.
    """
    case_data = await get_case(case_id)
    if not case_data:
        raise HTTPException(status_code=404, detail=f"Case {case_id} not found")

    case = CaseRecord(**case_data)

    if request.user_vitals:
        try:
            check_request_safety(str(request.user_vitals))
        except SafetyViolation as e:
            raise HTTPException(status_code=422, detail=str(e))

    files_with_bytes: list[dict] = []
    for uf in case.files:
        if not request.file_ids or uf.file_id in request.file_ids:
            fb = await get_file(uf.file_id)
            if fb:
                files_with_bytes.append({
                    "file_id": uf.file_id,
                    "filename": uf.filename,
                    "content_type": uf.content_type,
                    "bytes": fb,
                })

    stage_responses, case = await run_extraction_pipeline(
        case=case,
        files=files_with_bytes,
        user_vitals=request.user_vitals,
    )

    await store_case(case_id, case.model_dump(mode="json"))
    latest = get_latest_run(case_id)
    run_id = latest.get("run_id") if latest else None

    return add_disclaimer({
        "case_id": case_id,
        "status": case.status,
        "validated_field_count": len(case.validated_fields),
        "validated_fields": case.validated_fields,
        "stage_results": [r.model_dump() for r in stage_responses],
        "weave": weave_status(run_id),
    })


# ---------------------------------------------------------------------------
# Stage 4-5-7: Operate
# ---------------------------------------------------------------------------


@app.post("/api/v1/cases/{case_id}/operate")
async def operate(case_id: str, request: OperateRequest) -> dict:
    """Run stages 4 (State Builder), 5a+5b (EP + Hemodynamics), 7 (Evaluator).

    Builds the CardiacTwinState, simulates one cardiac cycle, and scores the run.
    Requires /extract to have been called first (validated_fields must exist).
    """
    case_data = await get_case(case_id)
    if not case_data:
        raise HTTPException(status_code=404, detail=f"Case {case_id} not found")

    case = CaseRecord(**case_data)

    if not case.validated_fields and case.status not in ("extracted", "operated"):
        raise HTTPException(
            status_code=422,
            detail="No validated evidence found — call /extract first, or POST /extract with user vitals.",
        )

    if request.operating_environment:
        if case.state is None:
            case.state = CardiacTwinState(case_id=case.case_id)
        case.state.simulation_config.operating = request.operating_environment

    stage_responses, viz_payload, eval_report = await run_operation_pipeline(case=case)

    # Localize the simulated state to anatomy (AHA 17-segment + coronary
    # territory) as educational, code-tagged findings for the 3D heart view.
    if isinstance(viz_payload, dict):
        viz_payload["cardiac_findings"] = derive_findings(
            case.state.model_dump() if case.state else None, viz_payload
        )

    await store_case(case_id, case.model_dump(mode="json"))
    latest = get_latest_run(case_id)
    run_id = latest.get("run_id") if latest else None

    return add_disclaimer({
        "case_id": case_id,
        "status": case.status,
        "data_quality_score": case.state.data_quality_score if case.state else 0.0,
        "state": case.state.model_dump() if case.state else None,
        "visualization": viz_payload,
        "evaluation": eval_report,
        "stage_results": [r.model_dump() for r in stage_responses],
        "weave": weave_status(run_id),
    })


# ---------------------------------------------------------------------------
# Stage 6-7: Simulate Recovery
# ---------------------------------------------------------------------------


@app.post("/api/v1/cases/{case_id}/simulate-recovery")
async def simulate_recovery_endpoint(case_id: str, request: SimulateRecoveryRequest) -> dict:
    """Run stages 6 (Recovery Orchestration) and 7 (Evaluator).

    Generates 2-4 bounded simulated recovery scenarios with uncertainty bands.
    Requires /operate to have been called first.
    """
    case_data = await get_case(case_id)
    if not case_data:
        raise HTTPException(status_code=404, detail=f"Case {case_id} not found")

    case = CaseRecord(**case_data)

    if not case.state:
        raise HTTPException(
            status_code=422,
            detail="No cardiac state — call /operate first to build the cardiac twin state.",
        )

    if request.recovery_config:
        case.state.simulation_config.recovery = request.recovery_config

    stage_responses, scenarios, eval_report = await run_recovery_pipeline(
        case=case,
        recovery_configs=request.scenarios,
    )

    await store_case(case_id, case.model_dump(mode="json"))
    latest = get_latest_run(case_id)
    run_id = latest.get("run_id") if latest else None

    return add_disclaimer({
        "case_id": case_id,
        "status": case.status,
        "scenarios": scenarios,
        "evaluation": eval_report,
        "stage_results": [r.model_dump() for r in stage_responses],
        "weave": weave_status(run_id),
        "simulation_note": (
            f"{CORE_SAFETY_PHRASE} All recovery trajectories are simulated estimates."
        ),
    })


@app.post("/api/v1/cases/{case_id}/self-improve")
async def self_improve(case_id: str) -> dict:
    """Improve simulation harness settings and rerun recovery once.

    This does not change uploaded evidence, user-provided values, or formulas.
    """
    case_data = await get_case(case_id)
    if not case_data:
        raise HTTPException(status_code=404, detail=f"Case {case_id} not found")

    case = CaseRecord(**case_data)
    result = await run_self_improvement_pipeline(case)
    await store_case(case_id, case.model_dump(mode="json"))
    return result


# ---------------------------------------------------------------------------
# Error handlers
# ---------------------------------------------------------------------------


@app.exception_handler(SafetyViolation)
async def safety_violation_handler(request: Any, exc: SafetyViolation) -> JSONResponse:
    return JSONResponse(
        status_code=422,
        content={
            "error": "safety_boundary_violation",
            "detail": str(exc),
            "safety_disclaimer": DISCLAIMER,
        },
    )
