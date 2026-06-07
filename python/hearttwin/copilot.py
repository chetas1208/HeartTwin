"""CopilotKit (AG-UI) backend for HeartTwin Lab.

This module exposes the deterministic HeartTwin pipeline to a CopilotKit
frontend as a set of server-side actions, served at ``/copilotkit`` via
``copilotkit.integrations.fastapi.add_fastapi_endpoint``.

Design rules (production-grade, no silent fallbacks):

  * All numeric work lives in the deterministic Python pipeline
    (``orchestrator`` + ``tools``). The LLM never computes vitals, EF, CO, etc.
  * ``answer_case_question`` is the ONLY action that calls an LLM. It uses
    REAL OpenAI reasoning over the already-computed, stored case state, and
    its INPUT and OUTPUT are both safety-checked. A clinical / diagnostic /
    treatment answer is blocked by raising ``SafetyViolation`` — it is never
    returned to the caller.
  * OpenAI calls are autopatched by Weave (``weave.init`` in
    ``tools.weave_trace``), so every model call is traced.

The actions mirror the HTTP pipeline so the same deterministic outputs are
produced regardless of whether the frontend calls REST or the copilot.
"""

from __future__ import annotations

import json
import os
from typing import Any, Optional

from copilotkit import Action, CopilotKitRemoteEndpoint

from python.hearttwin.orchestrator import (
    run_extraction_pipeline,
    run_operation_pipeline,
    run_recovery_pipeline,
)
from python.hearttwin.safety import (
    DISCLAIMER,
    SafetyViolation,
    check_request_safety,
    validate_simulation_outputs,
)
from python.hearttwin.schemas import (
    CardiacTwinState,
    CaseRecord,
    OperatingEnvironment,
    RecoveryConfig,
)
from python.hearttwin.tools.storage import get_case, store_case
from python.hearttwin.tools.weave_trace import get_latest_run, get_trace_sink, weave_status

# Model used for case Q&A reasoning. Numeric facts are supplied by the
# deterministic pipeline; the model only explains the already-computed state.
_ANSWER_MODEL = os.environ.get("HEARTTWIN_COPILOT_MODEL", "gpt-4o")

# Phrases that, if emitted by the model, indicate it crossed the clinical
# boundary. Used as a defense-in-depth check on top of check_request_safety,
# which only matches whole-word clinical request patterns.
_OUTPUT_RED_FLAGS = (
    "you should see a doctor about",
    "you should take",
    "i recommend you take",
    "i recommend taking",
    "you need to take",
    "start taking",
    "stop taking",
    "your diagnosis is",
    "you have been diagnosed",
    "the recommended treatment",
    "recommended treatment is",
    "you should be treated",
    "prescribe",
    "milligrams",
)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


async def _load_case(case_id: str) -> CaseRecord:
    """Load a persisted case or raise a clear error."""
    case_data = await get_case(case_id)
    if not case_data:
        raise ValueError(f"Case {case_id} not found. Call create_case first.")
    return CaseRecord(**case_data)


def _run_weave(case_id: str) -> dict[str, Any]:
    latest = get_latest_run(case_id)
    run_id = latest.get("run_id") if latest else None
    return weave_status(run_id)


def _with_disclaimer(payload: dict[str, Any]) -> dict[str, Any]:
    payload["safety_disclaimer"] = DISCLAIMER
    return payload


# ---------------------------------------------------------------------------
# Action: create_case
# ---------------------------------------------------------------------------


async def create_case(patient_notes: Optional[str] = None) -> dict[str, Any]:
    """Create a new cardiac twin case and persist it.

    Returns a structured result with the new ``case_id``.
    """
    if patient_notes:
        # Input safety: reject requests that ask for diagnosis/treatment.
        check_request_safety(patient_notes)

    case = CaseRecord(patient_notes=patient_notes or None, status="created")
    await store_case(case.case_id, case.model_dump(mode="json"))

    return _with_disclaimer(
        {
            "ok": True,
            "case_id": case.case_id,
            "status": case.status,
            "created_at": case.created_at.isoformat(),
        }
    )


