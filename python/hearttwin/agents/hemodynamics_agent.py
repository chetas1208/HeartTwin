"""Agent 6: Hemodynamics Simulation Agent.

Operates the HeartTwin: computes cardiac operation metrics, pressure-volume loops,
cardiac cycle arrays, environment effects, and 3D visualization payloads.

Rules:
- OPENAI_MODEL_HEMODYNAMICS configures the model (fallback: gpt-5.4-mini).
- LLM only produces a plain-language narrative summary of deterministic results.
- All numeric simulation uses deterministic Python tools — never the LLM.
- Missing required fields are handled safely per the missing-value policy.
- Impossible physiology (ESV >= EDV, DBP >= SBP) is clamped with a warning.
- Outputs are simulation-only educational estimates, never clinical advice.
"""

from __future__ import annotations

import json
import os
import time
from typing import Any, Optional

from pydantic import BaseModel

from python.hearttwin.safety import CORE_SAFETY_PHRASE, enforce_simulation_language
from python.hearttwin.schemas import (
    AgentResponse,
    AgentStatus,
    CardiacTwinState,
    Hemodynamics,
    MeasuredValue,
    MissingValuePolicy,
    OperatingMode,
    ValueSource,
)
from python.hearttwin.tools.cardiac_state import (
    compute_afterload_index,
    compute_arterial_compliance_index,
    compute_cardiac_output,
    compute_contractility_index,
    compute_ejection_fraction,
    compute_filling_pressure_index,
    compute_map,
    compute_preload_index,
    compute_stroke_volume,
    compute_svr_index,
)
from python.hearttwin.tools.hemodynamics import (
    compute_oxygen_demand_index,
    generate_3d_visual_payload,
    generate_cardiac_cycle,
    generate_pressure_volume_loop,
)
from python.hearttwin.tools.model_config import get_hemodynamics_model
from python.hearttwin.tools.weave_trace import TraceContext, get_trace_sink

# ---------------------------------------------------------------------------
# Agent-scoped input / output schemas
# ---------------------------------------------------------------------------

AGENT_ID = "hemodynamics_simulation"
AGENT_NAME = "Hemodynamics Simulation Agent"


class HemodynamicsInput(BaseModel):
    case_id: str
    cardiac_state: CardiacTwinState
    electrophysiology: Optional[Any] = None
    operating_environment: dict


class HemodynamicsOutput(BaseModel):
    operation_metrics: dict
    cardiac_cycle: dict
    pressure_volume_loop: dict
    visualization_payload: dict
    environment_effects: dict
    warnings: list[str]
    confidence: float


# ---------------------------------------------------------------------------
# Operating environment parameter bounds
# ---------------------------------------------------------------------------

_ENV_BOUNDS: dict[str, tuple[float, float]] = {
    "activity_level_mets": (0.0, 20.0),
    "hydration_index": (0.0, 2.0),
    "sleep_recovery_index": (0.0, 2.0),
    "stress_catecholamine_index": (0.0, 5.0),
    "ambient_temperature_c": (-10.0, 50.0),
    "altitude_m": (0.0, 5500.0),
    "oxygen_fraction": (0.10, 0.30),
    "simulation_duration_seconds": (1.0, 3600.0),
    "time_step_ms": (0.1, 100.0),
}


def _bound_env(env: Any) -> tuple[dict, list[str]]:
    """Read and clamp all numeric environment parameters. Returns (bounded_dict, warnings)."""
    raw = {
        "mode": env.mode.value if hasattr(env.mode, "value") else str(env.mode),
        "simulation_duration_seconds": float(env.simulation_duration_seconds),
        "time_step_ms": float(env.time_step_ms),
        "activity_level_mets": float(env.activity_level_mets),
        "hydration_index": float(env.hydration_index),
        "sleep_recovery_index": float(env.sleep_recovery_index),
        "stress_catecholamine_index": float(env.stress_catecholamine_index),
        "ambient_temperature_c": float(env.ambient_temperature_c),
        "altitude_m": float(env.altitude_m),
        "oxygen_fraction": float(env.oxygen_fraction),
        "medication_effect_profile": dict(env.medication_effect_profile or {}),
        "data_uncertainty_policy": env.data_uncertainty_policy.value
        if hasattr(env.data_uncertainty_policy, "value")
        else str(env.data_uncertainty_policy),
        "missing_value_policy": env.missing_value_policy.value
        if hasattr(env.missing_value_policy, "value")
        else str(env.missing_value_policy),
    }
    warns: list[str] = []
    for key, (lo, hi) in _ENV_BOUNDS.items():
        val = raw.get(key)
        if val is not None and isinstance(val, (int, float)):
            if val < lo or val > hi:
                warns.append(
                    f"Operating environment '{key}'={val} out of bounds [{lo}, {hi}]; clamped."
                )
                raw[key] = max(lo, min(hi, float(val)))
    return raw, warns


