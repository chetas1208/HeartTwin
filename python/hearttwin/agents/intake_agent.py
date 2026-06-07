"""Agent 1: Intake & Safety Agent.

Creates the safe case boundary before extraction, simulation, or recovery run.
The agent classifies intent, blocks unsafe medical requests, redacts obvious PII
from trace payloads, and returns a schema-bound safety decision.
"""

from __future__ import annotations

import json
import os
import re
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Literal

from pydantic import BaseModel, Field

from python.hearttwin.safety import CORE_SAFETY_PHRASE, DISCLAIMER
from python.hearttwin.schemas import AgentResponse, AgentStatus, AgentStageResult, CaseRecord, UploadedFile
from python.hearttwin.tools.model_config import get_intake_model
from python.hearttwin.tools.weave_trace import TraceContext, utc_now

_INTAKE_AGENT_ID = "intake_safety"
_INTAKE_AGENT_NAME = "Intake & Safety Agent"
_LEGACY_AGENT_NAME = "intake_safety_agent"
_INTAKE_TRACE_TOOL = "hearttwin.intake_safety"

_INTENT_CLASSES = {
    "educational_simulation",
    "physiology_explanation",
    "report_structuring",
    "operation_simulation",
    "recovery_simulation",
    "unsafe_diagnosis_request",
    "unsafe_treatment_request",
    "unsafe_emergency_triage",
    "unclear",
}

_ALL_ALLOWED_ACTIONS = [
    "educational simulation",
    "source extraction",
    "cardiac physiology explanation",
    "deterministic model operation",
    "bounded recovery scenario simulation",
    "report structuring",
    "file metadata processing",
]

_ACCEPTED_CONTENT_TYPES = {
    "application/pdf",
    "image/jpeg",
    "image/png",
    "image/tiff",
    "text/csv",
    "application/octet-stream",
}


class FileMetadata(BaseModel):
    file_id: str | None = None
    filename: str | None = None
    content_type: str | None = None
    size_bytes: int | None = None


class IntakeInput(BaseModel):
    case_id: str | None = None
    user_intent: str | None = None
    manual_vitals: dict[str, Any] | None = None
    files: list[FileMetadata] = Field(default_factory=list)
    previous_trace: list[dict[str, Any]] = Field(default_factory=list)


class IntakeOutput(BaseModel):
    allowed: bool
    intent_class: str
    safety_level: Literal["safe", "caution", "blocked"]
    blocked_reason: str | None
    required_disclaimer: str
    pii_redaction_applied: bool
    next_allowed_actions: list[str]
    warnings: list[str]


@dataclass(frozen=True)
class IntentDecision:
    intent_class: str
    safety_level: Literal["safe", "caution", "blocked"]
    blocked_reason: str | None
    safety_flags: list[str]
    confidence_hint: float


