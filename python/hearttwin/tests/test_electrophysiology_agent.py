"""Tests for the Electrophysiology Agent.

Covers schema-bound contracts, deterministic waveform handling, reported-label
non-diagnostic wording, payload generation, and trace/storage safety.
"""

from __future__ import annotations

import math

import pytest

from python.hearttwin.agents.electrophysiology_agent import (
    ElectrophysiologyOutput,
    run_electrophysiology_agent,
)
from python.hearttwin.schemas import CardiacTwinState
from python.hearttwin.tools.weave_trace import get_traces

_DIAGNOSTIC_WORDS = ["the patient has arrhythmia", "diagnosed rhythm", "ecg diagnosis", "diagnosis", "diagnosed", "diagnostic"]
_FORBIDDEN_CLINICAL_PHRASES = ["the patient has arrhythmia", "diagnosed rhythm", "ecg diagnosis"]


def _assert_no_forbidden_clinical_phrases(text: str | None) -> None:
    """Warnings may describe sanitization (e.g. 'removed diagnostic language') — only the
    exact clinical-claim phrasing the spec forbids must never appear."""
    if not text:
        return
    lowered = text.lower()
    for phrase in _FORBIDDEN_CLINICAL_PHRASES:
        assert phrase not in lowered, f"Forbidden clinical phrase '{phrase}' leaked into output: {text}"


def _synthetic_ecg_signal(num_beats: int = 12, sampling_rate_hz: float = 500.0, hr_bpm: float = 72.0) -> list[float]:
    """Deterministic periodic-spike waveform a Pan-Tompkins-style detector can resolve."""
    rr_samples = int(60.0 / hr_bpm * sampling_rate_hz)
    total_samples = rr_samples * num_beats
    signal = [0.05 * math.sin(i * 0.02) for i in range(total_samples)]
    for beat in range(num_beats):
        center = beat * rr_samples + rr_samples // 2
        for offset in range(-10, 11):
            idx = center + offset
            if 0 <= idx < total_samples:
                signal[idx] += math.exp(-(offset ** 2) / 8.0) * 1.5
    return signal


def _state() -> CardiacTwinState:
    return CardiacTwinState(case_id="ep-test-case")


def _assert_non_diagnostic(text: str | None) -> None:
    if not text:
        return
    lowered = text.lower()
    for phrase in _DIAGNOSTIC_WORDS:
        assert phrase not in lowered, f"Diagnostic phrase '{phrase}' leaked into output: {text}"


@pytest.mark.asyncio
class TestMissingEcg:
    async def test_missing_ecg_returns_unknown_safely(self, monkeypatch):
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        response, ep = await run_electrophysiology_agent(state=_state(), validated_fields={}, case_id="case-missing-ecg")

        structured = response.outputs["structured_output"]
        assert structured["rhythm_source"] == "unknown"
        assert structured["rhythm_label"] is None
        assert structured["ecg_chart_payload"] is None
        assert structured["electrical_visual_payload"] is not None
        assert response.confidence > 0.0
        assert ep.rhythm_label is None


@pytest.mark.asyncio
class TestReportedRhythmLabel:
    async def test_reported_label_stored_as_reported(self, monkeypatch):
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        validated_fields = {
            "rhythm_label": {"value": "sinus rhythm noted on report", "source": "file_extraction", "confidence": 0.7},
        }
        response, ep = await run_electrophysiology_agent(
            state=_state(), validated_fields=validated_fields, case_id="case-reported-label"
        )

        structured = response.outputs["structured_output"]
        assert structured["rhythm_source"] == "reported"
        assert "reported rhythm label" in structured["rhythm_label"].lower()
        assert response.outputs["reported_ecg_statement"] is not None
        assert "reported ecg statement" in response.outputs["reported_ecg_statement"].lower()
        _assert_non_diagnostic(structured["rhythm_label"])
        _assert_non_diagnostic(response.outputs["reported_ecg_statement"])

    async def test_diagnostic_wording_in_report_is_sanitized(self, monkeypatch):
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        validated_fields = {
            "rhythm_label": {"value": "diagnosed atrial fibrillation, the patient has arrhythmia", "confidence": 0.6},
        }
        response, _ = await run_electrophysiology_agent(
            state=_state(), validated_fields=validated_fields, case_id="case-diagnostic-wording"
        )

        structured = response.outputs["structured_output"]
        _assert_non_diagnostic(structured["rhythm_label"])
        _assert_non_diagnostic(response.outputs["reported_ecg_statement"])
        assert any("sanitiz" in w.lower() for w in response.warnings)