# ---------------------------------------------------------------------------
# Action: extract
# ---------------------------------------------------------------------------


async def extract(
    case_id: str,
    heart_rate_bpm: Optional[float] = None,
    systolic_bp_mmhg: Optional[float] = None,
    diastolic_bp_mmhg: Optional[float] = None,
    edv_ml: Optional[float] = None,
    esv_ml: Optional[float] = None,
) -> dict[str, Any]:
    """Run stages 1-3 (Intake, Extraction, Validation) on user-provided vitals.

    Stores validated evidence on the case. Numeric validation is performed by
    the deterministic pipeline — the copilot only forwards values verbatim.
    """
    case = await _load_case(case_id)

    user_vitals: dict[str, Any] = {}
    for key, value in (
        ("heart_rate_bpm", heart_rate_bpm),
        ("systolic_bp_mmhg", systolic_bp_mmhg),
        ("diastolic_bp_mmhg", diastolic_bp_mmhg),
        ("edv_ml", edv_ml),
        ("esv_ml", esv_ml),
    ):
        if value is not None:
            user_vitals[key] = float(value)

    if not user_vitals and not case.files:
        raise ValueError(
            "No evidence to extract. Provide at least one vital "
            "(e.g. heart_rate_bpm) or upload a file first."
        )

    if user_vitals:
        check_request_safety(str(user_vitals))

    _, case = await run_extraction_pipeline(
        case=case,
        files=[],
        user_vitals=user_vitals or None,
    )

    await store_case(case.case_id, case.model_dump(mode="json"))

    return _with_disclaimer(
        {
            "ok": case.status == "extracted",
            "case_id": case.case_id,
            "status": case.status,
            "validated_field_count": len(case.validated_fields),
            "validated_fields": sorted(case.validated_fields.keys()),
            "weave": _run_weave(case.case_id),
        }
    )


# ---------------------------------------------------------------------------
# Action: operate
# ---------------------------------------------------------------------------


async def operate(case_id: str, operating_mode: Optional[str] = None) -> dict[str, Any]:
    """Run stages 4, 5a/5b, 7 (State Builder, EP + Hemodynamics, Evaluator).

    Builds the cardiac twin state, simulates one cardiac cycle, and scores the
    run. Requires ``extract`` to have run first. All numbers come from the
    deterministic simulation.
    """
    case = await _load_case(case_id)

    if not case.validated_fields and case.status not in ("extracted", "operated"):
        raise ValueError("No validated evidence found — call extract first.")

    if operating_mode:
        valid_modes = {"rest", "mild_activity", "stress", "recovery"}
        if operating_mode not in valid_modes:
            raise ValueError(
                f"Invalid operating_mode '{operating_mode}'. "
                f"Choose one of: {', '.join(sorted(valid_modes))}."
            )
        if case.state is None:
            case.state = CardiacTwinState(case_id=case.case_id)
        case.state.simulation_config.operating = OperatingEnvironment(mode=operating_mode)  # type: ignore[arg-type]

    _, viz_payload, eval_report = await run_operation_pipeline(case=case)

    await store_case(case.case_id, case.model_dump(mode="json"))

    summary = viz_payload.get("summary", {}) if viz_payload else {}
    return _with_disclaimer(
        {
            "ok": case.status == "operated",
            "case_id": case.case_id,
            "status": case.status,
            "data_quality_score": case.state.data_quality_score if case.state else 0.0,
            "summary": {
                "ef_pct": summary.get("ef_pct"),
                "stroke_volume_ml": summary.get("stroke_volume_ml"),
                "cardiac_output_l_min": summary.get("cardiac_output_l_min"),
                "map_mmhg": summary.get("map_mmhg"),
                "heart_rate_bpm": summary.get("heart_rate_bpm"),
                "operating_mode": summary.get("operating_mode"),
            },
            "evaluation_passed": bool(eval_report.get("passed")),
            "overall_score": eval_report.get("eval_scores", {}).get("overall_score"),
            "weave": _run_weave(case.case_id),
        }
    )


# ---------------------------------------------------------------------------
# Action: simulate_recovery
# ---------------------------------------------------------------------------


