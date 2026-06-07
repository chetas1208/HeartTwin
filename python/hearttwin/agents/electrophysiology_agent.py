"""Agent 5: Electrophysiology Agent.

Builds the electrical operation state of the cardiac twin from ECG waveform
data, reported ECG labels, and validated report fields.

Boundaries:
- ECG feature extraction (R-peak detection, RR/QTc derivation) is deterministic
  and tool-based — never inferred by a language model.
- Reported rhythm labels are stored as *reported* descriptors only. They are
  never re-stated as a diagnosis or clinical conclusion.
- OpenAI is used only for structured explanation and reported-label wording
  normalization, never for numeric ECG feature estimation.
"""

from __future__ import annotations

import json
import os
import re
import time
from datetime import datetime, timezone
from typing import Any, Literal

from pydantic import BaseModel, Field

from python.hearttwin.safety import CORE_SAFETY_PHRASE
from python.hearttwin.schemas import (
    AgentResponse,
    AgentStatus,
    AgentStageResult,
    CardiacTwinState,
    Electrophysiology,
    MeasuredValue,
    ValueSource,
)
from python.hearttwin.tools.ecg_features import EcgFeatures, analyze_waveform
from python.hearttwin.tools.model_config import chat_tuning, get_electrophysiology_model
from python.hearttwin.tools.weave_trace import TraceContext, utc_now

_EP_AGENT_ID = "electrophysiology"
_EP_AGENT_NAME = "Electrophysiology Agent"
_LEGACY_AGENT_NAME = "electrophysiology_agent"
_EP_TRACE_TOOL = "hearttwin.simulate_electrophysiology"
_RPEAK_TRACE_TOOL = "hearttwin.detect_r_peaks"
_DEFAULT_SAMPLING_RATE_HZ = 500.0
_CHART_PREVIEW_MAX_POINTS = 300
_TRACE_PREVIEW_MAX_POINTS = 12

_REPORTED_LABEL_DISPLAY = "reported rhythm label"
_REPORTED_STATEMENT_DISPLAY = "reported ECG statement"
_VISUAL_DISPLAY_LABEL = "simulated electrical visualization"
_CHART_DISPLAY_LABEL = "simulated ECG chart"

_PREFERRED_LEAD_KEYS = ("lead_ii", "lead 2", "lead_2", "ii", "2")

_DIAGNOSTIC_PATTERN = re.compile(
    r"\b(diagnos\w*|(?:the\s+)?patient\s+(?:has|is\s+suffering\s+from)|confirmed\s+arrhythmia|clinical(?:ly)?\s+diagnosis)\b",
    re.IGNORECASE,
)


# ---------------------------------------------------------------------------
# Schema-bound input / output contracts
# ---------------------------------------------------------------------------


class FileMetadata(BaseModel):
    file_id: str | None = None
    filename: str | None = None
    content_type: str | None = None
    size_bytes: int | None = None


class ValidatedField(BaseModel):
    value: Any = None
    unit: str | None = None
    source: str | None = None
    confidence: float | None = None
    source_file_id: str | None = None
    method: str | None = None
    evidence: str | None = None
    flagged: bool | None = None
    flag_reason: str | None = None


class ElectrophysiologyInput(BaseModel):
    case_id: str
    cardiac_state: CardiacTwinState
    files: list[FileMetadata] = Field(default_factory=list)
    validated_fields: dict[str, ValidatedField] = Field(default_factory=dict)


class ElectrophysiologyOutput(BaseModel):
    rhythm_label: str | None
    rhythm_source: Literal["reported", "waveform_estimated", "simulated_visualization", "unknown"]
    rr_interval_ms: float | None
    qrs_duration_ms: float | None
    qt_interval_ms: float | None
    qtc_ms: float | None
    r_peak_count: int | None
    r_peak_confidence: float | None
    ecg_chart_payload: dict | None
    electrical_visual_payload: dict
    warnings: list[str]
    confidence: float


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------


