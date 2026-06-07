"""Agent 3: Evidence Validator Agent.

Validates extracted evidence before it enters the canonical cardiac state.

It checks units, physiological bounds, contradictions between candidates,
missing critical fields, and source quality. It never extracts evidence,
never assembles the cardiac state, never simulates, and never diagnoses.

All numeric validation (unit normalization, bounds, conflicts, scoring) is
deterministic Python. OpenAI is used only — and optionally — to turn detected
conflicts into short human-readable warning summaries.
"""

from __future__ import annotations

import json
import os
import time
from datetime import datetime, timezone
from typing import Any, Literal

from pydantic import BaseModel, Field

from python.hearttwin.schemas import AgentResponse, AgentStatus, AgentStageResult
from python.hearttwin.tools.model_config import chat_tuning, get_validator_model
from python.hearttwin.tools.weave_trace import TraceContext, utc_now

_VALIDATOR_AGENT_ID = "evidence_validator"
_VALIDATOR_AGENT_NAME = "Evidence Validator Agent"
_LEGACY_AGENT_NAME = "validator_agent"
_VALIDATOR_TRACE_TOOL = "hearttwin.validate_evidence"


# ---------------------------------------------------------------------------
# Schema-bound input / output contracts
# ---------------------------------------------------------------------------


class ExtractedMeasurement(BaseModel):
    field: str
    value: float | str | None = None
    unit: str | None = None
    source: str = "unknown"
    confidence: float = Field(default=0.5, ge=0.0, le=1.0)
    source_file_id: str | None = None
    method: str | None = None
    evidence: str | None = None


class ValidatorInput(BaseModel):
    case_id: str
    extracted_fields: list[ExtractedMeasurement]
    previous_state: dict[str, Any] | None = None


class ValidatedField(BaseModel):
    field: str
    selected_value: float | str | None
    unit: str | None
    source: str
    confidence: float
    status: Literal["valid", "warning", "conflict", "invalid", "missing"]
    evidence_candidates: list[ExtractedMeasurement]
    warnings: list[str]
    validation_rules_applied: list[str]


class ValidatorOutput(BaseModel):
    validated_fields: dict[str, ValidatedField]
    conflicts: list[dict[str, Any]]
    missing_critical_fields: list[str]
    invalid_fields: list[str]
    warnings: list[str]
    data_quality_score: float


# ---------------------------------------------------------------------------
# Deterministic validation knowledge: bounds, units, sources, criticality
# ---------------------------------------------------------------------------

# (lower, upper). `upper is None` means "lower bound only" (e.g. biomarkers >= 0).
_PHYSIOLOGICAL_BOUNDS: dict[str, tuple[float, float | None]] = {
    "heart_rate_bpm": (25.0, 220.0),
    "systolic_bp_mmhg": (60.0, 260.0),
    "diastolic_bp_mmhg": (30.0, 160.0),
    "edv_ml": (40.0, 350.0),
    "esv_ml": (10.0, 300.0),
    "ejection_fraction_pct": (5.0, 90.0),
    "oxygen_saturation_pct": (50.0, 100.0),
    "qrs_duration_ms": (40.0, 220.0),
    "qt_interval_ms": (200.0, 700.0),
    "qtc_ms": (250.0, 650.0),
    "troponin_ng_l": (0.0, None),
    "bnp_pg_ml": (0.0, None),
}

_CANONICAL_UNITS: dict[str, str] = {
    "heart_rate_bpm": "bpm",
    "systolic_bp_mmhg": "mmHg",
    "diastolic_bp_mmhg": "mmHg",
    "edv_ml": "mL",
    "esv_ml": "mL",
    "ejection_fraction_pct": "%",
    "oxygen_saturation_pct": "%",
    "qrs_duration_ms": "ms",
    "qt_interval_ms": "ms",
    "qtc_ms": "ms",
    "troponin_ng_l": "ng/L",
    "bnp_pg_ml": "pg/mL",
}

# Cleaned (lower-cased, space-stripped) raw unit -> canonical unit.
_UNIT_ALIASES: dict[str, str] = {
    "bpm": "bpm",
    "beats/min": "bpm",
    "beatsperminute": "bpm",
    "beatperminute": "bpm",
    "/min": "bpm",
    "mmhg": "mmHg",
    "ml": "mL",
    "millilitre": "mL",
    "milliliter": "mL",
    "cc": "mL",
    "%": "%",
    "percent": "%",
    "pct": "%",
    "ms": "ms",
    "msec": "ms",
    "millisecond": "ms",
    "milliseconds": "ms",
    "ng/l": "ng/L",
    "pg/ml": "pg/mL",
}

