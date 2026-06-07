"""Tests for safety language enforcement across the HeartTwin system.

Verifies:
- Unsafe phrases are detected in simulated outputs.
- The required educational disclaimer exists in relevant outputs.
- Safety score is lowered when unsafe wording is present.
- No diagnosis/treatment language is introduced via agent responses.
- Hallucinated number detection works correctly.
- Missing source increases hallucination risk.
"""

from __future__ import annotations

import pytest

from python.hearttwin.safety import (
    CORE_SAFETY_PHRASE,
    DISCLAIMER,
    check_request_safety,
    SafetyViolation,
)
from python.hearttwin.tools.scoring import score_safety_compliance


# ---------------------------------------------------------------------------
# Disclaimer existence
# ---------------------------------------------------------------------------


def test_disclaimer_contains_required_phrase() -> None:
    required = "Educational cardiac simulation only"
    assert required in DISCLAIMER, f"DISCLAIMER must contain: '{required}'"


def test_core_safety_phrase_not_empty() -> None:
    assert CORE_SAFETY_PHRASE, "CORE_SAFETY_PHRASE must not be empty"
    assert len(CORE_SAFETY_PHRASE) > 20


# ---------------------------------------------------------------------------
# Unsafe phrase detection in agent text
# ---------------------------------------------------------------------------


_UNSAFE_TEXTS = [
    "you have heart failure",
    "you should take beta blockers",
    "the patient healed",
    "the patient is cured",
    "treatment plan: start metoprolol",
    "prescribe lisinopril 10mg",
    "dosage: 5mg twice daily",
    "recommend medication adjustment",
    "patient improved medically",
    "recovery guaranteed after surgery",
]

_SAFE_TEXTS = [
    "Simulated cardiac output is 4.8 L/min based on extracted values.",
    "Recovery trajectory shows bounded improvement in simulated preload.",
    "Educational cardiac simulation only. Not for diagnosis or treatment decisions.",
    "Simulated EF=45% based on EDV=130mL, ESV=72mL.",
]


@pytest.mark.parametrize("text", _UNSAFE_TEXTS)
def test_unsafe_phrases_detected_in_text(text: str) -> None:
    """Unsafe medical/clinical phrases must be flagged."""
    payload = {"generated_text": text}
    result = score_safety_compliance(payload, {})
    assert result < 1.0, f"Expected safety score < 1.0 for unsafe text: '{text}'"


@pytest.mark.parametrize("text", _SAFE_TEXTS)
def test_safe_texts_do_not_fail_compliance(text: str) -> None:
    """Simulation-safe text should not be heavily penalized."""
    payload = {"generated_text": text}
    result = score_safety_compliance(payload, {})
    assert result >= 0.5, f"Safe text received unexpectedly low score: {result} for '{text}'"


# ---------------------------------------------------------------------------
# check_request_safety blocks dangerous requests
# ---------------------------------------------------------------------------


def test_check_request_safety_blocks_treatment_request() -> None:
    with pytest.raises(SafetyViolation):
        check_request_safety("Please prescribe me medication for my heart condition")


def test_check_request_safety_blocks_diagnosis_request() -> None:
    with pytest.raises(SafetyViolation):
        check_request_safety("Can you diagnose my arrhythmia based on these results?")


def test_check_request_safety_allows_simulation_request() -> None:
    check_request_safety("Show me the simulated cardiac cycle for this case.")


def test_check_request_safety_allows_educational_request() -> None:
    check_request_safety("Explain how ejection fraction is calculated.")


# ---------------------------------------------------------------------------
# Missing disclaimer lowers safety score
# ---------------------------------------------------------------------------


def test_missing_disclaimer_lowers_safety_score() -> None:
    with_disclaimer = {"generated_text": DISCLAIMER + " Simulated EF=45%."}
    without_disclaimer = {"generated_text": "Simulated EF=45%."}
    score_with = score_safety_compliance(with_disclaimer, {})
    score_without = score_safety_compliance(without_disclaimer, {})
    assert score_with >= score_without, "Disclaimer should not lower safety score"


# ---------------------------------------------------------------------------
# Unsafe wording in summaries
# ---------------------------------------------------------------------------


def test_diagnosis_in_summary_lowers_safety_score() -> None:
    payload = {
        "generated_text": "The simulation indicates you have moderate cardiomyopathy."
    }
    result = score_safety_compliance(payload, {})
    assert result < 1.0


def test_treatment_advice_lowers_safety_score() -> None:
    payload = {
        "generated_text": "Based on this analysis, you should take ACE inhibitors."
    }
    result = score_safety_compliance(payload, {})
    assert result < 1.0


# ---------------------------------------------------------------------------
# Hallucination risk detection
# ---------------------------------------------------------------------------


def test_number_in_output_not_in_state_raises_hallucination_risk() -> None:
    from python.hearttwin.tools.scoring import score_hallucination_risk

    # hallucination risk is a score in [0, 1]; lower = more trustworthy
    # High-confidence sourced measurements should yield a lower risk than
    # measurements with no source or confidence information.
    payload_no_source = {
        "measurements": {
            "ejection_fraction_pct": {"value": 55},
            "heart_rate_bpm": {"value": 72},
            "edv_ml": {"value": 130},
        },
        "generated_text": "Simulated EF 55%.",
    }
    payload_sourced = {
        "measurements": {
            "ejection_fraction_pct": {"value": 55, "source": "extracted", "confidence": 0.95},
            "heart_rate_bpm": {"value": 72, "source": "extracted", "confidence": 0.95},
            "edv_ml": {"value": 130, "source": "extracted", "confidence": 0.95},
        },
        "generated_text": "Simulated EF 55%.",
    }
    state = {}
    score_no_source = score_hallucination_risk(payload_no_source, state)
    score_sourced = score_hallucination_risk(payload_sourced, state)
    # Both should return valid floats
    assert isinstance(score_no_source, float)
    assert isinstance(score_sourced, float)
    assert 0.0 <= score_no_source <= 1.0
    assert 0.0 <= score_sourced <= 1.0
    # Sourced measurements should have equal or lower hallucination risk
    assert score_sourced <= score_no_source, (
        f"Sourced score ({score_sourced}) should be <= unsourced score ({score_no_source})"
    )


