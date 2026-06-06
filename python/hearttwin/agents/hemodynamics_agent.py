"""Agent 6: Hemodynamics Simulation Agent.

Simulates heart operation using deterministic tools.
Never calls LLM for numeric simulation.
Rejects impossible physiology.
"""

from __future__ import annotations

import time
from typing import Any

from python.hearttwin.schemas import (
    AgentResponse,
    AgentStatus,
    CardiacTwinState,
    Hemodynamics,
    MeasuredValue,
    OperatingMode,
    ValueSource,
)
from python.hearttwin.tools.cardiac_state import (
    compute_afterload_index,
    compute_arterial_compliance_index,
    compute_cardiac_output,
    compute_contractility_index,
    compute_filling_pressure_index,
    compute_map,
    compute_preload_index,
    compute_svr_index,
)
from python.hearttwin.tools.hemodynamics import simulate_cardiac_cycle, simulate_pv_loop
from python.hearttwin.tools.weave_trace import TraceContext


def _mv(val: float, unit: str, source: ValueSource = ValueSource.DERIVED, conf: float = 0.90) -> MeasuredValue:
    return MeasuredValue(value=val, unit=unit, source=source, confidence=conf)


async def run_hemodynamics_agent(
    state: CardiacTwinState,
    case_id: str,
) -> tuple[AgentResponse, Hemodynamics, dict[str, Any]]:
    """Simulate cardiac hemodynamics. Returns updated Hemodynamics and viz payload."""
    tracer = TraceContext(case_id=case_id, agent_name="hemodynamics_agent")
    t0 = time.time()
    warnings: list[str] = []

    meas = state.measurements

    def get_val(mv: MeasuredValue | None, fallback: float) -> float:
        return mv.value if mv is not None else fallback

    edv = get_val(meas.edv_ml, 130.0)
    esv = get_val(meas.esv_ml, 50.0)
    hr = get_val(meas.heart_rate_bpm, 70.0)
    sbp = get_val(meas.systolic_bp_mmhg, 120.0)
    dbp = get_val(meas.diastolic_bp_mmhg, 80.0)

    if esv >= edv:
        warnings.append(f"ESV ({esv}) >= EDV ({edv}): simulation will clamp ESV")
        esv = edv * 0.4

    if dbp >= sbp:
        warnings.append(f"Diastolic ({dbp}) >= Systolic ({sbp}): clamping diastolic")
        dbp = sbp * 0.65

    env = state.simulation_config.operating
    mode = env.mode

    hr_mod = hr
    sbp_mod = sbp
    if mode == OperatingMode.MILD_ACTIVITY:
        hr_mod = min(hr * 1.2, 180.0)
        sbp_mod = min(sbp * 1.1, 200.0)
    elif mode == OperatingMode.STRESS:
        hr_mod = min(hr * 1.5, 220.0)
        sbp_mod = min(sbp * 1.2, 220.0)
    elif mode == OperatingMode.RECOVERY:
        hr_mod = max(hr * 0.9, 40.0)

    contractility_mod = 1.0
    ts = state.tissue_state
    if ts.scar_fraction:
        contractility_mod *= max(0.3, 1.0 - ts.scar_fraction.value * 1.5)
    if ts.inflammation_index:
        contractility_mod *= max(0.5, 1.0 - ts.inflammation_index.value * 0.3)

    afterload_env = 1.0
    if env.stress_catecholamine_index > 1.0:
        afterload_env = 1.0 + (env.stress_catecholamine_index - 1.0) * 0.2

    cycle = simulate_cardiac_cycle(
        edv_ml=edv,
        esv_ml=esv,
        heart_rate_bpm=hr_mod,
        systolic_bp_mmhg=sbp_mod,
        diastolic_bp_mmhg=dbp,
        contractility_index=contractility_mod,
        afterload_index=afterload_env,
        time_step_ms=env.time_step_ms,
    )
    warnings.extend(cycle.warnings)

    tracer.record_tool(
        "simulate_cardiac_cycle",
        inputs={"edv": edv, "esv": esv, "hr": hr_mod, "sbp": sbp_mod, "dbp": dbp},
        outputs={
            "sv": cycle.stroke_volume_ml,
            "co": cycle.cardiac_output_l_min,
            "ef": cycle.pv_loop.ef_pct,
            "pv_area": cycle.pv_loop.pv_loop_area_mmhg_ml,
        },
        duration_ms=(time.time() - t0) * 1000,
    )

    tracer.record_tool(
        "generate_pressure_volume_loop",
        inputs={
            "edv_ml": edv,
            "esv_ml": esv,
            "heart_rate_bpm": hr_mod,
            "systolic_bp_mmhg": sbp_mod,
            "diastolic_bp_mmhg": dbp,
        },
        outputs={
            "point_count": len(cycle.pv_loop.volumes_ml),
            "pv_loop_area_mmhg_ml": cycle.pv_loop.pv_loop_area_mmhg_ml,
            "peak_pressure_mmhg": cycle.pv_loop.peak_pressure_mmhg,
        },
        duration_ms=1.0,
    )

    formula_t0 = time.time()
    map_val = compute_map(sbp_mod, dbp)
    tracer.record_tool(
        "compute_map",
        inputs={"systolic_bp_mmhg": sbp_mod, "diastolic_bp_mmhg": dbp},
        outputs={"map_mmhg": map_val},
        duration_ms=(time.time() - formula_t0) * 1000,
    )
    preload = compute_preload_index(edv)
    afterload = compute_afterload_index(map_val, cycle.cardiac_output_l_min)
    svr = compute_svr_index(map_val, cycle.cardiac_output_l_min)
    contractility = compute_contractility_index(cycle.pv_loop.ef_pct, afterload)
    pulse_pressure = sbp_mod - dbp
    compliance = compute_arterial_compliance_index(cycle.stroke_volume_ml, max(pulse_pressure, 1.0))
    stiffness_val = ts.stiffness_index.value if ts.stiffness_index else 0.3
    filling_press = compute_filling_pressure_index(edv, stiffness_val)
    pv_area_norm = cycle.pv_loop.pv_loop_area_mmhg_ml / 4000.0

    hd = Hemodynamics(
        preload_index=_mv(round(preload, 4), "index"),
        afterload_index=_mv(round(afterload, 4), "index"),
        contractility_index=_mv(round(contractility, 4), "index"),
        arterial_compliance_index=_mv(round(compliance, 4), "index"),
        systemic_vascular_resistance_index=_mv(round(svr, 4), "index"),
        filling_pressure_index=_mv(round(filling_press, 4), "index"),
        pv_loop_area_index=_mv(round(pv_area_norm, 4), "index"),
    )

    visualization_payload = {
        "cardiac_cycle": {
            "time_ms": cycle.time_ms,
            "lv_volume_ml": cycle.lv_volume_ml,
            "lv_pressure_mmhg": cycle.lv_pressure_mmhg,
            "aortic_flow_ml_s": cycle.aortic_flow_ml_s,
            "heart_rate_bpm": cycle.heart_rate_bpm,
            "cycle_duration_ms": cycle.cycle_duration_ms,
        },
        "pv_loop": {
            "volumes_ml": cycle.pv_loop.volumes_ml,
            "pressures_mmhg": cycle.pv_loop.pressures_mmhg,
            "pv_loop_area_mmhg_ml": cycle.pv_loop.pv_loop_area_mmhg_ml,
            "stroke_work_j": cycle.pv_loop.stroke_work_j,
            "peak_pressure_mmhg": cycle.pv_loop.peak_pressure_mmhg,
            "edp_mmhg": cycle.pv_loop.end_diastolic_pressure_mmhg,
        },
        "summary": {
            "edv_ml": edv,
            "esv_ml": esv,
            "stroke_volume_ml": cycle.stroke_volume_ml,
            "ef_pct": cycle.pv_loop.ef_pct,
            "cardiac_output_l_min": cycle.cardiac_output_l_min,
            "heart_rate_bpm": cycle.heart_rate_bpm,
            "map_mmhg": round(map_val, 1),
            "operating_mode": mode.value,
        },
        "hemodynamics": {
            "preload_index": round(preload, 4),
            "afterload_index": round(afterload, 4),
            "contractility_index": round(contractility, 4),
            "svr_index": round(svr, 4),
            "compliance_index": round(compliance, 4),
            "filling_pressure_index": round(filling_press, 4),
        },
        "simulation_note": (
            "All hemodynamic values are simulated estimates using deterministic mathematical models. "
            "Not for clinical interpretation."
        ),
    }

    return AgentResponse(
        agent="hemodynamics_agent",
        status=AgentStatus.SUCCESS if not warnings else AgentStatus.WARNING,
        inputs_used=["cardiac_twin_state", "operating_environment"],
        outputs={
            "ef_pct": cycle.pv_loop.ef_pct,
            "stroke_volume_ml": cycle.stroke_volume_ml,
            "cardiac_output_l_min": cycle.cardiac_output_l_min,
            "pv_loop_area": cycle.pv_loop.pv_loop_area_mmhg_ml,
            "operating_mode": mode.value,
        },
        warnings=warnings,
        confidence=0.85,
        trace=tracer.steps,
    ), hd, visualization_payload