async def run_electrophysiology_agent(
    state: CardiacTwinState,
    validated_fields: dict[str, Any],
    case_id: str,
) -> tuple[AgentResponse, Electrophysiology]:
    """Build electrophysiology state from ECG waveform and reported fields.

    Returns the legacy (AgentResponse, Electrophysiology) contract expected by
    the orchestrator, with a schema-bound ElectrophysiologyOutput and
    AgentStageResult embedded in the response outputs for traceability.
    """
    started = _utc_now()
    t0 = time.time()
    tracer = TraceContext(case_id=case_id, agent_name=_LEGACY_AGENT_NAME)
    tools_called: list[str] = []
    warnings: list[str] = []
    safety_flags: list[str] = []

    ep = state.electrophysiology
    validated_fields = validated_fields or {}

    ep_input = _build_input(state=state, validated_fields=validated_fields, case_id=case_id)

    waveform_entry = validated_fields.get("__ecg_waveform__")
    waveform_value = waveform_entry.get("value") if isinstance(waveform_entry, dict) else None
    waveform_present = isinstance(waveform_value, (list, dict)) and bool(waveform_value)

    reported_entry = validated_fields.get("rhythm_label")
    reported_raw, reported_confidence = _reported_label_value(reported_entry)

    rhythm_source: Literal["reported", "waveform_estimated", "simulated_visualization", "unknown"] = "unknown"
    rhythm_label: str | None = None
    chart_payload: dict | None = None
    r_peak_count: int | None = None
    r_peak_confidence: float | None = None
    reported_statement: str | None = None

    sampling_rate_hz = _sampling_rate(waveform_entry)

    # ------------------------------------------------------------------
    # 1) Deterministic waveform analysis (R-peak tool orchestration)
    # ------------------------------------------------------------------
    features: EcgFeatures | None = None
    lead_used: str | None = None
    if waveform_present:
        signal, lead_used, lead_warning = _select_lead(waveform_value)
        if lead_warning:
            warnings.append(lead_warning)

        if signal is None:
            warnings.append("ECG waveform detected but no valid numeric lead could be identified")
        else:
            tool_t0 = time.time()
            qrs_mv = ep.qrs_duration_ms.value if ep.qrs_duration_ms else None
            qt_mv = ep.qt_interval_ms.value if ep.qt_interval_ms else None
            features = analyze_waveform(
                signal=signal,
                sampling_rate_hz=sampling_rate_hz,
                qrs_duration_ms=qrs_mv,
                qt_ms=qt_mv,
            )
            tools_called.append("analyze_waveform")
            r_peak_count = features.r_peak_count
            r_peak_confidence = features.r_peak_confidence

            tracer.record_tool(
                _RPEAK_TRACE_TOOL,
                inputs={
                    "signal_length": len(signal),
                    "sampling_rate_hz": sampling_rate_hz,
                    "lead_used": lead_used,
                    "signal_preview_mv": _downsample(signal, _TRACE_PREVIEW_MAX_POINTS),
                },
                outputs={
                    "r_peak_count": features.r_peak_count,
                    "r_peak_confidence": features.r_peak_confidence,
                    "mean_rr_ms": features.mean_rr_ms,
                    "rhythm_descriptor": features.rhythm_descriptor,
                },
                duration_ms=(time.time() - tool_t0) * 1000,
            )

            if features.r_peak_count >= 2:
                rhythm_source = "waveform_estimated"
                rhythm_label = features.rhythm_descriptor

                ep.rr_interval_ms = MeasuredValue(
                    value=features.mean_rr_ms,
                    unit="ms",
                    source=ValueSource.DERIVED,
                    confidence=features.r_peak_confidence,
                    method="waveform_r_peak_detection",
                )
                ep.arrhythmia_instability_score = MeasuredValue(
                    value=features.arrhythmia_instability_score,
                    unit="index",
                    source=ValueSource.DERIVED,
                    confidence=features.r_peak_confidence,
                    method="waveform_rmssd",
                )
                ep.conduction_delay_score = MeasuredValue(
                    value=features.conduction_delay_score,
                    unit="index",
                    source=ValueSource.DERIVED,
                    confidence=0.7,
                    method="qrs_duration_threshold",
                )
                ep.r_peak_confidence = features.r_peak_confidence

                if features.qtc_ms and ep.qtc_ms is None:
                    ep.qtc_ms = MeasuredValue(
                        value=features.qtc_ms,
                        unit="ms",
                        source=ValueSource.DERIVED,
                        confidence=round(features.r_peak_confidence * 0.9, 3),
                        method="bazett_formula",
                    )

                ep.rhythm_label = rhythm_label
                chart_payload = _build_chart_payload(
                    signal=signal,
                    sampling_rate_hz=sampling_rate_hz,
                    lead_used=lead_used or "unknown",
                    features=features,
                    source=rhythm_source,
                )
            else:
                warnings.extend(features.warnings)
                warnings.append(
                    "Waveform detected but insufficient R peaks — falling back to reported or report-derived values"
                )
                ep.r_peak_confidence = features.r_peak_confidence
    else:
        tools_called.append("ecg_report_fallback")
        tracer.record_tool(
            "ecg_report_fallback",
            inputs={"has_waveform": False},
            outputs={"method": "reported_or_prior_values"},
            duration_ms=1.0,
        )

    # ------------------------------------------------------------------
    # 2) Reported rhythm label handling (non-diagnostic, normalization via OpenAI)
    # ------------------------------------------------------------------
    model_used: str | None = None
    if reported_raw:
        sanitized, sanitize_changed = _strip_diagnostic_language(reported_raw)
        if sanitize_changed:
            warnings.append("Reported rhythm wording sanitized to remove diagnostic language")
            safety_flags.append("reported_label_sanitized")

        normalized = sanitized
        if os.environ.get("OPENAI_API_KEY"):
            model_name = get_electrophysiology_model()
            normalized_candidate, norm_warning = await _normalize_reported_label_with_openai(sanitized, model_name)
            tools_called.append("openai_reported_label_normalizer")
            if norm_warning:
                warnings.append(norm_warning)
            if normalized_candidate:
                normalized = normalized_candidate
                model_used = model_name
        else:
            warnings.append("OpenAI API key missing — reported rhythm label normalized with rules only")

        reported_statement = f"{_REPORTED_STATEMENT_DISPLAY}: {normalized}"

        if rhythm_source == "unknown":
            rhythm_source = "reported"
            rhythm_label = f"{_REPORTED_LABEL_DISPLAY}: {normalized}"
            ep.rhythm_label = rhythm_label

    # ------------------------------------------------------------------
    # 3) Simulated-visualization fallback derived from report-extracted RR/HR
    # ------------------------------------------------------------------
    if rhythm_source == "unknown":
        derived_label = _simulated_label_from_rr(ep.rr_interval_ms)
        if derived_label:
            rhythm_source = "simulated_visualization"
            rhythm_label = derived_label
            ep.rhythm_label = rhythm_label
            warnings.append("No waveform or reported label available — rhythm label derived from report-extracted RR interval")
        else:
            ep.rhythm_label = None
            warnings.append("No ECG waveform, reported label, or RR interval available — rhythm source unknown")

    if ep.arrhythmia_instability_score is None:
        ep.arrhythmia_instability_score = MeasuredValue(
            value=0.1,
            unit="index",
            source=ValueSource.DEFAULT_MODEL_PRIOR,
            confidence=0.3,
            method="prior_no_waveform",
        )
    if ep.r_peak_confidence is None:
        ep.r_peak_confidence = 0.0
    if ep.conduction_delay_score is None and ep.qrs_duration_ms is not None:
        qrs_val = ep.qrs_duration_ms.value
        if qrs_val > 120:
            delay = min(1.0, (qrs_val - 120) / 80.0)
            ep.conduction_delay_score = MeasuredValue(
                value=round(delay, 4),
                unit="index",
                source=ValueSource.DERIVED,
                confidence=0.6,
                method="qrs_threshold_rule",
            )

    # ------------------------------------------------------------------
    # 4) Electrical visualization payload (always produced)
    # ------------------------------------------------------------------
    confidence = _score_confidence(
        rhythm_source=rhythm_source,
        r_peak_confidence=r_peak_confidence,
        reported_confidence=reported_confidence,
        warning_count=len(warnings),
    )
    visual_payload = _build_visual_payload(
        rhythm_source=rhythm_source,
        rr_interval_ms=ep.rr_interval_ms.value if ep.rr_interval_ms else None,
        conduction_delay_score=ep.conduction_delay_score.value if ep.conduction_delay_score else None,
        arrhythmia_instability_score=ep.arrhythmia_instability_score.value if ep.arrhythmia_instability_score else None,
        confidence=confidence,
    )

    ep_output = ElectrophysiologyOutput(
        rhythm_label=ep.rhythm_label,
        rhythm_source=rhythm_source,
        rr_interval_ms=ep.rr_interval_ms.value if ep.rr_interval_ms else None,
        qrs_duration_ms=ep.qrs_duration_ms.value if ep.qrs_duration_ms else None,
        qt_interval_ms=ep.qt_interval_ms.value if ep.qt_interval_ms else None,
        qtc_ms=ep.qtc_ms.value if ep.qtc_ms else None,
        r_peak_count=r_peak_count,
        r_peak_confidence=r_peak_confidence,
        ecg_chart_payload=chart_payload,
        electrical_visual_payload=visual_payload,
        warnings=warnings,
        confidence=confidence,
    )

    no_diagnostic_violation = _assert_no_diagnostic_language(ep_output)
    if no_diagnostic_violation:
        warnings.append(no_diagnostic_violation)
        safety_flags.append("non_diagnostic_language_enforced")

    finished = _utc_now()
    latency_ms = round((time.time() - t0) * 1000, 1)
    stage_status = _stage_status(warnings)
    output_summary = _output_summary(ep_output, waveform_present)

    stage_result = AgentStageResult(
        agent_id=_EP_AGENT_ID,
        agent_name=_EP_AGENT_NAME,
        model_used=model_used,
        status=stage_status,
        started_at=started,
        finished_at=finished,
        latency_ms=latency_ms,
        inputs_used=_inputs_used(waveform_present, reported_raw, ep_input),
        tools_called=tools_called,
        output_summary=output_summary,
        structured_output=ep_output.model_dump(mode="json"),
        warnings=warnings,
        confidence=confidence,
        source_refs=_source_refs(ep_input, waveform_entry),
        safety_flags=safety_flags,
        weave_call_id=None,
        local_trace_id=tracer.trace_id,
    )

    tracer.record_tool(
        _EP_TRACE_TOOL,
        inputs={
            "case_id": case_id,
            "waveform_present": waveform_present,
            "reported_rhythm_present": bool(reported_raw),
            "validated_field_count": len(ep_input.validated_fields),
        },
        outputs={
            "rhythm_source": rhythm_source,
            "r_peak_count": r_peak_count,
            "r_peak_confidence": r_peak_confidence,
            "chart_payload_ready": chart_payload is not None,
            "electrical_visual_payload_ready": True,
            "warnings": warnings,
            "confidence": confidence,
        },
        duration_ms=latency_ms,
    )

    await _store_electrophysiology_memory(
        case_id=case_id,
        ep_output=ep_output,
        lead_used=lead_used,
        sampling_rate_hz=sampling_rate_hz if waveform_present else None,
        reported_statement=reported_statement,
        finished_at=finished,
    )

    response = AgentResponse(
        agent=_LEGACY_AGENT_NAME,
        status=AgentStatus(stage_status if stage_status != "skipped" else "warning"),
        inputs_used=stage_result.inputs_used,
        outputs={
            "rhythm_label": ep_output.rhythm_label,
            "rhythm_source": ep_output.rhythm_source,
            "rr_interval_ms": ep_output.rr_interval_ms,
            "qrs_duration_ms": ep_output.qrs_duration_ms,
            "qt_interval_ms": ep_output.qt_interval_ms,
            "qtc_ms": ep_output.qtc_ms,
            "r_peak_count": ep_output.r_peak_count,
            "r_peak_confidence": ep_output.r_peak_confidence,
            "reported_ecg_statement": reported_statement,
            "ecg_chart_payload": ep_output.ecg_chart_payload,
            "electrical_visual_payload": ep_output.electrical_visual_payload,
            "structured_output": ep_output.model_dump(mode="json"),
            "agent_stage_result": stage_result.model_dump(mode="json"),
            "simulation_note": f"{CORE_SAFETY_PHRASE} Rhythm labels are non-diagnostic simulation descriptors.",
        },
        warnings=warnings,
        confidence=confidence,
        trace=tracer.steps,
    )

    return response, ep