# ---------------------------------------------------------------------------
# Environment effect modifiers
# ---------------------------------------------------------------------------

def _compute_environment_effects(env_bounded: dict) -> dict:
    """Derive normalized physiological modifier values from bounded environment params."""
    activity = float(env_bounded.get("activity_level_mets", 1.0))
    hydration = float(env_bounded.get("hydration_index", 1.0))
    sleep = float(env_bounded.get("sleep_recovery_index", 1.0))
    stress = float(env_bounded.get("stress_catecholamine_index", 1.0))
    temp = float(env_bounded.get("ambient_temperature_c", 22.0))
    altitude = float(env_bounded.get("altitude_m", 0.0))
    o2_frac = float(env_bounded.get("oxygen_fraction", 0.21))
    med = dict(env_bounded.get("medication_effect_profile") or {})

    # Activity: each MET above rest raises HR ~8%
    hr_activity = 1.0 + max(0.0, activity - 1.0) * 0.08
    # Stress catecholamines: afterload and HR
    hr_stress = 1.0 + max(0.0, stress - 1.0) * 0.10
    afterload_stress = 1.0 + max(0.0, stress - 1.0) * 0.15
    # Temperature deviation from 22 °C: up to +20% HR at extremes
    hr_temp = 1.0 + min(abs(temp - 22.0) * 0.007, 0.20)
    # Hydration: affects preload (EDV filling)
    preload_hydration = max(0.7, min(1.3, 0.7 + 0.3 * min(hydration, 2.0)))
    # Sleep recovery: reduced contractility when sleep_recovery_index < 1
    contractility_sleep = max(0.8, min(1.0, 0.8 + 0.2 * min(sleep, 1.0)))
    # Altitude: 5.5% O2 delivery drop per 1000 m
    o2_altitude = max(0.70, 1.0 - altitude * 0.000055)
    # O2 fraction relative to sea-level normal
    o2_frac_mod = o2_frac / 0.21

    # Medication multipliers (default 1.0 if absent)
    hr_med = float(med.get("heart_rate_multiplier", 1.0))
    contractility_med = float(med.get("contractility_multiplier", 1.0))
    afterload_med = float(med.get("afterload_multiplier", 1.0))

    hr_mod = hr_activity * hr_stress * hr_temp * hr_med
    afterload_mod = afterload_stress * afterload_med
    contractility_mod = contractility_sleep * contractility_med
    o2_delivery_mod = o2_altitude * o2_frac_mod
    preload_mod = preload_hydration

    return {
        "hr_modifier": round(hr_mod, 4),
        "afterload_modifier": round(afterload_mod, 4),
        "contractility_modifier": round(contractility_mod, 4),
        "preload_modifier": round(preload_mod, 4),
        "o2_delivery_modifier": round(o2_delivery_mod, 4),
        "activity_level_mets": activity,
        "hydration_index": hydration,
        "sleep_recovery_index": sleep,
        "stress_catecholamine_index": stress,
        "ambient_temperature_c": temp,
        "altitude_m": altitude,
        "oxygen_fraction": o2_frac,
        "medication_effects_applied": bool(med),
    }


# ---------------------------------------------------------------------------
# Field extraction helpers
# ---------------------------------------------------------------------------

def _get_mv(mv: Optional[MeasuredValue], fallback: float) -> tuple[float, bool, float]:
    """Return (value, is_prior, source_confidence). is_prior=True when mv is None or a model prior."""
    if mv is None:
        return fallback, True, 0.0
    is_prior = mv.source == ValueSource.DEFAULT_MODEL_PRIOR
    return mv.value, is_prior, mv.confidence


# ---------------------------------------------------------------------------
# Confidence scoring
# ---------------------------------------------------------------------------

