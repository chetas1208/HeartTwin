"""Deterministic hemodynamics simulation tool.

Implements time-varying elastance PV loop approximation.
All numeric computations are deterministic, reproducible, and unit-tested.
No LLM involvement in numeric generation.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field


@dataclass
class PVLoopResult:
    volumes_ml: list[float]
    pressures_mmhg: list[float]
    pv_loop_area_mmhg_ml: float
    stroke_work_j: float
    edv_ml: float
    esv_ml: float
    ef_pct: float
    peak_pressure_mmhg: float
    end_diastolic_pressure_mmhg: float
    contractility_index: float
    warnings: list[str] = field(default_factory=list)


@dataclass
class CardiacCycleResult:
    time_ms: list[float]
    lv_volume_ml: list[float]
    lv_pressure_mmhg: list[float]
    aortic_flow_ml_s: list[float]
    heart_rate_bpm: float
    cycle_duration_ms: float
    stroke_volume_ml: float
    cardiac_output_l_min: float
    pv_loop: PVLoopResult
    warnings: list[str] = field(default_factory=list)


def _normalized_elastance_curve(t_norm: float) -> float:
    """Time-normalized LV elastance curve E_n(t_n).

    t_norm in [0, 1] over the cardiac cycle.
    Uses a simple piecewise approximation of the elastance curve.
    Peaks at ~t_norm=0.35, returns to baseline by t_norm=0.7.
    """
    if t_norm < 0:
        t_norm = 0.0
    if t_norm > 1:
        t_norm = 1.0

    if t_norm <= 0.35:
        return math.sin(math.pi * t_norm / 0.7) ** 2
    elif t_norm <= 0.70:
        return math.sin(math.pi * t_norm / 0.7) ** 2
    else:
        decay = (t_norm - 0.70) / 0.30
        return max(0.0, 0.0 - decay * 0.05)


def simulate_pv_loop(
    edv_ml: float,
    esv_ml: float,
    heart_rate_bpm: float,
    systolic_bp_mmhg: float,
    diastolic_bp_mmhg: float,
    contractility_index: float = 1.0,
    afterload_index: float = 1.0,
    n_points: int = 200,
) -> PVLoopResult:
    """Simulate one cardiac cycle using time-varying elastance model.

    Returns a PVLoopResult with pressure-volume trajectory.
    Deterministic given inputs. No random values.
    """
    warnings: list[str] = []

    if esv_ml >= edv_ml:
        esv_ml = edv_ml * 0.4
        warnings.append("ESV >= EDV: clamped ESV to 40% of EDV for simulation")

    stroke_volume = edv_ml - esv_ml
    ef_pct = (stroke_volume / edv_ml) * 100.0

    cycle_ms = 60000.0 / heart_rate_bpm
    t_sys_end = cycle_ms * 0.40
    t_iso_vol_contract = cycle_ms * 0.07
    t_iso_vol_relax = cycle_ms * 0.08

    edp_mmhg = 8.0 + (edv_ml - 130.0) * 0.05
    edp_mmhg = max(2.0, min(edp_mmhg, 30.0))

    e_max = (systolic_bp_mmhg / (stroke_volume * 0.8)) * contractility_index
    e_max = max(0.5, e_max)

    v0 = esv_ml * 0.85

    volumes_ml: list[float] = []
    pressures_mmhg: list[float] = []

    for i in range(n_points):
        t_norm = i / n_points
        t_ms = t_norm * cycle_ms

        if t_ms < t_iso_vol_contract:
            v = edv_ml
            t_e = t_ms / t_sys_end
            en = _normalized_elastance_curve(t_e)
            p = edp_mmhg + en * e_max * (v - v0) * 0.3

        elif t_ms < t_sys_end - t_iso_vol_relax:
            ejection_frac = (t_ms - t_iso_vol_contract) / (
                t_sys_end - t_iso_vol_relax - t_iso_vol_contract
            )
            v = edv_ml - stroke_volume * math.sin(
                math.pi * ejection_frac / 2.0
            ) ** 2
            t_e = t_ms / t_sys_end
            en = _normalized_elastance_curve(t_e)
            p = en * e_max * (v - v0)
            p = max(diastolic_bp_mmhg, p)

        elif t_ms < t_sys_end:
            v = esv_ml
            t_e = t_ms / t_sys_end
            en = _normalized_elastance_curve(t_e)
            p = en * e_max * (v - v0) * 0.5 + diastolic_bp_mmhg * 0.5

        else:
            fill_frac = (t_ms - t_sys_end) / (cycle_ms - t_sys_end)
            v = esv_ml + stroke_volume * fill_frac
            relax_frac = min(1.0, (t_ms - t_sys_end) / (2.0 * t_iso_vol_relax))
            p = edp_mmhg * fill_frac + (1 - relax_frac) * diastolic_bp_mmhg * 0.2
            p = max(0.0, p)

        volumes_ml.append(round(float(v), 2))
        pressures_mmhg.append(round(float(p), 2))

    area = _compute_pv_loop_area(volumes_ml, pressures_mmhg)

    stroke_work_j = (area * 1e-6) * 133.322

    peak_p = max(pressures_mmhg)

    return PVLoopResult(
        volumes_ml=volumes_ml,
        pressures_mmhg=pressures_mmhg,
        pv_loop_area_mmhg_ml=round(area, 2),
        stroke_work_j=round(stroke_work_j, 6),
        edv_ml=edv_ml,
        esv_ml=esv_ml,
        ef_pct=round(ef_pct, 1),
        peak_pressure_mmhg=round(peak_p, 1),
        end_diastolic_pressure_mmhg=round(edp_mmhg, 1),
        contractility_index=contractility_index,
        warnings=warnings,
    )


def _compute_pv_loop_area(volumes: list[float], pressures: list[float]) -> float:
    """Compute enclosed PV loop area using the shoelace formula."""
    n = len(volumes)
    area = 0.0
    for i in range(n):
        j = (i + 1) % n
        area += volumes[i] * pressures[j]
        area -= volumes[j] * pressures[i]
    return abs(area) / 2.0


def compute_oxygen_demand_index(
    heart_rate_bpm: float,
    contractility_index: float,
    afterload_index: float,
    activity_mets: float = 1.0,
) -> float:
    """Simplified myocardial oxygen demand index (MVO2 proxy).

    Normalized composite: HR × contractility × afterload × activity.
    Deterministic. Range approximately 0.0–5.0 dimensionless.
    """
    hr_norm = heart_rate_bpm / 70.0
    raw = hr_norm * max(0.0, contractility_index) * max(0.0, afterload_index) * max(0.0, activity_mets)
    return round(min(5.0, max(0.0, raw)), 4)


def generate_pressure_volume_loop(
    edv_ml: float,
    esv_ml: float,
    heart_rate_bpm: float,
    systolic_bp_mmhg: float,
    diastolic_bp_mmhg: float,
    contractility_index: float = 1.0,
    afterload_index: float = 1.0,
    n_points: int = 200,
) -> dict:
    """Generate chart-ready PV loop arrays using the time-varying elastance model.

    Returns a dict suitable for direct frontend charting.  No LLM involvement.
    """
    result = simulate_pv_loop(
        edv_ml=edv_ml,
        esv_ml=esv_ml,
        heart_rate_bpm=heart_rate_bpm,
        systolic_bp_mmhg=systolic_bp_mmhg,
        diastolic_bp_mmhg=diastolic_bp_mmhg,
        contractility_index=contractility_index,
        afterload_index=afterload_index,
        n_points=n_points,
    )
    loop_area_index = round(result.pv_loop_area_mmhg_ml / 4000.0, 4)
    return {
        "volume_ml": result.volumes_ml,
        "pressure_mmhg": result.pressures_mmhg,
        "loop_area_index": loop_area_index,
        "pv_loop_area_mmhg_ml": result.pv_loop_area_mmhg_ml,
        "stroke_work_j": result.stroke_work_j,
        "ef_pct": result.ef_pct,
        "peak_pressure_mmhg": result.peak_pressure_mmhg,
        "end_diastolic_pressure_mmhg": result.end_diastolic_pressure_mmhg,
        "model": "simplified_time_varying_elastance",
        "simulation_label": "educational simulation",
        "warnings": result.warnings,
    }


def generate_cardiac_cycle(
    edv_ml: float,
    esv_ml: float,
    heart_rate_bpm: float,
    systolic_bp_mmhg: float,
    diastolic_bp_mmhg: float,
    contractility_index: float = 1.0,
    afterload_index: float = 1.0,
    time_step_ms: float = 5.0,
) -> dict:
    """Generate a cardiac cycle with time, volume, pressure, and phase label arrays.

    Returns a dict with chart-ready arrays.  Phase labels are simulation descriptors.
    """
    result = simulate_cardiac_cycle(
        edv_ml=edv_ml,
        esv_ml=esv_ml,
        heart_rate_bpm=heart_rate_bpm,
        systolic_bp_mmhg=systolic_bp_mmhg,
        diastolic_bp_mmhg=diastolic_bp_mmhg,
        contractility_index=contractility_index,
        afterload_index=afterload_index,
        time_step_ms=time_step_ms,
    )
    cycle_ms = result.cycle_duration_ms
    t_iso_c = cycle_ms * 0.07
    t_sys_end = cycle_ms * 0.40
    t_iso_r_end = t_sys_end + cycle_ms * 0.08

    phases: list[str] = []
    for t in result.time_ms:
        if t < t_iso_c:
            phases.append("isovolumetric_contraction")
        elif t < t_sys_end - cycle_ms * 0.08:
            phases.append("ejection")
        elif t < t_iso_r_end:
            phases.append("isovolumetric_relaxation")
        else:
            phases.append("filling")

    return {
        "time_ms": result.time_ms,
        "volume_ml": result.lv_volume_ml,
        "pressure_mmhg": result.lv_pressure_mmhg,
        "aortic_flow_ml_s": result.aortic_flow_ml_s,
        "phase": phases,
        "heart_rate_bpm": result.heart_rate_bpm,
        "cycle_duration_ms": result.cycle_duration_ms,
        "stroke_volume_ml": result.stroke_volume_ml,
        "cardiac_output_l_min": result.cardiac_output_l_min,
        "warnings": result.warnings,
    }


def generate_3d_visual_payload(
    heart_rate_bpm: float,
    contractility_index: float,
    afterload_index: float,
    preload_index: float,
    oxygen_delivery_index: float,
    inflammation_index: float,
    scar_fraction: float,
    beat_amplitude: float,
    electrical_wave_speed: float,
) -> dict:
    """Build 3D heart visualization payload for frontend rendering.

    All values are dimensionless indices clamped to frontend-safe ranges.
    Frontend mapping:
      HR           → beat speed (beat_interval_ms)
      contractility → beat amplitude
      afterload     → pressure field (stress_field_intensity)
      oxygen_delivery → blue particle density (blood_flow_particle_density)
      inflammation  → red glow (inflammation_index)
      scar_fraction → scar overlay
    """
    beat_interval_ms = round(60000.0 / max(heart_rate_bpm, 1.0), 1)
    blood_flow_particle_density = round(min(1.0, max(0.0, oxygen_delivery_index * 1.1)), 3)
    stress_field_intensity = round(
        min(1.0, max(0.0, afterload_index * 0.6 + inflammation_index * 0.4)), 3
    )
    return {
        "heart_rate_bpm": round(heart_rate_bpm, 1),
        "beat_interval_ms": beat_interval_ms,
        "beat_amplitude": round(min(1.5, max(0.1, beat_amplitude)), 3),
        "contractility_index": round(min(2.0, max(0.0, contractility_index)), 3),
        "afterload_index": round(min(3.0, max(0.0, afterload_index)), 3),
        "preload_index": round(min(3.0, max(0.0, preload_index)), 3),
        "oxygen_delivery_index": round(min(1.0, max(0.0, oxygen_delivery_index)), 3),
        "inflammation_index": round(min(1.0, max(0.0, inflammation_index)), 3),
        "scar_fraction": round(min(1.0, max(0.0, scar_fraction)), 3),
        "stress_field_intensity": stress_field_intensity,
        "blood_flow_particle_density": blood_flow_particle_density,
        "electrical_wave_speed": round(min(2.0, max(0.1, electrical_wave_speed)), 3),
        "simulation_label": "educational visualization",
    }


def simulate_cardiac_cycle(
    edv_ml: float,
    esv_ml: float,
    heart_rate_bpm: float,
    systolic_bp_mmhg: float,
    diastolic_bp_mmhg: float,
    contractility_index: float = 1.0,
    afterload_index: float = 1.0,
    time_step_ms: float = 5.0,
) -> CardiacCycleResult:
    """Simulate a full cardiac cycle with time-series outputs."""
    warnings: list[str] = []

    if esv_ml >= edv_ml:
        warnings.append("ESV >= EDV: clamped for simulation")
        esv_ml = edv_ml * 0.4

    cycle_ms = 60000.0 / heart_rate_bpm
    n_steps = max(50, int(cycle_ms / time_step_ms))

    time_ms: list[float] = []
    lv_volume: list[float] = []
    lv_pressure: list[float] = []
    aortic_flow: list[float] = []

    stroke_volume = edv_ml - esv_ml
    edp = 8.0 + (edv_ml - 130.0) * 0.05
    edp = max(2.0, min(edp, 30.0))

    t_sys_end = cycle_ms * 0.40
    t_iso_c = cycle_ms * 0.07
    t_iso_r = cycle_ms * 0.08
    e_max = (systolic_bp_mmhg / max(stroke_volume * 0.8, 1.0)) * contractility_index
    e_max = max(0.5, e_max)
    v0 = esv_ml * 0.85

    for i in range(n_steps):
        t = i * time_step_ms
        time_ms.append(round(t, 1))

        if t < t_iso_c:
            v = edv_ml
            p = edp + (t / t_iso_c) * (e_max * (edv_ml - v0) - edp)
            flow = 0.0
        elif t < t_sys_end - t_iso_r:
            ej = (t - t_iso_c) / (t_sys_end - t_iso_r - t_iso_c)
            v = edv_ml - stroke_volume * math.sin(math.pi * ej / 2.0) ** 2
            t_e = t / t_sys_end
            en = _normalized_elastance_curve(t_e)
            p = max(diastolic_bp_mmhg, en * e_max * (v - v0))
            prev_v = lv_volume[-1] if lv_volume else edv_ml
            flow = (prev_v - v) / (time_step_ms / 1000.0)
        elif t < t_sys_end:
            v = esv_ml
            relax = (t - (t_sys_end - t_iso_r)) / t_iso_r
            p = e_max * (1 - relax) * (esv_ml - v0) * 0.5 + diastolic_bp_mmhg
            flow = 0.0
        else:
            fill_frac = (t - t_sys_end) / (cycle_ms - t_sys_end)
            v = esv_ml + stroke_volume * fill_frac
            p = max(0.0, edp * fill_frac)
            flow = 0.0

        lv_volume.append(round(float(v), 2))
        lv_pressure.append(round(float(p), 2))
        aortic_flow.append(round(max(0.0, float(flow)), 2))

    pv_loop = simulate_pv_loop(
        edv_ml=edv_ml,
        esv_ml=esv_ml,
        heart_rate_bpm=heart_rate_bpm,
        systolic_bp_mmhg=systolic_bp_mmhg,
        diastolic_bp_mmhg=diastolic_bp_mmhg,
        contractility_index=contractility_index,
        afterload_index=afterload_index,
    )

    co = (heart_rate_bpm * stroke_volume) / 1000.0

    return CardiacCycleResult(
        time_ms=time_ms,
        lv_volume_ml=lv_volume,
        lv_pressure_mmhg=lv_pressure,
        aortic_flow_ml_s=aortic_flow,
        heart_rate_bpm=heart_rate_bpm,
        cycle_duration_ms=round(cycle_ms, 1),
        stroke_volume_ml=round(stroke_volume, 1),
        cardiac_output_l_min=round(co, 2),
        pv_loop=pv_loop,
        warnings=warnings,
    )