async def run_intake_agent(
    files: list[dict],
    patient_notes: str | None,
    user_request_text: str | None,
) -> tuple[AgentResponse, CaseRecord]:
    """Run intake and safety checks. Returns agent response and new case record."""
    started = _utc_now()
    t0 = time.time()
    tracer = TraceContext(case_id="pre-case", agent_name=_LEGACY_AGENT_NAME)
    tools_called: list[str] = []
    warnings: list[str] = []

    intake_input = IntakeInput(
        user_intent=user_request_text,
        files=[_file_metadata(file) for file in files],
    )
    combined_text = "\n".join(part for part in [user_request_text, patient_notes] if part)
    redacted_text, pii_redaction_applied, redaction_findings = _redact_pii_for_intake(combined_text)
    redacted_notes, notes_redacted, _ = _redact_pii_for_intake(patient_notes or "")
    pii_redaction_applied = pii_redaction_applied or notes_redacted
    if redaction_findings:
        warnings.append("Obvious PII was redacted before trace logging")

    rule_decision = _classify_intent_with_rules(combined_text)
    tools_called.extend(["pii_regex_redactor", "rule_based_intent_classifier"])

    model_used: str | None = None
    model_decision: IntentDecision | None = None
    if rule_decision.safety_level != "blocked" and os.environ.get("OPENAI_API_KEY"):
        model_name = get_intake_model()
        model_decision, model_warning = await _classify_intent_with_openai(redacted_text, model_name)
        tools_called.append("openai_intent_classifier")
        if model_warning:
            warnings.append(model_warning)
        elif model_decision:
            model_used = model_name

    decision = _merge_decisions(rule_decision, model_decision)
    accepted_files, file_warnings = _accepted_files(files)
    warnings.extend(file_warnings)

    if decision.intent_class == "unclear" and decision.safety_level != "blocked":
        warnings.append("Request intent is unclear; limited safe actions are available")

    next_actions = _next_allowed_actions(decision.intent_class, decision.safety_level)
    allowed = decision.safety_level != "blocked"
    confidence = _confidence_score(decision, model_decision, bool(redaction_findings), combined_text)
    intake_output = IntakeOutput(
        allowed=allowed,
        intent_class=decision.intent_class,
        safety_level=decision.safety_level,
        blocked_reason=decision.blocked_reason,
        required_disclaimer=CORE_SAFETY_PHRASE,
        pii_redaction_applied=pii_redaction_applied,
        next_allowed_actions=next_actions,
        warnings=warnings,
    )

    case_id = str(uuid.uuid4())
    case_status = "blocked" if not allowed else "intake_complete"
    case = CaseRecord(
        case_id=case_id,
        files=_uploaded_file_metadata(accepted_files),
        patient_notes=redacted_notes or None,
        status=case_status,
    )

    latency_ms = round((time.time() - t0) * 1000, 1)
    finished = _utc_now()
    stage_status = _stage_status(allowed, warnings)
    output_summary = _output_summary(intake_output, len(accepted_files), len(files))
    stage_result = AgentStageResult(
        agent_id=_INTAKE_AGENT_ID,
        agent_name=_INTAKE_AGENT_NAME,
        model_used=model_used,
        status=stage_status,
        started_at=started,
        finished_at=finished,
        latency_ms=latency_ms,
        inputs_used=_inputs_used(files, patient_notes, user_request_text),
        tools_called=tools_called,
        output_summary=output_summary,
        structured_output=intake_output.model_dump(mode="json"),
        warnings=warnings,
        confidence=confidence,
        source_refs=_source_refs(accepted_files),
        safety_flags=decision.safety_flags,
        weave_call_id=None,
        local_trace_id=tracer.trace_id,
    )

    tracer.record_tool(
        _INTAKE_TRACE_TOOL,
        inputs={
            "case_id": case_id,
            "redacted_intent_summary": _summarize(redacted_text),
            "file_count": len(files),
            "manual_vital_keys": sorted((intake_input.manual_vitals or {}).keys()),
        },
        outputs={
            "intent_class": decision.intent_class,
            "safety_level": decision.safety_level,
            "allowed": allowed,
            "safety_flags": decision.safety_flags,
            "warnings_count": len(warnings),
            "redaction_applied": pii_redaction_applied,
            "model_used": model_used,
            "latency_ms": latency_ms,
        },
        duration_ms=latency_ms,
    )

    response = AgentResponse(
        agent=_LEGACY_AGENT_NAME,
        status=AgentStatus(stage_status),
        inputs_used=stage_result.inputs_used,
        outputs={
            "case_id": case_id,
            "allowed": allowed,
            "intent_class": decision.intent_class,
            "accepted_file_count": len(accepted_files),
            "rejected_file_count": len(files) - len(accepted_files),
            "safety_level": decision.safety_level,
            "blocked_reason": decision.blocked_reason,
            "required_disclaimer": CORE_SAFETY_PHRASE,
            "safety_disclaimer": DISCLAIMER,
            "simulation_boundary_note": CORE_SAFETY_PHRASE,
            "next_allowed_actions": next_actions,
            "pii_redaction_applied": pii_redaction_applied,
            "structured_output": intake_output.model_dump(mode="json"),
            "agent_stage_result": stage_result.model_dump(mode="json"),
        },
        warnings=warnings,
        confidence=confidence,
        trace=tracer.steps,
    )

    return response, case


