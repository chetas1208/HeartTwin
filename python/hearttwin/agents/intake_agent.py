"""Agent 1: Intake & Safety Agent.

Accepts files/inputs, enforces safety boundaries, creates the case record.
Rejects diagnosis/treatment/triage requests.
"""

from __future__ import annotations

import time
import uuid
from typing import Any

from python.hearttwin.safety import DISCLAIMER, SafetyViolation, check_request_safety, redact_pii
from python.hearttwin.schemas import AgentResponse, AgentStatus, AgentTraceStep, CaseRecord, SafetyLevel
from python.hearttwin.tools.weave_trace import TraceContext


async def run_intake_agent(
    files: list[dict],
    patient_notes: str | None,
    user_request_text: str | None,
) -> tuple[AgentResponse, CaseRecord]:
    """Run intake and safety checks. Returns agent response and new case record."""
    tracer = TraceContext(case_id="pre-case", agent_name="intake_safety_agent")
    t0 = time.time()
    warnings: list[str] = []
    safety_level = SafetyLevel.CLEAR

    if user_request_text:
        redacted_request = redact_pii(user_request_text)
    else:
        redacted_request = ""

    if patient_notes:
        redacted_notes = redact_pii(patient_notes)
    else:
        redacted_notes = None

    try:
        if user_request_text:
            check_request_safety(user_request_text)
        if patient_notes:
            check_request_safety(patient_notes)
    except SafetyViolation as e:
        safety_level = SafetyLevel.BLOCKED
        response = AgentResponse(
            agent="intake_safety_agent",
            status=AgentStatus.FAILED,
            inputs_used=["user_request", "patient_notes"],
            outputs={
                "blocked": True,
                "reason": str(e),
                "safety_disclaimer": DISCLAIMER,
            },
            warnings=[str(e)],
            confidence=1.0,
            trace=tracer.steps,
        )
        case = CaseRecord(
            files=[],
            patient_notes=redacted_notes,
            status="blocked",
        )
        return response, case

    tracer.record_tool(
        "safety_check",
        inputs={"request_length": len(user_request_text or ""), "file_count": len(files)},
        outputs={"safety_level": "clear"},
        duration_ms=(time.time() - t0) * 1000,
    )

    accepted_files = []
    for f in files:
        ct = f.get("content_type", "")
        accepted_types = {
            "application/pdf", "image/jpeg", "image/png", "image/tiff",
            "text/csv", "application/octet-stream",
        }
        if ct in accepted_types or ct.startswith("image/") or ct.startswith("text/"):
            accepted_files.append(f)
        else:
            warnings.append(f"File '{f.get('filename', 'unknown')}' type '{ct}' not accepted — skipped")

    if len(files) > 10:
        warnings.append(f"Too many files ({len(files)}): only first 10 processed")
        accepted_files = accepted_files[:10]

    case_id = str(uuid.uuid4())

    case = CaseRecord(
        case_id=case_id,
        files=[],
        patient_notes=redacted_notes,
        status="intake_complete",
    )

    tracer.record_tool(
        "case_creation",
        inputs={"accepted_files": len(accepted_files)},
        outputs={"case_id": case_id},
        duration_ms=(time.time() - t0) * 1000,
    )

    confidence = 0.95 if accepted_files else 0.70

    response = AgentResponse(
        agent="intake_safety_agent",
        status=AgentStatus.SUCCESS if not warnings else AgentStatus.WARNING,
        inputs_used=["files", "patient_notes", "user_request"],
        outputs={
            "case_id": case_id,
            "accepted_file_count": len(accepted_files),
            "rejected_file_count": len(files) - len(accepted_files),
            "safety_level": safety_level.value,
            "safety_disclaimer": DISCLAIMER,
            "simulation_boundary_note": (
                "HeartTwin Lab provides educational cardiac simulation only. "
                "All outputs are clearly labeled as simulated estimates."
            ),
        },
        warnings=warnings,
        confidence=confidence,
        trace=tracer.steps,
    )

    return response, case