# Source/method classification, ordered from highest to lowest trust.
_SOURCE_PRIORITY: list[str] = [
    "manual_input",
    "csv_waveform",
    "vista3d_segmentation",
    "pdf_text",
    "openai_structured_extraction",
    "image_metadata",
    "unknown",
]
_SOURCE_PRIORITY_INDEX: dict[str, int] = {name: i for i, name in enumerate(_SOURCE_PRIORITY)}

# Critical-field sets per the operation-simulation contract.
_FULL_CRITICAL_FIELDS: list[str] = [
    "heart_rate_bpm",
    "systolic_bp_mmhg",
    "diastolic_bp_mmhg",
    "edv_ml",
    "esv_ml",
]
_PARTIAL_MINIMUM_FIELDS: list[str] = [
    "heart_rate_bpm",
    "systolic_bp_mmhg",
    "diastolic_bp_mmhg",
]

# How far apart two candidates for the same field may be before they're a conflict.
_CONFLICT_THRESHOLDS: dict[str, float] = {
    "heart_rate_bpm": 15.0,
    "systolic_bp_mmhg": 12.0,
    "diastolic_bp_mmhg": 10.0,
    "ejection_fraction_pct": 10.0,
    "edv_ml": 25.0,
    "esv_ml": 20.0,
    "oxygen_saturation_pct": 6.0,
}

_HIGH_QUALITY_SOURCES = {
    "manual_input",
    "csv_waveform",
    "vista3d_segmentation",
    "pdf_text",
    "openai_structured_extraction",
}


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


async def run_validator_agent(
    extracted_fields: dict[str, Any] | list[Any],
    case_id: str,
    previous_state: dict[str, Any] | None = None,
) -> AgentResponse:
    """Validate and normalize extracted cardiac evidence before it enters the state."""
    started = _utc_now()
    t0 = time.time()
    tracer = TraceContext(case_id=case_id, agent_name=_LEGACY_AGENT_NAME)
    tools_called: list[str] = []

    measurements = _to_extracted_measurements(extracted_fields)
    validator_input = ValidatorInput(
        case_id=case_id,
        extracted_fields=measurements,
        previous_state=previous_state,
    )
    tools_called.append("normalize_extraction_payload")

    grouped = _group_by_field(validator_input.extracted_fields)
    tools_called.append("group_evidence_by_field")

    validated: dict[str, ValidatedField] = {}
    for field in sorted(set(grouped) | set(_PHYSIOLOGICAL_BOUNDS)):
        validated[field] = _validate_field(field, grouped.get(field, []))
    tools_called.append("validate_units_and_bounds")

    conflicts = _detect_all_conflicts(grouped, validated)
    if conflicts:
        tools_called.append("detect_conflicts")

    invalid_fields = sorted(f for f, vf in validated.items() if vf.status == "invalid")
    missing_critical = _missing_critical_fields(validated)
    tools_called.append("detect_missing_critical_fields")

    warnings: list[str] = []
    for field in sorted(validated):
        warnings.extend(validated[field].warnings)
    for conflict in conflicts:
        warnings.append(_conflict_to_warning_text(conflict))
    if not _partial_operation_possible(validated):
        warnings.append(
            "Insufficient evidence for even a partial operation simulation "
            "(requires HR, SBP, DBP, and either EF or both EDV and ESV)"
        )

    data_quality_score = _compute_data_quality_score(validated, conflicts, invalid_fields, missing_critical)
    tools_called.append("score_data_quality")

    model_used: str | None = None
    if conflicts:
        model_name = _get_validator_model()
        summaries, summary_warning = await _summarize_conflicts_with_openai(conflicts, model_name)
        tools_called.append("openai_conflict_summarizer")
        if summary_warning:
            warnings.append(summary_warning)
        elif summaries:
            model_used = model_name
            for summary in summaries:
                message = summary.get("message")
                if message:
                    warnings.append(f"Conflict summary — {summary.get('field', 'unknown')}: {message}")

    warnings = _dedupe(warnings)

    validator_output = ValidatorOutput(
        validated_fields=validated,
        conflicts=conflicts,
        missing_critical_fields=missing_critical,
        invalid_fields=invalid_fields,
        warnings=warnings,
        data_quality_score=data_quality_score,
    )

    legacy_validated = _to_legacy_validated_fields(validated)
    # Pass through raw non-scalar artifacts (e.g. __ecg_waveform__) that are not
    # validated as scalar measurements but are required downstream (the
    # electrophysiology agent reads the waveform from validated_fields).
    if isinstance(extracted_fields, dict):
        for raw_key, raw_payload in extracted_fields.items():
            if raw_key.startswith("__") and raw_key not in legacy_validated:
                legacy_validated[raw_key] = raw_payload
    structured_output = validator_output.model_dump(mode="json")

    latency_ms = round((time.time() - t0) * 1000, 1)
    finished = _utc_now()
    stage_status = _stage_status(invalid_fields, conflicts, missing_critical, warnings)
    confidence = _overall_confidence(validated, conflicts, invalid_fields)

    stage_result = AgentStageResult(
        agent_id=_VALIDATOR_AGENT_ID,
        agent_name=_VALIDATOR_AGENT_NAME,
        model_used=model_used,
        status=stage_status,
        started_at=started,
        finished_at=finished,
        latency_ms=latency_ms,
        inputs_used=sorted(grouped) or ["no_extracted_evidence"],
        tools_called=tools_called,
        output_summary=_output_summary(validator_output),
        structured_output=structured_output,
        warnings=warnings,
        confidence=confidence,
        source_refs=_source_refs(measurements),
        safety_flags=_safety_flags(invalid_fields, conflicts, missing_critical),
        weave_call_id=None,
        local_trace_id=tracer.trace_id,
    )

    tracer.record_tool(
        _VALIDATOR_TRACE_TOOL,
        inputs={
            "case_id": case_id,
            "field_count": len(grouped),
        },
        outputs={
            "validated_field_count": len(validated),
            "conflict_count": len(conflicts),
            "invalid_count": len(invalid_fields),
            "missing_critical_count": len(missing_critical),
            "data_quality_score": data_quality_score,
            "model_used": model_used,
            "latency_ms": latency_ms,
        },
        duration_ms=latency_ms,
    )

    await _store_validation_memory(
        case_id,
        {
            "validated_fields": structured_output["validated_fields"],
            "conflicts": conflicts,
            "invalid_fields": invalid_fields,
            "data_quality_score": data_quality_score,
            "warnings": warnings,
        },
    )

    return AgentResponse(
        agent=_LEGACY_AGENT_NAME,
        status=AgentStatus(stage_status),
        inputs_used=stage_result.inputs_used,
        outputs={
            "validated_fields": legacy_validated,
            "validated_count": len(legacy_validated),
            "conflict_fields": sorted({c.get("field", "") for c in conflicts} - {""}),
            "conflicts": conflicts,
            "missing_critical_fields": missing_critical,
            "invalid_fields": invalid_fields,
            "data_quality_score": data_quality_score,
            "structured_output": structured_output,
            "agent_stage_result": stage_result.model_dump(mode="json"),
        },
        warnings=warnings,
        confidence=confidence,
        trace=tracer.steps,
    )


