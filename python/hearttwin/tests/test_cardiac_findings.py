"""Tests for the deterministic cardiac findings layer.

Findings localize the simulated state to anatomy (AHA 17-segment model +
coronary territory) as educational observations — never a diagnosis — so they
must (a) localize correctly, (b) carry reference codes + a 3D anchor, and
(c) never contain blocked diagnostic language.
"""

from __future__ import annotations

import re

from python.hearttwin.safety import _BLOCKED_PATTERNS
from python.hearttwin.tools.cardiac_findings import derive_findings


def _viz(ef=58.0, scar=0.0, qrs=95.0, qtc=420.0):
    return {
        "summary": {"ef_pct": ef},
        "3d_heart": {"scar_fraction": scar},
        "electrophysiology": {"qrs_duration_ms": qrs, "qtc_ms": qtc},
    }


def _state(damage_zone=None, scar=None):
    tissue = {}
    if damage_zone is not None:
        tissue["damage_zone_location"] = damage_zone
    if scar is not None:
        tissue["scar_fraction"] = {"value": scar, "unit": "fraction", "source": "file_extraction"}
    return {"tissue_state": tissue, "source_map": []}


def test_normal_state_has_no_findings() -> None:
    out = derive_findings(_state(), _viz(ef=58.0))
    assert out["findings"] == []
    assert out["segment_model"] == "AHA 17-segment"
    assert out["imaging_source"] == "none"


def test_reduced_ef_produces_global_finding() -> None:
    out = derive_findings(_state(), _viz(ef=35.0))
    glob = [f for f in out["findings"] if f["id"] == "global_systolic"]
    assert len(glob) == 1
    assert glob[0]["severity"] == "moderate"  # 30 <= 35 < 40
    assert "anchor" in glob[0] and set(glob[0]["anchor"]) == {"x", "y", "z"}
    assert glob[0]["aha_segments"] == list(range(1, 18))


def test_anterior_damage_zone_maps_to_lad_segments() -> None:
    out = derive_findings(
        _state(damage_zone="anterior wall hypokinesis", scar=0.22),
        _viz(ef=42.0, scar=0.22),
    )
    regional = [f for f in out["findings"] if f["id"].startswith("regional_")]
    assert len(regional) == 1
    f = regional[0]
    assert f["territory"] == "LAD"
    assert f["aha_segments"] == [1, 7, 13]
    assert f["severity"] == "moderate"  # 0.1 <= 0.22 < 0.25
    codes = {c["system"]: c["code"] for c in f["codes"]}
    assert codes["Coronary territory"] == "LAD"
    assert codes["AHA 17-segment model"] == "1,7,13"


def test_inferior_damage_zone_maps_to_rca() -> None:
    out = derive_findings(_state(damage_zone="inferior", scar=0.3), _viz(ef=48.0, scar=0.3))
    regional = [f for f in out["findings"] if f["id"].startswith("regional_")]
    assert regional and regional[0]["territory"] == "RCA"
    assert regional[0]["severity"] == "severe"  # >= 0.25


def test_widened_qrs_produces_conduction_finding() -> None:
    out = derive_findings(_state(), _viz(ef=55.0, qrs=140.0))
    qrs = [f for f in out["findings"] if f["id"] == "conduction_qrs"]
    assert len(qrs) == 1
    assert "QRS" in qrs[0]["title"]


def test_prolonged_qtc_produces_repolarization_finding() -> None:
    out = derive_findings(_state(), _viz(ef=55.0, qtc=480.0))
    qtc = [f for f in out["findings"] if f["id"] == "repolarization_qtc"]
    assert len(qtc) == 1


def test_imaging_source_detects_vista() -> None:
    state = {
        "tissue_state": {},
        "source_map": [{"source": "vista3d_segmentation", "method": "segmentation"}],
    }
    assert derive_findings(state, _viz())["imaging_source"] == "vista3d_segmentation"


def test_findings_contain_no_blocked_diagnostic_language() -> None:
    # Drive every finding type at once, then scan all human-readable text.
    out = derive_findings(
        _state(damage_zone="anteroseptal", scar=0.3),
        _viz(ef=28.0, scar=0.3, qrs=160.0, qtc=510.0),
    )
    assert len(out["findings"]) >= 3
    # Scan the observational content (not the disclaimer, which intentionally
    # contains the approved word "diagnosis").
    blob_parts: list[str] = []
    for f in out["findings"]:
        blob_parts.extend([str(f.get("title", "")), str(f.get("summary", "")), str(f.get("region", ""))])
    blob = " ".join(blob_parts)
    for pattern in _BLOCKED_PATTERNS:
        assert re.search(pattern, blob, re.IGNORECASE) is None, f"blocked term matched: {pattern}"
