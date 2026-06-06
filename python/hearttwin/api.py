"""FastAPI application for HeartTwin Lab.

All routes are under /api/v1.
Python functions are the source of truth for numeric outputs.

Pipeline per spec:
  POST /extract          → stages 1 (Intake) + 2 (Extraction) + 3 (Validator)
  POST /operate          → stages 4 (State Builder) + 5a/5b (EP + Hemodynamics) + 7 (Evaluator)
  POST /simulate-recovery → stages 6 (Recovery) + 7 (Evaluator)
"""

from __future__ import annotations

from typing import Any

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from python.hearttwin.orchestrator import (
    run_extraction_pipeline,
    run_operation_pipeline,
    run_recovery_pipeline,
    run_self_improvement_pipeline,
)
from python.hearttwin.safety import DISCLAIMER, SafetyViolation, add_disclaimer, check_request_safety
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
from python.hearttwin.tools.weave_trace import get_latest_run, get_traces, weave_status

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
# Health
# ---------------------------------------------------------------------------


@app.get("/api/v1/health", response_model=HealthResponse)
async def health() -> HealthResponse:
    return HealthResponse()


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


@app.get("/api/v1/system-check")
async def system_check() -> dict:
    """End-to-end deterministic health check using golden case vitals.

    Creates an ephemeral (not persisted) case, runs the full pipeline with
    known inputs, and validates outputs against expected values. Safe to
    call at any time — no storage side effects.
    """
    from python.hearttwin.tools.cardiac_state import (
        compute_cardiac_output,
        compute_ejection_fraction,
        compute_map,
        compute_stroke_volume,
    )

    results: dict[str, dict] = {}

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

        formula_ok = (
            abs(sv - _GOLDEN_EXPECTED["sv_ml"]) < 0.1
            and abs(ef - _GOLDEN_EXPECTED["ef_pct"]) < 0.1
            and abs(co - _GOLDEN_EXPECTED["co_l_min"]) < 0.05
            and abs(map_val - _GOLDEN_EXPECTED["map_mmhg"]) < 0.1
        )
        results["formulas"] = {
            "status": "ok" if formula_ok else "failed",
            "sv_ml": round(sv, 2),
            "ef_pct": round(ef, 2),
            "co_l_min": round(co, 2),
            "map_mmhg": round(map_val, 2),
            "expected_sv_ml": _GOLDEN_EXPECTED["sv_ml"],
            "expected_ef_pct": _GOLDEN_EXPECTED["ef_pct"],
            "expected_co_l_min": _GOLDEN_EXPECTED["co_l_min"],
            "expected_map_mmhg": _GOLDEN_EXPECTED["map_mmhg"],
        }
    except Exception as exc:
        results["formulas"] = {"status": "failed", "error": str(exc)}

    # --- 2. Full pipeline (ephemeral, not persisted) ---
    try:
        case = CaseRecord(status="created")
        _, case = await run_extraction_pipeline(
            case=case,
            files=[],
            user_vitals=_GOLDEN_VITALS,
        )
        results["extraction"] = {
            "status": "ok" if case.validated_fields else "failed",
            "validated_field_count": len(case.validated_fields),
        }
    except Exception as exc:
        results["extraction"] = {"status": "failed", "error": str(exc)}

    try:
        _, viz_payload, eval_report = await run_operation_pipeline(case=case)
        sim_ok = bool(viz_payload and "summary" in viz_payload)
        sim_ef = viz_payload["summary"].get("ef_pct") if sim_ok else None
        sim_co = viz_payload["summary"].get("cardiac_output_l_min") if sim_ok else None
        results["simulation"] = {
            "status": "ok" if sim_ok else "failed",
            "ef_pct": round(sim_ef, 2) if sim_ef else None,
            "co_l_min": round(sim_co, 3) if sim_co else None,
            "has_pv_loop": bool(viz_payload.get("pv_loop")) if sim_ok else False,
            "has_cardiac_cycle": bool(viz_payload.get("cardiac_cycle")) if sim_ok else False,
        }
    except Exception as exc:
        results["simulation"] = {"status": "failed", "error": str(exc)}

    try:
        _, scenarios, _ = await run_recovery_pipeline(case=case)
        results["recovery"] = {
            "status": "ok" if scenarios else "failed",
            "scenario_count": len(scenarios),
        }
    except Exception as exc:
        results["recovery"] = {"status": "failed", "error": str(exc)}

    # --- 3. Safety layer ---
    try:
        from python.hearttwin.safety import check_request_safety
        blocked = False
        try:
            check_request_safety("what diagnosis do I have and what treatment should I take?")
            blocked = False
        except Exception:
            blocked = True
        results["safety"] = {"status": "ok" if blocked else "failed", "blocks_diagnosis_requests": blocked}
    except Exception as exc:
        results["safety"] = {"status": "failed", "error": str(exc)}

    overall = "ok" if all(v.get("status") == "ok" for v in results.values()) else "degraded"
    failed = [k for k, v in results.items() if v.get("status") != "ok"]

    return {
        "status": overall,
        "checks": results,
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
            "All recovery trajectories are simulated educational estimates. "
            "Not for diagnosis or treatment decisions."
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
