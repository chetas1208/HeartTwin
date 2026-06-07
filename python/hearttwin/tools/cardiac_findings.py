"""Deterministic cardiac findings layer.

Turns the simulated ``CardiacTwinState`` + visualization payload into
anatomically-localized, code-tagged findings for the 3D heart view and for
clinicians reading the output.

Every finding is an EDUCATIONAL SIMULATION OBSERVATION carrying *reference*
cardiology terminology — the AHA 17-segment left-ventricle model, the coronary
artery territory, and the anatomical wall — NOT a clinical diagnosis. No
diagnostic verbs are used, so the output is consistent with the strict safety
posture (see ``safety.py``).

For each finding the frontend gets:
  * a region/wall label and the coronary territory,
  * the AHA segment numbers it covers,
  * a normalized 3D ``anchor`` (x,y,z in [-1,1]) to place a callout on the mesh,
  * a severity band, a brief observational summary, the driving metric,
  * reference ``codes``, and the data ``source``.

The mapping of walls → coronary territory → AHA segments follows the standard
AHA 17-segment model (Cerqueira et al., Circulation 2002).
"""

from __future__ import annotations

from typing import Any, Optional

MODEL_VERSION = "deterministic-cardiac-findings-v1"

DISCLAIMER = (
    "Educational simulation observations with reference cardiology terminology "
    "(AHA 17-segment model, coronary artery territory). Not a clinical diagnosis."
)

TERRITORY_LABEL = {
    "LAD": "Left anterior descending artery territory",
    "RCA": "Right coronary artery territory",
    "LCx": "Left circumflex artery territory",
}

# wall keyword -> (territory, wall display name, AHA segments, 3D anchor)
# Anchors are in a normalized heart space: +z front (anterior), -z back
# (inferior/posterior), +x patient-left (lateral), -x septal, -y apex.
WALL_MAP: dict[str, tuple[str, str, list[int], dict[str, float]]] = {
    "anteroseptal": ("LAD", "Anteroseptal wall", [2, 8, 14], {"x": -0.3, "y": 0.1, "z": 0.7}),
    "anterior": ("LAD", "Anterior wall", [1, 7, 13], {"x": 0.0, "y": 0.2, "z": 0.95}),
    "apical": ("LAD", "Apex", [13, 14, 15, 16, 17], {"x": 0.0, "y": -0.9, "z": 0.3}),
    "apex": ("LAD", "Apex", [13, 14, 15, 16, 17], {"x": 0.0, "y": -0.9, "z": 0.3}),
    "inferoseptal": ("RCA", "Inferoseptal wall", [3, 9], {"x": -0.3, "y": -0.2, "z": -0.5}),
    "inferior": ("RCA", "Inferior wall", [4, 10, 15], {"x": 0.0, "y": -0.4, "z": -0.8}),
    "posterolateral": ("LCx", "Posterolateral wall", [5, 11], {"x": 0.6, "y": -0.2, "z": -0.6}),
    "posterior": ("LCx", "Posterolateral wall", [5, 11], {"x": 0.6, "y": -0.2, "z": -0.6}),
    "lateral": ("LCx", "Lateral wall", [5, 6, 11, 12, 16], {"x": 0.9, "y": 0.0, "z": 0.0}),
    "septal": ("LAD", "Septum", [2, 3, 8, 9, 14], {"x": -0.4, "y": 0.0, "z": 0.2}),
    "septum": ("LAD", "Septum", [2, 3, 8, 9, 14], {"x": -0.4, "y": 0.0, "z": 0.2}),
}


def _num(value: Any) -> Optional[float]:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        f = float(value)
        return f if f == f else None  # drop NaN
    if isinstance(value, str):
        try:
            return float(value)
        except ValueError:
            return None
    return None


def _measured(value: Any) -> Optional[float]:
    """Read a MeasuredValue (dict with `value`) or a plain number."""
    if isinstance(value, dict):
        return _num(value.get("value"))
    return _num(value)


def _match_wall(text: str) -> Optional[str]:
    """Return the first matching wall key (most specific first)."""
    low = text.lower()
    for key in WALL_MAP:  # dict preserves insertion order: specific before generic
        if key in low:
            return key
    return None


def _finding(**kw: Any) -> dict[str, Any]:
    kw.setdefault("educational", True)
    return kw


def _imaging_source(state: Optional[dict[str, Any]]) -> str:
    """Honest report of what imaging actually informed the state."""
    if not state:
        return "none"
    source_map = state.get("source_map") or []
    saw_vista = False
    saw_image = False
    for entry in source_map:
        if not isinstance(entry, dict):
            continue
        src = str(entry.get("source", "")).lower()
        method = str(entry.get("method", "")).lower()
        if "vista" in src or "segment" in method:
            saw_vista = True
        if "image" in method or "vision" in method or "image" in src:
            saw_image = True
    if saw_vista:
        return "vista3d_segmentation"
    if saw_image:
        return "image_extraction"
    return "none"


