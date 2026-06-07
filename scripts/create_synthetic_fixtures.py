#!/usr/bin/env python3
"""Generate synthetic, non-PHI cardiac fixtures for HeartTwin Lab tests.

All output is synthetic and inspired by the *structure* of public datasets
(EchoNet-Dynamic, PTB-XL, CAMUS, ACDC). No real patient data is used or
downloaded. Safe to run offline and idempotently.

Usage:
    python scripts/create_synthetic_fixtures.py
"""

from __future__ import annotations

import json
import math
import pathlib

FIXTURE_DIR = pathlib.Path(__file__).resolve().parent.parent / "fixtures" / "hearttwin"

SAFETY_NOTE = (
    "Educational cardiac simulation only. Not for diagnosis or treatment decisions."
)


# ---------------------------------------------------------------------------
# JSON / text fixtures (idempotent — only written if missing or changed)
# ---------------------------------------------------------------------------

_MANUAL_BASELINE = {
    "fixture_id": "manual_baseline",
    "description": "Baseline cardiac function simulation input (synthetic, non-PHI).",
    "label": "baseline simulation input",
    "user_vitals": {
        "heart_rate_bpm": 72,
        "systolic_bp_mmhg": 120,
        "diastolic_bp_mmhg": 80,
        "edv_ml": 120,
        "esv_ml": 50,
        "oxygen_saturation_pct": 98,
    },
    "expected_deterministic": {
        "sv_ml": 70.0,
        "ef_pct": 58.33,
        "co_l_min": 5.04,
        "map_mmhg": 93.33,
        "rr_interval_ms": 833.33,
    },
    "safety_note": SAFETY_NOTE,
}

_MANUAL_REDUCED = {
    "fixture_id": "manual_reduced_function",
    "description": "Reduced pump function simulation input (synthetic, non-PHI). Not a diagnosis.",
    "label": "reduced pump function simulation input",
    "user_vitals": {
        "heart_rate_bpm": 88,
        "systolic_bp_mmhg": 135,
        "diastolic_bp_mmhg": 85,
        "edv_ml": 150,
        "esv_ml": 95,
        "oxygen_saturation_pct": 96,
    },
    "expected_deterministic": {
        "sv_ml": 55.0,
        "ef_pct": 36.67,
        "co_l_min": 4.84,
        "map_mmhg": 101.67,
        "rr_interval_ms": 681.82,
    },
    "safety_note": SAFETY_NOTE,
}

_MANUAL_PARTIAL = {
    "fixture_id": "manual_partial_data",
    "description": "Partial data stress test (synthetic, non-PHI). EDV/ESV intentionally missing.",
    "label": "partial data simulation input",
    "user_vitals": {
        "heart_rate_bpm": 92,
        "systolic_bp_mmhg": 142,
        "diastolic_bp_mmhg": 90,
        "ejection_fraction_pct": 45,
    },
    "expected_behavior": {
        "no_crash": True,
        "edv_available": False,
        "esv_available": False,
        "sv_invented_without_prior": False,
        "warning_expected": True,
        "operation": "runs_with_labeled_priors_or_blocks_with_reason",
        "recovery_uncertainty": "high_or_blocked_with_reason",
    },
    "safety_note": SAFETY_NOTE,
}

_REPORT_BASELINE = """Synthetic educational cardiac report.
Heart rate: 72 bpm.
Blood pressure: 120/80 mmHg.
End-diastolic volume: 120 mL.
End-systolic volume: 50 mL.
Reported ejection fraction: 58%.
Oxygen saturation: 98%.
This synthetic text is for software testing only.
"""

_REPORT_REDUCED = """Synthetic educational cardiac report.
Heart rate: 88 bpm.
Blood pressure: 135/85 mmHg.
End-diastolic volume: 150 mL.
End-systolic volume: 95 mL.
Reported ejection fraction: 37%.
Oxygen saturation: 96%.
Reported clinical terms may appear in real reports, but this fixture does not diagnose.
This synthetic text is for software testing only.
"""

_REPORT_PARTIAL = """Synthetic educational cardiac report.
Heart rate: 92 bpm.
Blood pressure: 142/90 mmHg.
Reported ejection fraction: 45%.
EDV and ESV are not provided.
This synthetic text is for software testing only.
"""

_ECHO_BASELINE = {
    "source": "synthetic_echo_metadata",
    "modality": "echocardiogram",
    "view": "apical_4_chamber",
    "edv_ml": 120,
    "esv_ml": 50,
    "ejection_fraction_pct": 58,
    "lv_tracing_available": True,
    "frames": {"end_diastole": 12, "end_systole": 27},
    "safety_note": "Synthetic metadata inspired by public echo dataset structure. Not patient data. Not for diagnosis.",
}