def _compute_confidence(
    state: CardiacTwinState,
    field_presence: dict[str, bool],
    priors_used: list[str],
    clamped_fields: list[str],
    impossible_states: list[str],
    viz_ready: bool,
) -> float:
    """Weighted confidence score clamped to [0.0, 1.0]."""
    base = state.data_quality_score

    required = ["edv_ml", "esv_ml", "heart_rate_bpm", "systolic_bp_mmhg", "diastolic_bp_mmhg"]
    n_present = sum(1 for f in required if field_presence.get(f, False))
    presence_bonus = (n_present / len(required)) * 0.20

    src_confs = [e.confidence for e in state.source_map if e.field in required]
    avg_src = (sum(src_confs) / len(src_confs)) if src_confs else 0.5
    source_bonus = avg_src * 0.20

    prior_penalty = min(0.30, len(priors_used) * 0.06)
    impossible_penalty = min(0.25, len(impossible_states) * 0.10)
    clamp_penalty = min(0.10, len(clamped_fields) * 0.03)
    viz_bonus = 0.05 if viz_ready else 0.0

    score = base + presence_bonus + source_bonus - prior_penalty - impossible_penalty - clamp_penalty + viz_bonus
    return round(max(0.0, min(1.0, score)), 3)


# ---------------------------------------------------------------------------
# Redis state write
# ---------------------------------------------------------------------------

async def _write_redis_operation(case_id: str, payload: dict) -> bool:
    """Write operation data to hearttwin:case:{case_id}:operation. Best-effort."""
    from python.hearttwin.tools.env_config import redis_memory_enabled

    if not redis_memory_enabled():
        return False
    url = os.environ.get("UPSTASH_REDIS_REST_URL", "")
    token = os.environ.get("UPSTASH_REDIS_REST_TOKEN", "")
    if not (url and token):
        return False
    key = f"hearttwin:case:{case_id}:operation"
    try:
        import httpx

        async with httpx.AsyncClient() as client:
            resp = await client.post(
                f"{url}/set/{key}",
                headers={"Authorization": f"Bearer {token}", "Content-Type": "text/plain"},
                content=json.dumps(payload),
                timeout=10.0,
            )
        return resp.status_code < 300
    except Exception:
        return False


# ---------------------------------------------------------------------------
# LLM operation summary (text-only; never touches numerics)
# ---------------------------------------------------------------------------

async def _generate_operation_summary(
    model: str,
    operation_metrics: dict,
    env_mode: str,
    agent_warnings: list[str],
) -> str:
    """Ask the LLM to narrate pre-computed simulation metrics.

    Returns a safety-checked plain-language summary. Falls back to a
    static template when OPENAI_API_KEY is absent or the call fails.
    """
    fallback = (
        f"Educational cardiac simulation only. Not for diagnosis or treatment decisions. "
        f"Hemodynamics simulated in {env_mode} mode. "
        f"EF: {operation_metrics.get('ejection_fraction_pct', 'N/A')}%, "
        f"CO: {operation_metrics.get('cardiac_output_l_min', 'N/A')} L/min, "
        f"SV: {operation_metrics.get('stroke_volume_ml', 'N/A')} mL."
    )

    if not os.environ.get("OPENAI_API_KEY"):
        return fallback

    try:
        import openai

        client = openai.AsyncOpenAI(api_key=os.environ["OPENAI_API_KEY"])
        metrics_text = (
            f"EF={operation_metrics.get('ejection_fraction_pct')}%, "
            f"SV={operation_metrics.get('stroke_volume_ml')} mL, "
            f"CO={operation_metrics.get('cardiac_output_l_min')} L/min, "
            f"MAP={operation_metrics.get('map_mmhg')} mmHg, "
            f"mode={env_mode}"
        )
        prompt = (
            "You are narrating deterministic cardiac simulation results for an educational tool. "
            "Do NOT provide medical advice, diagnosis, or treatment information. "
            "Summarize the following computed simulation metrics in 1-2 sentences. "
            "Begin with: 'Educational cardiac simulation only. Not for diagnosis or treatment decisions.' "
            f"Metrics: {metrics_text}"
        )
        response = await client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": prompt}],
            max_tokens=120,
            temperature=0.0,
        )
        raw = (response.choices[0].message.content or "").strip()
        return enforce_simulation_language(raw) or fallback
    except Exception:
        return fallback


# ---------------------------------------------------------------------------
# Main agent entry point
# ---------------------------------------------------------------------------