@pytest.mark.asyncio
class TestWaveformHandling:
    async def test_waveform_csv_triggers_deterministic_tool(self, monkeypatch):
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        signal = _synthetic_ecg_signal()
        validated_fields = {
            "__ecg_waveform__": {
                "value": signal,
                "unit": "mV",
                "source": "extracted",
                "confidence": 0.7,
                "source_file_id": "file-ecg-1",
                "method": "csv_waveform",
            },
        }
        response, ep = await run_electrophysiology_agent(
            state=_state(), validated_fields=validated_fields, case_id="case-waveform"
        )

        structured = response.outputs["structured_output"]
        assert structured["rhythm_source"] == "waveform_estimated"
        assert structured["r_peak_count"] is not None and structured["r_peak_count"] >= 2
        assert structured["r_peak_confidence"] is not None and structured["r_peak_confidence"] > 0
        assert ep.rr_interval_ms is not None
        assert ep.r_peak_confidence == structured["r_peak_confidence"]

        tool_names = [step.tool for step in response.trace]
        assert "hearttwin.detect_r_peaks" in tool_names
        assert "hearttwin.simulate_electrophysiology" in tool_names

    async def test_chart_payload_exists_when_waveform_present(self, monkeypatch):
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        signal = _synthetic_ecg_signal()
        validated_fields = {
            "__ecg_waveform__": {"value": signal, "unit": "mV", "source": "extracted", "confidence": 0.7},
        }
        response, _ = await run_electrophysiology_agent(
            state=_state(), validated_fields=validated_fields, case_id="case-chart-payload"
        )

        chart = response.outputs["structured_output"]["ecg_chart_payload"]
        assert chart is not None
        for key in ("lead_used", "sampling_rate_hz", "preview_signal_mv", "r_peak_indices", "rr_intervals_ms", "display_label"):
            assert key in chart
        assert chart["display_label"] == "simulated ECG chart"
        assert len(chart["preview_signal_mv"]) <= 300

    async def test_insufficient_waveform_does_not_crash(self, monkeypatch):
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        validated_fields = {
            "__ecg_waveform__": {"value": [0.01 * i for i in range(60)], "unit": "mV", "source": "extracted", "confidence": 0.5},
        }
        response, _ = await run_electrophysiology_agent(
            state=_state(), validated_fields=validated_fields, case_id="case-insufficient-waveform"
        )

        structured = response.outputs["structured_output"]
        assert structured["rhythm_source"] in {"waveform_estimated", "simulated_visualization", "unknown", "reported"}
        assert response.outputs["electrical_visual_payload"] is not None


