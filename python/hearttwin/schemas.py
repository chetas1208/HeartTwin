"""Canonical Pydantic schemas for HeartTwin Lab.

All numeric values must carry source, unit, and confidence.
No value may be invented or hallucinated.
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any, Optional
from uuid import uuid4

from pydantic import BaseModel, Field, model_validator

from python.hearttwin.safety import DISCLAIMER


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


class OperatingMode(str, Enum):
    REST = "rest"
    MILD_ACTIVITY = "mild_activity"
    STRESS = "stress"
    RECOVERY = "recovery"


class RecoveryScenarioType(str, Enum):
    LOAD_REDUCTION = "load_reduction"
    OXYGEN_DELIVERY_IMPROVEMENT = "oxygen_delivery_improvement"
    CONTRACTILITY_SUPPORT = "contractility_support"
    CONDITIONING = "conditioning"
    STABILITY_MONITORING = "stability_monitoring"
    CUSTOM = "custom"


class TargetMetric(str, Enum):
    CARDIAC_OUTPUT = "cardiac_output"
    EF = "ef"
    PV_LOOP_EFFICIENCY = "pv_loop_efficiency"
    STABILITY = "stability"
    BALANCED = "balanced"


class DataUncertaintyPolicy(str, Enum):
    CONSERVATIVE = "conservative"
    MODERATE = "moderate"
    OPTIMISTIC = "optimistic"


class MissingValuePolicy(str, Enum):
    NULL = "null"
    PRIOR = "prior"
    REFUSE = "refuse"


class AgentStatus(str, Enum):
    SUCCESS = "success"
    WARNING = "warning"
    FAILED = "failed"


class SafetyLevel(str, Enum):
    CLEAR = "clear"
    CAUTION = "caution"
    BLOCKED = "blocked"


class ValueSource(str, Enum):
    FILE_EXTRACTION = "file_extraction"
    USER_INPUT = "user_input"
    DEFAULT_MODEL_PRIOR = "default_model_prior"
    DERIVED = "derived"


# ---------------------------------------------------------------------------
# Annotated measurement value with provenance
# ---------------------------------------------------------------------------


class MeasuredValue(BaseModel):
    value: float
    unit: str
    source: ValueSource
    confidence: float = Field(ge=0.0, le=1.0)
    source_file_id: Optional[str] = None
    method: Optional[str] = None
    evidence: Optional[str] = None


# ---------------------------------------------------------------------------
# Patient context (all optional — missing stays null)
# ---------------------------------------------------------------------------


class PatientContext(BaseModel):
    age_years: Optional[MeasuredValue] = None
    sex: Optional[str] = None
    height_cm: Optional[MeasuredValue] = None
    weight_kg: Optional[MeasuredValue] = None
    bsa_m2: Optional[MeasuredValue] = None
    notes: Optional[str] = None


# ---------------------------------------------------------------------------
# Clinical measurements
# ---------------------------------------------------------------------------


class Measurements(BaseModel):
    heart_rate_bpm: Optional[MeasuredValue] = None
    systolic_bp_mmhg: Optional[MeasuredValue] = None
    diastolic_bp_mmhg: Optional[MeasuredValue] = None
    edv_ml: Optional[MeasuredValue] = None
    esv_ml: Optional[MeasuredValue] = None
    ejection_fraction_pct: Optional[MeasuredValue] = None
    stroke_volume_ml: Optional[MeasuredValue] = None
    cardiac_output_l_min: Optional[MeasuredValue] = None
    troponin_ng_l: Optional[MeasuredValue] = None
    bnp_pg_ml: Optional[MeasuredValue] = None
    oxygen_saturation_pct: Optional[MeasuredValue] = None


# ---------------------------------------------------------------------------
# Electrophysiology
# ---------------------------------------------------------------------------


class Electrophysiology(BaseModel):
    rhythm_label: Optional[str] = None
    rr_interval_ms: Optional[MeasuredValue] = None
    qrs_duration_ms: Optional[MeasuredValue] = None
    qt_interval_ms: Optional[MeasuredValue] = None
    qtc_ms: Optional[MeasuredValue] = None
    r_peak_confidence: Optional[float] = Field(None, ge=0.0, le=1.0)
    conduction_delay_score: Optional[MeasuredValue] = None
    arrhythmia_instability_score: Optional[MeasuredValue] = None


# ---------------------------------------------------------------------------
# Hemodynamics indices
# ---------------------------------------------------------------------------


class Hemodynamics(BaseModel):
    preload_index: Optional[MeasuredValue] = None
    afterload_index: Optional[MeasuredValue] = None
    contractility_index: Optional[MeasuredValue] = None
    arterial_compliance_index: Optional[MeasuredValue] = None
    systemic_vascular_resistance_index: Optional[MeasuredValue] = None
    filling_pressure_index: Optional[MeasuredValue] = None
    pv_loop_area_index: Optional[MeasuredValue] = None


# ---------------------------------------------------------------------------
# Tissue state
# ---------------------------------------------------------------------------


class TissueState(BaseModel):
    scar_fraction: Optional[MeasuredValue] = None
    inflammation_index: Optional[MeasuredValue] = None
    oxygen_delivery_index: Optional[MeasuredValue] = None
    myocardial_oxygen_demand_index: Optional[MeasuredValue] = None
    stiffness_index: Optional[MeasuredValue] = None
    remodeling_index: Optional[MeasuredValue] = None
    damage_zone_location: Optional[str] = None


# ---------------------------------------------------------------------------
# Operating environment
# ---------------------------------------------------------------------------


class OperatingEnvironment(BaseModel):
    mode: OperatingMode = OperatingMode.REST
    simulation_duration_seconds: float = 60.0
    time_step_ms: float = 1.0
    activity_level_mets: float = 1.0
    hydration_index: float = 1.0
    sleep_recovery_index: float = 1.0
    stress_catecholamine_index: float = 1.0
    ambient_temperature_c: float = 22.0
    altitude_m: float = 0.0
    oxygen_fraction: float = 0.21
    medication_effect_profile: Optional[dict[str, float]] = None
    data_uncertainty_policy: DataUncertaintyPolicy = DataUncertaintyPolicy.MODERATE
    missing_value_policy: MissingValuePolicy = MissingValuePolicy.PRIOR


# ---------------------------------------------------------------------------
# Recovery / healing scenario config
# ---------------------------------------------------------------------------


class RecoveryConfig(BaseModel):
    recovery_horizon_days: int = Field(30, ge=1, le=365)
    scenario_type: RecoveryScenarioType = RecoveryScenarioType.LOAD_REDUCTION
    contractility_delta_per_day: float = 0.005
    afterload_delta_per_day: float = -0.005
    preload_delta_per_day: float = -0.003
    inflammation_decay_rate: float = 0.03
    oxygen_delivery_delta_per_day: float = 0.003
    stiffness_delta_per_day: float = -0.002
    scar_remodeling_rate: float = 0.001
    heart_rate_adaptation_rate: float = 0.002
    arrhythmia_stability_delta: float = 0.005
    max_safe_parameter_shift: float = 0.30
    uncertainty_penalty_weight: float = 0.2
    target_metric: TargetMetric = TargetMetric.BALANCED


# ---------------------------------------------------------------------------
# Simulation config (combines operating + recovery)
# ---------------------------------------------------------------------------


class SimulationConfig(BaseModel):
    operating: OperatingEnvironment = Field(default_factory=OperatingEnvironment)
    recovery: RecoveryConfig = Field(default_factory=RecoveryConfig)
    random_seed: int = 42


# ---------------------------------------------------------------------------
# Source map entry
# ---------------------------------------------------------------------------


class SourceMapEntry(BaseModel):
    field: str
    value: Optional[float] = None
    unit: str = ""
    source: ValueSource
    source_file_id: Optional[str] = None
    confidence: float
    method: Optional[str] = None
    evidence: Optional[str] = None


# ---------------------------------------------------------------------------
# Canonical cardiac twin state
# ---------------------------------------------------------------------------


class CardiacTwinState(BaseModel):
    case_id: str = Field(default_factory=lambda: str(uuid4()))
    created_at: datetime = Field(default_factory=datetime.utcnow)
    data_quality_score: float = Field(0.0, ge=0.0, le=1.0)
    safety_level: SafetyLevel = SafetyLevel.CLEAR
    patient_context: PatientContext = Field(default_factory=PatientContext)
    measurements: Measurements = Field(default_factory=Measurements)
    electrophysiology: Electrophysiology = Field(default_factory=Electrophysiology)
    hemodynamics: Hemodynamics = Field(default_factory=Hemodynamics)
    tissue_state: TissueState = Field(default_factory=TissueState)
    operating_environment: OperatingEnvironment = Field(default_factory=OperatingEnvironment)
    simulation_config: SimulationConfig = Field(default_factory=SimulationConfig)
    source_map: list[SourceMapEntry] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Agent response envelope
# ---------------------------------------------------------------------------


class AgentTraceStep(BaseModel):
    tool: str
    inputs: dict[str, Any]
    outputs: dict[str, Any]
    duration_ms: float


class AgentResponse(BaseModel):
    agent: str
    status: AgentStatus
    inputs_used: list[str] = Field(default_factory=list)
    outputs: dict[str, Any] = Field(default_factory=dict)
    warnings: list[str] = Field(default_factory=list)
    confidence: float = Field(0.0, ge=0.0, le=1.0)
    trace: list[AgentTraceStep] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# File metadata
# ---------------------------------------------------------------------------


class UploadedFile(BaseModel):
    file_id: str = Field(default_factory=lambda: str(uuid4()))
    filename: str
    content_type: str
    size_bytes: int
    storage_url: Optional[str] = None
    uploaded_at: datetime = Field(default_factory=datetime.utcnow)


# ---------------------------------------------------------------------------
# Case record
# ---------------------------------------------------------------------------


class CaseRecord(BaseModel):
    case_id: str = Field(default_factory=lambda: str(uuid4()))
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)
    files: list[UploadedFile] = Field(default_factory=list)
    patient_notes: Optional[str] = None
    validated_fields: dict[str, Any] = Field(default_factory=dict)
    state: Optional[CardiacTwinState] = None
    stage_results: list[AgentResponse] = Field(default_factory=list)
    simulation_result: Optional[dict[str, Any]] = None
    recovery_scenarios: Optional[list[dict[str, Any]]] = None
    status: str = "created"
    safety_disclaimer: str = DISCLAIMER


# ---------------------------------------------------------------------------
# API request/response models
# ---------------------------------------------------------------------------


class CreateCaseRequest(BaseModel):
    patient_notes: Optional[str] = None
    simulation_config: Optional[SimulationConfig] = None


class ExtractRequest(BaseModel):
    file_ids: list[str]
    user_vitals: Optional[dict[str, Any]] = None


class OperateRequest(BaseModel):
    operating_environment: Optional[OperatingEnvironment] = None


class SimulateRecoveryRequest(BaseModel):
    recovery_config: Optional[RecoveryConfig] = None
    scenarios: Optional[list[RecoveryConfig]] = None


class HealthResponse(BaseModel):
    status: str = "ok"
    service: str = "hearttwin-api"
    disclaimer: str = DISCLAIMER
    environment: dict[str, Any] = Field(default_factory=dict)