async def simulate_recovery(
    case_id: str,
    recovery_horizon_days: Optional[int] = None,
) -> dict[str, Any]:
    """Run stages 6-7 (Recovery Orchestration, Evaluator).

    Generates bounded simulated recovery scenarios with uncertainty bands.
    Requires ``operate`` to have run first.
    """
    case = await _load_case(case_id)

    if not case.state:
        raise ValueError("No cardiac state — call operate first.")

    if recovery_horizon_days is not None:
        horizon = int(recovery_horizon_days)
        if horizon < 1 or horizon > 365:
            raise ValueError("recovery_horizon_days must be between 1 and 365.")
        case.state.simulation_config.recovery = RecoveryConfig(
            **{
                **case.state.simulation_config.recovery.model_dump(),
                "recovery_horizon_days": horizon,
            }
        )

    _, scenarios, eval_report = await run_recovery_pipeline(case=case)

    await store_case(case.case_id, case.model_dump(mode="json"))

    return _with_disclaimer(
        {
            "ok": bool(scenarios),
            "case_id": case.case_id,
            "status": case.status,
            "scenario_count": len(scenarios),
            "scenarios": [
                {
                    "scenario_label": sc.get("scenario_label"),
                    "summary_metrics": sc.get("summary_metrics"),
                    "warnings": sc.get("warnings", []),
                }
                for sc in scenarios
            ],
            "evaluation_passed": bool(eval_report.get("passed")),
            "weave": _run_weave(case.case_id),
            "simulation_note": (
                "All recovery trajectories are simulated educational estimates. "
                "Not for diagnosis or treatment decisions."
            ),
        }
    )


# ---------------------------------------------------------------------------
# Action: answer_case_question  (the only LLM-backed action)
# ---------------------------------------------------------------------------


_SYSTEM_PROMPT = (
    "You are HeartTwin Lab's read-only explainer for an EDUCATIONAL cardiac "
    "simulation. You are NOT a clinician and this is NOT a medical device.\n\n"
    "You will receive a JSON snapshot of an already-computed simulated cardiac "
    "state. Answer the user's question using ONLY the numbers present in that "
    "snapshot. Do not perform new calculations, do not invent values, and do "
    "not estimate anything that is null.\n\n"
    "ABSOLUTE RULES — never break these:\n"
    "  * Do NOT provide a diagnosis, prognosis, or any clinical interpretation.\n"
    "  * Do NOT recommend, suggest, or comment on treatment, medication, "
    "dosing, therapy, or triage.\n"
    "  * Do NOT tell the user what they 'have', 'need', or 'should do' "
    "medically.\n"
    "  * Always speak about the SIMULATION ('the simulated ejection fraction "
    "is ...'), never about a real patient's health.\n\n"
    "If the question asks for diagnosis, treatment, or any clinical advice, "
    "refuse and explain this is an educational simulation only. Keep answers "
    "concise (1-4 sentences) and grounded in the snapshot numbers."
)


def _build_state_snapshot(case: CaseRecord) -> dict[str, Any]:
    """Build a compact, numeric snapshot of the computed case for the LLM.

    Only already-computed deterministic outputs are included. No raw uploaded
    content, notes, or PII.
    """
    snapshot: dict[str, Any] = {
        "case_id": case.case_id,
        "status": case.status,
        "validated_fields": sorted(case.validated_fields.keys()),
    }

    sim = case.simulation_result or {}
    summary = sim.get("summary") if isinstance(sim, dict) else None
    if summary:
        snapshot["simulation_summary"] = {
            "ejection_fraction_pct": summary.get("ef_pct"),
            "stroke_volume_ml": summary.get("stroke_volume_ml"),
            "cardiac_output_l_min": summary.get("cardiac_output_l_min"),
            "map_mmhg": summary.get("map_mmhg"),
            "heart_rate_bpm": summary.get("heart_rate_bpm"),
            "edv_ml": summary.get("edv_ml"),
            "esv_ml": summary.get("esv_ml"),
            "operating_mode": summary.get("operating_mode"),
        }

    if isinstance(sim, dict) and sim.get("electrophysiology"):
        ep = sim["electrophysiology"]
        snapshot["electrophysiology"] = {
            "rhythm_label": ep.get("rhythm_label"),
            "rr_interval_ms": ep.get("rr_interval_ms"),
            "qrs_duration_ms": ep.get("qrs_duration_ms"),
            "qtc_ms": ep.get("qtc_ms"),
        }

    if isinstance(sim, dict) and sim.get("hemodynamics"):
        snapshot["hemodynamics_indices"] = sim["hemodynamics"]

    if case.recovery_scenarios:
        snapshot["recovery_scenarios"] = [
            {
                "scenario_label": sc.get("scenario_label"),
                "summary_metrics": sc.get("summary_metrics"),
            }
            for sc in case.recovery_scenarios
        ]

    return snapshot


