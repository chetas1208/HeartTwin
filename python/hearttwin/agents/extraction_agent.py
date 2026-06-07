"""Agent 2: Multimodal Extraction Agent.

Extracts structured observations from PDFs, images, CSVs, and text.
Every value includes source, unit, confidence, and extraction method.
Never fills missing fields.
"""

from __future__ import annotations

import csv
import io
import json
import time
from typing import Any

from python.hearttwin.schemas import AgentResponse, AgentStatus, AgentTraceStep
from python.hearttwin.tools.image_extract import extract_from_image
from python.hearttwin.tools.pdf_extract import extract_pdf_text
from python.hearttwin.tools.vista3d_client import segment_ct_and_analyze
from python.hearttwin.tools.weave_trace import TraceContext

_CT_EXTENSIONS = (".nii", ".nii.gz", ".dcm", ".zip")

_AGENT_ID = "multimodal_extraction"
_AGENT_NAME = "Multimodal Extraction Agent"


async def run_extraction_agent(
    files: list[dict],
    user_vitals: dict[str, Any] | None,
    case_id: str,
) -> AgentResponse:
    """Extract structured cardiac data from all uploaded files."""
    tracer = TraceContext(case_id=case_id, agent_name="extraction_agent")
    t0 = time.time()
    warnings: list[str] = []
    all_extracted: dict[str, Any] = {}

    for f in files:
        file_id = f.get("file_id", "unknown")
        filename = f.get("filename", "")
        content_type = f.get("content_type", "")
        file_bytes: bytes = f.get("bytes", b"")

        if not file_bytes:
            warnings.append(f"File {filename}: no content available")
            continue

        ft0 = time.time()

        if content_type == "application/pdf" or filename.lower().endswith(".pdf"):
            result = extract_pdf_text(file_bytes, file_id, filename)
            extracted = result.extracted_values
            warnings.extend(result.warnings)
            method = "pdf_text_regex"

        elif content_type.startswith("image/"):
            result = await extract_from_image(file_bytes, file_id, filename, content_type)
            extracted = result.extracted_values
            warnings.extend(result.warnings)
            method = result.method

        elif content_type == "text/csv" or filename.lower().endswith(".csv"):
            extracted, csv_warnings = _extract_from_csv(file_bytes, file_id, filename)
            warnings.extend(csv_warnings)
            method = "csv_parse"

        elif content_type == "application/json" or filename.lower().endswith(".json"):
            extracted, json_warnings = _extract_from_json(file_bytes, file_id, filename)
            warnings.extend(json_warnings)
            method = "json_parse"

        elif _is_ct_volume(filename, content_type):
            extracted, ct_warnings = await _extract_from_ct(file_bytes, file_id, filename)
            warnings.extend(ct_warnings)
            method = "ct_segmentation"

        elif content_type.startswith("video/") or filename.lower().endswith((".avi", ".mp4", ".mov", ".webm")):
            extracted, vid_warnings = await _extract_from_video(file_bytes, file_id, filename, content_type)
            warnings.extend(vid_warnings)
            method = "video_frame_extraction"

        else:
            extracted = {}
            warnings.append(f"File type '{content_type}' not supported for extraction")
            method = "unsupported"

        tracer.record_tool(
            f"extract_{method}",
            inputs={"file_id": file_id, "filename": filename},
            outputs={"extracted_count": len(extracted)},
            duration_ms=(time.time() - ft0) * 1000,
        )

        for field, value_data in extracted.items():
            if field not in all_extracted:
                all_extracted[field] = value_data
            else:
                existing_conf = all_extracted[field].get("confidence", 0)
                new_conf = value_data.get("confidence", 0)
                if new_conf > existing_conf:
                    all_extracted[field] = value_data
                    warnings.append(
                        f"Field '{field}': replaced lower-confidence value with higher-confidence extraction"
                    )

    if user_vitals:
        user_extracted, user_warnings = _extract_user_vitals(user_vitals)
        warnings.extend(user_warnings)
        for field, value_data in user_extracted.items():
            if field not in all_extracted:
                all_extracted[field] = value_data
            elif value_data.get("confidence", 0) >= all_extracted[field].get("confidence", 0):
                all_extracted[field] = value_data

        tracer.record_tool(
            "extract_user_vitals",
            inputs={"field_count": len(user_vitals)},
            outputs={"extracted_count": len(user_extracted)},
            duration_ms=1.0,
        )

    confidence = min(1.0, 0.3 + len(all_extracted) * 0.07) if all_extracted else 0.1

    return AgentResponse(
        agent="extraction_agent",
        status=AgentStatus.SUCCESS if all_extracted else AgentStatus.WARNING,
        inputs_used=[f.get("file_id", "") for f in files],
        outputs={
            "extracted_fields": all_extracted,
            "field_count": len(all_extracted),
            "files_processed": len(files),
        },
        warnings=warnings,
        confidence=confidence,
        trace=tracer.steps,
    )