# ---------------------------------------------------------------------------
# Evidence ingestion + grouping
# ---------------------------------------------------------------------------


def _to_extracted_measurements(
    extracted_fields: dict[str, Any] | list[Any],
) -> list[ExtractedMeasurement]:
    """Convert raw extraction evidence into schema-bound candidates.

    Two shapes are accepted:
      * dict[field_name, candidate_dict] — the extraction agent's current shape,
        one candidate per field (legacy /extract pipeline compatibility).
      * list[candidate_dict | ExtractedMeasurement] — the ValidatorInput contract
        shape, where each item carries its own `field` and several items may
        share the same field (multiple candidates, e.g. two EF estimates).
    """
    if isinstance(extracted_fields, list):
        return _coerce_measurement_list(extracted_fields)
    return _coerce_measurement_dict(extracted_fields)


def _coerce_measurement_dict(extracted_fields: dict[str, Any]) -> list[ExtractedMeasurement]:
    measurements: list[ExtractedMeasurement] = []
    for field, payload in (extracted_fields or {}).items():
        if field.startswith("__") or not isinstance(payload, dict):
            continue
        value = payload.get("value")
        if isinstance(value, (list, dict)):
            continue
        try:
            measurements.append(
                ExtractedMeasurement(
                    field=field,
                    value=value,
                    unit=payload.get("unit"),
                    source=str(payload.get("source") or "unknown"),
                    confidence=float(payload.get("confidence", 0.5)),
                    source_file_id=payload.get("source_file_id"),
                    method=payload.get("method"),
                    evidence=payload.get("evidence"),
                )
            )
        except (TypeError, ValueError):
            continue
    return measurements


