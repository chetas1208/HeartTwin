"""Tests for deterministic recovery simulation."""

import pytest

from python.hearttwin.tools.recovery_sim import (
    build_default_scenarios,
    simulate_recovery,
)

BASE_PARAMS = {
    "edv_ml": 130.0,
    "esv_ml": 50.0,
    "heart_rate_bpm": 75.0,
    "contractility_index": 0.65,
    "afterload_index": 0.55,
    "preload_index": 0.55,
    "inflammation_index": 0.3,
    "oxygen_delivery_index": 0.75,
    "stiffness_index": 0.4,
    "scar_fraction": 0.05,
    "arrhythmia_instability_score": 0.15,
}

RECOVERY_PARAMS = {
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
    "max_safe_parameter_shift": 0.30,
    "uncertainty_penalty_weight": 0.2,
}


class TestRecoverySim:
    def test_trajectory_length(self):
        result = simulate_recovery(**BASE_PARAMS, recovery_horizon_days=30, **RECOVERY_PARAMS, random_seed=42)
        assert len(result.trajectory) == 31  # day 0 to day 30

    def test_day_zero_matches_input(self):
        result = simulate_recovery(**BASE_PARAMS, recovery_horizon_days=30, **RECOVERY_PARAMS, random_seed=42)
        d0 = result.trajectory[0]
        assert d0.day == 0
        assert abs(d0.edv_ml - 130.0) < 0.1

    def test_ef_in_valid_range(self):
        result = simulate_recovery(**BASE_PARAMS, recovery_horizon_days=30, **RECOVERY_PARAMS, random_seed=42)
        for day in result.trajectory:
            assert 5.0 <= day.ef_pct <= 90.0, f"EF {day.ef_pct} out of range on day {day.day}"

    def test_esv_always_less_than_edv(self):
        result = simulate_recovery(**BASE_PARAMS, recovery_horizon_days=30, **RECOVERY_PARAMS, random_seed=42)
        for day in result.trajectory:
            assert day.esv_ml < day.edv_ml, f"ESV >= EDV on day {day.day}"

    def test_uncertainty_bands_valid(self):
        result = simulate_recovery(**BASE_PARAMS, recovery_horizon_days=30, **RECOVERY_PARAMS, random_seed=42)
        for day in result.trajectory:
            assert day.uncertainty_low <= day.cardiac_output_l_min
            assert day.uncertainty_high >= day.cardiac_output_l_min

    def test_deterministic_same_seed(self):
        r1 = simulate_recovery(**BASE_PARAMS, recovery_horizon_days=30, **RECOVERY_PARAMS, random_seed=42)
        r2 = simulate_recovery(**BASE_PARAMS, recovery_horizon_days=30, **RECOVERY_PARAMS, random_seed=42)
        assert r1.trajectory[-1].ef_pct == r2.trajectory[-1].ef_pct

    def test_uncertainty_bands_vary_across_days(self):
        r1 = simulate_recovery(**BASE_PARAMS, recovery_horizon_days=30, **RECOVERY_PARAMS, random_seed=42)
        # Uncertainty bands should differ across days as CO changes
        unc_lows = [d.uncertainty_low for d in r1.trajectory]
        assert len(set(unc_lows)) > 1, "Uncertainty bands should vary across recovery days"

    def test_inflammation_decays(self):
        result = simulate_recovery(**BASE_PARAMS, recovery_horizon_days=30, **RECOVERY_PARAMS, random_seed=42)
        d0 = result.trajectory[0]
        d30 = result.trajectory[-1]
        assert d30.inflammation_index < d0.inflammation_index

    def test_arrhythmia_improves(self):
        result = simulate_recovery(**BASE_PARAMS, recovery_horizon_days=30, **RECOVERY_PARAMS, random_seed=42)
        d0 = result.trajectory[0]
        d30 = result.trajectory[-1]
        assert d30.arrhythmia_instability_score <= d0.arrhythmia_instability_score

    def test_summary_metrics_present(self):
        result = simulate_recovery(**BASE_PARAMS, recovery_horizon_days=30, **RECOVERY_PARAMS, random_seed=42)
        assert "initial_ef_pct" in result.summary_metrics
        assert "final_ef_pct" in result.summary_metrics
        assert "ef_delta_pct" in result.summary_metrics

    def test_scenario_label_safe(self):
        result = simulate_recovery(**BASE_PARAMS, recovery_horizon_days=30, **RECOVERY_PARAMS, random_seed=42)
        assert "simulated" in result.scenario_label.lower()
        assert "healed" not in result.scenario_label.lower()
        assert "treatment" not in result.scenario_label.lower()

    def test_build_default_scenarios_count(self):
        scenarios = build_default_scenarios(BASE_PARAMS, recovery_horizon_days=14, random_seed=0)
        assert len(scenarios) == 4

    def test_all_scenario_types_present(self):
        scenarios = build_default_scenarios(BASE_PARAMS, recovery_horizon_days=14, random_seed=0)
        types = {s.scenario_type for s in scenarios}
        assert "load_reduction" in types
        assert "oxygen_delivery_improvement" in types

    def test_esv_clamp_warning(self):
        params = {**BASE_PARAMS, "esv_ml": 200.0}
        result = simulate_recovery(**params, recovery_horizon_days=10, **RECOVERY_PARAMS, random_seed=42)
        assert any("ESV" in w for w in result.warnings)