def _is_ct_volume(filename: str, content_type: str) -> bool:
    """True for CT volume / DICOM-series uploads VISTA-3D can segment."""
    name = (filename or "").lower()
    if name.endswith(_CT_EXTENSIONS):
        return True
    return content_type in ("application/gzip", "application/x-gzip") and name.endswith((".nii", ".gz"))


async def _extract_from_ct(
    file_bytes: bytes, file_id: str, filename: str
) -> tuple[dict[str, Any], list[str]]:
    """Segment a CT volume via VISTA-3D and derive deterministic volumetry.

    Emits a non-scalar ``__ct_segmentation__`` artifact (volumes + educational
    abnormality observations + provenance). Never invents cardiac scalars: the
    single heart label cannot yield chamber EF, so this only carries CT-derived
    volumetric proxies. Fail-safe — VISTA-3D being disabled/down degrades to a
    labelled artifact with warnings, never an exception.
    """
    warnings: list[str] = []
    try:
        result = await segment_ct_and_analyze(file_bytes, filename, file_id=file_id)
    except Exception as exc:  # defensive: the client is already fail-safe
        return {}, [f"CT segmentation error ({filename}): {type(exc).__name__}: {exc}"]

    status = result.get("status")
    if status not in ("analyzed",):
        warnings.append(
            f"CT '{filename}': segmentation status '{status}' — "
            f"{result.get('note', 'no CT-derived values available')}."
        )
    warnings.extend(result.get("warnings", []))

    extracted = {
        "__ct_segmentation__": {
            "value": result,
            "unit": "segmentation",
            "source": "vista3d",
            "method": "ct_segmentation",
            "confidence": 0.80 if status == "analyzed" else 0.0,
            "source_file_id": file_id,
        }
    }
    return extracted, warnings