def _coerce_measurement_list(items: list[Any]) -> list[ExtractedMeasurement]:
    measurements: list[ExtractedMeasurement] = []
    for item in items:
        if isinstance(item, ExtractedMeasurement):
            measurements.append(item)
            continue
        if not isinstance(item, dict):
            continue
        field = item.get("field")
        if not field or str(field).startswith("__"):
            continue
        value = item.get("value")
        if isinstance(value, (list, dict)):
            continue
        try:
            measurements.append(
                ExtractedMeasurement(
                    field=str(field),
                    value=value,
                    unit=item.get("unit"),
                    source=str(item.get("source") or "unknown"),
                    confidence=float(item.get("confidence", 0.5)),
                    source_file_id=item.get("source_file_id"),
                    method=item.get("method"),
                    evidence=item.get("evidence"),
                )
            )
        except (TypeError, ValueError):
            continue
    return measurements


def _group_by_field(measurements: list[ExtractedMeasurement]) -> dict[str, list[ExtractedMeasurement]]:
    grouped: dict[str, list[ExtractedMeasurement]] = {}
    for measurement in measurements:
        grouped.setdefault(measurement.field, []).append(measurement)
    return grouped


# ---------------------------------------------------------------------------
# Unit normalization
# ---------------------------------------------------------------------------


def _normalize_unit(field: str, raw_unit: str | None) -> tuple[str | None, list[str], list[str]]:
    """Return (normalized_unit, warnings, validation_rules_applied)."""
    rules = ["unit_normalization"]
    warnings: list[str] = []
    canonical = _CANONICAL_UNITS.get(field)
    cleaned = (raw_unit or "").strip().lower().replace(" ", "")

    if not cleaned:
        if canonical:
            warnings.append(f"Field '{field}': unit missing — inferred '{canonical}' from field name")
            rules.append("unit_inferred_from_field_name")
            return canonical, warnings, rules
        return None, warnings, rules

    normalized = _UNIT_ALIASES.get(cleaned)
    if normalized is None:
        warnings.append(f"Field '{field}': unrecognized unit '{raw_unit}' — kept as-is")
        rules.append("unit_unrecognized")
        return raw_unit, warnings, rules

    if canonical and normalized != canonical:
        warnings.append(
            f"Field '{field}': unit '{raw_unit}' normalized to '{normalized}', "
            f"which does not match the expected unit '{canonical}'"
        )

    return normalized, warnings, rules


# ---------------------------------------------------------------------------
# Bounds validation
# ---------------------------------------------------------------------------


def _check_bounds(field: str, value: float) -> tuple[Literal["valid", "warning", "invalid"], list[str]]:
    bound = _PHYSIOLOGICAL_BOUNDS.get(field)
    if bound is None:
        return "valid", []

    lower, upper = bound
    if value < lower:
        deficit_ratio = (lower - value) / lower if lower else 1.0
        if deficit_ratio > 0.4:
            return "invalid", [
                f"Field '{field}': value {value} is far below the physiological "
                f"bound [{lower}, {upper if upper is not None else '∞'}] — marked invalid"
            ]
        return "warning", [
            f"Field '{field}': value {value} is below the expected lower bound {lower} — flagged"
        ]

    if upper is not None and value > upper:
        excess_ratio = (value - upper) / upper if upper else 1.0
        if excess_ratio > 0.4:
            return "invalid", [
                f"Field '{field}': value {value} is far above the physiological "
                f"bound [{lower}, {upper}] — marked invalid"
            ]
        return "warning", [
            f"Field '{field}': value {value} is above the expected upper bound {upper} — flagged"
        ]

    return "valid", []


# ---------------------------------------------------------------------------
# Source quality classification + candidate selection
# ---------------------------------------------------------------------------


def _classify_source(measurement: ExtractedMeasurement) -> str:
    """Bucket a candidate's provenance into the canonical priority taxonomy."""
    combined = f"{(measurement.source or '').lower()} {(measurement.method or '').lower()}"
    if "manual" in combined or "user_input" in combined:
        return "manual_input"
    if "waveform" in combined:
        return "csv_waveform"
    if "vista3d" in combined or "segmentation" in combined:
        return "vista3d_segmentation"
    if "pdf" in combined or "regex" in combined:
        return "pdf_text"
    if "openai" in combined or "vision_api" in combined or "structured_extraction" in combined:
        return "openai_structured_extraction"
    if "metadata" in combined or "exif" in combined:
        return "image_metadata"
    return "unknown"


