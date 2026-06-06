"""Agent 2: Multimodal Extraction Agent.

Extracts structured observations from PDFs, images, CSVs, and text.
Every value includes source, unit, confidence, and extraction method.
Never fills missing fields.
"""

from __future__ import annotations

import csv
import io
import time
from typing import Any

from python.hearttwin.schemas import AgentResponse, AgentStatus, AgentTraceStep
from python.hearttwin.tools.image_extract import extract_from_image
from python.hearttwin.tools.pdf_extract import extract_pdf_text
from python.hearttwin.tools.weave_trace import TraceContext


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