async def _extract_from_video(
    file_bytes: bytes, file_id: str, filename: str, content_type: str
) -> tuple[dict[str, Any], list[str]]:
    """Extract a representative frame from an echo video and run image extraction.

    Decoding needs an optional codec lib (imageio-ffmpeg). When absent, this
    degrades to a labelled warning — the upload is accepted, nothing crashes,
    and no values are invented.
    """
    warnings: list[str] = []
    frame_png: bytes | None = None
    try:
        import imageio.v3 as iio  # type: ignore

        import numpy as np

        frames = iio.imread(io.BytesIO(file_bytes), index=None)  # all frames
        arr = frames[len(frames) // 2] if getattr(frames, "ndim", 0) == 4 else frames
        from PIL import Image

        buf = io.BytesIO()
        Image.fromarray(np.asarray(arr)).convert("RGB").save(buf, format="PNG")
        frame_png = buf.getvalue()
    except Exception as exc:
        warnings.append(
            f"Video '{filename}': frame extraction unavailable "
            f"({type(exc).__name__}) — install imageio-ffmpeg to enable echo-video frames. "
            "Upload accepted; no values invented."
        )
        return {}, warnings

    result = await extract_from_image(frame_png, file_id, f"{filename}.frame.png", "image/png")
    warnings.extend(result.warnings)
    return result.extracted_values, warnings


# Alias -> canonical field map for JSON cardiac payloads (manual vitals, echo
# metadata, case manifests). Lowercased keys.
_JSON_FIELD_ALIASES: dict[str, str] = {
    "heart_rate_bpm": "heart_rate_bpm", "heart_rate": "heart_rate_bpm", "hr": "heart_rate_bpm",
    "pulse": "heart_rate_bpm", "pulse_bpm": "heart_rate_bpm",
    "systolic_bp_mmhg": "systolic_bp_mmhg", "systolic": "systolic_bp_mmhg", "sbp": "systolic_bp_mmhg",
    "systolic_bp": "systolic_bp_mmhg",
    "diastolic_bp_mmhg": "diastolic_bp_mmhg", "diastolic": "diastolic_bp_mmhg", "dbp": "diastolic_bp_mmhg",
    "diastolic_bp": "diastolic_bp_mmhg",
    "edv_ml": "edv_ml", "edv": "edv_ml", "end_diastolic_volume": "edv_ml", "end_diastolic_volume_ml": "edv_ml",
    "esv_ml": "esv_ml", "esv": "esv_ml", "end_systolic_volume": "esv_ml", "end_systolic_volume_ml": "esv_ml",
    "ejection_fraction_pct": "ejection_fraction_pct", "ejection_fraction": "ejection_fraction_pct",
    "ejection_fraction_pct_reported": "ejection_fraction_pct", "ef": "ejection_fraction_pct",
    "ef_pct": "ejection_fraction_pct", "lvef": "ejection_fraction_pct",
    "stroke_volume_ml": "stroke_volume_ml", "stroke_volume": "stroke_volume_ml", "sv_ml": "stroke_volume_ml",
    "cardiac_output_l_min": "cardiac_output_l_min", "cardiac_output": "cardiac_output_l_min",
    "co_l_min": "cardiac_output_l_min",
    "oxygen_saturation_pct": "oxygen_saturation_pct", "oxygen_saturation": "oxygen_saturation_pct",
    "spo2": "oxygen_saturation_pct", "o2_sat": "oxygen_saturation_pct",
    "troponin_ng_l": "troponin_ng_l", "troponin": "troponin_ng_l",
    "bnp_pg_ml": "bnp_pg_ml", "bnp": "bnp_pg_ml",
    "qrs_duration_ms": "qrs_duration_ms", "qrs": "qrs_duration_ms", "qrs_duration": "qrs_duration_ms",
    "qt_interval_ms": "qt_interval_ms", "qt": "qt_interval_ms", "qt_interval": "qt_interval_ms",
    "qtc_ms": "qtc_ms", "qtc": "qtc_ms",
}


def _extract_from_json(
    file_bytes: bytes, file_id: str, filename: str
) -> tuple[dict[str, Any], list[str]]:
    """Extract cardiac measurements from JSON payloads.

    Handles manual vitals (`user_vitals: {...}`), echo metadata (flat keys), and
    case manifests (nested `sampled_inputs`/`expected_deterministic`). Walks the
    object recursively; first numeric occurrence of a known field wins. Never
    invents values — non-cardiac/missing keys are ignored.
    """
    warnings: list[str] = []
    extracted: dict[str, Any] = {}

    try:
        payload = json.loads(file_bytes.decode("utf-8", errors="replace"))
    except (ValueError, UnicodeDecodeError) as exc:
        return {}, [f"JSON {filename}: parse error: {exc}"]

    def collect(node: Any, path: str) -> None:
        if isinstance(node, dict):
            for k, v in node.items():
                key = str(k).strip().lower()
                field = _JSON_FIELD_ALIASES.get(key)
                if field and field not in extracted and isinstance(v, (int, float)) and not isinstance(v, bool):
                    extracted[field] = {
                        "value": float(v),
                        "unit": _get_unit(field),
                        "source": "file_extraction",
                        "confidence": 0.85,
                        "source_file_id": file_id,
                        "evidence": f"JSON key '{path}.{k}'" if path else f"JSON key '{k}'",
                        "method": "json_parse",
                    }
                collect(v, f"{path}.{k}" if path else str(k))
        elif isinstance(node, list):
            for i, v in enumerate(node):
                collect(v, f"{path}[{i}]")

    collect(payload, "")
    if not extracted:
        warnings.append(f"JSON {filename}: no recognizable cardiac fields found")
    return extracted, warnings


def _extract_from_csv(
    file_bytes: bytes, file_id: str, filename: str
) -> tuple[dict[str, Any], list[str]]:
    """Parse CSV for cardiac measurement columns or ECG waveform."""
    warnings: list[str] = []
    extracted: dict[str, Any] = {}

    try:
        text = file_bytes.decode("utf-8", errors="replace")
        reader = csv.DictReader(io.StringIO(text))
        rows = list(reader)

        if not rows:
            warnings.append(f"CSV {filename}: empty file")
            return extracted, warnings

        headers = [h.lower().strip() for h in (reader.fieldnames or [])]

        known_columns = {
            "heart_rate": "heart_rate_bpm",
            "hr": "heart_rate_bpm",
            "systolic": "systolic_bp_mmhg",
            "sbp": "systolic_bp_mmhg",
            "diastolic": "diastolic_bp_mmhg",
            "dbp": "diastolic_bp_mmhg",
            "ef": "ejection_fraction_pct",
            "ejection_fraction": "ejection_fraction_pct",
            "edv": "edv_ml",
            "esv": "esv_ml",
            "spo2": "oxygen_saturation_pct",
            "o2_sat": "oxygen_saturation_pct",
        }

        for col, field in known_columns.items():
            if col in headers:
                values = []
                for row in rows:
                    try:
                        key = next(k for k in row.keys() if k.lower().strip() == col)
                        values.append(float(row[key]))
                    except (ValueError, StopIteration):
                        continue
                if values:
                    avg_val = sum(values) / len(values)
                    extracted[field] = {
                        "value": round(avg_val, 2),
                        "unit": _get_unit(field),
                        "source": "extracted",
                        "confidence": 0.85,
                        "source_file_id": file_id,
                        "evidence": f"CSV column '{col}', {len(values)} values, mean={avg_val:.2f}",
                        "method": "csv_parse",
                    }

        ecg_cols = {"amplitude", "voltage", "ecg", "signal", "mv", "lead_ii", "lead ii"}
        ecg_col = next((h for h in headers if h in ecg_cols or "ecg" in h or "voltage" in h), None)
        if ecg_col:
            signal_values = []
            for row in rows:
                try:
                    key = next(k for k in row.keys() if k.lower().strip() == ecg_col)
                    signal_values.append(float(row[key]))
                except (ValueError, StopIteration):
                    continue
            if len(signal_values) > 50:
                extracted["__ecg_waveform__"] = {
                    "value": signal_values,
                    "unit": "mV",
                    "source": "extracted",
                    "confidence": 0.70,
                    "source_file_id": file_id,
                    "method": "csv_waveform",
                }

    except Exception as e:
        warnings.append(f"CSV parse error: {e}")

    return extracted, warnings


def _extract_user_vitals(user_vitals: dict[str, Any]) -> tuple[dict[str, Any], list[str]]:
    """Wrap user-provided vitals with proper source metadata."""
    warnings: list[str] = []
    extracted: dict[str, Any] = {}

    field_units = {
        "heart_rate_bpm": "bpm",
        "systolic_bp_mmhg": "mmHg",
        "diastolic_bp_mmhg": "mmHg",
        "ejection_fraction_pct": "%",
        "edv_ml": "mL",
        "esv_ml": "mL",
        "stroke_volume_ml": "mL",
        "cardiac_output_l_min": "L/min",
        "troponin_ng_l": "ng/L",
        "bnp_pg_ml": "pg/mL",
        "oxygen_saturation_pct": "%",
        "age_years": "years",
        "height_cm": "cm",
        "weight_kg": "kg",
    }

    for field, value in user_vitals.items():
        if value is None:
            continue
        try:
            numeric = float(value)
            extracted[field] = {
                "value": numeric,
                "unit": field_units.get(field, ""),
                "source": "user_input",
                "confidence": 0.95,
                "source_file_id": None,
                "method": "user_input",
            }
        except (ValueError, TypeError):
            if isinstance(value, str):
                extracted[field] = {
                    "value": value,
                    "unit": "",
                    "source": "user_input",
                    "confidence": 0.90,
                    "source_file_id": None,
                    "method": "user_input",
                }
            else:
                warnings.append(f"User vital '{field}': invalid value type")

    return extracted, warnings


def _get_unit(field: str) -> str:
    units = {
        "heart_rate_bpm": "bpm",
        "systolic_bp_mmhg": "mmHg",
        "diastolic_bp_mmhg": "mmHg",
        "ejection_fraction_pct": "%",
        "edv_ml": "mL",
        "esv_ml": "mL",
        "stroke_volume_ml": "mL",
        "cardiac_output_l_min": "L/min",
        "oxygen_saturation_pct": "%",
    }
    return units.get(field, "")