async def _classify_intent_with_openai(
    redacted_text: str,
    model_name: str,
) -> tuple[IntentDecision | None, str | None]:
    if not redacted_text.strip():
        return None, None

    try:
        import openai

        client = openai.AsyncOpenAI(api_key=os.environ["OPENAI_API_KEY"])
        response = await client.chat.completions.create(
            model=model_name,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "Classify a HeartTwin Lab request into exactly one allowed intent. "
                        "Do not answer the request. Return JSON with intent_class only. "
                        f"Allowed intents: {', '.join(sorted(_INTENT_CLASSES))}."
                    ),
                },
                {
                    "role": "user",
                    "content": f"Redacted request summary:\n{_summarize(redacted_text, max_chars=700)}",
                },
            ],
            temperature=0,
            max_tokens=80,
            response_format={"type": "json_object"},
        )
        raw = response.choices[0].message.content or "{}"
        parsed = json.loads(raw)
        intent = str(parsed.get("intent_class", "")).strip()
        if intent not in _INTENT_CLASSES:
            return None, f"OpenAI intake classifier returned unsupported intent '{intent}'"
        decision = _decision_for_intent(intent)
        return decision, None
    except Exception as exc:
        return None, f"OpenAI intake classifier unavailable; used rule fallback ({type(exc).__name__})"


def _classify_intent_with_rules(text: str) -> IntentDecision:
    normalized = _normalize(text)
    if not normalized:
        return IntentDecision("unclear", "caution", None, ["unclear_intent"], 0.45)

    if _contains_any(
        normalized,
        [
            r"\bam i having (a )?heart attack\b",
            r"\bheart attack\b",
            r"\bshould i go to (the )?e\.?r\.?\b",
            r"\bgo to (the )?emergency room\b",
            r"\bemergency\b",
            r"\btriage\b",
            r"\b911\b",
            r"\bambulance\b",
        ],
    ):
        return IntentDecision(
            "unsafe_emergency_triage",
            "blocked",
            _blocked_reason("emergency triage"),
            ["emergency_triage_blocked"],
            0.98,
        )

    if _contains_any(
        normalized,
        [
            r"\bwhat should i take\b",
            r"\bwhich medication should i use\b",
            r"\bmedic(ine|ation)\b",
            r"\bdrug\b",
            r"\bdosage\b",
            r"\bdose\b",
            r"\bdosing\b",
            r"\bprescrib(e|ed|ing|tion)\b",
            r"\btreatment plan\b",
            r"\btreat(ment)?\b",
        ],
    ):
        return IntentDecision(
            "unsafe_treatment_request",
            "blocked",
            _blocked_reason("medication or treatment guidance"),
            ["treatment_request_blocked"],
            0.96,
        )

    if _contains_any(
        normalized,
        [
            r"\bdiagnos(e|is|tic)\b",
            r"\bdo i have\b",
            r"\bwhat do i have\b",
            r"\bwhat disease\b",
            r"\bis this disease\b",
            r"\bis this (a )?(condition|illness)\b",
        ],
    ):
        return IntentDecision(
            "unsafe_diagnosis_request",
            "blocked",
            _blocked_reason("diagnostic interpretation"),
            ["diagnosis_request_blocked"],
            0.96,
        )

    if _contains_any(normalized, [r"\brecovery scenario\b", r"\brecovery simulation\b", r"\bbounded recovery\b"]):
        return IntentDecision("recovery_simulation", "safe", None, [], 0.88)

    if _contains_any(
        normalized,
        [
            r"\boperate\b",
            r"\boperation simulation\b",
            r"\bhemodynamic",
            r"\belectrophysiolog",
            r"\bpv loop\b",
            r"\bdeterministic model\b",
        ],
    ):
        return IntentDecision("operation_simulation", "safe", None, [], 0.86)

    if _contains_any(normalized, [r"\breport\b", r"\bstructure\b", r"\bsummarize\b", r"\bformat\b"]):
        return IntentDecision("report_structuring", "safe", None, [], 0.82)

    if _contains_any(
        normalized,
        [r"\bphysiology\b", r"\bexplain\b", r"\bhow does\b", r"\bwhy does\b", r"\bcardiac function\b"],
    ):
        return IntentDecision("physiology_explanation", "safe", None, [], 0.82)

    if _contains_any(
        normalized,
        [
            r"\bsimulat(e|ion)\b",
            r"\beducational\b",
            r"\bmodel\b",
            r"\bcardiac twin\b",
            r"\bvisualiz(e|ation)\b",
        ],
    ):
        return IntentDecision("educational_simulation", "safe", None, [], 0.84)

    if _contains_any(normalized, [r"\bsymptom", r"\bchest pain\b", r"\bdisease\b", r"\bcondition\b"]):
        return IntentDecision("unclear", "caution", None, ["medical_context_caution"], 0.58)

    return IntentDecision("unclear", "caution", None, ["unclear_intent"], 0.50)