def _scar_severity(scar: Optional[float]) -> str:
    if scar is None:
        return "info"
    if scar >= 0.25:
        return "severe"
    if scar >= 0.1:
        return "moderate"
    if scar > 0.0:
        return "mild"
    return "info"


def derive_findings(
    state: Optional[dict[str, Any]],
    visualization: Optional[dict[str, Any]],
) -> dict[str, Any]:
    """Build the structured, code-tagged educational findings payload.

    `state` is a CardiacTwinState dump (or None); `visualization` is the operate
    visualization payload (summary / 3d_heart / electrophysiology).
    """
    viz = visualization or {}
    summary = viz.get("summary") or {}
    heart3d = viz.get("3d_heart") or {}
    ep = viz.get("electrophysiology") or {}
    tissue = (state or {}).get("tissue_state") or {}

    findings: list[dict[str, Any]] = []

    # 1. Global LV systolic function from ejection fraction.
    ef = _num(summary.get("ef_pct"))
    if ef is not None:
        sev = "severe" if ef < 30 else "moderate" if ef < 40 else "mild" if ef < 50 else None
        if sev:
            findings.append(_finding(
                id="global_systolic",
                title=f"Reduced ejection fraction ({ef:.0f}%)",
                region="Left ventricle (global)",
                territory=None,
                aha_segments=list(range(1, 18)),
                anchor={"x": 0.0, "y": -0.1, "z": 0.55},
                severity=sev,
                summary=(
                    f"Simulation shows globally reduced left-ventricular systolic "
                    f"function (ejection fraction {ef:.0f}%)."
                ),
                metric=f"EF {ef:.0f}%",
                codes=[
                    {"system": "AHA 17-segment model", "code": "1-17", "label": "Global left ventricle"},
                ],
                source="visualization.summary.ef_pct",
            ))

    # 2. Regional wall change localized from damage_zone_location + scar_fraction.
    damage_zone = tissue.get("damage_zone_location")
    scar = _measured(tissue.get("scar_fraction"))
    if scar is None:
        scar = _num(heart3d.get("scar_fraction"))
    if isinstance(damage_zone, str) and damage_zone.strip():
        key = _match_wall(damage_zone)
        if key:
            territory, wall, segments, anchor = WALL_MAP[key]
            findings.append(_finding(
                id=f"regional_{key}",
                title=f"{wall} regional change",
                region=wall,
                territory=territory,
                aha_segments=segments,
                anchor=anchor,
                severity=_scar_severity(scar),
                summary=(
                    f"Simulation localizes reduced regional wall motion to the "
                    f"{wall.lower()} ({TERRITORY_LABEL[territory]})."
                ),
                metric=(
                    f"scar fraction {scar:.2f}" if scar is not None
                    else f"reported zone: {damage_zone}"
                ),
                codes=[
                    {
                        "system": "AHA 17-segment model",
                        "code": ",".join(str(s) for s in segments),
                        "label": f"{wall} segments",
                    },
                    {"system": "Coronary territory", "code": territory, "label": TERRITORY_LABEL[territory]},
                ],
                source="state.tissue_state.damage_zone_location + scar_fraction",
            ))

    # 3. Conduction / repolarization observations from the electrophysiology output.
    qrs = _num(ep.get("qrs_duration_ms"))
    if qrs is not None and qrs > 120:
        findings.append(_finding(
            id="conduction_qrs",
            title=f"Widened QRS ({qrs:.0f} ms)",
            region="Interventricular conduction system",
            territory=None,
            aha_segments=[2, 3, 8, 9, 14],
            anchor={"x": -0.4, "y": 0.0, "z": 0.2},
            severity="moderate" if qrs >= 150 else "mild",
            summary=(
                f"Simulation shows widened ventricular depolarization "
                f"(QRS {qrs:.0f} ms), reflecting slowed intraventricular conduction."
            ),
            metric=f"QRS {qrs:.0f} ms",
            codes=[{"system": "ECG interval", "code": "QRS", "label": "QRS duration"}],
            source="visualization.electrophysiology.qrs_duration_ms",
        ))

    qtc = _num(ep.get("qtc_ms"))
    if qtc is not None and qtc > 460:
        findings.append(_finding(
            id="repolarization_qtc",
            title=f"Prolonged QTc ({qtc:.0f} ms)",
            region="Ventricular repolarization",
            territory=None,
            aha_segments=[],
            anchor={"x": 0.0, "y": -0.5, "z": 0.4},
            severity="moderate" if qtc >= 500 else "mild",
            summary=(
                f"Simulation shows prolonged ventricular repolarization "
                f"(QTc {qtc:.0f} ms, Bazett)."
            ),
            metric=f"QTc {qtc:.0f} ms",
            codes=[{"system": "ECG interval", "code": "QTc", "label": "Corrected QT interval"}],
            source="visualization.electrophysiology.qtc_ms",
        ))

    return {
        "findings": findings,
        "imaging_source": _imaging_source(state),
        "segment_model": "AHA 17-segment",
        "disclaimer": DISCLAIMER,
        "model": MODEL_VERSION,
    }
