"""Tests for deterministic cardiac formulas.

Covers every pure function in tools/cardiac_state.py.
All expected values are derived from first principles or published reference ranges.
No mocking — these are deterministic math functions.
"""

import math
import pytest

from python.hearttwin.tools.cardiac_state import (
    check_ef_consistency,
    compute_afterload_index,
    compute_arterial_compliance_index,
    compute_bsa_mosteller,
    compute_cardiac_output,
    compute_contractility_index,
    compute_ejection_fraction,
    compute_filling_pressure_index,
    compute_map,
    compute_preload_index,
    compute_qtc_bazett,
    compute_rr_from_hr,
    compute_stroke_volume,
    compute_svr_index,
    validate_bounds,
)


# ---------------------------------------------------------------------------
# Stroke volume: SV = EDV - ESV
# ---------------------------------------------------------------------------

class TestStrokeVolume:
    def test_normal_values(self):
        assert compute_stroke_volume(130, 50) == 80.0

    def test_small_ventricle(self):
        assert compute_stroke_volume(80, 30) == 50.0

    def test_dilated_cardiomyopathy_like(self):
        assert compute_stroke_volume(250, 180) == 70.0

    def test_exact_boundary_esv_just_below_edv(self):
        sv = compute_stroke_volume(100.0, 99.9)
        assert abs(sv - 0.1) < 1e-9

    def test_raises_esv_equal_edv(self):
        with pytest.raises(ValueError, match="ESV"):
            compute_stroke_volume(100, 100)

    def test_raises_esv_greater_than_edv(self):
        with pytest.raises(ValueError, match="ESV"):
            compute_stroke_volume(80, 100)

    def test_large_stroke_volume(self):
        # Exercise physiology: trained athlete at peak
        assert compute_stroke_volume(220, 70) == 150.0


# ---------------------------------------------------------------------------
# Ejection fraction: EF = (SV / EDV) × 100
# ---------------------------------------------------------------------------

class TestEjectionFraction:
    def test_normal_ef(self):
        ef = compute_ejection_fraction(130, 50)
        assert abs(ef - 61.538) < 0.01

    def test_preserved_ef(self):
        # EF ~55% — lower end of normal
        ef = compute_ejection_fraction(130, 58.5)
        assert abs(ef - 55.0) < 0.1

    def test_reduced_ef(self):
        # Heart failure with reduced EF
        ef = compute_ejection_fraction(200, 140)
        assert abs(ef - 30.0) < 0.1

    def test_severely_reduced_ef(self):
        ef = compute_ejection_fraction(250, 225)
        assert abs(ef - 10.0) < 0.1

    def test_ef_always_between_0_and_100(self):
        for edv, esv in [(130, 50), (200, 150), (80, 20), (300, 290)]:
            ef = compute_ejection_fraction(edv, esv)
            assert 0 < ef < 100

    def test_ef_consistent_with_sv(self):
        edv, esv = 130.0, 50.0
        sv = compute_stroke_volume(edv, esv)
        ef_direct = compute_ejection_fraction(edv, esv)
        ef_from_sv = (sv / edv) * 100
        assert abs(ef_direct - ef_from_sv) < 1e-9

    def test_raises_zero_edv(self):
        with pytest.raises(ValueError):
            compute_ejection_fraction(0, 0)

    def test_raises_negative_edv(self):
        with pytest.raises(ValueError):
            compute_ejection_fraction(-10, -20)


# ---------------------------------------------------------------------------
# Cardiac output: CO = (HR × SV) / 1000
# ---------------------------------------------------------------------------

class TestCardiacOutput:
    def test_resting_normal(self):
        co = compute_cardiac_output(70, 80)
        assert abs(co - 5.6) < 0.001

    def test_low_co_heart_failure(self):
        co = compute_cardiac_output(90, 30)
        assert abs(co - 2.7) < 0.001

    def test_high_co_exercise(self):
        co = compute_cardiac_output(160, 130)
        assert abs(co - 20.8) < 0.001

    def test_unit_check(self):
        # SV in mL, HR in bpm → CO in L/min = HR × SV / 1000
        hr, sv = 60, 1000
        co = compute_cardiac_output(hr, sv)
        assert co == 60.0

    def test_raises_zero_hr(self):
        with pytest.raises(ValueError, match="Heart rate"):
            compute_cardiac_output(0, 80)

    def test_raises_negative_hr(self):
        with pytest.raises(ValueError):
            compute_cardiac_output(-10, 80)

    def test_raises_zero_sv(self):
        with pytest.raises(ValueError, match="Stroke volume"):
            compute_cardiac_output(70, 0)


# ---------------------------------------------------------------------------
# Mean arterial pressure: MAP = DBP + (SBP - DBP) / 3
# ---------------------------------------------------------------------------

