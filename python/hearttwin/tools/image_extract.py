"""Image/ECG image extraction tool.

Uses OpenAI Vision API when configured.
Falls back to empty extraction with warnings when API is unavailable.
Never invents values — missing stays null.
"""

from __future__ import annotations

import base64
import os
from dataclasses import dataclass, field
from typing import Any, Optional

from python.hearttwin.safety import CORE_SAFETY_PHRASE
from python.hearttwin.tools.model_config import get_vision_model


@dataclass
class ImageExtractionResult:
    file_id: str
    filename: str
    content_type: str
    extracted_values: dict[str, Any]
    raw_response: Optional[str]
    warnings: list[str] = field(default_factory=list)
    method: str = "vision_api"


_VISION_PROMPT = f"""{CORE_SAFETY_PHRASE}

Extract ONLY values that are CLEARLY and EXPLICITLY visible in the image.
Return a JSON object with ONLY the fields you can see with confidence >= 0.7.
Do NOT infer, estimate, or fill in missing values.

Possible fields (include only those clearly visible):
- heart_rate_bpm: numeric value in bpm
- systolic_bp_mmhg: numeric value in mmHg
- diastolic_bp_mmhg: numeric value in mmHg
- ejection_fraction_pct: numeric percentage
- edv_ml: end-diastolic volume in mL
- esv_ml: end-systolic volume in mL
- qrs_duration_ms: QRS duration in milliseconds
- qt_interval_ms: QT interval in milliseconds
- qtc_ms: corrected QT in milliseconds
- rhythm_label: text description of rhythm if labeled
- waveform_type: "ecg_12lead", "ecg_rhythm_strip", "echo", "mri", "other"

For each field include:
{{
  "value": <number or string>,
  "confidence": <0.0-1.0, how certain you are this is correct>,
  "evidence": "<brief quote or description of what you saw>"
}}

IMPORTANT: Return {{}} if nothing is clearly readable. Never guess.
"""


async def extract_from_image(
    file_bytes: bytes,
    file_id: str,
    filename: str,
    content_type: str,
) -> ImageExtractionResult:
    """Extract cardiac measurements from an image using OpenAI Vision API."""
    warnings: list[str] = []
    api_key = os.environ.get("OPENAI_API_KEY", "")

    if not api_key:
        warnings.append("OPENAI_API_KEY not configured — image extraction unavailable")
        return ImageExtractionResult(
            file_id=file_id,
            filename=filename,
            content_type=content_type,
            extracted_values={},
            raw_response=None,
            warnings=warnings,
            method="unavailable_no_api_key",
        )

    try:
        import openai
        import json

        b64 = base64.b64encode(file_bytes).decode("utf-8")
        mime = content_type or "image/png"
        model = get_vision_model()

        client = openai.AsyncOpenAI(api_key=api_key)
        response = await client.chat.completions.create(
            model=model,
            messages=[
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": _VISION_PROMPT},
                        {
                            "type": "image_url",
                            "image_url": {"url": f"data:{mime};base64,{b64}", "detail": "high"},
                        },
                    ],
                }
            ],
            max_tokens=1000,
            response_format={"type": "json_object"},
        )

        raw = response.choices[0].message.content or "{}"
        parsed = json.loads(raw)

        extracted: dict[str, Any] = {}
        for field_name, data in parsed.items():
            if isinstance(data, dict) and "value" in data:
                confidence = float(data.get("confidence", 0.5))
                if confidence < 0.70:
                    warnings.append(
                        f"Field '{field_name}' skipped — confidence {confidence:.2f} below 0.70 threshold"
                    )
                    continue
                extracted[field_name] = {
                    "value": data["value"],
                    "unit": _get_unit(field_name),
                    "source": "file_extraction",
                    "confidence": confidence,
                    "source_file_id": file_id,
                    "evidence": data.get("raw_evidence", data.get("evidence", ""))[:200],
                    "method": "vision_api_openai",
                }

        return ImageExtractionResult(
            file_id=file_id,
            filename=filename,
            content_type=content_type,
            extracted_values=extracted,
            raw_response=raw[:2000],
            warnings=warnings,
            method="vision_api_openai",
        )

    except Exception as e:
        warnings.append(f"Image extraction failed: {type(e).__name__}: {e}")
        return ImageExtractionResult(
            file_id=file_id,
            filename=filename,
            content_type=content_type,
            extracted_values={},
            raw_response=None,
            warnings=warnings,
            method="vision_api_failed",
        )


def _get_unit(field: str) -> str:
    units = {
        "heart_rate_bpm": "bpm",
        "systolic_bp_mmhg": "mmHg",
        "diastolic_bp_mmhg": "mmHg",
        "ejection_fraction_pct": "%",
        "edv_ml": "mL",
        "esv_ml": "mL",
        "qrs_duration_ms": "ms",
        "qt_interval_ms": "ms",
        "qtc_ms": "ms",
    }
    return units.get(field, "")