# ---------------------------------------------------------------------------
# Input construction
# ---------------------------------------------------------------------------


def _build_input(
    state: CardiacTwinState,
    validated_fields: dict[str, Any],
    case_id: str,
) -> ElectrophysiologyInput:
    field_models: dict[str, ValidatedField] = {}
    file_ids_seen: set[str] = set()
    files: list[FileMetadata] = []

    for key, entry in validated_fields.items():
        if key.startswith("__"):
            continue
        if not isinstance(entry, dict):
            continue
        try:
            field_models[key] = ValidatedField(
                value=entry.get("value"),
                unit=entry.get("unit"),
                source=entry.get("source"),
                confidence=_safe_float(entry.get("confidence")),
                source_file_id=entry.get("source_file_id"),
                method=entry.get("method"),
                evidence=entry.get("evidence"),
                flagged=entry.get("flagged"),
                flag_reason=entry.get("flag_reason"),
            )
        except Exception:
            continue

        file_id = entry.get("source_file_id")
        if file_id and file_id not in file_ids_seen:
            file_ids_seen.add(file_id)
            files.append(FileMetadata(file_id=file_id, content_type="text/csv" if key == "__ecg_waveform__" else None))

    waveform_entry = validated_fields.get("__ecg_waveform__")
    if isinstance(waveform_entry, dict):
        file_id = waveform_entry.get("source_file_id")
        if file_id and file_id not in file_ids_seen:
            file_ids_seen.add(file_id)
            files.append(FileMetadata(file_id=file_id, content_type="text/csv"))

    return ElectrophysiologyInput(
        case_id=case_id,
        cardiac_state=state,
        files=files,
        validated_fields=field_models,
    )