class TestMAP:
    def test_normal_bp(self):
        # 120/80 → MAP = 80 + 40/3 ≈ 93.33
        m = compute_map(120, 80)
        assert abs(m - 93.333) < 0.01

    def test_formula_identity(self):
        sbp, dbp = 140.0, 90.0
        m = compute_map(sbp, dbp)
        expected = dbp + (sbp - dbp) / 3.0
        assert abs(m - expected) < 1e-9

    def test_hypertensive_crisis(self):
        m = compute_map(220, 130)
        assert abs(m - 160.0) < 0.01

    def test_hypotension(self):
        m = compute_map(80, 50)
        assert abs(m - 60.0) < 0.01

    def test_raises_dbp_equal_sbp(self):
        with pytest.raises(ValueError, match="Diastolic"):
            compute_map(100, 100)

    def test_raises_dbp_greater_than_sbp(self):
        with pytest.raises(ValueError):
            compute_map(80, 100)


# ---------------------------------------------------------------------------
# RR interval: RR = 60000 / HR
# ---------------------------------------------------------------------------

class TestRRInterval:
    def test_normal_hr(self):
        rr = compute_rr_from_hr(70)
        assert abs(rr - 857.14) < 0.1

    def test_bradycardia(self):
        rr = compute_rr_from_hr(40)
        assert abs(rr - 1500.0) < 0.01

    def test_tachycardia(self):
        rr = compute_rr_from_hr(150)
        assert abs(rr - 400.0) < 0.01

    def test_inverse_of_hr(self):
        hr = 72
        rr = compute_rr_from_hr(hr)
        hr_back = 60000 / rr
        assert abs(hr_back - hr) < 1e-6

    def test_raises_zero_hr(self):
        with pytest.raises(ValueError):
            compute_rr_from_hr(0)


# ---------------------------------------------------------------------------
# QTc Bazett: QTc = QT / sqrt(RR in seconds)
# ---------------------------------------------------------------------------

class TestQTcBazett:
    def test_normal_qtc(self):
        # QT 400 ms, HR 70 bpm → RR 857 ms
        qtc = compute_qtc_bazett(400, 857)
        assert abs(qtc - 432) < 5

    def test_prolonged_qtc(self):
        # QT 500 ms, HR 80 → RR 750 ms
        qtc = compute_qtc_bazett(500, 750)
        assert qtc > 500

    def test_short_rr_inflates_qtc(self):
        qtc_slow = compute_qtc_bazett(400, 1000)
        qtc_fast = compute_qtc_bazett(400, 600)
        assert qtc_fast > qtc_slow

    def test_raises_zero_rr(self):
        with pytest.raises(ValueError):
            compute_qtc_bazett(400, 0)


# ---------------------------------------------------------------------------
# BSA Mosteller: sqrt(H × W / 3600)
# ---------------------------------------------------------------------------

class TestBSAMosteller:
    def test_reference_adult(self):
        # 170 cm, 70 kg → ~1.82 m²
        bsa = compute_bsa_mosteller(170, 70)
        assert abs(bsa - 1.820) < 0.01

    def test_formula_identity(self):
        h, w = 180.0, 80.0
        bsa = compute_bsa_mosteller(h, w)
        assert abs(bsa - math.sqrt(h * w / 3600)) < 1e-9

    def test_small_person(self):
        bsa = compute_bsa_mosteller(150, 50)
        assert bsa < 1.6

    def test_large_person(self):
        bsa = compute_bsa_mosteller(200, 120)
        assert bsa > 2.3

    def test_raises_zero_height(self):
        with pytest.raises(ValueError):
            compute_bsa_mosteller(0, 70)

    def test_raises_zero_weight(self):
        with pytest.raises(ValueError):
            compute_bsa_mosteller(170, 0)


# ---------------------------------------------------------------------------
# Derived index calculations
# ---------------------------------------------------------------------------

