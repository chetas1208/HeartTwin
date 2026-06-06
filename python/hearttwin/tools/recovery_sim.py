"""Deterministic recovery scenario simulation.

Simulates day-by-day cardiac parameter trajectories.
No LLM involvement. Pure deterministic math with bounded updates.
All outputs labeled as simulated recovery trajectories.
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class DayState:
    day: int
    edv_ml: float
    esv_ml: float
    ef_pct: float
    stroke_volume_ml: float
    cardiac_output_l_min: float
    heart_rate_bpm: float
    contractility_index: float
    afterload_index: float
    preload_index: float
    inflammation_index: float
    oxygen_delivery_index: float
    stiffness_index: float
    scar_fraction: float
    arrhythmia_instability_score: float
    uncertainty_low: float
    uncertainty_high: float


@dataclass
class RecoveryScenarioResult:
    scenario_type: str
    scenario_label: str
    trajectory: list[DayState]
    summary_metrics: dict
    warnings: list[str] = field(default_factory=list)
    simulation_note: str = (
        "This is a simulated educational recovery trajectory. "
        "Not for diagnosis or treatment decisions."
    )


def _clamp(value: float, min_val: float, max_val: float) -> float:
    return max(min_val, min(max_val, value))


def _exp_decay(current: float, decay_rate: float, floor: float = 0.0) -> float:
    return floor + (current - floor) * math.exp(-decay_rate)


def _bounded_delta(current: float, delta: float, min_val: float, max_val: float) -> float:
    return _clamp(current + delta, min_val, max_val)


def simulate_recovery(
    *,
    edv_ml: float,
    esv_ml: float,
    heart_rate_bpm: float,
    contractility_index: float,
    afterload_index: float,
    preload_index: float,
    inflammation_index: float,
    oxygen_delivery_index: float,
    stiffness_index: float,
    scar_fraction: float,
    arrhythmia_instability_score: float,
    recovery_horizon_days: int,
    scenario_type: str,
    contractility_delta_per_day: float,
    afterload_delta_per_day: float,
    preload_delta_per_day: float,
    inflammation_decay_rate: float,
    oxygen_delivery_delta_per_day: float,
    stiffness_delta_per_day: float,
    scar_remodeling_rate: float,
    heart_rate_adaptation_rate: float,
    arrhythmia_stability_delta: float,
    max_safe_parameter_shift: float,
    uncertainty_penalty_weight: float,
    random_seed: int = 42,
) -> RecoveryScenarioResult:
    """Simulate day-by-day recovery trajectory.

    All parameter changes are bounded by max_safe_parameter_shift.
    Impossible physiological states are rejected.
    Returns labeled simulated trajectory only.
    """
    rng = random.Random(random_seed)
    warnings: list[str] = []

    if esv_ml >= edv_ml:
        esv_ml = edv_ml * 0.4
        warnings.append("ESV clamped to 40% EDV at simulation start")

    current = {
        "edv_ml": edv_ml,
        "esv_ml": esv_ml,
        "heart_rate_bpm": heart_rate_bpm,
        "contractility": contractility_index,
        "afterload": afterload_index,
        "preload": preload_index,
        "inflammation": inflammation_index,
        "oxygen_delivery": oxygen_delivery_index,
        "stiffness": stiffness_index,
        "scar": scar_fraction,
        "arrhythmia": arrhythmia_instability_score,
    }

    initial_co = (heart_rate_bpm * (edv_ml - esv_ml)) / 1000.0
    trajectory: list[DayState] = []

    for day in range(recovery_horizon_days + 1):
        sv = max(5.0, current["edv_ml"] - current["esv_ml"])
        ef = (sv / max(current["edv_ml"], 1.0)) * 100.0
        co = (current["heart_rate_bpm"] * sv) / 1000.0

        noise_frac = rng.gauss(0, 0.025)
        unc_range = uncertainty_penalty_weight * 0.10 + abs(noise_frac)
        uncertainty_low = co * (1.0 - unc_range)
        uncertainty_high = co * (1.0 + unc_range)

        trajectory.append(
            DayState(
                day=day,
                edv_ml=round(current["edv_ml"], 2),
                esv_ml=round(current["esv_ml"], 2),
                ef_pct=round(ef, 1),
                stroke_volume_ml=round(sv, 1),
                cardiac_output_l_min=round(co, 2),
                heart_rate_bpm=round(current["heart_rate_bpm"], 1),
                contractility_index=round(current["contractility"], 4),
                afterload_index=round(current["afterload"], 4),
                preload_index=round(current["preload"], 4),
                inflammation_index=round(current["inflammation"], 4),
                oxygen_delivery_index=round(current["oxygen_delivery"], 4),
                stiffness_index=round(current["stiffness"], 4),
                scar_fraction=round(current["scar"], 4),
                arrhythmia_instability_score=round(current["arrhythmia"], 4),
                uncertainty_low=round(uncertainty_low, 2),
                uncertainty_high=round(uncertainty_high, 2),
            )
        )

        if day == recovery_horizon_days:
            break

        max_shift = max_safe_parameter_shift

        current["inflammation"] = _exp_decay(
            current["inflammation"], inflammation_decay_rate, floor=0.0
        )
        current["inflammation"] = _clamp(current["inflammation"], 0.0, 1.5)

        current["contractility"] = _bounded_delta(
            current["contractility"],
            _clamp(contractility_delta_per_day, -max_shift, max_shift),
            0.0,
            1.5,
        )

        current["afterload"] = _bounded_delta(
            current["afterload"],
            _clamp(afterload_delta_per_day, -max_shift, max_shift),
            0.0,
            2.0,
        )

        current["preload"] = _bounded_delta(
            current["preload"],
            _clamp(preload_delta_per_day, -max_shift, max_shift),
            0.0,
            1.5,
        )

        current["oxygen_delivery"] = _bounded_delta(
            current["oxygen_delivery"],
            _clamp(oxygen_delivery_delta_per_day, -max_shift, max_shift),
            0.0,
            1.5,
        )

        current["stiffness"] = _bounded_delta(
            current["stiffness"],
            _clamp(stiffness_delta_per_day, -max_shift, max_shift),
            0.0,
            2.0,
        )

        current["scar"] = _bounded_delta(
            current["scar"],
            _clamp(-scar_remodeling_rate, -0.01, 0.0),
            0.0,
            0.6,
        )

        current["arrhythmia"] = _bounded_delta(
            current["arrhythmia"],
            _clamp(-arrhythmia_stability_delta, -max_shift, max_shift),
            0.0,
            1.0,
        )

        hr_target = 60.0 if scenario_type == "load_reduction" else heart_rate_bpm
        hr_delta = (hr_target - current["heart_rate_bpm"]) * heart_rate_adaptation_rate
        current["heart_rate_bpm"] = _bounded_delta(
            current["heart_rate_bpm"], hr_delta, 30.0, 200.0
        )

        contractility_effect = (current["contractility"] - contractility_index) * 15.0
        afterload_effect = (afterload_index - current["afterload"]) * 10.0
        stiffness_effect = (stiffness_index - current["stiffness"]) * 8.0
        volume_shift = contractility_effect + afterload_effect + stiffness_effect

        current["esv_ml"] = _clamp(
            current["esv_ml"] - _clamp(volume_shift * 0.5, -5.0, 5.0),
            5.0,
            current["edv_ml"] * 0.9,
        )

        if current["esv_ml"] >= current["edv_ml"]:
            current["esv_ml"] = current["edv_ml"] * 0.4
            warnings.append(f"Day {day}: ESV >= EDV — clamped to 40% EDV")

    final = trajectory[-1]
    initial = trajectory[0]

    ef_delta = final.ef_pct - initial.ef_pct
    co_delta = final.cardiac_output_l_min - initial.cardiac_output_l_min

    labels = {
        "load_reduction": "Simulated Load Reduction Scenario",
        "oxygen_delivery_improvement": "Simulated Oxygen Delivery Improvement Scenario",
        "contractility_support": "Simulated Contractility Support Scenario",
        "conditioning": "Simulated Conditioning Scenario",
        "stability_monitoring": "Simulated Stability Monitoring Scenario",
        "custom": "Custom Simulated Scenario",
    }

    return RecoveryScenarioResult(
        scenario_type=scenario_type,
        scenario_label=labels.get(scenario_type, "Simulated Recovery Scenario"),
        trajectory=trajectory,
        summary_metrics={
            "initial_ef_pct": initial.ef_pct,
            "final_ef_pct": final.ef_pct,
            "ef_delta_pct": round(ef_delta, 2),
            "initial_co_l_min": initial.cardiac_output_l_min,
            "final_co_l_min": final.cardiac_output_l_min,
            "co_delta_l_min": round(co_delta, 3),
            "final_inflammation_index": final.inflammation_index,
            "final_arrhythmia_instability": final.arrhythmia_instability_score,
            "horizon_days": recovery_horizon_days,
        },
        warnings=warnings,
    )


def build_default_scenarios(
    state_params: dict,
    recovery_horizon_days: int = 30,
    random_seed: int = 42,
) -> list[RecoveryScenarioResult]:
    """Build the default 4-scenario comparison set from a cardiac state."""
    scenario_configs = [
        {
            "scenario_type": "load_reduction",
            "contractility_delta_per_day": 0.003,
            "afterload_delta_per_day": -0.008,
            "preload_delta_per_day": -0.005,
            "inflammation_decay_rate": 0.02,
            "oxygen_delivery_delta_per_day": 0.002,
            "stiffness_delta_per_day": -0.003,
            "scar_remodeling_rate": 0.001,
            "heart_rate_adaptation_rate": 0.003,
            "arrhythmia_stability_delta": 0.004,
        },
        {
            "scenario_type": "oxygen_delivery_improvement",
            "contractility_delta_per_day": 0.004,
            "afterload_delta_per_day": -0.003,
            "preload_delta_per_day": -0.002,
            "inflammation_decay_rate": 0.03,
            "oxygen_delivery_delta_per_day": 0.008,
            "stiffness_delta_per_day": -0.001,
            "scar_remodeling_rate": 0.001,
            "heart_rate_adaptation_rate": 0.002,
            "arrhythmia_stability_delta": 0.003,
        },
        {
            "scenario_type": "contractility_support",
            "contractility_delta_per_day": 0.010,
            "afterload_delta_per_day": -0.002,
            "preload_delta_per_day": -0.001,
            "inflammation_decay_rate": 0.02,
            "oxygen_delivery_delta_per_day": 0.003,
            "stiffness_delta_per_day": -0.002,
            "scar_remodeling_rate": 0.001,
            "heart_rate_adaptation_rate": 0.001,
            "arrhythmia_stability_delta": 0.005,
        },
        {
            "scenario_type": "conditioning",
            "contractility_delta_per_day": 0.006,
            "afterload_delta_per_day": -0.004,
            "preload_delta_per_day": 0.002,
            "inflammation_decay_rate": 0.025,
            "oxygen_delivery_delta_per_day": 0.005,
            "stiffness_delta_per_day": -0.004,
            "scar_remodeling_rate": 0.002,
            "heart_rate_adaptation_rate": 0.004,
            "arrhythmia_stability_delta": 0.006,
        },
    ]

    results = []
    for i, cfg in enumerate(scenario_configs):
        result = simulate_recovery(
            **state_params,
            recovery_horizon_days=recovery_horizon_days,
            max_safe_parameter_shift=0.30,
            uncertainty_penalty_weight=0.2,
            random_seed=random_seed + i,
            **cfg,
        )
        results.append(result)

    return results