def _safe_float(value: Any) -> float | None:
    try:
        if value is None:
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


# ---------------------------------------------------------------------------
# Waveform / lead handling
# ---------------------------------------------------------------------------


def _sampling_rate(waveform_entry: dict | None) -> float:
    if isinstance(waveform_entry, dict):
        rate = _safe_float(waveform_entry.get("sampling_rate_hz"))
        if rate and rate > 0:
            return rate
    return _DEFAULT_SAMPLING_RATE_HZ


def _is_numeric_series(series: Any) -> bool:
    return (
        isinstance(series, list)
        and len(series) > 0
        and all(isinstance(x, (int, float)) and not isinstance(x, bool) for x in series)
    )


def _select_lead(raw_value: Any) -> tuple[list[float] | None, str | None, str | None]:
    """Choose a single ECG lead from waveform data that may carry multiple leads.

    Returns (signal, lead_label, warning). Prefers lead II by project convention;
    falls back to the first valid numeric lead with a warning when uncertain.
    """
    if isinstance(raw_value, dict):
        keys = list(raw_value.keys())
        normalized_keys = {k: re.sub(r"[\s_]+", "_", k.strip().lower()) for k in keys}

        for preferred in _PREFERRED_LEAD_KEYS:
            for original, normalized in normalized_keys.items():
                if normalized == preferred.replace(" ", "_") and _is_numeric_series(raw_value[original]):
                    return [float(x) for x in raw_value[original]], original, None

        for original in keys:
            series = raw_value[original]
            if _is_numeric_series(series):
                return (
                    [float(x) for x in series],
                    original,
                    f"Lead II not identified in multi-lead waveform — using first valid numeric lead '{original}'",
                )

        return None, None, "Multi-lead ECG waveform present but no valid numeric lead could be identified"

    if isinstance(raw_value, list) and raw_value and isinstance(raw_value[0], list):
        for idx, series in enumerate(raw_value):
            if _is_numeric_series(series):
                if idx == 1:
                    return [float(x) for x in series], "lead_ii", None
                return (
                    [float(x) for x in series],
                    f"lead_index_{idx}",
                    f"Lead II not identified in multi-lead waveform — using first valid numeric lead at index {idx}",
                )
        return None, None, "Multi-lead ECG waveform present but no valid numeric lead could be identified"

    if _is_numeric_series(raw_value):
        return [float(x) for x in raw_value], "single_lead", None

    return None, None, None


