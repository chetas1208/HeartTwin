"""Golden deterministic cardiac formula tests against synthetic fixtures.

Baseline:        SV 70, EF 58.33, CO 5.04, MAP 93.33, RR 833.33
Reduced function: SV 55, EF 36.67, CO 4.84, MAP 101.67, RR 681.82

Also covers impossible/invalid states. These formulas are the deterministic
core — the LLM never computes them.
"""

from __future__ import annotations

import pytest

from python.hearttwin.tools.cardiac_state import (
    compute_cardiac_output,
    compute_ejection_fraction,
    compute_map,
    compute_rr_from_hr,
    compute_stroke_volume,
)


# ---------------------------------------------------------------------------
# Baseline fixture
# ---------------------------------------------------------------------------


def test_baseline_sv(baseline_vitals, baseline_expected) -> None:
    sv = compute_stroke_volume(baseline_vitals["edv_ml"], baseline_vitals["esv_ml"])
    assert sv == pytest.approx(baseline_expected["sv_ml"], abs=0.01)


def test_baseline_ef(baseline_vitals, baseline_expected) -> None:
    ef = compute_ejection_fraction(baseline_vitals["edv_ml"], baseline_vitals["esv_ml"])
    assert ef == pytest.approx(baseline_expected["ef_pct"], abs=0.01)


def test_baseline_co(baseline_vitals, baseline_expected) -> None:
    sv = compute_stroke_volume(baseline_vitals["edv_ml"], baseline_vitals["esv_ml"])
    co = compute_cardiac_output(baseline_vitals["heart_rate_bpm"], sv)
    assert co == pytest.approx(baseline_expected["co_l_min"], abs=0.01)


def test_baseline_map(baseline_vitals, baseline_expected) -> None:
    m = compute_map(baseline_vitals["systolic_bp_mmhg"], baseline_vitals["diastolic_bp_mmhg"])
    assert m == pytest.approx(baseline_expected["map_mmhg"], abs=0.01)


def test_baseline_rr(baseline_vitals, baseline_expected) -> None:
    rr = compute_rr_from_hr(baseline_vitals["heart_rate_bpm"])
    assert rr == pytest.approx(baseline_expected["rr_interval_ms"], abs=0.01)


# ---------------------------------------------------------------------------
# Reduced function fixture
# ---------------------------------------------------------------------------


def test_reduced_sv(reduced_function_vitals, reduced_function_expected) -> None:
    sv = compute_stroke_volume(reduced_function_vitals["edv_ml"], reduced_function_vitals["esv_ml"])
    assert sv == pytest.approx(reduced_function_expected["sv_ml"], abs=0.01)


def test_reduced_ef(reduced_function_vitals, reduced_function_expected) -> None:
    ef = compute_ejection_fraction(reduced_function_vitals["edv_ml"], reduced_function_vitals["esv_ml"])
    assert ef == pytest.approx(reduced_function_expected["ef_pct"], abs=0.01)


def test_reduced_co(reduced_function_vitals, reduced_function_expected) -> None:
    sv = compute_stroke_volume(reduced_function_vitals["edv_ml"], reduced_function_vitals["esv_ml"])
    co = compute_cardiac_output(reduced_function_vitals["heart_rate_bpm"], sv)
    assert co == pytest.approx(reduced_function_expected["co_l_min"], abs=0.01)


def test_reduced_map(reduced_function_vitals, reduced_function_expected) -> None:
    m = compute_map(reduced_function_vitals["systolic_bp_mmhg"], reduced_function_vitals["diastolic_bp_mmhg"])
    assert m == pytest.approx(reduced_function_expected["map_mmhg"], abs=0.01)


def test_reduced_rr(reduced_function_vitals, reduced_function_expected) -> None:
    rr = compute_rr_from_hr(reduced_function_vitals["heart_rate_bpm"])
    assert rr == pytest.approx(reduced_function_expected["rr_interval_ms"], abs=0.01)


# ---------------------------------------------------------------------------
# Impossible / invalid states — the deterministic core REJECTS them (raises),
# rather than silently producing nonsense numbers.
# ---------------------------------------------------------------------------


def test_esv_greater_than_edv_rejected() -> None:
    with pytest.raises(ValueError):
        compute_stroke_volume(80.0, 100.0)


def test_esv_equal_edv_rejected() -> None:
    with pytest.raises(ValueError):
        compute_stroke_volume(100.0, 100.0)


def test_zero_hr_rejected_for_cardiac_output() -> None:
    with pytest.raises(ValueError):
        compute_cardiac_output(0.0, 70.0)


def test_negative_hr_rejected() -> None:
    with pytest.raises(ValueError):
        compute_cardiac_output(-5.0, 70.0)


def test_rr_from_nonpositive_hr_rejected() -> None:
    with pytest.raises(ValueError):
        compute_rr_from_hr(0.0)


def test_nonpositive_edv_rejected_for_ef() -> None:
    with pytest.raises(ValueError):
        compute_ejection_fraction(0.0, 0.0)


def test_diastolic_ge_systolic_rejected_for_map() -> None:
    with pytest.raises(ValueError):
        compute_map(90.0, 140.0)


def test_formulas_are_deterministic_repeated() -> None:
    a = compute_stroke_volume(120, 50)
    b = compute_stroke_volume(120, 50)
    assert a == b == 70.0