@pytest.mark.asyncio
class TestSchemaAndSafety:
    async def test_output_schema_validates(self, monkeypatch):
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        signal = _synthetic_ecg_signal()
        validated_fields = {
            "__ecg_waveform__": {"value": signal, "unit": "mV", "source": "extracted", "confidence": 0.7},
            "rhythm_label": {"value": "sinus rhythm reported on prior ECG", "confidence": 0.6},
        }
        response, _ = await run_electrophysiology_agent(
            state=_state(), validated_fields=validated_fields, case_id="case-schema-validate"
        )

        structured = response.outputs["structured_output"]
        # Re-validate round trip through the schema-bound output contract.
        validated = ElectrophysiologyOutput.model_validate(structured)
        assert validated.rhythm_source in {"reported", "waveform_estimated", "simulated_visualization", "unknown"}
        assert 0.0 <= validated.confidence <= 1.0
        assert isinstance(validated.electrical_visual_payload, dict)
        for key in ("beat_interval_ms", "wave_speed", "conduction_delay_score", "arrhythmia_instability_score", "display_label", "source", "confidence"):
            assert key in validated.electrical_visual_payload

    async def test_no_diagnostic_language_anywhere_in_outputs(self, monkeypatch):
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        signal = _synthetic_ecg_signal()
        validated_fields = {
            "__ecg_waveform__": {"value": signal, "unit": "mV", "source": "extracted", "confidence": 0.7},
            "rhythm_label": {"value": "ECG diagnosis: the patient has arrhythmia, diagnosed rhythm disorder", "confidence": 0.6},
        }
        response, ep = await run_electrophysiology_agent(
            state=_state(), validated_fields=validated_fields, case_id="case-no-diagnostic"
        )

        structured = response.outputs["structured_output"]
        _assert_non_diagnostic(structured["rhythm_label"])
        _assert_non_diagnostic(response.outputs.get("reported_ecg_statement"))
        _assert_non_diagnostic(structured["electrical_visual_payload"].get("display_label"))
        if structured["ecg_chart_payload"]:
            _assert_non_diagnostic(structured["ecg_chart_payload"].get("display_label"))
        _assert_non_diagnostic(ep.rhythm_label)
        for warning in response.warnings:
            _assert_no_forbidden_clinical_phrases(warning)


@pytest.mark.asyncio
class TestModelRoutingAndTracing:
    async def test_openai_missing_key_does_not_crash(self, monkeypatch):
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        validated_fields = {"rhythm_label": {"value": "irregular rhythm noted", "confidence": 0.5}}
        response, _ = await run_electrophysiology_agent(
            state=_state(), validated_fields=validated_fields, case_id="case-no-api-key"
        )

        assert response.outputs["structured_output"]["rhythm_source"] == "reported"
        assert response.outputs["agent_stage_result"]["model_used"] is None
        assert any("api key" in w.lower() for w in response.warnings)

    async def test_weave_local_trace_records_expected_tools(self, monkeypatch):
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        signal = _synthetic_ecg_signal()
        validated_fields = {
            "__ecg_waveform__": {"value": signal, "unit": "mV", "source": "extracted", "confidence": 0.7},
        }
        case_id = "case-trace-local"
        response, _ = await run_electrophysiology_agent(state=_state(), validated_fields=validated_fields, case_id=case_id)

        tool_names = [step.tool for step in response.trace]
        assert "hearttwin.detect_r_peaks" in tool_names
        assert "hearttwin.simulate_electrophysiology" in tool_names

        rpeak_step = next(step for step in response.trace if step.tool == "hearttwin.detect_r_peaks")
        # Raw signal arrays must never be logged — only metadata + a small downsampled preview.
        assert "signal_preview_mv" in rpeak_step.inputs
        assert len(rpeak_step.inputs["signal_preview_mv"]) <= 12
        assert rpeak_step.inputs["signal_length"] == len(signal)

        stage_result = response.outputs["agent_stage_result"]
        assert stage_result["agent_id"] == "electrophysiology"
        assert stage_result["agent_name"] == "Electrophysiology Agent"
        assert stage_result["local_trace_id"]

    async def test_redis_write_is_safe_without_credentials(self, monkeypatch):
        monkeypatch.delenv("UPSTASH_REDIS_REST_URL", raising=False)
        monkeypatch.delenv("UPSTASH_REDIS_REST_TOKEN", raising=False)
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        signal = _synthetic_ecg_signal()
        validated_fields = {
            "__ecg_waveform__": {"value": signal, "unit": "mV", "source": "extracted", "confidence": 0.7},
        }
        # Should complete without raising even though no Redis credentials are configured.
        response, _ = await run_electrophysiology_agent(
            state=_state(), validated_fields=validated_fields, case_id="case-redis-safe"
        )
        assert response.status is not None