def _downsample(signal: list[float], max_points: int) -> list[float]:
    if len(signal) <= max_points:
        return [round(float(v), 4) for v in signal]
    step = max(1, -(-len(signal) // max_points))  # ceil division keeps result within max_points
    return [round(float(signal[i]), 4) for i in range(0, len(signal), step)]


# ---------------------------------------------------------------------------
# Reported label handling
# ---------------------------------------------------------------------------


def _reported_label_value(entry: Any) -> tuple[str | None, float | None]:
    if not isinstance(entry, dict):
        return None, None
    raw = entry.get("value")
    if raw is None:
        return None, None
    text = str(raw).strip()
    if not text:
        return None, None
    return text, _safe_float(entry.get("confidence"))


def _strip_diagnostic_language(text: str) -> tuple[str, bool]:
    """Replace diagnostic phrasing with neutral, simulation-safe wording."""
    sanitized = _DIAGNOSTIC_PATTERN.sub("reported descriptor", text)
    sanitized = re.sub(r"\s+", " ", sanitized).strip()
    return sanitized, sanitized != text.strip()


async def _normalize_reported_label_with_openai(
    sanitized_label: str,
    model_name: str,
) -> tuple[str | None, str | None]:
    """Use OpenAI to rephrase a reported label as a neutral, non-diagnostic statement.

    Never used to estimate ECG numeric features — wording normalization only.
    Returns (normalized_label, warning).
    """
    try:
        import openai

        client = openai.AsyncOpenAI(api_key=os.environ["OPENAI_API_KEY"])
        response = await client.chat.completions.create(
            model=model_name,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "Rewrite a reported ECG rhythm statement as one short, neutral sentence "
                        "that frames it explicitly as reported wording, not a clinical conclusion. "
                        "Never use the words diagnosis, diagnosed, or diagnostic. Never say 'the "
                        "patient has' anything. Do not add any new clinical claims. "
                        "Return JSON with key 'normalized_label' only."
                    ),
                },
                {
                    "role": "user",
                    "content": f"Reported rhythm text: {sanitized_label}",
                },
            ],
            **chat_tuning(model_name, 120, 0),
            response_format={"type": "json_object"},
        )
        raw = response.choices[0].message.content or "{}"
        parsed = json.loads(raw)
        normalized = str(parsed.get("normalized_label", "")).strip()
        if not normalized:
            return None, "OpenAI rhythm-label normalizer returned an empty result; used sanitized reported text"
        normalized, _ = _strip_diagnostic_language(normalized)
        return normalized, None
    except Exception as exc:
        return None, f"OpenAI rhythm-label normalizer unavailable; used sanitized reported text ({type(exc).__name__})"