def _select_best_candidate(candidates: list[ExtractedMeasurement]) -> ExtractedMeasurement:
    """Pick the highest-priority, highest-confidence candidate. Never discards the rest."""
    return min(
        candidates,
        key=lambda c: (
            _SOURCE_PRIORITY_INDEX.get(_classify_source(c), len(_SOURCE_PRIORITY)),
            -c.confidence,
        ),
    )


# ---------------------------------------------------------------------------
# Per-field validation
# ---------------------------------------------------------------------------


def _validate_field(field: str, candidates: list[ExtractedMeasurement]) -> ValidatedField:
    if not candidates:
        rule = "missing_critical_field_detection" if field in _FULL_CRITICAL_FIELDS else "missing_field_detection"
        return ValidatedField(
            field=field,
            selected_value=None,
            unit=_CANONICAL_UNITS.get(field),
            source="unknown",
            confidence=0.0,
            status="missing",
            evidence_candidates=[],
            warnings=[f"Field '{field}': no evidence found for this measurement"],
            validation_rules_applied=[rule],
        )

    rules: list[str] = ["candidate_selection", "source_quality_assessment"]
    warnings: list[str] = []

    selected = _select_best_candidate(candidates)

    normalized_unit, unit_warnings, unit_rules = _normalize_unit(field, selected.unit)
    warnings.extend(unit_warnings)
    for rule in unit_rules:
        if rule not in rules:
            rules.append(rule)

    status: Literal["valid", "warning", "conflict", "invalid", "missing"] = "valid"

    if selected.value is None:
        status = "missing"
        warnings.append(f"Field '{field}': selected candidate carries no value")
    elif isinstance(selected.value, (int, float)):
        rules.append("bounds_validation")
        bound_status, bound_warnings = _check_bounds(field, float(selected.value))
        warnings.extend(bound_warnings)
        status = bound_status

    if selected.confidence < 0.4:
        warnings.append(
            f"Field '{field}': selected evidence has low confidence ({selected.confidence}) "
            f"from source '{_classify_source(selected)}'"
        )
        if status == "valid":
            status = "warning"

    return ValidatedField(
        field=field,
        selected_value=selected.value,
        unit=normalized_unit,
        source=_classify_source(selected),
        confidence=selected.confidence,
        status=status,
        evidence_candidates=candidates,
        warnings=warnings,
        validation_rules_applied=rules,
    )


# ---------------------------------------------------------------------------
# Conflict detection (preserves all candidates; never discards evidence)
# ---------------------------------------------------------------------------


def _detect_all_conflicts(
    grouped: dict[str, list[ExtractedMeasurement]],
    validated: dict[str, ValidatedField],
) -> list[dict[str, Any]]:
    conflicts: list[dict[str, Any]] = []

    for field in sorted(grouped):
        duplicate_conflict = _duplicate_value_conflict(field, grouped[field])
        if duplicate_conflict:
            conflicts.append(duplicate_conflict)
            _mark_conflict(validated, field)

    ef_conflict = _ef_volume_consistency_conflict(validated)
    if ef_conflict:
        conflicts.append(ef_conflict)
        _mark_conflict(validated, "ejection_fraction_pct")

    edv_esv_conflict = _edv_esv_ordering_conflict(validated)
    if edv_esv_conflict:
        conflicts.append(edv_esv_conflict)
        _mark_conflict(validated, "edv_ml")
        _mark_conflict(validated, "esv_ml")

    hr_conflict = _manual_vs_derived_hr_conflict(grouped.get("heart_rate_bpm", []))
    if hr_conflict:
        conflicts.append(hr_conflict)
        _mark_conflict(validated, "heart_rate_bpm")

    bp_conflict = _bp_ordering_conflict(validated)
    if bp_conflict:
        conflicts.append(bp_conflict)
        _mark_conflict(validated, "systolic_bp_mmhg")
        _mark_conflict(validated, "diastolic_bp_mmhg")

    return conflicts


def _mark_conflict(validated: dict[str, ValidatedField], field: str) -> None:
    vf = validated.get(field)
    if vf is None or vf.selected_value is None:
        return
    if vf.status != "invalid":
        vf.status = "conflict"
    if "conflict_detection" not in vf.validation_rules_applied:
        vf.validation_rules_applied.append("conflict_detection")


def _numeric_candidates(candidates: list[ExtractedMeasurement]) -> list[tuple[ExtractedMeasurement, float]]:
    return [(c, float(c.value)) for c in candidates if isinstance(c.value, (int, float))]