def _check_output_safety(answer: str) -> None:
    """Raise SafetyViolation if the model output crosses the clinical boundary.

    This is a hard, non-bypassable gate applied to EVERY answer before it is
    returned. It layers two checks:
      1. The shared request-pattern matcher (diagnosis/treatment/medication/...).
      2. Output-specific red-flag phrases the request matcher would miss.
    """
    # Reuse the canonical blocked-pattern matcher on the model output.
    check_request_safety(answer)

    lowered = answer.lower()
    for phrase in _OUTPUT_RED_FLAGS:
        if phrase in lowered:
            raise SafetyViolation(
                "Model answer blocked: it contained clinical advice "
                "(diagnosis/treatment/medication), which HeartTwin Lab never "
                "provides. This is an educational simulation only.",
                pattern=phrase,
            )

    # validate_simulation_outputs flags raw clinical vocabulary leaking out.
    if validate_simulation_outputs({"answer": answer}):
        raise SafetyViolation(
            "Model answer blocked: it used clinical language that is not "
            "permitted in HeartTwin Lab's educational simulation context.",
            pattern="validate_simulation_outputs",
        )


async def answer_case_question(case_id: str, question: str) -> dict[str, Any]:
    """Answer a question about a case using REAL OpenAI reasoning.

    The model reasons over the already-computed deterministic state snapshot.
    Both the incoming question and the model's answer are safety-checked; any
    diagnosis/treatment/clinical content is blocked via ``SafetyViolation``
    and never returned.
    """
    if not question or not question.strip():
        raise ValueError("question must not be empty.")

    # Input safety gate.
    check_request_safety(question)

    case = await _load_case(case_id)
    snapshot = _build_state_snapshot(case)

    if "simulation_summary" not in snapshot:
        raise ValueError(
            "No simulation results to reason over — call operate first so the "
            "cardiac state is computed."
        )

    api_key = os.environ.get("OPENAI_API_KEY", "")
    if not api_key:
        # No silent fallback: surface the misconfiguration explicitly.
        raise RuntimeError(
            "OPENAI_API_KEY is not configured — answer_case_question requires "
            "live OpenAI access and does not fabricate answers."
        )

    import openai

    client = openai.AsyncOpenAI(api_key=api_key)

    trace_sink = get_trace_sink()
    run_id = trace_sink.start_run(
        case.case_id,
        "copilot_answer",
        {"question_len": len(question)},
    )

    user_content = (
        "Simulated cardiac state snapshot (JSON):\n"
        f"{json.dumps(snapshot, default=str)}\n\n"
        f"Question: {question.strip()}"
    )

    try:
        response = await client.chat.completions.create(
            model=_ANSWER_MODEL,
            messages=[
                {"role": "system", "content": _SYSTEM_PROMPT},
                {"role": "user", "content": user_content},
            ],
            temperature=0.2,
            max_tokens=400,
        )
    except Exception as exc:
        trace_sink.finish_run(run_id, "failed", {"error": type(exc).__name__})
        raise RuntimeError(f"OpenAI call failed: {type(exc).__name__}: {exc}") from exc

    answer = (response.choices[0].message.content or "").strip()
    if not answer:
        trace_sink.finish_run(run_id, "failed", {"error": "empty_answer"})
        raise RuntimeError("OpenAI returned an empty answer.")

    # Output safety gate — non-bypassable. Raises SafetyViolation on failure.
    _check_output_safety(answer)

    trace_sink.log_tool_call(
        run_id,
        "openai_chat_completion",
        inputs={"model": _ANSWER_MODEL, "question": question.strip()},
        outputs={"answer_len": len(answer)},
    )
    trace_sink.finish_run(run_id, "success", {"answer_len": len(answer)})

    return _with_disclaimer(
        {
            "ok": True,
            "case_id": case.case_id,
            "question": question.strip(),
            "answer": answer,
            "model": _ANSWER_MODEL,
            "grounded_on": sorted(snapshot.keys()),
            "weave": _run_weave(case.case_id),
        }
    )