def _simulated_label_from_rr(rr_mv: MeasuredValue | None) -> str | None:
    if rr_mv is None or not rr_mv.value:
        return None
    hr = 60000.0 / rr_mv.value
    if hr < 60:
        return "simulated bradycardic rhythm pattern (visualization estimate)"
    if hr > 100:
        return "simulated tachycardic rhythm pattern (visualization estimate)"
    return "simulated regular rhythm pattern (visualization estimate)"


# ---------------------------------------------------------------------------
# Payload builders
# ---------------------------------------------------------------------------


def _build_chart_payload(
    signal: list[float],
    sampling_rate_hz: float,
    lead_used: str,
    features: EcgFeatures,
    source: str,
) -> dict:
    return {
        "lead_used": lead_used,
        "sampling_rate_hz": sampling_rate_hz,
        "duration_s": round(len(signal) / sampling_rate_hz, 2),
        "preview_signal_mv": _downsample(signal, _CHART_PREVIEW_MAX_POINTS),
        "r_peak_indices": features.r_peak_indices,
        "rr_intervals_ms": features.rr_intervals_ms,
        "mean_rr_ms": features.mean_rr_ms,
        "heart_rate_bpm_estimate": features.heart_rate_bpm,
        "display_label": _CHART_DISPLAY_LABEL,
        "source": source,
        "confidence": features.r_peak_confidence,
    }