def _merge_decisions(
    rule_decision: IntentDecision,
    model_decision: IntentDecision | None,
) -> IntentDecision:
    if rule_decision.safety_level == "blocked":
        return rule_decision
    if model_decision is None:
        return rule_decision
    if model_decision.safety_level == "blocked":
        return model_decision
    if rule_decision.safety_level == "caution":
        return IntentDecision(
            model_decision.intent_class if model_decision.intent_class != "unclear" else rule_decision.intent_class,
            "caution",
            None,
            sorted(set([*rule_decision.safety_flags, *model_decision.safety_flags])),
            max(rule_decision.confidence_hint, model_decision.confidence_hint),
        )
    return model_decision


def _decision_for_intent(intent: str) -> IntentDecision:
    if intent == "unsafe_emergency_triage":
        return IntentDecision(intent, "blocked", _blocked_reason("emergency triage"), ["emergency_triage_blocked"], 0.92)
    if intent == "unsafe_treatment_request":
        return IntentDecision(intent, "blocked", _blocked_reason("medication or treatment guidance"), ["treatment_request_blocked"], 0.90)
    if intent == "unsafe_diagnosis_request":
        return IntentDecision(intent, "blocked", _blocked_reason("diagnostic interpretation"), ["diagnosis_request_blocked"], 0.90)
    if intent == "unclear":
        return IntentDecision(intent, "caution", None, ["unclear_intent"], 0.55)
    return IntentDecision(intent, "safe", None, [], 0.82)


def _next_allowed_actions(
    intent_class: str,
    safety_level: Literal["safe", "caution", "blocked"],
) -> list[str]:
    if safety_level == "blocked":
        return []
    if intent_class == "physiology_explanation":
        return ["cardiac physiology explanation", "report structuring", "file metadata processing"]
    if intent_class == "report_structuring":
        return ["report structuring", "source extraction", "file metadata processing"]
    if intent_class == "operation_simulation":
        return ["source extraction", "deterministic model operation", "cardiac physiology explanation"]
    if intent_class == "recovery_simulation":
        return [
            "source extraction",
            "deterministic model operation",
            "bounded recovery scenario simulation",
            "cardiac physiology explanation",
        ]
    if intent_class == "unclear":
        return ["report structuring", "file metadata processing", "cardiac physiology explanation"]
    return _ALL_ALLOWED_ACTIONS.copy()


