"""Whole-system adapter — runs the ENTIRE 8-agent HeartTwin pipeline on a case.

Unlike system_adapter.py (which exercises only the deterministic core), this runs
`orchestrator.run_full_pipeline` end-to-end: intake/safety -> extraction ->
validation -> state builder -> electrophysiology + hemodynamics -> recovery ->
evaluator. VISTA-3D stays disabled. The pipeline's optional LLM agent steps fall
back to deterministic logic when no key is set.

Inputs a case may carry (any combination):
  input.ecg_csv        path to a time_ms,ecg waveform CSV  -> ECG analysis
  input.report_text    free-text report                    -> regex extraction
  input.vitals         structured vitals dict              -> sourced extraction
  input.request_text   a user request                      -> safety boundary
"""

from __future__ import annotations

import asyncio
from pathlib import Path

from .common import AdapterOutput, Measurement

from python.hearttwin.orchestrator import run_full_pipeline

NAME = "HeartTwin-pipeline"
BENCH_ROOT = Path(__file__).resolve().parent.parent  # benchmark/

_RHYTHM_MAP = [
    ("irregular", "irregular"),
    ("tachycard", "tachy"),
    ("bradycard", "brady"),
    ("regular", "regular"),
    ("sinus", "regular"),
]


def _rhythm_category(label: str | None) -> str | None:
    if not label:
        return None
    low = label.lower()
    for needle, cat in _RHYTHM_MAP:
        if needle in low:
            return cat
    return None


def _mval(meas: dict, field: str):
    v = meas.get(field)
    return (v.get("value"), v.get("source"), v.get("confidence")) if isinstance(v, dict) else (None, None, None)


_LOOP = None


def _loop():
    # one persistent loop across all cases — avoids "Event loop is closed" noise
    # from httpx async clients created by the pipeline's optional agent LLM calls.
    global _LOOP
    if _LOOP is None:
        _LOOP = asyncio.new_event_loop()
    return _LOOP


def infer(case: dict) -> AdapterOutput:
    return _loop().run_until_complete(_infer_async(case))


async def _infer_async(case: dict) -> AdapterOutput:
    inp = case.get("input", {})
    out = AdapterOutput()

    files = []
    ecg_csv = inp.get("ecg_csv")
    if ecg_csv:
        path = (BENCH_ROOT / ecg_csv).resolve()
        files.append({"file_id": "ecg1", "filename": path.name,
                      "content_type": "text/csv", "bytes": path.read_bytes()})

    res = await run_full_pipeline(
        files=files,
        user_vitals=inp.get("vitals"),
        user_request_text=inp.get("request_text"),
    )

    status = res.get("status")
    if status == "blocked":
        out.blocked = True
        return out

    state = res.get("state") or {}
    meas = state.get("measurements", {})
    viz = res.get("visualization", {}) or {}
    ep = viz.get("electrophysiology", {}) or {}

    # ECG-derived rhythm + heart rate (HR comes from the EP stage, not the prior)
    rhythm_cat = _rhythm_category(ep.get("rhythm_label"))
    if rhythm_cat:
        out.measurements["rhythm_category"] = Measurement(
            value=rhythm_cat, source="ecg_waveform_analysis", confidence=ep.get("r_peak_confidence"))
    rr = ep.get("rr_interval_ms")
    if isinstance(rr, (int, float)) and rr > 0:
        out.measurements["heart_rate_bpm"] = Measurement(
            value=round(60000.0 / rr, 1), source="ecg_waveform_analysis",
            confidence=ep.get("r_peak_confidence"))
    if isinstance(ep.get("qtc_ms"), (int, float)):
        out.measurements["qtc_ms"] = Measurement(ep["qtc_ms"], "ecg_waveform_analysis", ep.get("r_peak_confidence"))

    # hemodynamic measurements (from report/vitals path) with provenance
    for field in ("ejection_fraction_pct", "edv_ml", "esv_ml", "stroke_volume_ml",
                  "cardiac_output_l_min", "map_mmhg", "systolic_bp_mmhg",
                  "diastolic_bp_mmhg", "oxygen_saturation_pct"):
        val, src, conf = _mval(meas, field)
        # heart_rate_bpm from ECG already set above; don't overwrite with the prior
        if val is not None and field not in out.measurements:
            out.measurements[field] = Measurement(val, src, conf)

    # MAP is reported in the visualization summary, not measurements
    summary = viz.get("summary") or {}
    if "map_mmhg" not in out.measurements and isinstance(summary.get("map_mmhg"), (int, float)):
        out.measurements["map_mmhg"] = Measurement(summary["map_mmhg"], "computed", 0.9)

    return out
