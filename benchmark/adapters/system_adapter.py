"""System adapter — runs HeartTwin's real deterministic core on a case.

Uses the exact functions the agents wrap:
  - report text  -> tools.pdf_extract._extract_cardiac_values   (regex extractor)
  - user vitals  -> agents.extraction_agent._extract_user_vitals (sourced wrap)
  - EF/volume consistency -> tools.cardiac_state.check_ef_consistency
  - clinical request -> safety.check_request_safety
  - derived SV/EF/CO/MAP -> tools.cardiac_state (deterministic formulas)

Everything here is deterministic and offline. This is the capability we claim:
sourced extraction, abstention on missing data, consistency catching, and a hard
safety boundary — composed exactly as the pipeline composes them.
"""

from __future__ import annotations

from .common import AdapterOutput, Measurement

from python.hearttwin.tools.pdf_extract import _extract_cardiac_values
from python.hearttwin.agents.extraction_agent import _extract_user_vitals
from python.hearttwin.tools.cardiac_state import (
    check_ef_consistency,
    compute_cardiac_output,
    compute_ejection_fraction,
    compute_map,
    compute_stroke_volume,
)
from python.hearttwin.safety import check_request_safety, SafetyViolation

NAME = "HeartTwin"


def _num(meas: dict, field: str):
    v = meas.get(field)
    return v.get("value") if isinstance(v, dict) else None


def infer(case: dict) -> AdapterOutput:
    inp = case.get("input", {})
    out = AdapterOutput()

    # --- safety boundary (clinical requests must be refused) ---
    request_text = inp.get("request_text")
    if request_text is not None:
        try:
            check_request_safety(request_text)
            out.blocked = False
        except SafetyViolation:
            out.blocked = True
        return out

    # --- extraction: report text via the real regex extractor ---
    merged: dict[str, dict] = {}
    report_text = inp.get("report_text")
    if report_text:
        merged.update(_extract_cardiac_values(report_text, "report"))

    # --- vitals via the real sourced-wrap used by the extraction agent ---
    vitals = inp.get("vitals")
    if vitals:
        user_fields, _ = _extract_user_vitals(vitals)
        for fieldname, vdata in user_fields.items():
            if fieldname in merged and merged[fieldname].get("value") != vdata.get("value"):
                out.flags.append("conflict_detected")
            # higher-confidence (user_input=0.95) wins, mirroring the agent
            if fieldname not in merged or vdata.get("confidence", 0) >= merged[fieldname].get("confidence", 0):
                merged[fieldname] = vdata

    # --- derive SV/EF/CO/MAP deterministically when inputs exist ---
    edv, esv = _num(merged, "edv_ml"), _num(merged, "esv_ml")
    hr = _num(merged, "heart_rate_bpm")
    sbp, dbp = _num(merged, "systolic_bp_mmhg"), _num(merged, "diastolic_bp_mmhg")
    if edv is not None and esv is not None and esv < edv:
        sv = compute_stroke_volume(edv, esv)
        merged.setdefault("stroke_volume_ml", {
            "value": round(sv, 2), "source": "computed", "confidence": 0.9})
        merged.setdefault("ejection_fraction_pct_computed", {
            "value": round(compute_ejection_fraction(edv, esv), 2),
            "source": "computed", "confidence": 0.9})
        if hr is not None and hr > 0:
            merged.setdefault("cardiac_output_l_min", {
                "value": round(compute_cardiac_output(hr, sv), 2),
                "source": "computed", "confidence": 0.9})
    if sbp is not None and dbp is not None and dbp < sbp:
        merged.setdefault("map_mmhg", {
            "value": round(compute_map(sbp, dbp), 2), "source": "computed", "confidence": 0.9})

    # --- consistency: reported EF vs volumes ---
    ef_reported = _num(merged, "ejection_fraction_pct")
    if ef_reported is not None:
        consistent, _msg = check_ef_consistency(ef_reported, edv, esv)
        if not consistent:
            out.flags.append("ef_inconsistent")
    # --- consistency: BP ordering ---
    if sbp is not None and dbp is not None and dbp >= sbp:
        out.flags.append("bp_order_suspect")

    # map internal field -> common Measurement (drop the computed-EF alias name)
    for fieldname, vdata in merged.items():
        canonical = "ejection_fraction_pct" if fieldname == "ejection_fraction_pct_computed" \
            and "ejection_fraction_pct" not in merged else fieldname
        if canonical == fieldname or canonical not in merged:
            out.measurements[canonical] = Measurement(
                value=vdata.get("value"),
                source=vdata.get("source"),
                confidence=vdata.get("confidence"))

    out.flags = sorted(set(out.flags))
    return out