_ECHO_REDUCED = {
    "source": "synthetic_echo_metadata",
    "modality": "echocardiogram",
    "view": "apical_4_chamber",
    "edv_ml": 150,
    "esv_ml": 95,
    "ejection_fraction_pct": 37,
    "lv_tracing_available": True,
    "frames": {"end_diastole": 14, "end_systole": 31},
    "safety_note": "Synthetic metadata inspired by public echo dataset structure. Reduced pump function simulation input. Not patient data. Not for diagnosis.",
}

_VISTA_SUCCESS = {
    "status": "success",
    "request_id": "vista-synthetic-001",
    "classes_detected": ["heart", "left ventricle", "right ventricle", "myocardium"],
    "masks": [
        {
            "class": "left ventricle",
            "mask_uri": "synthetic://vista/lv-mask.nii.gz",
            "volume_proxy_ml": 120,
        }
    ],
    "measurements": {"lv_volume_proxy_ml": 120, "myocardium_volume_proxy_ml": 155},
    "preview_uri": "synthetic://vista/preview.png",
    "warnings": [],
    "confidence": 0.82,
}

_VISTA_FAILURE = {
    "status": "failed",
    "request_id": "vista-synthetic-fail",
    "classes_detected": [],
    "masks": [],
    "measurements": {},
    "preview_uri": None,
    "warnings": ["Synthetic VISTA endpoint failure for test coverage."],
    "confidence": None,
}


def _synthetic_ecg(heart_rate_bpm: float, duration_s: float = 10.0, fs_hz: float = 250.0) -> str:
    """Generate a deterministic synthetic ECG-like waveform CSV string.

    Not clinically faithful — only exercises CSV parsing, chart rendering, and
    the R-peak detection / HR-RR estimate code path. Each beat is a Gaussian
    QRS spike with a small baseline wander and T-wave bump.
    """
    rr_s = 60.0 / heart_rate_bpm
    n = int(duration_s * fs_hz)
    lines = ["time_ms,lead_ii_mv"]
    for i in range(n):
        t = i / fs_hz
        # baseline wander
        v = 0.05 * math.sin(2 * math.pi * 0.25 * t)
        # phase within current beat
        phase = (t % rr_s)
        # QRS spike near start of beat
        v += 1.2 * math.exp(-((phase - 0.02) ** 2) / (2 * 0.008 ** 2))
        # small Q dip just before R
        v -= 0.15 * math.exp(-((phase - 0.0) ** 2) / (2 * 0.006 ** 2))
        # T wave bump later in the beat
        v += 0.25 * math.exp(-((phase - 0.30) ** 2) / (2 * 0.04 ** 2))
        lines.append(f"{round(t * 1000.0, 2)},{round(v, 4)}")
    return "\n".join(lines) + "\n"


def _write_json(path: pathlib.Path, obj: dict) -> bool:
    content = json.dumps(obj, indent=2) + "\n"
    return _write_if_changed(path, content)


def _write_if_changed(path: pathlib.Path, content: str) -> bool:
    if path.exists() and path.read_text() == content:
        return False
    path.write_text(content)
    return True


def main() -> int:
    FIXTURE_DIR.mkdir(parents=True, exist_ok=True)
    written: list[str] = []

    targets = [
        (FIXTURE_DIR / "manual_baseline.json", json.dumps(_MANUAL_BASELINE, indent=2) + "\n"),
        (FIXTURE_DIR / "manual_reduced_function.json", json.dumps(_MANUAL_REDUCED, indent=2) + "\n"),
        (FIXTURE_DIR / "manual_partial_data.json", json.dumps(_MANUAL_PARTIAL, indent=2) + "\n"),
        (FIXTURE_DIR / "report_baseline.txt", _REPORT_BASELINE),
        (FIXTURE_DIR / "report_reduced_function.txt", _REPORT_REDUCED),
        (FIXTURE_DIR / "report_partial_data.txt", _REPORT_PARTIAL),
        (FIXTURE_DIR / "echo_metadata_baseline.json", json.dumps(_ECHO_BASELINE, indent=2) + "\n"),
        (FIXTURE_DIR / "echo_metadata_reduced_function.json", json.dumps(_ECHO_REDUCED, indent=2) + "\n"),
        (FIXTURE_DIR / "vista3d_success_response.json", json.dumps(_VISTA_SUCCESS, indent=2) + "\n"),
        (FIXTURE_DIR / "vista3d_failure_response.json", json.dumps(_VISTA_FAILURE, indent=2) + "\n"),
        (FIXTURE_DIR / "ecg_synthetic_normal.csv", _synthetic_ecg(72.0)),
        (FIXTURE_DIR / "ecg_synthetic_fast.csv", _synthetic_ecg(120.0)),
    ]

    for path, content in targets:
        if _write_if_changed(path, content):
            written.append(path.name)

    if written:
        print(f"Generated/updated {len(written)} fixture(s): {', '.join(written)}")
    else:
        print("All fixtures already up to date.")
    print(f"Fixture directory: {FIXTURE_DIR}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
