"""Agent 3: Evidence Validator Agent.

Validates units, ranges, contradictions, and data quality.
Resolves conflicts by confidence and recency.
Preserves conflicting evidence in warnings.
"""

from __future__ import annotations

import json
import pathlib
import time
from typing import Any

from python.hearttwin.schemas import AgentResponse, AgentStatus
from python.hearttwin.tools.cardiac_state import check_ef_consistency, validate_bounds
from python.hearttwin.tools.weave_trace import TraceContext

_BOUNDS_PATH = pathlib.Path(__file__).parent.parent / "data" / "parameter_bounds.json"
_BOUNDS: dict = json.loads(_BOUNDS_PATH.read_text())

_UNIT_CONVERSIONS: dict[str, dict[str, float]] = {
    "heart_rate_bpm": {"beats/min": 1.0, "bpm": 1.0},
    "systolic_bp_mmhg": {"mmhg": 1.0, "kpa": 7.500617, "pa": 0.007500617},
    "diastolic_bp_mmhg": {"mmhg": 1.0, "kpa": 7.500617},
    "ejection_fraction_pct": {"%": 1.0, "fraction": 100.0},
    "edv_ml": {"ml": 1.0, "cc": 1.0, "l": 1000.0},
    "esv_ml": {"ml": 1.0, "cc": 1.0, "l": 1000.0},
    "stroke_volume_ml": {"ml": 1.0, "cc": 1.0},
    "cardiac_output_l_min": {"l/min": 1.0, "lpm": 1.0, "ml/min": 0.001},
    "oxygen_saturation_pct": {"%": 1.0},
    "troponin_ng_l": {"ng/l": 1.0, "ng/ml": 1000.0, "ug/l": 1000.0},
    "bnp_pg_ml": {"pg/ml": 1.0, "ng/l": 1.0},
    "qrs_duration_ms": {"ms": 1.0, "msec": 1.0},
    "qt_interval_ms": {"ms": 1.0, "msec": 1.0},
    "qtc_ms": {"ms": 1.0, "msec": 1.0},
}


async def run_validator_agent(
    extracted_fields: dict[str, Any],
    case_id: str,
) -> AgentResponse:
    """Validate and normalize extracted cardiac measurements."""
    tracer = TraceContext(case_id=case_id, agent_name="validator_agent")
    t0 = time.time()
    warnings: list[str] = []
    validated: dict[str, Any] = {}
    conflicts: list[str] = []

    for field, value_data in extracted_fields.items():
        if field.startswith("__"):
            validated[field] = value_data
            continue

        if not isinstance(value_data, dict):
            warnings.append(f"Field '{field}': malformed value data — skipped")
            continue

        raw_value = value_data.get("value")
        unit = (value_data.get("unit") or "").lower().strip()

        if isinstance(raw_value, str):
            validated[field] = value_data
            continue

        try:
            numeric = float(raw_value)
        except (TypeError, ValueError):
            warnings.append(f"Field '{field}': non-numeric value '{raw_value}' — skipped")
            continue

        conversions = _UNIT_CONVERSIONS.get(field, {})
        if unit and conversions and unit not in conversions:
            closest = _find_closest_unit(unit, conversions)
            if closest:
                factor = conversions[closest]
                numeric = numeric * factor
                warnings.append(
                    f"Field '{field}': unit '{unit}' converted via '{closest}' factor {factor}"
                )
            else:
                warnings.append(f"Field '{field}': unknown unit '{unit}' — value kept as-is")
        elif unit and conversions and unit in conversions:
            numeric = numeric * conversions[unit]

        bound_warnings = validate_bounds(field, numeric, _BOUNDS)
        if bound_warnings:
            warnings.extend(bound_warnings)
            conflicts.append(field)
            validated[field] = {
                **value_data,
                "value": numeric,
                "flagged": True,
                "flag_reason": bound_warnings[0],
            }
        else:
            validated[field] = {**value_data, "value": numeric}

    ef = validated.get("ejection_fraction_pct", {}).get("value")
    edv = validated.get("edv_ml", {}).get("value")
    esv = validated.get("esv_ml", {}).get("value")

    if ef is not None and edv is not None and esv is not None:
        consistent, msg = check_ef_consistency(ef, edv, esv)
        if not consistent:
            warnings.append(msg)
            conflicts.append("ejection_fraction_pct (volume consistency)")

    sbp = validated.get("systolic_bp_mmhg", {}).get("value")
    dbp = validated.get("diastolic_bp_mmhg", {}).get("value")
    if sbp is not None and dbp is not None and dbp >= sbp:
        warnings.append(f"BP contradiction: diastolic ({dbp}) >= systolic ({sbp})")
        conflicts.append("bp_ordering")

    tracer.record_tool(
        "validate_bounds",
        inputs={"field_count": len(extracted_fields)},
        outputs={
            "validated_count": len(validated),
            "conflict_count": len(conflicts),
        },
        duration_ms=(time.time() - t0) * 1000,
    )

    confidence = max(0.1, 1.0 - len(conflicts) * 0.1)

    return AgentResponse(
        agent="validator_agent",
        status=AgentStatus.SUCCESS if not conflicts else AgentStatus.WARNING,
        inputs_used=list(extracted_fields.keys()),
        outputs={
            "validated_fields": validated,
            "validated_count": len(validated),
            "conflict_fields": conflicts,
        },
        warnings=warnings,
        confidence=round(confidence, 3),
        trace=tracer.steps,
    )


def _find_closest_unit(unit: str, conversions: dict) -> str | None:
    unit_clean = unit.replace(" ", "").replace(".", "").lower()
    for k in conversions:
        if k.replace("/", "").replace(".", "") == unit_clean:
            return k
    return None
