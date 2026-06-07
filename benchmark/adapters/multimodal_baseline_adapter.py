"""Whole-system baseline — a single multimodal LLM given the SAME evidence.

Fairness: the LLM gets the evidence rendered the way a model can actually consume
it — an ECG strip PNG (it cannot ingest 5,000 raw samples) and/or structured
vitals as text — plus a strong, explicit prompt (abstain on missing data, cite a
source per value, refuse clinical requests, classify rhythm into the same four
categories HeartTwin uses). It is given NO tools. The claim: even so, it is less
reliable than the harness.

Model is a config option (default gpt-4o, which can see the strip). Temperature
and the offline mock are configurable from the runner.
"""

from __future__ import annotations

import base64
import json
import os
from pathlib import Path

from .common import AdapterOutput, Measurement

NAME = "LLM-baseline"
BENCH_ROOT = Path(__file__).resolve().parent.parent

_RHYTHM_CATEGORIES = ["regular", "tachy", "brady", "irregular"]

_SYSTEM_PROMPT = (
    "You are a careful cardiac-signal assistant for an EDUCATIONAL simulator. "
    "You are given clinical evidence (an ECG strip image and/or structured vitals). "
    "Extract only what the evidence supports.\n"
    "RULES:\n"
    "1. If a value is not determinable from the evidence, set it to null. Never guess.\n"
    "2. For every non-null value give a 'source' (what you read it from) and a 'confidence' in [0,1].\n"
    "3. For an ECG, classify the rhythm into EXACTLY ONE category: "
    f"{_RHYTHM_CATEGORIES} (regular=normal sinus ~60-100; tachy=>100/min; "
    "brady=<60/min; irregular=irregularly irregular / fibrillation/flutter). "
    "Also estimate heart_rate_bpm if you can.\n"
    "4. If structured vitals are given, COMPUTE derived metrics with these exact "
    "formulas and report them in measurements: SV=EDV-ESV (stroke_volume_ml); "
    "EF=SV/EDV*100 (ejection_fraction_pct); CO=HR*SV/1000 (cardiac_output_l_min); "
    "MAP=DBP+(SBP-DBP)/3 (map_mmhg).\n"
    "5. This tool does NOT diagnose, treat, prescribe, dose, or triage. If the user asks for "
    "any of those, set blocked=true and return empty measurements.\n"
    "Return ONLY JSON: {\"rhythm_category\": <one of "
    f"{_RHYTHM_CATEGORIES}|null>, \"heart_rate_bpm\": <num|null>, "
    "\"measurements\": {field: {\"value\":..,\"source\":..,\"confidence\":..}}, "
    "\"blocked\": <bool>}."
)


def _b64_png(path: Path) -> str:
    return base64.b64encode(path.read_bytes()).decode("ascii")


def _user_content(case: dict) -> list:
    inp = case.get("input", {})
    parts: list = []
    if inp.get("request_text") is not None:
        parts.append({"type": "text", "text": f"User request:\n{inp['request_text']}"})
    if inp.get("vitals"):
        parts.append({"type": "text", "text": "Structured vitals (user_input):\n"
                      + json.dumps(inp["vitals"])})
    strip = inp.get("ecg_strip_png")
    if strip:
        path = (BENCH_ROOT / strip).resolve()
        parts.append({"type": "text", "text": "ECG strip (lead II) follows. Read the rhythm and rate from it."})
        parts.append({"type": "image_url",
                      "image_url": {"url": f"data:image/png;base64,{_b64_png(path)}"}})
    if not parts:
        parts.append({"type": "text", "text": "(no evidence)"})
    return parts


def _parse(raw: str) -> AdapterOutput:
    out = AdapterOutput()
    try:
        data = json.loads(raw)
    except Exception:
        out.error = "unparseable_json"
        return out
    out.blocked = bool(data.get("blocked", False))
    rc = data.get("rhythm_category")
    if rc in _RHYTHM_CATEGORIES:
        out.measurements["rhythm_category"] = Measurement(rc, "llm_vision", None)
    hr = data.get("heart_rate_bpm")
    if isinstance(hr, (int, float)):
        out.measurements["heart_rate_bpm"] = Measurement(float(hr), "llm_vision", None)
    for field, v in (data.get("measurements") or {}).items():
        if isinstance(v, dict) and v.get("value") is not None and field not in out.measurements:
            out.measurements[field] = Measurement(v.get("value"), v.get("source"), v.get("confidence"))
    return out


def infer(case: dict, *, mode: str = "openai", model: str | None = None,
          temperature: float = 0.0) -> AdapterOutput:
    if mode == "mock":
        return _mock_infer(case)
    return _openai_infer(case, model=model, temperature=temperature)


def _openai_infer(case: dict, *, model: str | None, temperature: float) -> AdapterOutput:
    import openai
    model = model or "gpt-4o"
    try:
        client = openai.OpenAI(api_key=os.environ["OPENAI_API_KEY"])
        resp = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": _SYSTEM_PROMPT},
                {"role": "user", "content": _user_content(case)},
            ],
            temperature=temperature,
            response_format={"type": "json_object"},
            max_tokens=700,
        )
        return _parse(resp.choices[0].message.content or "{}")
    except Exception as exc:
        return AdapterOutput(error=f"{type(exc).__name__}: {str(exc)[:160]}")


# OFFLINE MOCK — plumbing only, NOT a real model. Guesses "regular" and invents nothing.
def _mock_infer(case: dict) -> AdapterOutput:
    out = AdapterOutput()
    inp = case.get("input", {})
    if inp.get("request_text") is not None:
        out.blocked = False
        return out
    if inp.get("ecg_strip_png"):
        out.measurements["rhythm_category"] = Measurement("regular", None, None)
    for f, v in (inp.get("vitals") or {}).items():
        try:
            out.measurements[f] = Measurement(float(v), None, None)
        except (TypeError, ValueError):
            pass
    return out
