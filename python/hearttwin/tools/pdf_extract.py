"""PDF text extraction tool.

Uses pypdf for local text extraction.
All extracted values must include source_file_id and confidence.
Never fills missing fields — missing stays null.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Optional


@dataclass
class ExtractedTextBlock:
    page: int
    text: str


@dataclass
class PdfExtractionResult:
    file_id: str
    filename: str
    pages: int
    text_blocks: list[ExtractedTextBlock]
    raw_text: str
    extracted_values: dict[str, Any]
    warnings: list[str] = field(default_factory=list)


_CARDIAC_PATTERNS: dict[str, list[tuple[str, str]]] = {
    "heart_rate_bpm": [
        (r"heart\s*rate[:\s]+(\d{2,3})\s*(?:bpm|beats)", "heart_rate"),
        (r"hr[:\s]+(\d{2,3})\s*(?:bpm|beats)?", "hr_abbr"),
        (r"(\d{2,3})\s*bpm", "bpm_value"),
        (r"pulse[:\s]+(\d{2,3})", "pulse"),
    ],
    "systolic_bp_mmhg": [
        (r"(?:systolic|sbp)[:\s]+(\d{2,3})\s*(?:mmhg)?", "sbp_label"),
        (r"bp[:\s]+(\d{2,3})[/\\](\d{2,3})", "bp_slash_systolic"),
        (r"blood\s*pressure[:\s]+(\d{2,3})[/\\]", "bp_labeled"),
    ],
    "diastolic_bp_mmhg": [
        (r"(?:diastolic|dbp)[:\s]+(\d{2,3})\s*(?:mmhg)?", "dbp_label"),
        (r"bp[:\s]+\d{2,3}[/\\](\d{2,3})", "bp_slash_diastolic"),
    ],
    "ejection_fraction_pct": [
        (r"(?:ejection\s*fraction|lvef|ef)[:\s]+(\d{2,3}(?:\.\d)?)\s*%?", "ef"),
        (r"(\d{2,3}(?:\.\d)?)\s*%\s*(?:ef|ejection)", "ef_pct"),
    ],
    "edv_ml": [
        (r"(?:end[\s-]*diastolic\s*volume|edv)[:\s]+(\d{2,3}(?:\.\d)?)\s*(?:ml|cc)?", "edv"),
    ],
    "esv_ml": [
        (r"(?:end[\s-]*systolic\s*volume|esv)[:\s]+(\d{2,3}(?:\.\d)?)\s*(?:ml|cc)?", "esv"),
    ],
    "stroke_volume_ml": [
        (r"(?:stroke\s*volume|sv)[:\s]+(\d{2,3}(?:\.\d)?)\s*(?:ml|cc)?", "sv"),
    ],
    "cardiac_output_l_min": [
        (r"(?:cardiac\s*output|co)[:\s]+(\d(?:\.\d{1,2})?)\s*(?:l/min|lpm)?", "co"),
    ],
    "troponin_ng_l": [
        (r"troponin[:\s]+(\d+(?:\.\d+)?)\s*(?:ng/l|ng/ml|ug/l)?", "troponin"),
        (r"(?:high\s*sensitivity\s*)?(?:hs[-\s])?troponin[:\s]+(\d+(?:\.\d+)?)", "hstroponin"),
    ],
    "bnp_pg_ml": [
        (r"(?:bnp|b[-\s]type\s*natriuretic\s*peptide)[:\s]+(\d+(?:\.\d+)?)\s*(?:pg/ml)?", "bnp"),
        (r"nt[-\s]?pro[-\s]?bnp[:\s]+(\d+(?:\.\d+)?)", "ntprobnp"),
    ],
    "oxygen_saturation_pct": [
        (r"(?:o2\s*sat|spo2|oxygen\s*sat)[:\s]+(\d{2,3}(?:\.\d)?)\s*%?", "spo2"),
        (r"(\d{2,3})\s*%\s*(?:o2\s*sat|spo2)", "spo2_pct"),
    ],
    "qrs_duration_ms": [
        (r"qrs[:\s]+(\d{2,3})\s*(?:ms|msec)?", "qrs"),
        (r"qrs\s*duration[:\s]+(\d{2,3})", "qrs_dur"),
    ],
    "qt_interval_ms": [
        (r"qt\s*(?:interval)?[:\s]+(\d{2,3})\s*(?:ms|msec)?", "qt"),
    ],
    "qtc_ms": [
        (r"qtc[:\s]+(\d{2,3})\s*(?:ms|msec)?", "qtc"),
        (r"corrected\s*qt[:\s]+(\d{2,3})", "qtc_long"),
    ],
    "rhythm_label": [
        (r"rhythm[:\s]+((?:normal\s*sinus|atrial\s*fibrillation|sinus\s*tachycardia|sinus\s*bradycardia|atrial\s*flutter)[^\n.]*)", "rhythm"),
        (r"(normal\s*sinus\s*rhythm|atrial\s*fibrillation|sinus\s*tachycardia|sinus\s*bradycardia)", "rhythm_bare"),
    ],
}


def extract_pdf_text(file_bytes: bytes, file_id: str, filename: str) -> PdfExtractionResult:
    """Extract text from PDF bytes using pypdf."""
    warnings: list[str] = []
    text_blocks: list[ExtractedTextBlock] = []

    try:
        import pypdf
        import io

        reader = pypdf.PdfReader(io.BytesIO(file_bytes))
        pages = len(reader.pages)

        for i, page in enumerate(reader.pages):
            try:
                text = page.extract_text() or ""
                text_blocks.append(ExtractedTextBlock(page=i + 1, text=text))
            except Exception as e:
                warnings.append(f"Page {i + 1} extraction error: {e}")

    except ImportError:
        warnings.append("pypdf not installed — PDF extraction unavailable")
        pages = 0

    raw_text = "\n".join(block.text for block in text_blocks)
    extracted_values = _extract_cardiac_values(raw_text, file_id)

    return PdfExtractionResult(
        file_id=file_id,
        filename=filename,
        pages=pages,
        text_blocks=text_blocks,
        raw_text=raw_text,
        extracted_values=extracted_values,
        warnings=warnings,
    )


def _extract_cardiac_values(text: str, file_id: str) -> dict[str, Any]:
    """Apply regex patterns to extract cardiac measurements from text."""
    extracted: dict[str, Any] = {}
    text_lower = text.lower()

    for field, patterns in _CARDIAC_PATTERNS.items():
        for pattern, method in patterns:
            match = re.search(pattern, text_lower, re.IGNORECASE)
            if match:
                raw_value = match.group(1).strip()

                if field == "rhythm_label":
                    extracted[field] = {
                        "value": raw_value,
                        "unit": "label",
                        "source": "file_extraction",
                        "confidence": 0.75,
                        "source_file_id": file_id,
                        "evidence": match.group(0)[:200],
                        "method": f"regex:{method}",
                    }
                else:
                    try:
                        numeric_value = float(raw_value)
                        extracted[field] = {
                            "value": numeric_value,
                            "unit": _get_unit(field),
                            "source": "file_extraction",
                            "confidence": 0.80,
                            "source_file_id": file_id,
                            "evidence": match.group(0)[:200],
                            "method": f"regex:{method}",
                        }
                    except ValueError:
                        continue
                break

    return extracted


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
        "troponin_ng_l": "ng/L",
        "bnp_pg_ml": "pg/mL",
        "oxygen_saturation_pct": "%",
        "qrs_duration_ms": "ms",
        "qt_interval_ms": "ms",
        "qtc_ms": "ms",
    }
    return units.get(field, "")
