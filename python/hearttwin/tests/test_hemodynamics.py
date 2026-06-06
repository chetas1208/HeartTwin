"""Tests for hemodynamics PV loop simulation and cardiac cycle generation.

Basic cardiac formula tests live in test_cardiac_formulas.py.
"""

import pytest

from python.hearttwin.tools.hemodynamics import (
    _compute_pv_loop_area,
    simulate_cardiac_cycle,
    simulate_pv_loop,
)


class TestPVLoop:
    def test_pv_loop_area_positive(self):
        result = simulate_pv_loop(
            edv_ml=130,
            esv_ml=50,
            heart_rate_bpm=70,
            systolic_bp_mmhg=120,
            diastolic_bp_mmhg=80,
        )
        assert result.pv_loop_area_mmhg_ml > 0
        assert result.ef_pct > 0
        assert result.peak_pressure_mmhg > 0
        assert len(result.volumes_ml) == 200
        assert len(result.pressures_mmhg) == 200

    def test_pv_loop_esv_clamp(self):
        result = simulate_pv_loop(
            edv_ml=100,
            esv_ml=110,
            heart_rate_bpm=70,
            systolic_bp_mmhg=120,
            diastolic_bp_mmhg=80,
        )
        assert len(result.warnings) > 0

    def test_pv_loop_area_formula(self):
        square_v = [0, 10, 10, 0, 0]
        square_p = [0, 0, 10, 10, 0]
        area = _compute_pv_loop_area(square_v, square_p)
        assert abs(area - 100.0) < 0.1

    def test_cardiac_cycle_outputs(self):
        result = simulate_cardiac_cycle(
            edv_ml=130,
            esv_ml=50,
            heart_rate_bpm=70,
            systolic_bp_mmhg=120,
            diastolic_bp_mmhg=80,
            time_step_ms=5.0,
        )
        assert result.stroke_volume_ml == 80.0
        assert abs(result.cardiac_output_l_min - 5.6) < 0.1
        assert len(result.time_ms) > 0
        assert len(result.lv_volume_ml) == len(result.time_ms)
        assert len(result.lv_pressure_mmhg) == len(result.time_ms)

    def test_cardiac_cycle_high_hr(self):
        result = simulate_cardiac_cycle(
            edv_ml=120,
            esv_ml=48,
            heart_rate_bpm=140,
            systolic_bp_mmhg=140,
            diastolic_bp_mmhg=90,
            time_step_ms=5.0,
        )
        assert result.cardiac_output_l_min > 8.0

    def test_no_negative_volumes(self):
        result = simulate_cardiac_cycle(
            edv_ml=130, esv_ml=50, heart_rate_bpm=70,
            systolic_bp_mmhg=120, diastolic_bp_mmhg=80,
        )
        assert all(v >= 0 for v in result.lv_volume_ml)
