"""Agent 5: Electrophysiology Agent.

Analyzes ECG-related data and produces electrical operation parameters.
Uses deterministic ECG tools when waveform exists.
Does not diagnose arrhythmia — uses simulation descriptors only.
"""

from __future__ import annotations

import time
from typing import Any

from python.hearttwin.schemas import (
    AgentResponse,
    AgentStatus,
    CardiacTwinState,
    Electrophysiology,
    MeasuredValue,
    ValueSource,
)
from python.hearttwin.safety import CORE_SAFETY_PHRASE
from python.hearttwin.tools.ecg_features import analyze_waveform
from python.hearttwin.tools.weave_trace import TraceContext


async def run_electrophysiology_agent(
    state: CardiacTwinState,
    validated_fields: dict[str, Any],
    case_id: str,
) -> tuple[AgentResponse, Electrophysiology]:
    """Analyze ECG data and update electrophysiology state."""
    tracer = TraceContext(case_id=case_id, agent_name="electrophysiology_agent")
    t0 = time.time()
    warnings: list[str] = []

    ep = state.electrophysiology

    waveform_entry = validated_fields.get("__ecg_waveform__")
    if waveform_entry and isinstance(waveform_entry.get("value"), list):
        signal = waveform_entry["value"]

        sampling_rate = 500.0

        qrs_mv = ep.qrs_duration_ms.value if ep.qrs_duration_ms else None
        qt_mv = ep.qt_interval_ms.value if ep.qt_interval_ms else None

        features = analyze_waveform(
            signal=signal,
            sampling_rate_hz=sampling_rate,
            qrs_duration_ms=qrs_mv,
            qt_ms=qt_mv,
        )

        warnings.extend(features.warnings)

        if features.r_peak_count >= 2:
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
                    confidence=features.r_peak_confidence * 0.9,
                    method="bazett_formula",
                )

            ep.rhythm_label = features.rhythm_descriptor

            tracer.record_tool(
                "waveform_ecg_analysis",
                inputs={"signal_length": len(signal), "sampling_rate": sampling_rate},
                outputs={
                    "r_peaks": features.r_peak_count,
                    "mean_rr_ms": features.mean_rr_ms,
                    "rhythm": features.rhythm_descriptor,
                    "confidence": features.r_peak_confidence,
                },
                duration_ms=(time.time() - t0) * 1000,
            )
        else:
            warnings.append("Waveform detected but insufficient R peaks — falling back to report-extracted values")
    else:
        if ep.qrs_duration_ms:
            qrs_val = ep.qrs_duration_ms.value
            if qrs_val > 120:
                delay = min(1.0, (qrs_val - 120) / 80.0)
                ep.conduction_delay_score = MeasuredValue(
                    value=delay,
                    unit="index",
                    source=ValueSource.DERIVED,
                    confidence=0.6,
                    method="qrs_threshold_rule",
                )

        ep.arrhythmia_instability_score = MeasuredValue(
            value=0.1,
            unit="index",
            source=ValueSource.DEFAULT_MODEL_PRIOR,
            confidence=0.3,
            method="prior_no_waveform",
        )
        ep.r_peak_confidence = 0.0
        warnings.append("No ECG waveform available — electrophysiology from report values or priors only")

        tracer.record_tool(
            "ecg_report_fallback",
            inputs={"has_waveform": False},
            outputs={"method": "report_extracted_or_prior"},
            duration_ms=1.0,
        )

    if ep.rhythm_label and "diagnos" in ep.rhythm_label.lower():
        ep.rhythm_label = "simulated rhythm pattern (report descriptor)"
        warnings.append("Rhythm label sanitized to simulation-safe descriptor")

    if not ep.rhythm_label:
        rr = ep.rr_interval_ms.value if ep.rr_interval_ms else None
        if rr:
            hr = 60000.0 / rr
            if hr < 60:
                ep.rhythm_label = "simulated bradycardic rhythm pattern"
            elif hr > 100:
                ep.rhythm_label = "simulated tachycardic rhythm pattern"
            else:
                ep.rhythm_label = "simulated regular rhythm pattern"

    confidence = ep.r_peak_confidence if ep.r_peak_confidence else 0.4

    return AgentResponse(
        agent="electrophysiology_agent",
        status=AgentStatus.SUCCESS if not warnings else AgentStatus.WARNING,
        inputs_used=["ecg_waveform", "validated_ecg_fields"],
        outputs={
            "rhythm_label": ep.rhythm_label,
            "mean_rr_ms": ep.rr_interval_ms.value if ep.rr_interval_ms else None,
            "qrs_duration_ms": ep.qrs_duration_ms.value if ep.qrs_duration_ms else None,
            "qtc_ms": ep.qtc_ms.value if ep.qtc_ms else None,
            "arrhythmia_instability_score": ep.arrhythmia_instability_score.value if ep.arrhythmia_instability_score else None,
            "conduction_delay_score": ep.conduction_delay_score.value if ep.conduction_delay_score else None,
            "r_peak_confidence": ep.r_peak_confidence,
            "simulation_note": (
                f"{CORE_SAFETY_PHRASE} Rhythm labels are simulation descriptors."
            ),
        },
        warnings=warnings,
        confidence=round(confidence, 3),
        trace=tracer.steps,
    ), ep