async def run_hemodynamics_agent(
    state: CardiacTwinState,
    case_id: str,
) -> tuple[AgentResponse, Hemodynamics, dict[str, Any]]:
    """Simulate cardiac hemodynamics deterministically.

    Returns:
        (AgentResponse, updated Hemodynamics schema, visualization_payload dict)
    """
    tracer = TraceContext(case_id=case_id, agent_name=AGENT_NAME)
    sink = get_trace_sink()
    run_id = sink.start_run(
        case_id=case_id,
        run_type="hearttwin.simulate_hemodynamics",
        metadata={"agent_id": AGENT_ID, "agent_name": AGENT_NAME},
    )
    t0 = time.time()
    warnings: list[str] = []
    priors_used: list[str] = []
    clamped_fields: list[str] = []
    impossible_states: list[str] = []

    model = get_hemodynamics_model()

    # ------------------------------------------------------------------
    # 1. Bound operating environment
    # ------------------------------------------------------------------
    env = state.simulation_config.operating
    env_bounded, env_warns = _bound_env(env)
    warnings.extend(env_warns)
    for w in env_warns:
        parts = w.split("'")
        if len(parts) >= 2:
            clamped_fields.append(parts[1])

    env_effects = _compute_environment_effects(env_bounded)

    # ------------------------------------------------------------------
    # 2. Extract cardiac state fields
    # ------------------------------------------------------------------
    meas = state.measurements
    ts = state.tissue_state
    ep_state = state.electrophysiology
    field_presence: dict[str, bool] = {}

    edv, edv_prior, _ = _get_mv(meas.edv_ml, 130.0)
    field_presence["edv_ml"] = meas.edv_ml is not None
    if edv_prior and meas.edv_ml is None:
        priors_used.append("edv_ml")
        warnings.append("EDV unavailable — using population prior (130 mL); uncertainty elevated.")

    esv, esv_prior, _ = _get_mv(meas.esv_ml, 50.0)
    field_presence["esv_ml"] = meas.esv_ml is not None
    if esv_prior and meas.esv_ml is None:
        priors_used.append("esv_ml")
        warnings.append("ESV unavailable — using population prior (50 mL); uncertainty elevated.")

    hr, hr_prior, _ = _get_mv(meas.heart_rate_bpm, 70.0)
    field_presence["heart_rate_bpm"] = meas.heart_rate_bpm is not None
    if hr_prior and meas.heart_rate_bpm is None:
        priors_used.append("heart_rate_bpm")
        warnings.append("Heart rate unavailable — using prior (70 bpm).")

    sbp, sbp_prior, _ = _get_mv(meas.systolic_bp_mmhg, 120.0)
    field_presence["systolic_bp_mmhg"] = meas.systolic_bp_mmhg is not None
    if sbp_prior and meas.systolic_bp_mmhg is None:
        priors_used.append("systolic_bp_mmhg")
        warnings.append("Systolic BP unavailable — using prior (120 mmHg).")

    dbp, dbp_prior, _ = _get_mv(meas.diastolic_bp_mmhg, 80.0)
    field_presence["diastolic_bp_mmhg"] = meas.diastolic_bp_mmhg is not None
    if dbp_prior and meas.diastolic_bp_mmhg is None:
        priors_used.append("diastolic_bp_mmhg")
        warnings.append("Diastolic BP unavailable — using prior (80 mmHg).")

    scar_frac, _, _ = _get_mv(ts.scar_fraction, 0.0)
    inflammation, _, _ = _get_mv(ts.inflammation_index, 0.0)
    o2_delivery, _, _ = _get_mv(ts.oxygen_delivery_index, 0.85)
    stiffness, _, _ = _get_mv(ts.stiffness_index, 0.3)

    # ------------------------------------------------------------------
    # 3. Missing-value policy gate
    # ------------------------------------------------------------------
    missing_policy = env.missing_value_policy
    if missing_policy == MissingValuePolicy.REFUSE and priors_used:
        reason = (
            f"Missing required fields {priors_used}. "
            f"Operating environment missing_value_policy=refuse — simulation blocked."
        )
        blocked_viz: dict[str, Any] = {
            "blocked": True,
            "reason": reason,
            "simulation_label": "blocked — required fields missing",
        }
        sink.finish_run(run_id, "failed", {"reason": reason})
        return (
            AgentResponse(
                agent="hemodynamics_agent",
                status=AgentStatus.FAILED,
                inputs_used=[],
                outputs={"agent_id": AGENT_ID, "agent_name": AGENT_NAME, "blocked": True, "reason": reason},
                warnings=[reason],
                confidence=0.0,
                trace=tracer.steps,
            ),
            Hemodynamics(),
            blocked_viz,
        )

    # ------------------------------------------------------------------
    # 4. Impossible physiology checks and clamping
    # ------------------------------------------------------------------
    if esv >= edv:
        msg = f"Impossible: ESV ({esv:.1f} mL) >= EDV ({edv:.1f} mL). Clamped ESV to 40% of EDV."
        warnings.append(msg)
        impossible_states.append(msg)
        esv = edv * 0.4
        clamped_fields.append("esv_ml")

    if dbp >= sbp:
        msg = f"Impossible: Diastolic BP ({dbp:.0f}) >= Systolic BP ({sbp:.0f}). Clamped diastolic."
        warnings.append(msg)
        impossible_states.append(msg)
        dbp = sbp * 0.65
        clamped_fields.append("diastolic_bp_mmhg")

    if hr <= 0 or hr > 300:
        msg = f"Heart rate {hr:.0f} bpm outside plausible range (0–300). Clamped to 70 bpm."
        warnings.append(msg)
        impossible_states.append(msg)
        hr = 70.0
        clamped_fields.append("heart_rate_bpm")

    # ------------------------------------------------------------------
    # 5. Apply tissue and environment modifiers
    # ------------------------------------------------------------------
    # Tissue-derived contractility reduction (scar and inflammation)
    contractility_tissue = max(0.3, 1.0 - scar_frac * 1.5)
    contractility_tissue *= max(0.5, 1.0 - inflammation * 0.3)

    # Environment-derived modifiers applied on top of tissue
    contractility_env_mod = contractility_tissue * env_effects["contractility_modifier"]
    contractility_env_mod = max(0.1, min(2.0, contractility_env_mod))

    afterload_env_mod = max(0.1, min(3.0, env_effects["afterload_modifier"]))

    hr_mod = hr * env_effects["hr_modifier"]
    hr_mod = max(30.0, min(220.0, hr_mod))

    # Mode-level overrides
    mode = env.mode
    if mode == OperatingMode.MILD_ACTIVITY:
        hr_mod = min(hr_mod * 1.2, 180.0)
        sbp = min(sbp * 1.1, 200.0)
    elif mode == OperatingMode.STRESS:
        hr_mod = min(hr_mod * 1.5, 220.0)
        sbp = min(sbp * 1.2, 220.0)
    elif mode == OperatingMode.RECOVERY:
        hr_mod = max(hr_mod * 0.9, 40.0)

    # ------------------------------------------------------------------
    # 6. Deterministic formula tools
    # ------------------------------------------------------------------
    t_tools = time.time()

    sv = compute_stroke_volume(edv, esv)
    sink.log_tool_call(
        run_id, "hearttwin.compute_stroke_volume",
        inputs={"edv_ml": edv, "esv_ml": esv},
        outputs={"stroke_volume_ml": round(sv, 1)},
    )

    ef = compute_ejection_fraction(edv, esv)
    sink.log_tool_call(
        run_id, "hearttwin.compute_ejection_fraction",
        inputs={"edv_ml": edv, "esv_ml": esv},
        outputs={"ejection_fraction_pct": round(ef, 1)},
    )

    co = compute_cardiac_output(hr_mod, sv)
    sink.log_tool_call(
        run_id, "hearttwin.compute_cardiac_output",
        inputs={"heart_rate_bpm": round(hr_mod, 1), "stroke_volume_ml": round(sv, 1)},
        outputs={"cardiac_output_l_min": round(co, 2)},
    )

    map_val = compute_map(sbp, dbp)
    sink.log_tool_call(
        run_id, "hearttwin.compute_map",
        inputs={"systolic_bp_mmhg": round(sbp, 1), "diastolic_bp_mmhg": round(dbp, 1)},
        outputs={"map_mmhg": round(map_val, 1)},
    )

    preload = compute_preload_index(edv) * env_effects["preload_modifier"]
    preload = min(3.0, max(0.0, preload))

    afterload = compute_afterload_index(map_val, co) * afterload_env_mod
    afterload = min(3.0, max(0.0, afterload))

    svr = compute_svr_index(map_val, co)

    contractility = compute_contractility_index(ef, afterload) * contractility_env_mod
    contractility = min(2.0, max(0.0, contractility))

    pulse_pressure = max(sbp - dbp, 1.0)
    compliance = compute_arterial_compliance_index(sv, pulse_pressure)

    filling_press = compute_filling_pressure_index(edv, stiffness)

    activity_mets = float(env_bounded.get("activity_level_mets", 1.0))
    o2_demand = compute_oxygen_demand_index(hr_mod, contractility, afterload, activity_mets)

    tracer.record_tool(
        "compute_hemodynamics_indices",
        inputs={"edv_ml": edv, "esv_ml": esv, "hr_bpm": hr_mod, "sbp": sbp, "dbp": dbp},
        outputs={
            "sv_ml": round(sv, 1), "ef_pct": round(ef, 1), "co_l_min": round(co, 2),
            "map_mmhg": round(map_val, 1), "preload": round(preload, 4),
            "afterload": round(afterload, 4), "contractility": round(contractility, 4),
            "o2_demand": round(o2_demand, 4),
        },
        duration_ms=(time.time() - t_tools) * 1000,
    )

    # ------------------------------------------------------------------
    # 7. Pressure-volume loop
    # ------------------------------------------------------------------
    t_pv = time.time()
    pv_dict = generate_pressure_volume_loop(
        edv_ml=edv,
        esv_ml=esv,
        heart_rate_bpm=hr_mod,
        systolic_bp_mmhg=sbp,
        diastolic_bp_mmhg=dbp,
        contractility_index=contractility_env_mod,
        afterload_index=afterload_env_mod,
    )
    warnings.extend(pv_dict.get("warnings", []))
    pv_area_index = pv_dict["loop_area_index"]

    pv_warnings = [
        "Simplified time-varying elastance model — not a calibrated clinical PV loop",
        "Educational simulation only — results are not for clinical use",
    ]
    if priors_used:
        pv_warnings.append("Uncertainty elevated: one or more input values are population priors")

    sink.log_tool_call(
        run_id, "hearttwin.generate_pressure_volume_loop",
        inputs={"edv_ml": edv, "esv_ml": esv, "hr_bpm": round(hr_mod, 1)},
        outputs={
            "point_count": len(pv_dict["volume_ml"]),
            "loop_area_index": pv_area_index,
            "pv_loop_area_mmhg_ml": pv_dict["pv_loop_area_mmhg_ml"],
        },
    )
    tracer.record_tool(
        "generate_pressure_volume_loop",
        inputs={"edv_ml": edv, "esv_ml": esv},
        outputs={"point_count": len(pv_dict["volume_ml"]), "loop_area_index": pv_area_index},
        duration_ms=(time.time() - t_pv) * 1000,
    )

    # ------------------------------------------------------------------
    # 8. Cardiac cycle
    # ------------------------------------------------------------------
    t_cc = time.time()
    cc_dict = generate_cardiac_cycle(
        edv_ml=edv,
        esv_ml=esv,
        heart_rate_bpm=hr_mod,
        systolic_bp_mmhg=sbp,
        diastolic_bp_mmhg=dbp,
        contractility_index=contractility_env_mod,
        afterload_index=afterload_env_mod,
        time_step_ms=float(env_bounded.get("time_step_ms", 5.0)),
    )
    warnings.extend(cc_dict.get("warnings", []))

    tracer.record_tool(
        "generate_cardiac_cycle",
        inputs={"hr_bpm": round(hr_mod, 1), "time_step_ms": env_bounded.get("time_step_ms", 5.0)},
        outputs={"point_count": len(cc_dict["time_ms"]), "sv_ml": cc_dict["stroke_volume_ml"]},
        duration_ms=(time.time() - t_cc) * 1000,
    )

    # ------------------------------------------------------------------
    # 9. 3D visualization payload
    # ------------------------------------------------------------------
    o2_combined = min(1.0, max(0.0, o2_delivery * env_effects["o2_delivery_modifier"]))
    beat_amplitude = min(1.5, max(0.1, contractility_env_mod * (sv / 80.0)))

    rr_ms = 60000.0 / max(hr_mod, 1.0)
    if ep_state.rr_interval_ms:
        rr_ms = ep_state.rr_interval_ms.value
    qrs_dur = ep_state.qrs_duration_ms.value if ep_state.qrs_duration_ms else 95.0
    electrical_wave_speed = min(2.0, max(0.2, 1.0 / max(qrs_dur / 95.0, 0.1)))

    viz_payload_3d = generate_3d_visual_payload(
        heart_rate_bpm=hr_mod,
        contractility_index=contractility,
        afterload_index=afterload,
        preload_index=preload,
        oxygen_delivery_index=o2_combined,
        inflammation_index=inflammation,
        scar_fraction=scar_frac,
        beat_amplitude=beat_amplitude,
        electrical_wave_speed=electrical_wave_speed,
    )

    viz_ready = len(pv_dict["volume_ml"]) > 0 and len(cc_dict["time_ms"]) > 0

    # ------------------------------------------------------------------
    # 10. Confidence scoring
    # ------------------------------------------------------------------
    confidence = _compute_confidence(
        state=state,
        field_presence=field_presence,
        priors_used=priors_used,
        clamped_fields=clamped_fields,
        impossible_states=impossible_states,
        viz_ready=viz_ready,
    )

    # ------------------------------------------------------------------
    # 11. Structured operation metrics
    # ------------------------------------------------------------------
    operation_metrics = {
        "stroke_volume_ml": round(sv, 1),
        "ef_pct": round(ef, 1),
        "ejection_fraction_pct": round(ef, 1),  # alias kept for completeness
        "cardiac_output_l_min": round(co, 2),
        "heart_rate_bpm": round(hr_mod, 1),
        "map_mmhg": round(map_val, 1),
        "rr_interval_ms": round(60000.0 / max(hr_mod, 1.0), 1),
        "preload_index": round(preload, 4),
        "afterload_index": round(afterload, 4),
        "contractility_index": round(contractility, 4),
        "svr_index": round(svr, 4),
        "compliance_index": round(compliance, 4),
        "filling_pressure_index": round(filling_press, 4),
        "pv_loop_area_index": round(pv_area_index, 4),
        "oxygen_demand_index": round(o2_demand, 4),
        "operating_mode": mode.value,
        "simulation_label": "educational simulation",
    }

    # ------------------------------------------------------------------
    # 12. LLM narrative summary (summarizes deterministic results only)
    # ------------------------------------------------------------------
    t_llm = time.time()
    operation_summary = await _generate_operation_summary(
        model=model,
        operation_metrics=operation_metrics,
        env_mode=mode.value,
        agent_warnings=warnings,
    )
    tracer.record_tool(
        "llm_operation_summary",
        inputs={"model": model, "mode": mode.value},
        outputs={"summary_length": len(operation_summary)},
        duration_ms=(time.time() - t_llm) * 1000,
    )

    # ------------------------------------------------------------------
    # 13. Full visualization payload (for frontend)
    # ------------------------------------------------------------------
    visualization_payload: dict[str, Any] = {
        "cardiac_cycle": cc_dict,
        "pv_loop": {
            "volume_ml": pv_dict["volume_ml"],
            "pressure_mmhg": pv_dict["pressure_mmhg"],
            "loop_area_index": pv_dict["loop_area_index"],
            "pv_loop_area_mmhg_ml": pv_dict["pv_loop_area_mmhg_ml"],
            "ef_pct": pv_dict["ef_pct"],
            "peak_pressure_mmhg": pv_dict["peak_pressure_mmhg"],
            "stroke_work_j": pv_dict["stroke_work_j"],
            "model": pv_dict["model"],
            "simulation_label": pv_dict["simulation_label"],
            "pv_warnings": pv_warnings,
        },
        "3d_heart": viz_payload_3d,
        "summary": operation_metrics,
        "simulation_note": (
            f"{CORE_SAFETY_PHRASE} Hemodynamic values are simulated estimates "
            "from deterministic mathematical models."
        ),
        "operation_summary": operation_summary,
    }

    # ------------------------------------------------------------------
    # 14. Updated Hemodynamics schema
    # ------------------------------------------------------------------
    hd = Hemodynamics(
        preload_index=MeasuredValue(
            value=round(preload, 4), unit="index", source=ValueSource.DERIVED, confidence=0.85
        ),
        afterload_index=MeasuredValue(
            value=round(afterload, 4), unit="index", source=ValueSource.DERIVED, confidence=0.85
        ),
        contractility_index=MeasuredValue(
            value=round(contractility, 4), unit="index", source=ValueSource.DERIVED, confidence=confidence
        ),
        arterial_compliance_index=MeasuredValue(
            value=round(compliance, 4), unit="index", source=ValueSource.DERIVED, confidence=0.80
        ),
        systemic_vascular_resistance_index=MeasuredValue(
            value=round(svr, 4), unit="index", source=ValueSource.DERIVED, confidence=0.80
        ),
        filling_pressure_index=MeasuredValue(
            value=round(filling_press, 4), unit="index", source=ValueSource.DERIVED, confidence=0.70
        ),
        pv_loop_area_index=MeasuredValue(
            value=round(pv_area_index, 4), unit="index", source=ValueSource.DERIVED, confidence=0.80
        ),
    )

    # ------------------------------------------------------------------
    # 15. Redis write (non-blocking best-effort; no large arrays stored)
    # ------------------------------------------------------------------
    redis_payload = {
        "case_id": case_id,
        "operation_metrics": operation_metrics,
        "pv_loop_summary": {
            "loop_area_index": pv_area_index,
            "pv_loop_area_mmhg_ml": pv_dict["pv_loop_area_mmhg_ml"],
            "ef_pct": pv_dict["ef_pct"],
            "point_count": len(pv_dict["volume_ml"]),
        },
        "visualization_payload": viz_payload_3d,
        "environment_effects": env_effects,
        "warnings": warnings,
        "confidence": confidence,
        "timestamp": t0,
    }
    await _write_redis_operation(case_id, redis_payload)

    # ------------------------------------------------------------------
    # 16. Weave trace log
    # ------------------------------------------------------------------
    sink.log_agent_stage(run_id, {
        "agent_id": AGENT_ID,
        "agent_name": AGENT_NAME,
        "case_id": case_id,
        "model_used": model,
        "metrics_computed": list(operation_metrics.keys()),
        "tools_called": [
            "compute_stroke_volume",
            "compute_ejection_fraction",
            "compute_cardiac_output",
            "compute_map",
            "compute_preload_index",
            "compute_afterload_index",
            "compute_contractility_index",
            "compute_oxygen_demand_index",
            "generate_pressure_volume_loop",
            "generate_cardiac_cycle",
            "generate_3d_visual_payload",
        ],
        "pv_loop_ready": len(pv_dict["volume_ml"]) > 0,
        "cardiac_cycle_ready": len(cc_dict["time_ms"]) > 0,
        "visualization_ready": viz_ready,
        "input_fields_used": list(field_presence.keys()),
        "priors_used": priors_used,
        "environment_effects": {k: v for k, v in env_effects.items() if isinstance(v, (int, float, bool))},
        "warnings_count": len(warnings),
        "confidence": confidence,
    })

    sink.finish_run(
        run_id,
        "warning" if impossible_states else "success",
        {
            "ef_pct": round(ef, 1),
            "co_l_min": round(co, 2),
            "pv_loop_area_index": round(pv_area_index, 4),
            "warnings_count": len(warnings),
            "confidence": confidence,
            "viz_ready": viz_ready,
        },
    )

    has_impossible = bool(impossible_states)
    return (
        AgentResponse(
            agent="hemodynamics_agent",  # backward-compatible ID used by orchestrator/tests
            status=AgentStatus.WARNING if (warnings or has_impossible) else AgentStatus.SUCCESS,
            inputs_used=[
                "cardiac_twin_state",
                "operating_environment",
                *[f"prior:{f}" for f in priors_used],
            ],
            outputs={
                "agent_id": AGENT_ID,
                "agent_name": AGENT_NAME,
                "model_used": model,
                "ef_pct": round(ef, 1),
                "stroke_volume_ml": round(sv, 1),
                "cardiac_output_l_min": round(co, 2),
                "map_mmhg": round(map_val, 1),
                "pv_loop_area_index": round(pv_area_index, 4),
                "operating_mode": mode.value,
                "pv_loop_ready": len(pv_dict["volume_ml"]) > 0,
                "cardiac_cycle_ready": len(cc_dict["time_ms"]) > 0,
                "visualization_ready": viz_ready,
                "tools_called": [
                    "compute_stroke_volume", "compute_ejection_fraction",
                    "compute_cardiac_output", "compute_map",
                    "compute_preload_index", "compute_afterload_index",
                    "compute_contractility_index", "compute_oxygen_demand_index",
                    "generate_pressure_volume_loop", "generate_cardiac_cycle",
                    "generate_3d_visual_payload",
                ],
                "simulation_note": f"{CORE_SAFETY_PHRASE} All outputs are educational simulations.",
            },
            warnings=warnings,
            confidence=confidence,
            trace=tracer.steps,
        ),
        hd,
        visualization_payload,
    )
