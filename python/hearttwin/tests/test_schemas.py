"""Tests for Pydantic schemas and safety layer."""

import pytest
from pydantic import ValidationError

from python.hearttwin.safety import (
    SafetyViolation,
    add_disclaimer,
    check_request_safety,
    enforce_simulation_language,
    redact_pii,
)
from python.hearttwin.schemas import (
    CardiacTwinState,
    CaseRecord,
    MeasuredValue,
    Measurements,
    OperatingEnvironment,
    RecoveryConfig,
    SafetyLevel,
    SimulationConfig,
    ValueSource,
)


class TestMeasuredValue:
    def test_valid_measured_value(self):
        mv = MeasuredValue(value=70.0, unit="bpm", source=ValueSource.FILE_EXTRACTION, confidence=0.85)
        assert mv.value == 70.0
        assert mv.unit == "bpm"
        assert mv.confidence == 0.85

    def test_confidence_out_of_range(self):
        with pytest.raises(ValidationError):
            MeasuredValue(value=70.0, unit="bpm", source=ValueSource.FILE_EXTRACTION, confidence=1.5)

    def test_confidence_negative(self):
        with pytest.raises(ValidationError):
            MeasuredValue(value=70.0, unit="bpm", source=ValueSource.FILE_EXTRACTION, confidence=-0.1)


class TestCardiacTwinState:
    def test_default_state(self):
        state = CardiacTwinState()
        assert state.case_id is not None
        assert state.data_quality_score == 0.0
        assert state.safety_level == SafetyLevel.CLEAR
        assert state.warnings == []
        assert state.source_map == []

    def test_state_with_measurements(self):
        state = CardiacTwinState()
        state.measurements.heart_rate_bpm = MeasuredValue(
            value=72.0, unit="bpm", source=ValueSource.USER_INPUT, confidence=0.95
        )
        assert state.measurements.heart_rate_bpm.value == 72.0

    def test_state_serializes(self):
        state = CardiacTwinState()
        d = state.model_dump()
        assert "case_id" in d
        assert "measurements" in d
        assert "electrophysiology" in d

    def test_state_round_trips(self):
        state = CardiacTwinState()
        state.measurements.heart_rate_bpm = MeasuredValue(
            value=75.0, unit="bpm", source=ValueSource.FILE_EXTRACTION, confidence=0.80
        )
        data = state.model_dump()
        state2 = CardiacTwinState(**data)
        assert state2.measurements.heart_rate_bpm.value == 75.0


class TestCaseRecord:
    def test_default_case(self):
        case = CaseRecord()
        assert case.case_id is not None
        assert case.files == []
        assert case.stage_results == []
        assert case.status == "created"
        assert "SIMULATION ONLY" in case.safety_disclaimer

    def test_case_disclaimer_present(self):
        case = CaseRecord()
        assert "not for" in case.safety_disclaimer.lower() or "does not" in case.safety_disclaimer.lower()


class TestSafetyLayer:
    def test_safe_text_passes(self):
        check_request_safety("Show me the ejection fraction simulation")

    def test_diagnosis_blocked(self):
        with pytest.raises(SafetyViolation):
            check_request_safety("Can you diagnose my heart condition?")

    def test_prescription_blocked(self):
        with pytest.raises(SafetyViolation):
            check_request_safety("What medication should I prescribe for this?")

    def test_emergency_blocked(self):
        with pytest.raises(SafetyViolation):
            check_request_safety("This is an emergency triage situation")

    def test_treatment_blocked(self):
        with pytest.raises(SafetyViolation):
            check_request_safety("What treatment do you recommend?")

    def test_simulation_language_replaces_healed(self):
        result = enforce_simulation_language("The patient has healed after 30 days")
        assert "healed" not in result.lower()
        assert "simulated" in result.lower()

    def test_add_disclaimer(self):
        resp = {"data": "some output"}
        out = add_disclaimer(resp)
        assert "safety_disclaimer" in out
        assert "SIMULATION" in out["safety_disclaimer"]

    def test_redact_ssn(self):
        text = "Patient SSN: 123-45-6789"
        result = redact_pii(text)
        assert "123-45-6789" not in result
        assert "REDACTED" in result

    def test_redact_email(self):
        text = "Email: patient@hospital.com"
        result = redact_pii(text)
        assert "patient@hospital.com" not in result


class TestSimulationConfig:
    def test_default_config(self):
        cfg = SimulationConfig()
        assert cfg.operating.mode.value == "rest"
        assert cfg.recovery.recovery_horizon_days == 30
        assert cfg.random_seed == 42

    def test_recovery_horizon_bounds(self):
        with pytest.raises(ValidationError):
            RecoveryConfig(recovery_horizon_days=0)
        with pytest.raises(ValidationError):
            RecoveryConfig(recovery_horizon_days=400)