def _build_visual_payload(
    rhythm_source: str,
    rr_interval_ms: float | None,
    conduction_delay_score: float | None,
    arrhythmia_instability_score: float | None,
    confidence: float,
) -> dict:
    beat_interval_ms = rr_interval_ms if rr_interval_ms else 800.0
    delay = conduction_delay_score if conduction_delay_score is not None else 0.0
    wave_speed = round(max(0.2, 1.0 - delay * 0.6), 4)
    return {
        "beat_interval_ms": round(beat_interval_ms, 1),
        "wave_speed": wave_speed,
        "conduction_delay_score": round(conduction_delay_score, 4) if conduction_delay_score is not None else None,
        "arrhythmia_instability_score": (
            round(arrhythmia_instability_score, 4) if arrhythmia_instability_score is not None else None
        ),
        "display_label": _VISUAL_DISPLAY_LABEL,
        "source": rhythm_source,
        "confidence": confidence,
    }


# ---------------------------------------------------------------------------
# Confidence scoring
# ---------------------------------------------------------------------------


def _score_confidence(
    rhythm_source: str,
    r_peak_confidence: float | None,
    reported_confidence: float | None,
    warning_count: int,
) -> float:
    if rhythm_source == "waveform_estimated":
        base = max(0.35, r_peak_confidence or 0.0)
    elif rhythm_source == "reported":
        base = min(0.65, reported_confidence if reported_confidence is not None else 0.5)
    elif rhythm_source == "simulated_visualization":
        base = 0.35
    else:
        base = 0.15

    base -= 0.03 * min(warning_count, 3)
    return round(max(0.05, min(1.0, base)), 3)


# ---------------------------------------------------------------------------
# Non-diagnostic language enforcement
# ---------------------------------------------------------------------------


def _assert_no_diagnostic_language(output: ElectrophysiologyOutput) -> str | None:
    """Final guard: scan agent-authored text fields for diagnostic phrasing.

    Sanitizes in place if a violation slips through and returns a warning string.
    """
    found = False
    if output.rhythm_label and _DIAGNOSTIC_PATTERN.search(output.rhythm_label):
        output.rhythm_label, _ = _strip_diagnostic_language(output.rhythm_label)
        found = True

    display_label = output.electrical_visual_payload.get("display_label")
    if isinstance(display_label, str) and _DIAGNOSTIC_PATTERN.search(display_label):
        output.electrical_visual_payload["display_label"] = _VISUAL_DISPLAY_LABEL
        found = True

    if output.ecg_chart_payload:
        chart_label = output.ecg_chart_payload.get("display_label")
        if isinstance(chart_label, str) and _DIAGNOSTIC_PATTERN.search(chart_label):
            output.ecg_chart_payload["display_label"] = _CHART_DISPLAY_LABEL
            found = True

    if found:
        return "Diagnostic language detected and sanitized in electrophysiology output"
    return None


