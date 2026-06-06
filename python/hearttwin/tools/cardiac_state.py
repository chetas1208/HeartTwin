"""Deterministic cardiac state computations.

Pure functions only. No LLM calls. No side effects.
All formulas are explicit and unit-tested.
"""

from __future__ import annotations

import math
from typing import Optional


def compute_stroke_volume(edv_ml: float, esv_ml: float) -> float:
    """SV = EDV - ESV"""
    if esv_ml >= edv_ml:
        raise ValueError(f"ESV ({esv_ml} mL) must be less than EDV ({edv_ml} mL)")
    return edv_ml - esv_ml


def compute_ejection_fraction(edv_ml: float, esv_ml: float) -> float:
    """EF = SV / EDV * 100"""
    if edv_ml <= 0:
        raise ValueError("EDV must be positive")
    sv = compute_stroke_volume(edv_ml, esv_ml)
    return (sv / edv_ml) * 100.0


def compute_cardiac_output(heart_rate_bpm: float, stroke_volume_ml: float) -> float:
    """CO = HR * SV / 1000  (result in L/min)"""
    if heart_rate_bpm <= 0:
        raise ValueError("Heart rate must be positive")
    if stroke_volume_ml <= 0:
        raise ValueError("Stroke volume must be positive")
    return (heart_rate_bpm * stroke_volume_ml) / 1000.0


def compute_map(systolic_bp: float, diastolic_bp: float) -> float:
    """MAP = DBP + (SBP - DBP) / 3"""
    if diastolic_bp >= systolic_bp:
        raise ValueError("Diastolic BP must be less than systolic BP")
    return diastolic_bp + (systolic_bp - diastolic_bp) / 3.0


def compute_afterload_index(map_mmhg: float, cardiac_output: float) -> float:
    """Simplified afterload index: normalized MAP / normalized CO.
    Both normalized to population typical (MAP=93, CO=5.0).
    Returns dimensionless index.
    """
    if cardiac_output <= 0:
        raise ValueError("Cardiac output must be positive")
    map_norm = map_mmhg / 93.0
    co_norm = cardiac_output / 5.0
    return map_norm / co_norm


def compute_svr_index(map_mmhg: float, cardiac_output: float, cvp_mmhg: float = 5.0) -> float:
    """Simplified SVR index: (MAP - CVP) / CO, normalized."""
    if cardiac_output <= 0:
        raise ValueError("Cardiac output must be positive")
    svr = (map_mmhg - cvp_mmhg) / cardiac_output
    return svr / 17.6  # normalize to typical value (~880 / 5.0 / 10 = 17.6)


def compute_preload_index(edv_ml: float) -> float:
    """Simplified preload index normalized to typical EDV (130 mL)."""
    if edv_ml <= 0:
        raise ValueError("EDV must be positive")
    return edv_ml / 130.0


def compute_contractility_index(ef_pct: float, afterload_index: float) -> float:
    """Simplified contractility index: EF-derived, afterload-adjusted."""
    ef_norm = ef_pct / 60.0
    return ef_norm / max(afterload_index, 0.1)


def compute_bsa_mosteller(height_cm: float, weight_kg: float) -> float:
    """Body surface area via Mosteller formula: sqrt(H * W / 3600)"""
    if height_cm <= 0 or weight_kg <= 0:
        raise ValueError("Height and weight must be positive")
    return math.sqrt((height_cm * weight_kg) / 3600.0)


def compute_qtc_bazett(qt_ms: float, rr_ms: float) -> float:
    """Bazett formula: QTc = QT / sqrt(RR in seconds)"""
    if rr_ms <= 0:
        raise ValueError("RR interval must be positive")
    rr_seconds = rr_ms / 1000.0
    return qt_ms / math.sqrt(rr_seconds)


def compute_rr_from_hr(heart_rate_bpm: float) -> float:
    """RR interval from heart rate: RR (ms) = 60000 / HR"""
    if heart_rate_bpm <= 0:
        raise ValueError("Heart rate must be positive")
    return 60000.0 / heart_rate_bpm


def check_ef_consistency(
    ef_reported: float,
    edv_ml: Optional[float],
    esv_ml: Optional[float],
    tolerance_pct: float = 5.0,
) -> tuple[bool, str]:
    """Check if reported EF is consistent with volumes. Returns (consistent, message)."""
    if edv_ml is None or esv_ml is None:
        return True, "Cannot verify — volumes not available"
    computed_ef = compute_ejection_fraction(edv_ml, esv_ml)
    diff = abs(computed_ef - ef_reported)
    if diff > tolerance_pct:
        return (
            False,
            f"EF inconsistency: reported {ef_reported:.1f}% vs computed {computed_ef:.1f}% "
            f"(diff {diff:.1f}% > tolerance {tolerance_pct}%)",
        )
    return True, "EF consistent with reported volumes"


def compute_filling_pressure_index(edv_ml: float, stiffness_index: float) -> float:
    """Simplified filling pressure proxy: EDV * stiffness, normalized."""
    normalized_edv = edv_ml / 130.0
    return normalized_edv * stiffness_index


def compute_arterial_compliance_index(stroke_volume_ml: float, pulse_pressure_mmhg: float) -> float:
    """Simplified arterial compliance: SV / pulse pressure, normalized."""
    if pulse_pressure_mmhg <= 0:
        raise ValueError("Pulse pressure must be positive")
    raw = stroke_volume_ml / pulse_pressure_mmhg
    return raw / 2.0  # normalize: typical ~80/40 = 2.0


def validate_bounds(field: str, value: float, bounds: dict) -> list[str]:
    """Return list of bound violations for a value."""
    warnings = []
    field_bounds = bounds.get("measurements", {}).get(field) or bounds.get("indices", {}).get(field)
    if field_bounds is None:
        return warnings
    if value < field_bounds["min"]:
        warnings.append(
            f"{field}: {value} is below physiological minimum {field_bounds['min']} "
            f"{field_bounds.get('unit', '')}"
        )
    if value > field_bounds["max"]:
        warnings.append(
            f"{field}: {value} is above physiological maximum {field_bounds['max']} "
            f"{field_bounds.get('unit', '')}"
        )
    return warnings