# ---------------------------------------------------------------------------
# Action wiring
# ---------------------------------------------------------------------------


def build_actions() -> list[Action]:
    """Build the CopilotKit action list for the HeartTwin pipeline."""
    return [
        Action(
            name="create_case",
            handler=create_case,
            description=(
                "Create a new HeartTwin cardiac simulation case. Returns a "
                "case_id used by all subsequent actions."
            ),
            parameters=[
                {
                    "name": "patient_notes",
                    "type": "string",
                    "description": "Optional free-text context for the case (no PII).",
                    "required": False,
                }
            ],
        ),
        Action(
            name="extract",
            handler=extract,
            description=(
                "Stage 1-3: validate user-provided cardiac vitals onto a case. "
                "Call before operate."
            ),
            parameters=[
                {"name": "case_id", "type": "string", "description": "The case to extract into."},
                {
                    "name": "heart_rate_bpm",
                    "type": "number",
                    "description": "Heart rate in beats per minute.",
                    "required": False,
                },
                {
                    "name": "systolic_bp_mmhg",
                    "type": "number",
                    "description": "Systolic blood pressure in mmHg.",
                    "required": False,
                },
                {
                    "name": "diastolic_bp_mmhg",
                    "type": "number",
                    "description": "Diastolic blood pressure in mmHg.",
                    "required": False,
                },
                {
                    "name": "edv_ml",
                    "type": "number",
                    "description": "End-diastolic volume in mL.",
                    "required": False,
                },
                {
                    "name": "esv_ml",
                    "type": "number",
                    "description": "End-systolic volume in mL.",
                    "required": False,
                },
            ],
        ),
        Action(
            name="operate",
            handler=operate,
            description=(
                "Stage 4-5-7: build the cardiac twin state and run one "
                "deterministic cardiac-cycle simulation. Returns simulated EF, "
                "stroke volume, cardiac output, and MAP. Call after extract."
            ),
            parameters=[
                {"name": "case_id", "type": "string", "description": "The case to operate on."},
                {
                    "name": "operating_mode",
                    "type": "string",
                    "description": "Operating mode for the simulation.",
                    "enum": ["rest", "mild_activity", "stress", "recovery"],
                    "required": False,
                },
            ],
        ),
        Action(
            name="simulate_recovery",
            handler=simulate_recovery,
            description=(
                "Stage 6-7: generate bounded simulated recovery scenarios with "
                "uncertainty bands. Call after operate."
            ),
            parameters=[
                {"name": "case_id", "type": "string", "description": "The case to simulate recovery for."},
                {
                    "name": "recovery_horizon_days",
                    "type": "number",
                    "description": "Recovery horizon in days (1-365).",
                    "required": False,
                },
            ],
        ),
        Action(
            name="answer_case_question",
            handler=answer_case_question,
            description=(
                "Answer a question about a case's SIMULATED results using the "
                "computed cardiac state. Educational explanation only — never "
                "provides diagnosis, treatment, or clinical advice."
            ),
            parameters=[
                {"name": "case_id", "type": "string", "description": "The case to ask about."},
                {
                    "name": "question",
                    "type": "string",
                    "description": "A question about the simulated cardiac results.",
                },
            ],
        ),
    ]


def build_sdk() -> CopilotKitRemoteEndpoint:
    """Build the CopilotKit remote endpoint (AG-UI) for HeartTwin Lab."""
    return CopilotKitRemoteEndpoint(actions=build_actions())