# ---------------------------------------------------------------------------
# Redis case memory
# ---------------------------------------------------------------------------


async def _store_electrophysiology_memory(
    case_id: str,
    ep_output: ElectrophysiologyOutput,
    lead_used: str | None,
    sampling_rate_hz: float | None,
    reported_statement: str | None,
    finished_at: str,
) -> None:
    """Persist a compact electrophysiology summary for case memory recall.

    Never raises — storage failures must not break the agent pipeline, and raw
    waveform arrays are never written here (chart/visual summaries only).
    """
    from python.hearttwin.tools import redis_client

    if not redis_client.is_configured():
        return

    chart_summary = None
    if ep_output.ecg_chart_payload:
        chart_summary = {
            "lead_used": lead_used,
            "sampling_rate_hz": sampling_rate_hz,
            "r_peak_count": ep_output.r_peak_count,
            "mean_rr_ms": ep_output.ecg_chart_payload.get("mean_rr_ms"),
            "display_label": ep_output.ecg_chart_payload.get("display_label"),
        }

    payload = {
        "rhythm_label": ep_output.rhythm_label,
        "rhythm_source": ep_output.rhythm_source,
        "reported_ecg_statement": reported_statement,
        "rr_interval_ms": ep_output.rr_interval_ms,
        "qrs_duration_ms": ep_output.qrs_duration_ms,
        "qt_interval_ms": ep_output.qt_interval_ms,
        "qtc_ms": ep_output.qtc_ms,
        "r_peak_count": ep_output.r_peak_count,
        "r_peak_confidence": ep_output.r_peak_confidence,
        "ecg_chart_payload_summary": chart_summary,
        "electrical_visual_payload": ep_output.electrical_visual_payload,
        "warnings": ep_output.warnings,
        "confidence": ep_output.confidence,
        "updated_at": finished_at,
    }

    await redis_client.set_json(f"hearttwin:case:{case_id}:electrophysiology", payload)


# ---------------------------------------------------------------------------
# Stage bookkeeping helpers
# ---------------------------------------------------------------------------


def _stage_status(warnings: list[str]) -> Literal["success", "warning", "failed", "skipped"]:
    return "warning" if warnings else "success"


def _inputs_used(waveform_present: bool, reported_label: str | None, ep_input: ElectrophysiologyInput) -> list[str]:
    inputs: list[str] = ["cardiac_twin_state"]
    if waveform_present:
        inputs.append("ecg_waveform")
    if reported_label:
        inputs.append("reported_rhythm_label")
    if ep_input.validated_fields:
        inputs.append("validated_ecg_fields")
    return inputs


def _source_refs(ep_input: ElectrophysiologyInput, waveform_entry: Any) -> list[dict[str, Any]]:
    refs: list[dict[str, Any]] = []
    for file in ep_input.files:
        refs.append({"file_id": file.file_id, "content_type": file.content_type})
    if isinstance(waveform_entry, dict) and waveform_entry.get("method"):
        refs.append({"method": waveform_entry.get("method"), "source": waveform_entry.get("source")})
    return refs


def _output_summary(output: ElectrophysiologyOutput, waveform_present: bool) -> str:
    if output.rhythm_source == "unknown":
        return "No ECG waveform or reported rhythm available; electrophysiology state is unknown"
    descriptor = output.rhythm_label or "no rhythm descriptor"
    waveform_note = "with waveform analysis" if waveform_present and output.ecg_chart_payload else "without waveform analysis"
    return f"Electrophysiology resolved via {output.rhythm_source} ({waveform_note}): {descriptor}"


_utc_now = utc_now