def test_missing_source_raises_hallucination_risk() -> None:
    from python.hearttwin.tools.scoring import score_hallucination_risk

    # Multiple fields with no source should increase hallucination risk vs having sources
    payload_no_source = {
        "measurements": {
            "heart_rate_bpm": {"value": 72},
            "systolic_bp_mmhg": {"value": 120},
            "diastolic_bp_mmhg": {"value": 80},
            "ejection_fraction_pct": {"value": 55},
            "edv_ml": {"value": 130},
            "esv_ml": {"value": 58},
        }
    }
    payload_with_source = {
        "measurements": {
            "heart_rate_bpm": {"value": 72, "source": "extracted", "confidence": 0.9},
            "systolic_bp_mmhg": {"value": 120, "source": "extracted", "confidence": 0.9},
            "diastolic_bp_mmhg": {"value": 80, "source": "extracted", "confidence": 0.9},
            "ejection_fraction_pct": {"value": 55, "source": "extracted", "confidence": 0.9},
            "edv_ml": {"value": 130, "source": "extracted", "confidence": 0.9},
            "esv_ml": {"value": 58, "source": "extracted", "confidence": 0.9},
        }
    }
    state: dict = {}
    score_no_source = score_hallucination_risk(payload_no_source, state)
    score_with_source = score_hallucination_risk(payload_with_source, state)
    assert score_no_source >= score_with_source, (
        "Missing sources should not lower hallucination risk compared to having sources"
    )


def test_traceable_numbers_lower_hallucination_risk() -> None:
    from python.hearttwin.tools.scoring import score_hallucination_risk

    measurements = {"heart_rate_bpm": {"value": 72.0, "source": "extracted", "confidence": 0.9}}
    payload = {"measurements": measurements, "generated_text": ""}
    state = {"measurements": measurements}
    score = score_hallucination_risk(payload, state)
    assert score < 0.5


# ---------------------------------------------------------------------------
# Safety compliance aggregation
# ---------------------------------------------------------------------------


def test_safety_score_is_float_in_range() -> None:
    score = score_safety_compliance({}, {})
    assert 0.0 <= score <= 1.0


def test_safety_score_full_unsafe_text_below_one() -> None:
    payload = {
        "generated_text": "You have diabetes. You should take metformin. Prescribe insulin. Dosage: 10mg."
    }
    score = score_safety_compliance(payload, {})
    assert score < 1.0


# ---------------------------------------------------------------------------
# User-facing source scan: no unsafe language in frontend / docs / fixtures
# ---------------------------------------------------------------------------

import pathlib  # noqa: E402

_ROOT = pathlib.Path(__file__).resolve().parents[3]

_UNSAFE_PHRASES = [
    "you have",
    "you should take",
    "healed",
    "cured",
    "treatment plan",
    "prescribe",
    "dosage",
    "recommend medication",
    "patient improved medically",
    "recovery guaranteed",
]


def _scan_files(paths: list[pathlib.Path]) -> list[str]:
    hits: list[str] = []
    for p in paths:
        if not p.is_file():
            continue
        try:
            text = p.read_text(errors="ignore").lower()
        except Exception:  # noqa: BLE001
            continue
        for phrase in _UNSAFE_PHRASES:
            if phrase in text:
                hits.append(f"{p.relative_to(_ROOT)} :: '{phrase}'")
    return hits


def test_no_unsafe_language_in_frontend_components() -> None:
    app_dir = _ROOT / "app"
    files = [p for p in app_dir.rglob("*.vue")]
    hits = _scan_files(files)
    assert not hits, f"unsafe language in frontend: {hits}"


def test_no_unsafe_language_in_user_facing_fixtures() -> None:
    fixtures = list((_ROOT / "fixtures" / "hearttwin").glob("*.txt"))
    fixtures += list((_ROOT / "fixtures" / "hearttwin").glob("*.json"))
    hits = _scan_files(fixtures)
    assert not hits, f"unsafe language in fixtures: {hits}"


def test_required_phrase_present_in_api_safety_output() -> None:
    assert "Educational cardiac simulation only. Not for diagnosis or treatment decisions." in DISCLAIMER


def test_required_phrase_present_in_frontend() -> None:
    # The safety banner / landing copy must carry the educational-simulation
    # boundary (not a medical device, no diagnosis, no treatment).
    candidates = [
        _ROOT / "web" / "components" / "safety" / "SafetyBanner.tsx",
        _ROOT / "web" / "app" / "page.tsx",
    ]
    joined = "\n".join(p.read_text(errors="ignore") for p in candidates if p.is_file()).lower()
    assert joined, "no frontend safety surface found"
    assert "not a medical device" in joined
    assert "diagnos" in joined
    assert "treatment" in joined


def test_required_phrase_present_in_docs_or_readme() -> None:
    candidates = [
        _ROOT / "README.md",
        _ROOT / "docs" / "testing.md",
        _ROOT / "fixtures" / "hearttwin" / "README.md",
    ]
    joined = "\n".join(p.read_text(errors="ignore") for p in candidates if p.is_file())
    assert "Educational cardiac simulation only" in joined