def _duplicate_value_conflict(field: str, candidates: list[ExtractedMeasurement]) -> dict[str, Any] | None:
    """Multiple candidates for the same field that disagree by more than the threshold."""
    numeric = _numeric_candidates(candidates)
    if len(numeric) < 2:
        return None

    values = [v for _, v in numeric]
    spread = max(values) - min(values)
    threshold = _CONFLICT_THRESHOLDS.get(field)
    if threshold is None:
        threshold = max(abs(v) for v in values) * 0.15

    if spread <= threshold:
        return None

    return {
        "type": "duplicate_value_conflict",
        "field": field,
        "candidates": [
            {
                "value": value,
                "source": _classify_source(candidate),
                "confidence": candidate.confidence,
                "method": candidate.method,
            }
            for candidate, value in numeric
        ],
        "spread": round(spread, 3),
        "threshold": round(threshold, 3),
    }


def _ef_volume_consistency_conflict(validated: dict[str, ValidatedField]) -> dict[str, Any] | None:
    """Extracted EF disagrees with EF derived from EDV/ESV by more than ~10 points."""
    ef = validated.get("ejection_fraction_pct")
    edv = validated.get("edv_ml")
    esv = validated.get("esv_ml")
    if not (ef and edv and esv):
        return None
    if not all(isinstance(x.selected_value, (int, float)) for x in (ef, edv, esv)):
        return None

    edv_v = float(edv.selected_value)
    esv_v = float(esv.selected_value)
    if edv_v <= 0:
        return None

    derived_ef = (edv_v - esv_v) / edv_v * 100.0
    extracted_ef = float(ef.selected_value)
    diff = abs(derived_ef - extracted_ef)
    if diff <= 10.0:
        return None

    return {
        "type": "ef_volume_consistency_conflict",
        "field": "ejection_fraction_pct",
        "extracted_ef_pct": extracted_ef,
        "derived_ef_pct": round(derived_ef, 2),
        "difference_pct_points": round(diff, 2),
    }


def _edv_esv_ordering_conflict(validated: dict[str, ValidatedField]) -> dict[str, Any] | None:
    """ESV must be smaller than EDV; ESV >= EDV is physiologically inconsistent."""
    edv = validated.get("edv_ml")
    esv = validated.get("esv_ml")
    if not (edv and esv):
        return None
    if not (isinstance(edv.selected_value, (int, float)) and isinstance(esv.selected_value, (int, float))):
        return None

    edv_v = float(edv.selected_value)
    esv_v = float(esv.selected_value)
    if esv_v < edv_v:
        return None

    return {
        "type": "edv_esv_ordering_conflict",
        "field": "esv_ml",
        "edv_ml": edv_v,
        "esv_ml": esv_v,
        "note": "End-systolic volume should be smaller than end-diastolic volume",
    }


def _manual_vs_derived_hr_conflict(candidates: list[ExtractedMeasurement]) -> dict[str, Any] | None:
    """Manually entered heart rate disagrees with a waveform/segmentation-derived estimate."""
    manual = [c for c in candidates if _classify_source(c) == "manual_input" and isinstance(c.value, (int, float))]
    derived = [
        c
        for c in candidates
        if _classify_source(c) in ("csv_waveform", "vista3d_segmentation") and isinstance(c.value, (int, float))
    ]
    if not manual or not derived:
        return None

    manual_value = float(manual[0].value)
    derived_value = float(derived[0].value)
    if abs(manual_value - derived_value) <= _CONFLICT_THRESHOLDS["heart_rate_bpm"]:
        return None

    return {
        "type": "manual_vs_derived_hr_conflict",
        "field": "heart_rate_bpm",
        "manual_value": manual_value,
        "derived_value": derived_value,
        "difference": round(abs(manual_value - derived_value), 2),
    }


def _bp_ordering_conflict(validated: dict[str, ValidatedField]) -> dict[str, Any] | None:
    """Diastolic pressure should always be lower than systolic pressure."""
    sbp = validated.get("systolic_bp_mmhg")
    dbp = validated.get("diastolic_bp_mmhg")
    if not (sbp and dbp):
        return None
    if not (isinstance(sbp.selected_value, (int, float)) and isinstance(dbp.selected_value, (int, float))):
        return None

    sbp_v = float(sbp.selected_value)
    dbp_v = float(dbp.selected_value)
    if dbp_v < sbp_v:
        return None

    return {
        "type": "bp_ordering_conflict",
        "field": "systolic_bp_mmhg",
        "systolic": sbp_v,
        "diastolic": dbp_v,
    }


