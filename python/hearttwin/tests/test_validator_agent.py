"""Tests for the Evidence Validator Agent.

All tests run fully offline: no OpenAI key, no Redis credentials. They assert
the deterministic validation rules — unit normalization, bounds checks,
conflict detection, candidate selection/preservation, missing-critical-field
detection, and data-quality scoring — plus the schema-bound output contract.
"""

from __future__ import annotations

import pytest

from python.hearttwin.agents.validator_agent import (
    ValidatorOutput,
    run_validator_agent,
)
from python.hearttwin.schemas import AgentStatus


@pytest.fixture(autouse=True)
def _no_external_services(monkeypatch):
    """Isolate every test from OpenAI and Redis — purely deterministic checks."""
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_MODEL_VALIDATOR", raising=False)
    monkeypatch.delenv("UPSTASH_REDIS_REST_URL", raising=False)
    monkeypatch.delenv("UPSTASH_REDIS_REST_TOKEN", raising=False)
    yield


def _candidate(value, unit="", source="extracted", confidence=0.85, method=None, **kwargs):
    return {
        "value": value,
        "unit": unit,
        "source": source,
        "confidence": confidence,
        "method": method,
        **kwargs,
    }


def _measurement(field, value, unit="", source="extracted", confidence=0.85, method=None):
    """Build a list-shaped ExtractedMeasurement payload (supports multiple
    candidates per field — the dict[field] -> single-candidate shape used by
    the legacy /extract pipeline cannot represent that)."""
    return {
        "field": field,
        "value": value,
        "unit": unit,
        "source": source,
        "confidence": confidence,
        "method": method,
    }


GOLDEN_FIELDS = {
    "heart_rate_bpm": _candidate(72.0, "bpm", method="user_input"),
    "systolic_bp_mmhg": _candidate(120.0, "mmHg", method="user_input"),
    "diastolic_bp_mmhg": _candidate(80.0, "mmHg", method="user_input"),
    "edv_ml": _candidate(130.0, "mL", method="user_input"),
    "esv_ml": _candidate(50.0, "mL", method="user_input"),
    "ejection_fraction_pct": _candidate(61.5, "%", method="user_input"),
}


async def test_valid_values_pass():
    response = await run_validator_agent(extracted_fields=GOLDEN_FIELDS, case_id="case-valid")

    structured = response.outputs["structured_output"]
    output = ValidatorOutput.model_validate(structured)

    for field in GOLDEN_FIELDS:
        assert output.validated_fields[field].status == "valid"
    assert output.conflicts == []
    assert output.invalid_fields == []
    assert output.missing_critical_fields == []
    assert response.status in (AgentStatus.SUCCESS, AgentStatus.WARNING)


async def test_invalid_heart_rate_flagged():
    fields = dict(GOLDEN_FIELDS)
    fields["heart_rate_bpm"] = _candidate(8.0, "bpm", method="user_input")

    response = await run_validator_agent(extracted_fields=fields, case_id="case-invalid-hr")
    output = ValidatorOutput.model_validate(response.outputs["structured_output"])

    hr = output.validated_fields["heart_rate_bpm"]
    assert hr.status == "invalid"
    assert hr.selected_value == 8.0
    assert "heart_rate_bpm" in output.invalid_fields
    assert any("heart_rate_bpm" in w for w in output.warnings)


def test_edv_esv_ordering_conflict_detected():
    import asyncio

    fields = dict(GOLDEN_FIELDS)
    fields["edv_ml"] = _candidate(90.0, "mL", method="user_input")
    fields["esv_ml"] = _candidate(120.0, "mL", method="user_input")
    # Remove EF so the volume-ordering conflict (not the EF-consistency conflict) fires cleanly.
    fields.pop("ejection_fraction_pct")

    response = asyncio.get_event_loop().run_until_complete(
        run_validator_agent(extracted_fields=fields, case_id="case-edv-esv")
    )
    output = ValidatorOutput.model_validate(response.outputs["structured_output"])

    conflict_types = {c["type"] for c in output.conflicts}
    assert "edv_esv_ordering_conflict" in conflict_types
    assert output.validated_fields["esv_ml"].status == "conflict"
    assert output.validated_fields["edv_ml"].status == "conflict"
    # Evidence is preserved, not discarded.
    assert output.validated_fields["esv_ml"].selected_value == 120.0
    assert len(output.validated_fields["esv_ml"].evidence_candidates) == 1


async def test_multiple_ef_candidates_preserved_and_conflict_flagged():
    """Two disagreeing EF estimates must both survive in evidence_candidates,
    and the spread between them must be flagged as a conflict."""
    measurements = [
        _measurement("heart_rate_bpm", 72.0, "bpm", source="user_input", method="user_input"),
        _measurement("systolic_bp_mmhg", 120.0, "mmHg", source="user_input", method="user_input"),
        _measurement("diastolic_bp_mmhg", 80.0, "mmHg", source="user_input", method="user_input"),
        _measurement("edv_ml", 130.0, "mL", source="user_input", method="user_input"),
        _measurement("esv_ml", 50.0, "mL", source="user_input", method="user_input"),
        _measurement("ejection_fraction_pct", 35.0, "%", source="extracted", confidence=0.6, method="regex:pdf"),
        _measurement(
            "ejection_fraction_pct", 58.0, "%", source="extracted", confidence=0.8, method="vision_api_openai"
        ),
    ]

    response = await run_validator_agent(extracted_fields=measurements, case_id="case-multi-ef")
    output = ValidatorOutput.model_validate(response.outputs["structured_output"])

    ef_field = output.validated_fields["ejection_fraction_pct"]
    candidate_values = {c.value for c in ef_field.evidence_candidates}
    assert candidate_values == {35.0, 58.0}

    conflict_types = {c["type"] for c in output.conflicts}
    assert "duplicate_value_conflict" in conflict_types
    assert ef_field.status == "conflict"


