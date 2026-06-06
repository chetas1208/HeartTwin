"""Agent 7: Recovery Orchestration Agent.

Generates and compares simulated recovery scenarios.
Never provides medical decisions; all outputs are labeled educational simulations.
"""

from __future__ import annotations

import time
from typing import Any

from python.hearttwin.schemas import (
    AgentResponse,
    AgentStatus,
    CardiacTwinState,
    RecoveryConfig,
)
from python.hearttwin.tools.recovery_sim import RecoveryScenarioResult, build_default_scenarios, simulate_recovery
from python.hearttwin.tools.weave_trace import TraceContext

_SIMULATION_DISCLAIMER = (
    "All recovery trajectories are educational simulations only. "
    "They are bounded model scenarios and not for diagnosis or treatment decisions."
)


def _state_to_recovery_params(state: CardiacTwinState) -> dict:
    """Extract parameters needed for recovery simulation from state."""

    def get_val(mv, fallback: float) -> float:
        return mv.value if mv is not None else fallback

    meas = state.measurements
    ts = state.tissue_state
    hd = state.hemodynamics
    ep = state.electrophysiology

    return {
        "edv_ml": get_val(meas.edv_ml, 130.0),
        "esv_ml": get_val(meas.esv_ml, 50.0),
        "heart_rate_bpm": get_val(meas.heart_rate_bpm, 70.0),
        "contractility_index": get_val(hd.contractility_index, 0.65),
        "afterload_index": get_val(hd.afterload_index, 0.5),
        "preload_index": get_val(hd.preload_index, 0.55),
        "inflammation_index": get_val(ts.inflammation_index, 0.1),
        "oxygen_delivery_index": get_val(ts.oxygen_delivery_index, 0.85),
        "stiffness_index": get_val(ts.stiffness_index, 0.3),
        "scar_fraction": get_val(ts.scar_fraction, 0.0),
        "arrhythmia_instability_score": get_val(ep.arrhythmia_instability_score, 0.1),
    }


async def run_recovery_agent(
    state: CardiacTwinState,
    recovery_configs: list[RecoveryConfig] | None,
    case_id: str,
) -> tuple[AgentResponse, list[dict[str, Any]]]:
    """Generate recovery scenarios from cardiac twin state."""
    tracer = TraceContext(case_id=case_id, agent_name="recovery_agent")
    t0 = time.time()
    warnings: list[str] = []

    base_params = _state_to_recovery_params(state)
    sim_config = state.simulation_config
    horizon = sim_config.recovery.recovery_horizon_days
    seed = sim_config.random_seed

    if recovery_configs:
        scenarios: list[RecoveryScenarioResult] = []
        for i, cfg in enumerate(recovery_configs[:4]):
            scenario = simulate_recovery(
                **base_params,
                recovery_horizon_days=horizon,
                scenario_type=cfg.scenario_type.value,
                contractility_delta_per_day=cfg.contractility_delta_per_day,
                afterload_delta_per_day=cfg.afterload_delta_per_day,
                preload_delta_per_day=cfg.preload_delta_per_day,
                inflammation_decay_rate=cfg.inflammation_decay_rate,
                oxygen_delivery_delta_per_day=cfg.oxygen_delivery_delta_per_day,
                stiffness_delta_per_day=cfg.stiffness_delta_per_day,
                scar_remodeling_rate=cfg.scar_remodeling_rate,
                heart_rate_adaptation_rate=cfg.heart_rate_adaptation_rate,
                arrhythmia_stability_delta=cfg.arrhythmia_stability_delta,
                max_safe_parameter_shift=cfg.max_safe_parameter_shift,
                uncertainty_penalty_weight=cfg.uncertainty_penalty_weight,
                random_seed=seed + i,
            )
            scenarios.append(scenario)
            warnings.extend(scenario.warnings)
    else:
        scenarios = build_default_scenarios(
            state_params=base_params,
            recovery_horizon_days=horizon,
            random_seed=seed,
        )
        for s in scenarios:
            warnings.extend(s.warnings)

    tracer.record_tool(
        "simulate_recovery_scenarios",
        inputs={
            "scenario_count": len(scenarios),
            "horizon_days": horizon,
        },
        outputs={
            "scenarios": [s.scenario_type for s in scenarios],
        },
        duration_ms=(time.time() - t0) * 1000,
    )

    scenario_payloads: list[dict[str, Any]] = []
    for scenario in scenarios:
        traj_payload = [
            {
                "day": d.day,
                "ef_pct": d.ef_pct,
                "cardiac_output_l_min": d.cardiac_output_l_min,
                "stroke_volume_ml": d.stroke_volume_ml,
                "heart_rate_bpm": d.heart_rate_bpm,
                "contractility_index": d.contractility_index,
                "inflammation_index": d.inflammation_index,
                "oxygen_delivery_index": d.oxygen_delivery_index,
                "uncertainty_low": d.uncertainty_low,
                "uncertainty_high": d.uncertainty_high,
            }
            for d in scenario.trajectory
        ]

        payload = {
            "scenario_type": scenario.scenario_type,
            "scenario_label": scenario.scenario_label,
            "summary_metrics": scenario.summary_metrics,
            "trajectory": traj_payload,
            "warnings": scenario.warnings,
            "simulation_disclaimer": _SIMULATION_DISCLAIMER,
            "simulation_note": scenario.simulation_note,
        }
        scenario_payloads.append(payload)

    tradeoffs = _compute_tradeoffs(scenarios)

    return AgentResponse(
        agent="recovery_agent",
        status=AgentStatus.SUCCESS if not warnings else AgentStatus.WARNING,
        inputs_used=["cardiac_twin_state", "recovery_config"],
        outputs={
            "scenario_count": len(scenarios),
            "scenario_types": [s.scenario_type for s in scenarios],
            "tradeoffs": tradeoffs,
            "simulation_disclaimer": _SIMULATION_DISCLAIMER,
        },
        warnings=warnings,
        confidence=0.80,
        trace=tracer.steps,
    ), scenario_payloads


def _compute_tradeoffs(scenarios: list[RecoveryScenarioResult]) -> list[dict]:
    """Compute comparative tradeoff summary across scenarios."""
    tradeoffs = []
    for s in scenarios:
        sm = s.summary_metrics
        tradeoffs.append({
            "scenario": s.scenario_label,
            "ef_gain_pct": sm.get("ef_delta_pct", 0),
            "co_gain_l_min": sm.get("co_delta_l_min", 0),
            "final_inflammation": sm.get("final_inflammation_index", 0),
            "final_arrhythmia": sm.get("final_arrhythmia_instability", 0),
        })

    if len(tradeoffs) >= 2:
        best_ef = max(tradeoffs, key=lambda x: x["ef_gain_pct"])
        best_co = max(tradeoffs, key=lambda x: x["co_gain_l_min"])
        lowest_inflammation = min(tradeoffs, key=lambda x: x["final_inflammation"])
        for t in tradeoffs:
            t["best_for_ef"] = t["scenario"] == best_ef["scenario"]
            t["best_for_co"] = t["scenario"] == best_co["scenario"]
            t["lowest_inflammation"] = t["scenario"] == lowest_inflammation["scenario"]

    return tradeoffs