def _conflict_to_warning_text(conflict: dict[str, Any]) -> str:
    ctype = conflict.get("type", "conflict")
    field = conflict.get("field", "unknown")

    if ctype == "duplicate_value_conflict":
        return (
            f"Conflict in '{field}': {len(conflict.get('candidates', []))} candidates disagree "
            f"by {conflict.get('spread')} (threshold {conflict.get('threshold')})"
        )
    if ctype == "ef_volume_consistency_conflict":
        return (
            f"Conflict in '{field}': extracted EF {conflict.get('extracted_ef_pct')}% disagrees with "
            f"EDV/ESV-derived EF {conflict.get('derived_ef_pct')}% by "
            f"{conflict.get('difference_pct_points')} points"
        )
    if ctype == "edv_esv_ordering_conflict":
        return (
            f"Conflict in '{field}': ESV ({conflict.get('esv_ml')} mL) is not smaller than "
            f"EDV ({conflict.get('edv_ml')} mL)"
        )
    if ctype == "manual_vs_derived_hr_conflict":
        return (
            f"Conflict in '{field}': manually entered HR {conflict.get('manual_value')} bpm disagrees "
            f"with derived HR {conflict.get('derived_value')} bpm "
            f"(difference {conflict.get('difference')} bpm)"
        )
    if ctype == "bp_ordering_conflict":
        return (
            f"Conflict in '{field}': diastolic ({conflict.get('diastolic')} mmHg) is not lower than "
            f"systolic ({conflict.get('systolic')} mmHg)"
        )
    return f"Conflict detected in '{field}'"


# ---------------------------------------------------------------------------
# Critical-field detection
# ---------------------------------------------------------------------------


def _missing_critical_fields(validated: dict[str, ValidatedField]) -> list[str]:
    return [
        field
        for field in _FULL_CRITICAL_FIELDS
        if validated.get(field) is None or validated[field].selected_value is None
    ]


def _partial_operation_possible(validated: dict[str, ValidatedField]) -> bool:
    for field in _PARTIAL_MINIMUM_FIELDS:
        vf = validated.get(field)
        if vf is None or vf.selected_value is None:
            return False

    has_ef = bool(validated.get("ejection_fraction_pct") and validated["ejection_fraction_pct"].selected_value is not None)
    has_volumes = bool(
        validated.get("edv_ml")
        and validated["edv_ml"].selected_value is not None
        and validated.get("esv_ml")
        and validated["esv_ml"].selected_value is not None
    )
    return has_ef or has_volumes


def _safety_flags(invalid_fields: list[str], conflicts: list[dict[str, Any]], missing_critical: list[str]) -> list[str]:
    flags: list[str] = []
    if invalid_fields:
        flags.append("invalid_fields_detected")
    if conflicts:
        flags.append("evidence_conflicts_detected")
    if missing_critical:
        flags.append("missing_critical_fields")
    return flags


# ---------------------------------------------------------------------------
# Data quality scoring
# ---------------------------------------------------------------------------


def _compute_data_quality_score(
    validated: dict[str, ValidatedField],
    conflicts: list[dict[str, Any]],
    invalid_fields: list[str],
    missing_critical: list[str],
) -> float:
    expected_fields = list(_PHYSIOLOGICAL_BOUNDS)
    present = [f for f in expected_fields if validated.get(f) and validated[f].selected_value is not None]
    completeness = len(present) / len(expected_fields) if expected_fields else 0.0

    present_sources = {validated[f].source for f in present}
    source_coverage = (
        len(present_sources & _HIGH_QUALITY_SOURCES) / len(_HIGH_QUALITY_SOURCES) if _HIGH_QUALITY_SOURCES else 0.0
    )

    confidences = [validated[f].confidence for f in present]
    average_confidence = sum(confidences) / len(confidences) if confidences else 0.0

    base_score = 0.35 * completeness + 0.20 * source_coverage + 0.45 * average_confidence

    conflict_penalty = min(0.30, 0.06 * len(conflicts))
    invalid_penalty = min(0.30, 0.08 * len(invalid_fields))
    missing_critical_penalty = min(0.30, 0.10 * len(missing_critical))

    score = base_score - conflict_penalty - invalid_penalty - missing_critical_penalty
    return round(max(0.0, min(1.0, score)), 3)


def _overall_confidence(
    validated: dict[str, ValidatedField],
    conflicts: list[dict[str, Any]],
    invalid_fields: list[str],
) -> float:
    confidences = [vf.confidence for vf in validated.values() if vf.selected_value is not None]
    base = sum(confidences) / len(confidences) if confidences else 0.30
    penalty = 0.05 * len(conflicts) + 0.05 * len(invalid_fields)
    return round(max(0.05, min(1.0, base - penalty)), 3)