class TestDerivedIndices:
    def test_preload_index_typical(self):
        pi = compute_preload_index(130)
        assert abs(pi - 1.0) < 0.01

    def test_preload_index_high_edv(self):
        assert compute_preload_index(200) > 1.0

    def test_preload_index_low_edv(self):
        assert compute_preload_index(80) < 1.0

    def test_preload_index_raises_zero(self):
        with pytest.raises(ValueError):
            compute_preload_index(0)

    def test_arterial_compliance_normal(self):
        # SV 80 mL, pulse pressure 40 mmHg → raw 2.0, normalized 1.0
        ci = compute_arterial_compliance_index(80, 40)
        assert abs(ci - 1.0) < 0.01

    def test_arterial_compliance_raises_zero_pp(self):
        with pytest.raises(ValueError):
            compute_arterial_compliance_index(80, 0)

    def test_filling_pressure_index_positive(self):
        fi = compute_filling_pressure_index(130, 0.3)
        assert fi > 0

    def test_filling_pressure_increases_with_stiffness(self):
        fi_low = compute_filling_pressure_index(130, 0.2)
        fi_high = compute_filling_pressure_index(130, 0.8)
        assert fi_high > fi_low

    def test_afterload_index_normal(self):
        # MAP 93, CO 5.0 → both normalized to ~1
        ai = compute_afterload_index(93, 5.0)
        assert abs(ai - 1.0) < 0.1

    def test_afterload_raises_zero_co(self):
        with pytest.raises(ValueError):
            compute_afterload_index(93, 0)

    def test_svr_index_normal(self):
        svr = compute_svr_index(93, 5.0)
        assert 0.5 < svr < 1.5

    def test_svr_index_raises_zero_co(self):
        with pytest.raises(ValueError):
            compute_svr_index(93, 0)

    def test_contractility_index_positive(self):
        ci = compute_contractility_index(60, 1.0)
        assert ci > 0

    def test_contractility_index_decreases_with_afterload(self):
        ci_low_al = compute_contractility_index(60, 0.5)
        ci_high_al = compute_contractility_index(60, 2.0)
        assert ci_low_al > ci_high_al


# ---------------------------------------------------------------------------
# EF consistency check
# ---------------------------------------------------------------------------

class TestEFConsistency:
    def test_consistent_ef(self):
        # Reported EF 61.5%, EDV 130, ESV 50 → computed ~61.5%
        ok, msg = check_ef_consistency(61.5, 130, 50)
        assert ok

    def test_inconsistent_ef(self):
        # Reported 70%, but volumes give ~61.5%
        ok, msg = check_ef_consistency(70.0, 130, 50, tolerance_pct=5.0)
        assert not ok
        assert "inconsistency" in msg.lower()

    def test_within_tolerance(self):
        ok, _ = check_ef_consistency(62.0, 130, 50, tolerance_pct=5.0)
        assert ok

    def test_no_volumes_skips_check(self):
        ok, msg = check_ef_consistency(60.0, None, None)
        assert ok
        assert "Cannot verify" in msg


# ---------------------------------------------------------------------------
# Bounds validation
# ---------------------------------------------------------------------------

class TestBoundsValidation:
    def setup_method(self):
        import json
        import pathlib
        bounds_path = pathlib.Path("python/hearttwin/data/parameter_bounds.json")
        self.bounds = json.loads(bounds_path.read_text())

    def test_normal_hr_no_warnings(self):
        w = validate_bounds("heart_rate_bpm", 72, self.bounds)
        assert len(w) == 0

    def test_zero_hr_flagged(self):
        w = validate_bounds("heart_rate_bpm", 0, self.bounds)
        assert len(w) > 0

    def test_extreme_tachycardia_flagged(self):
        w = validate_bounds("heart_rate_bpm", 350, self.bounds)
        assert len(w) > 0

    def test_normal_ef_no_warnings(self):
        w = validate_bounds("ejection_fraction_pct", 60, self.bounds)
        assert len(w) == 0

    def test_negative_ef_flagged(self):
        w = validate_bounds("ejection_fraction_pct", -5, self.bounds)
        assert len(w) > 0

    def test_unknown_field_no_crash(self):
        w = validate_bounds("nonexistent_field", 99, self.bounds)
        assert w == []


# ---------------------------------------------------------------------------
# Cross-formula consistency
# ---------------------------------------------------------------------------

class TestCrossFormulaConsistency:
    """Verify formulas are internally consistent with each other."""

    def test_sv_ef_co_triangle(self):
        edv, esv, hr = 130.0, 50.0, 70.0
        sv = compute_stroke_volume(edv, esv)
        ef = compute_ejection_fraction(edv, esv)
        co = compute_cardiac_output(hr, sv)

        assert abs(sv - 80.0) < 0.001
        assert abs(ef - 61.538) < 0.01
        assert abs(co - 5.6) < 0.001

        # EF from SV and EDV must equal direct EF calculation
        ef_check = (sv / edv) * 100
        assert abs(ef - ef_check) < 1e-9

    def test_rr_and_qtc_consistency(self):
        hr = 70
        qt = 400
        rr = compute_rr_from_hr(hr)
        qtc = compute_qtc_bazett(qt, rr)
        # At 70 bpm, QTc from Bazett should be ~ 415–445 ms
        assert 400 < qtc < 480

    def test_map_formula_components(self):
        sbp, dbp = 120.0, 80.0
        m = compute_map(sbp, dbp)
        # MAP = (SBP + 2·DBP) / 3 — equivalent formula
        m_alt = (sbp + 2 * dbp) / 3
        assert abs(m - m_alt) < 1e-9