def _redact_pii_for_intake(text: str) -> tuple[str, bool, list[str]]:
    redacted = text or ""
    findings: list[str] = []
    patterns = [
        ("ssn", r"\b\d{3}-\d{2}-\d{4}\b", "[SSN-REDACTED]"),
        ("email", r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b", "[EMAIL-REDACTED]"),
        ("phone", r"\b(?:\+?1[-.\s]?)?(?:\(?\d{3}\)?[-.\s]?)\d{3}[-.\s]?\d{4}\b", "[PHONE-REDACTED]"),
        (
            "date_of_birth",
            r"\b(?:dob|date of birth)\s*[:#-]?\s*(?:\d{1,2}[/-]\d{1,2}[/-]\d{2,4}|[A-Za-z]{3,9}\s+\d{1,2},?\s+\d{4})\b",
            "[DOB-REDACTED]",
        ),
        (
            "street_address",
            r"\b\d{1,6}\s+[A-Za-z0-9.' -]{2,40}\s+(?:street|st|avenue|ave|road|rd|drive|dr|lane|ln|boulevard|blvd)\b",
            "[ADDRESS-REDACTED]",
        ),
        (
            "patient_name",
            r"\b(?:patient\s+name|name)\s*[:#-]\s*[A-Z][A-Za-z' -]{1,60}\b",
            "[PATIENT-NAME-REDACTED]",
        ),
    ]

    for label, pattern, replacement in patterns:
        redacted, count = re.subn(pattern, replacement, redacted, flags=re.IGNORECASE)
        if count:
            findings.append(label)
    return redacted, bool(findings), findings


def _accepted_files(files: list[dict]) -> tuple[list[dict], list[str]]:
    warnings: list[str] = []
    accepted: list[dict] = []

    for file in files:
        content_type = str(file.get("content_type") or "")
        filename = str(file.get("filename") or "unknown")
        if content_type in _ACCEPTED_CONTENT_TYPES or content_type.startswith(("image/", "text/")):
            accepted.append(file)
        else:
            warnings.append(f"File '{filename}' type '{content_type or 'unknown'}' not accepted; skipped")

    if len(accepted) > 10:
        warnings.append(f"Too many files ({len(accepted)} accepted): only first 10 processed")
        accepted = accepted[:10]

    return accepted, warnings


def _uploaded_file_metadata(files: list[dict]) -> list[UploadedFile]:
    uploaded: list[UploadedFile] = []
    for file in files:
        try:
            file_bytes = file.get("bytes") or b""
            uploaded.append(
                UploadedFile(
                    file_id=str(file.get("file_id") or uuid.uuid4()),
                    filename=str(file.get("filename") or "unknown"),
                    content_type=str(file.get("content_type") or "application/octet-stream"),
                    size_bytes=int(file.get("size_bytes") or len(file_bytes)),
                    storage_url=file.get("storage_url"),
                )
            )
        except Exception:
            continue
    return uploaded


def _file_metadata(file: dict) -> FileMetadata:
    file_bytes = file.get("bytes") or b""
    return FileMetadata(
        file_id=file.get("file_id"),
        filename=file.get("filename"),
        content_type=file.get("content_type"),
        size_bytes=file.get("size_bytes") or len(file_bytes),
    )


def _confidence_score(
    decision: IntentDecision,
    model_decision: IntentDecision | None,
    redaction_applied: bool,
    text: str,
) -> float:
    confidence = decision.confidence_hint
    if model_decision and model_decision.intent_class == decision.intent_class:
        confidence += 0.08
    if decision.safety_level == "blocked":
        confidence += 0.04
    if decision.intent_class == "unclear":
        confidence -= 0.08
    if redaction_applied:
        confidence -= 0.02
    if not text.strip():
        confidence -= 0.10
    return round(max(0.0, min(1.0, confidence)), 2)


def _stage_status(allowed: bool, warnings: list[str]) -> Literal["success", "warning", "failed"]:
    if not allowed:
        return "failed"
    if warnings:
        return "warning"
    return "success"


def _inputs_used(files: list[dict], patient_notes: str | None, user_request_text: str | None) -> list[str]:
    inputs: list[str] = []
    if files:
        inputs.append("files")
    if patient_notes:
        inputs.append("patient_notes")
    if user_request_text:
        inputs.append("user_request_text")
    return inputs or ["empty_intake"]


def _source_refs(files: list[dict]) -> list[dict[str, Any]]:
    refs: list[dict[str, Any]] = []
    for file in files:
        refs.append(
            {
                "file_id": file.get("file_id"),
                "filename": file.get("filename"),
                "content_type": file.get("content_type"),
            }
        )
    return refs


def _output_summary(output: IntakeOutput, accepted_count: int, total_count: int) -> str:
    if not output.allowed:
        return f"Blocked {output.intent_class}; no next actions allowed"
    return (
        f"Allowed {output.intent_class} with {output.safety_level} boundary; "
        f"{accepted_count}/{total_count} files accepted"
    )


def _blocked_reason(reason: str) -> str:
    return (
        f"HeartTwin Lab cannot provide {reason}. "
        "Use it only for educational cardiac simulation and report organization."
    )


def _contains_any(text: str, patterns: list[str]) -> bool:
    return any(re.search(pattern, text, flags=re.IGNORECASE) for pattern in patterns)


def _normalize(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").strip().lower())


def _summarize(text: str, max_chars: int = 180) -> str:
    compact = re.sub(r"\s+", " ", (text or "").strip())
    if len(compact) <= max_chars:
        return compact
    return f"{compact[: max_chars - 3]}..."


_utc_now = utc_now