# ---------------------------------------------------------------------------
# OpenAI-assisted conflict summarization (deterministic fallback always wins)
# ---------------------------------------------------------------------------


def _get_validator_model() -> str:
    return get_validator_model()


async def _summarize_conflicts_with_openai(
    conflicts: list[dict[str, Any]],
    model_name: str,
) -> tuple[list[dict[str, Any]] | None, str | None]:
    """Turn detected conflicts into short warning summaries. Never asked to judge medical normalcy."""
    if not conflicts:
        return None, None
    if not os.environ.get("OPENAI_API_KEY"):
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
                        "You turn detected evidence-validation conflicts into short, neutral, "
                        "human-readable warning summaries for a cardiac data pipeline. "
                        "Do not say whether any value is medically normal or abnormal. "
                        "Do not diagnose. Do not recommend treatment. "
                        'Return JSON: {"summaries": [{"field": str, "message": str}]}.'
                    ),
                },
                {
                    "role": "user",
                    "content": json.dumps({"conflicts": conflicts[:10]}),
                },
            ],
            **chat_tuning(model_name, 400, 0),
            response_format={"type": "json_object"},
        )
        raw = response.choices[0].message.content or "{}"
        parsed = json.loads(raw)
        summaries = parsed.get("summaries")
        if not isinstance(summaries, list):
            return None, "OpenAI conflict summarizer returned an unexpected payload; used deterministic warnings"
        cleaned = [
            {"field": str(item.get("field", "")), "message": str(item.get("message", ""))}
            for item in summaries
            if isinstance(item, dict)
        ]
        return cleaned, None
    except Exception as exc:
        return None, f"OpenAI conflict summarizer unavailable; used deterministic warnings ({type(exc).__name__})"


# ---------------------------------------------------------------------------
# Redis case memory (best-effort; never raises, never blocks validation)
# ---------------------------------------------------------------------------


async def _store_validation_memory(case_id: str, payload: dict[str, Any]) -> None:
    from python.hearttwin.tools import redis_client

    await redis_client.set_json(f"hearttwin:case:{case_id}:validation", payload)


# ---------------------------------------------------------------------------
# Output shaping: legacy-compatible validated_fields + stage summaries
# ---------------------------------------------------------------------------


def _to_legacy_validated_fields(validated: dict[str, ValidatedField]) -> dict[str, Any]:
    """Project ValidatedField results into the dict shape state_builder_agent expects."""
    legacy: dict[str, Any] = {}
    for field, vf in validated.items():
        if vf.selected_value is None:
            continue
        match = next(
            (c for c in vf.evidence_candidates if c.value == vf.selected_value and _classify_source(c) == vf.source),
            vf.evidence_candidates[0] if vf.evidence_candidates else None,
        )
        legacy[field] = {
            "value": vf.selected_value,
            "unit": vf.unit,
            "source": match.source if match else "extracted",
            "confidence": vf.confidence,
            "source_file_id": match.source_file_id if match else None,
            "method": match.method if match else None,
            "evidence": match.evidence if match else None,
            "validation_status": vf.status,
            "flagged": vf.status in ("warning", "conflict", "invalid"),
        }
    return legacy


def _source_refs(measurements: list[ExtractedMeasurement]) -> list[dict[str, Any]]:
    refs: list[dict[str, Any]] = []
    seen: set[tuple[str | None, str | None]] = set()
    for measurement in measurements:
        key = (measurement.source_file_id, measurement.method)
        if key in seen:
            continue
        seen.add(key)
        refs.append(
            {
                "source_file_id": measurement.source_file_id,
                "method": measurement.method,
                "source": measurement.source,
            }
        )
    return refs


def _stage_status(
    invalid_fields: list[str],
    conflicts: list[dict[str, Any]],
    missing_critical: list[str],
    warnings: list[str],
) -> Literal["success", "warning"]:
    if invalid_fields or conflicts or missing_critical or warnings:
        return "warning"
    return "success"


def _output_summary(output: ValidatorOutput) -> str:
    return (
        f"Validated {len(output.validated_fields)} fields — "
        f"{len(output.conflicts)} conflicts, {len(output.invalid_fields)} invalid, "
        f"{len(output.missing_critical_fields)} missing critical "
        f"(data quality {output.data_quality_score})"
    )


def _dedupe(values: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for value in values:
        if value not in seen:
            out.append(value)
            seen.add(value)
    return out


_utc_now = utc_now