async def test_source_priority_prefers_manual_input_over_pdf_text():
    """Candidate selection ranks by source-priority bucket first, confidence second —
    a lower-confidence manual entry beats a higher-confidence regex/PDF extraction,
    and the losing candidate is preserved rather than discarded."""
    measurements = [
        _measurement("heart_rate_bpm", 95.0, "bpm", source="extracted", confidence=0.95, method="regex:vitals"),
        _measurement("heart_rate_bpm", 74.0, "bpm", source="user_input", confidence=0.7, method="manual_input"),
        _measurement("systolic_bp_mmhg", 120.0, "mmHg", source="user_input", method="user_input"),
        _measurement("diastolic_bp_mmhg", 80.0, "mmHg", source="user_input", method="user_input"),
        _measurement("edv_ml", 130.0, "mL", source="user_input", method="user_input"),
        _measurement("esv_ml", 50.0, "mL", source="user_input", method="user_input"),
        _measurement("ejection_fraction_pct", 61.5, "%", source="user_input", method="user_input"),
    ]

    response = await run_validator_agent(extracted_fields=measurements, case_id="case-priority")
    output = ValidatorOutput.model_validate(response.outputs["structured_output"])

    hr = output.validated_fields["heart_rate_bpm"]
    assert hr.source == "manual_input"
    assert hr.selected_value == 74.0
    assert len(hr.evidence_candidates) == 2
    assert {c.value for c in hr.evidence_candidates} == {95.0, 74.0}


async def test_missing_critical_fields_reported_without_crashing():
    sparse = {
        "heart_rate_bpm": _candidate(75.0, "bpm", method="user_input"),
        "systolic_bp_mmhg": _candidate(118.0, "mmHg", method="user_input"),
    }

    response = await run_validator_agent(extracted_fields=sparse, case_id="case-sparse")
    output = ValidatorOutput.model_validate(response.outputs["structured_output"])

    assert "diastolic_bp_mmhg" in output.missing_critical_fields
    assert "edv_ml" in output.missing_critical_fields
    assert "esv_ml" in output.missing_critical_fields
    assert output.validated_fields["edv_ml"].status == "missing"
    assert response.status != AgentStatus.FAILED


async def test_data_quality_score_is_clamped():
    empty_response = await run_validator_agent(extracted_fields={}, case_id="case-empty")
    empty_output = ValidatorOutput.model_validate(empty_response.outputs["structured_output"])
    assert 0.0 <= empty_output.data_quality_score <= 1.0

    rich = {
        "heart_rate_bpm": _candidate(72.0, "bpm", source="user_input", confidence=0.97, method="user_input"),
        "systolic_bp_mmhg": _candidate(118.0, "mmHg", source="user_input", confidence=0.97, method="user_input"),
        "diastolic_bp_mmhg": _candidate(76.0, "mmHg", source="user_input", confidence=0.97, method="user_input"),
        "edv_ml": _candidate(125.0, "mL", source="user_input", confidence=0.97, method="user_input"),
        "esv_ml": _candidate(48.0, "mL", source="user_input", confidence=0.97, method="user_input"),
        "ejection_fraction_pct": _candidate(61.6, "%", source="user_input", confidence=0.97, method="user_input"),
        "oxygen_saturation_pct": _candidate(98.0, "%", source="user_input", confidence=0.97, method="user_input"),
        "qrs_duration_ms": _candidate(95.0, "ms", source="user_input", confidence=0.97, method="user_input"),
        "qt_interval_ms": _candidate(380.0, "ms", source="user_input", confidence=0.97, method="user_input"),
        "qtc_ms": _candidate(420.0, "ms", source="user_input", confidence=0.97, method="user_input"),
        "troponin_ng_l": _candidate(8.0, "ng/L", source="user_input", confidence=0.97, method="user_input"),
        "bnp_pg_ml": _candidate(60.0, "pg/mL", source="user_input", confidence=0.97, method="user_input"),
    }
    rich_response = await run_validator_agent(extracted_fields=rich, case_id="case-rich")
    rich_output = ValidatorOutput.model_validate(rich_response.outputs["structured_output"])
    assert 0.0 <= rich_output.data_quality_score <= 1.0
    assert rich_output.data_quality_score > empty_output.data_quality_score


async def test_openai_missing_key_does_not_fail_validation(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)

    fields = dict(GOLDEN_FIELDS)
    fields["edv_ml"] = _candidate(90.0, "mL", method="user_input")
    fields["esv_ml"] = _candidate(120.0, "mL", method="user_input")
    fields.pop("ejection_fraction_pct")

    response = await run_validator_agent(extracted_fields=fields, case_id="case-no-openai")
    output = ValidatorOutput.model_validate(response.outputs["structured_output"])

    assert output.conflicts  # conflict detection still ran deterministically
    assert response.status != AgentStatus.FAILED
    stage_result = response.outputs["agent_stage_result"]
    assert stage_result["model_used"] is None


async def test_output_schema_validates():
    response = await run_validator_agent(extracted_fields=GOLDEN_FIELDS, case_id="case-schema")

    output = ValidatorOutput.model_validate(response.outputs["structured_output"])
    assert isinstance(output.data_quality_score, float)
    assert response.outputs["agent_stage_result"]["agent_id"] == "evidence_validator"
    assert response.outputs["agent_stage_result"]["agent_name"] == "Evidence Validator Agent"
