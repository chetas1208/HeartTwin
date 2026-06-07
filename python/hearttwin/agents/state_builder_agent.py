"""Agent 4: Cardiac State Builder Agent.

Builds the canonical CardiacTwinState — the single source of truth for the
app — from validated evidence, explicitly labelled population priors, and
safe simulation defaults.

Every numeric value is computed only through deterministic Python tools and
carries a source-map entry (value/unit/source/confidence/method/evidence).
The configured OpenAI model is used solely to narrate *how* the mapping was
done (schema-mapping summaries / ambiguity explanations) — it never produces
or adjusts a number.
"""

from __future__ import annotations

import json
import os
import pathlib
import time
from typing import Any, Optional

from pydantic import BaseModel, Field

from python.hearttwin.schemas import (
    AgentResponse,
    AgentStatus,
    CardiacTwinState,
    DataUncertaintyPolicy,
    Electrophysiology,
    Hemodynamics,
    MeasuredValue,
    Measurements,
    MissingValuePolicy,
    OperatingEnvironment,
    OperatingMode,
    PatientContext,
    SafetyLevel,
    SimulationConfig,
    SourceMapEntry,
    TissueState,
    ValueSource,
)
from python.hearttwin.tools.cardiac_state import (
    compute_bsa_mosteller,
    compute_cardiac_output,
    compute_ejection_fraction,
    compute_map,
    compute_qtc_bazett,
    compute_rr_from_hr,
    compute_stroke_volume,
)
from python.hearttwin.tools.model_config import chat_tuning, get_state_builder_model
from python.hearttwin.tools.scoring import compute_data_quality_score
from python.hearttwin.tools.weave_trace import TraceContext

_PRIORS_PATH = pathlib.Path(__file__).parent.parent / "data" / "priors.json"
_PRIORS: dict = json.loads(_PRIORS_PATH.read_text())

_BOUNDS_PATH = pathlib.Path(__file__).parent.parent / "data" / "parameter_bounds.json"
_BOUNDS: dict = json.loads(_BOUNDS_PATH.read_text())

_AGENT_ID = "cardiac_state_builder"
_AGENT_NAME = "Cardiac State Builder Agent"
_TRACE_TOOL = "hearttwin.build_cardiac_state"
_DEFAULT_STATE_BUILDER_MODEL = "gpt-5.5"

# Hard ceiling for any default_model_prior confidence — priors must always
# read as clearly lower-confidence than real evidence.
_PRIOR_CONFIDENCE_CAP = 0.45

# In-memory fallback for the case-scoped state memory key (mirrors the
# module-level stores in tools/storage.py and tools/case_memory.py).
_STATE_MEMORY: dict[str, dict[str, Any]] = {}


# ---------------------------------------------------------------------------
# Schema-bound input/output contracts for this stage
# ---------------------------------------------------------------------------


class ValidatedField(BaseModel):
    """One piece of validated evidence handed to the state builder."""

    model_config = {"extra": "allow"}

    value: Any = None
    unit: Optional[str] = None
    source: Optional[str] = None
    confidence: Optional[float] = None
    source_file_id: Optional[str] = None
    method: Optional[str] = None
    evidence: Optional[str] = None
    extraction_method: Optional[str] = None
    raw_evidence: Optional[str] = None


class StateBuilderInput(BaseModel):
    case_id: str
    validated_fields: dict[str, ValidatedField]
    operating_environment: Optional[dict[str, Any]] = None
    priors: dict[str, Any] = Field(default_factory=dict)
    parameter_bounds: dict[str, Any] = Field(default_factory=dict)


class StateBuilderStageResult(BaseModel):
    """Schema-bound contribution record for the cardiac state builder stage."""

    agent_id: str = _AGENT_ID
    agent_name: str = _AGENT_NAME
    model_used: Optional[str] = None
    fields_mapped: list[str] = Field(default_factory=list)
    priors_used: list[dict[str, Any]] = Field(default_factory=list)
    derived_values_computed: list[dict[str, Any]] = Field(default_factory=list)
    missing_values: list[str] = Field(default_factory=list)
    source_coverage: dict[str, float] = Field(default_factory=dict)
    warnings: list[str] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Small mapping primitives
# ---------------------------------------------------------------------------


def _to_source(source_str: Optional[str]) -> ValueSource:
    mapping = {
        "file_extraction": ValueSource.FILE_EXTRACTION,
        "extracted": ValueSource.FILE_EXTRACTION,
        "user_input": ValueSource.USER_INPUT,
        "manual_input": ValueSource.USER_INPUT,
        "default_model_prior": ValueSource.DEFAULT_MODEL_PRIOR,
        "derived": ValueSource.DERIVED,
        "computed": ValueSource.DERIVED,
    }
    return mapping.get((source_str or "").lower(), ValueSource.FILE_EXTRACTION)


def _coerce_validated_field(entry: Any) -> ValidatedField:
    """Wrap a heterogeneous validated_fields entry in the schema-bound model."""
    if isinstance(entry, ValidatedField):
        return entry
    if isinstance(entry, dict):
        try:
            return ValidatedField(**entry)
        except Exception:
            return ValidatedField(value=entry.get("value"))
    return ValidatedField(value=entry)


def _build_measured_from_validated(field: str, vf: ValidatedField) -> Optional[MeasuredValue]:
    if vf.value is None or not isinstance(vf.value, (int, float)) or isinstance(vf.value, bool):
        return None
    return MeasuredValue(
        value=float(vf.value),
        unit=vf.unit or "",
        source=_to_source(vf.source),
        confidence=vf.confidence if vf.confidence is not None else 0.7,
        source_file_id=vf.source_file_id,
        method=vf.method or vf.extraction_method,
        evidence=vf.evidence or vf.raw_evidence,
    )


def _source_entry(field: str, mv: MeasuredValue, **overrides: Any) -> SourceMapEntry:
    return SourceMapEntry(
        field=field,
        value=mv.value,
        unit=mv.unit,
        source=mv.source,
        source_file_id=mv.source_file_id,
        confidence=mv.confidence,
        method=overrides.get("method", mv.method),
        evidence=overrides.get("evidence", mv.evidence),
    )


def _is_real_evidence(mv: Optional[MeasuredValue]) -> bool:
    """True when a value is grounded in evidence (not a population prior)."""
    return mv is not None and mv.source in (
        ValueSource.FILE_EXTRACTION,
        ValueSource.USER_INPUT,
        ValueSource.DERIVED,
    )


def _derived_measured(value: float, unit: str, confidence: float = 0.95) -> MeasuredValue:
    return MeasuredValue(
        value=round(value, 4),
        unit=unit,
        source=ValueSource.DERIVED,
        confidence=confidence,
        method="deterministic_formula",
    )


def _record_derived(
    source_map: list[SourceMapEntry],
    derived_values: list[dict[str, Any]],
    field: str,
    value: float,
    unit: str,
    formula: str,
    confidence: float = 0.95,
) -> None:
    rounded = round(value, 4)
    source_map.append(SourceMapEntry(
        field=field,
        value=rounded,
        unit=unit,
        source=ValueSource.DERIVED,
        confidence=confidence,
        method="deterministic_formula",
        evidence=formula,
    ))
    derived_values.append({
        "field": field,
        "value": rounded,
        "unit": unit,
        "method": "deterministic_formula",
        "formula": formula,
    })


def _timed_tool(tracer: TraceContext, name: str, fn, inputs: dict[str, float], output_key: str) -> float:
    t0 = time.time()
    value = fn(**inputs)
    tracer.record_tool(
        name,
        inputs=inputs,
        outputs={output_key: round(value, 4)},
        duration_ms=(time.time() - t0) * 1000,
    )
    return value


def _apply_scalar_prior(
    field: str,
    prior_entry: Optional[dict[str, Any]],
    unit_fallback: str,
    *,
    note: str,
    source_map: list[SourceMapEntry],
    warnings: list[str],
    priors_used: list[dict[str, Any]],
) -> Optional[MeasuredValue]:
    """Apply an explicitly labelled population prior — confidence capped, warning logged."""
    if not prior_entry:
        return None
    confidence = min(prior_entry.get("confidence", 0.3), _PRIOR_CONFIDENCE_CAP)
    mv = MeasuredValue(
        value=float(prior_entry["value"]),
        unit=prior_entry.get("unit", unit_fallback),
        source=ValueSource.DEFAULT_MODEL_PRIOR,
        confidence=confidence,
        method="population_prior",
        evidence=note,
    )
    warnings.append(
        f"{field}: no evidence available — using population prior "
        f"(source: default_model_prior, confidence={confidence})"
    )
    priors_used.append({
        "field": field,
        "value": mv.value,
        "confidence": confidence,
        "label": "default_model_prior",
    })
    source_map.append(_source_entry(field, mv))
    return mv


def _attach_ct_segmentation(
    validated_fields: dict[str, Any],
    source_map: list[SourceMapEntry],
    warnings: list[str],
) -> Optional[dict[str, Any]]:
    """Carry the CT segmentation artifact onto the state + record provenance.

    Adds a `method="ct_segmentation"` source-map entry so the findings layer
    reports `imaging_source = vista3d_segmentation`. Never invents cardiac
    scalars — CT here yields only volumetric proxies (single heart label).
    """
    entry = validated_fields.get("__ct_segmentation__")
    if not isinstance(entry, dict):
        return None
    payload = entry.get("value")
    if not isinstance(payload, dict):
        return None

    status = payload.get("status")
    source_map.append(SourceMapEntry(
        field="ct_segmentation",
        value=None,
        unit="segmentation",
        source=ValueSource.FILE_EXTRACTION,
        source_file_id=entry.get("source_file_id"),
        confidence=float(entry.get("confidence", 0.0) or 0.0),
        method="ct_segmentation",
        evidence=(f"VISTA-3D CT segmentation ({status}); "
                  f"job {payload.get('job_id', 'n/a')}"),
    ))
    if status != "analyzed":
        warnings.append(
            f"CT segmentation present but not analyzed (status: {status}) — "
            "no CT-derived volumes available; no values invented."
        )
    return payload


# ---------------------------------------------------------------------------
# Section builders — the unique state-building logic for this agent
# ---------------------------------------------------------------------------

_SCALAR_MEASUREMENT_FIELDS: list[tuple[str, Optional[str]]] = [
    ("heart_rate_bpm", "heart_rate_bpm"),
    ("systolic_bp_mmhg", "systolic_bp_mmhg"),
    ("diastolic_bp_mmhg", "diastolic_bp_mmhg"),
    ("edv_ml", "edv_ml"),
    ("esv_ml", "esv_ml"),
    ("ejection_fraction_pct", "ejection_fraction_pct"),
    ("stroke_volume_ml", "stroke_volume_ml"),
    ("cardiac_output_l_min", "cardiac_output_l_min"),
    ("troponin_ng_l", None),
    ("bnp_pg_ml", None),
    ("oxygen_saturation_pct", "oxygen_saturation_pct"),
]


def _map_measurements(
    coerced: dict[str, ValidatedField],
    priors: dict[str, Any],
    source_map: list[SourceMapEntry],
    warnings: list[str],
    fields_mapped: list[str],
    priors_used: list[dict[str, Any]],
    missing_values: list[str],
) -> tuple[Measurements, dict[str, Optional[MeasuredValue]]]:
    """Map validated evidence onto canonical measurement slots.

    Validated evidence always wins. A population prior only ever fills a gap,
    is explicitly labelled `default_model_prior`, capped at the prior
    confidence ceiling, and always carries a warning — it never overwrites an
    extracted or user-provided value.
    """
    adult_typical = priors.get("adult_typical", {})
    values: dict[str, Optional[MeasuredValue]] = {}

    for field, prior_key in _SCALAR_MEASUREMENT_FIELDS:
        vf = coerced.get(field)
        mv = _build_measured_from_validated(field, vf) if vf else None

        if mv is not None:
            values[field] = mv
            fields_mapped.append(field)
            source_map.append(_source_entry(field, mv))
            continue

        prior_mv = None
        if prior_key:
            prior_mv = _apply_scalar_prior(
                field,
                adult_typical.get(prior_key),
                "",
                note="No patient evidence available — adult population typical applied",
                source_map=source_map,
                warnings=warnings,
                priors_used=priors_used,
            )

        values[field] = prior_mv
        if prior_mv is None:
            missing_values.append(field)

    return Measurements(**values), values


def _derive_measurement_metrics(
    meas: Measurements,
    values: dict[str, Optional[MeasuredValue]],
    source_map: list[SourceMapEntry],
    warnings: list[str],
    derived_values: list[dict[str, Any]],
    tracer: TraceContext,
) -> None:
    """Derive SV, EF, CO, and MAP — strictly from real evidence, deterministic tools only.

    Rules enforced here: EDV must exceed ESV before SV/EF are derived; missing
    EDV/ESV means no SV is invented; an existing reported EF is left as-is
    rather than overwritten by a volumes-derived figure; nothing is "derived"
    by chaining through low-confidence priors (that would mislabel a guess as
    a deterministic computation).
    """
    edv_mv, esv_mv = values.get("edv_ml"), values.get("esv_ml")
    hr_mv = values.get("heart_rate_bpm")
    sbp_mv, dbp_mv = values.get("systolic_bp_mmhg"), values.get("diastolic_bp_mmhg")

    if _is_real_evidence(edv_mv) and _is_real_evidence(esv_mv):
        edv, esv = edv_mv.value, esv_mv.value
        if esv < edv:
            sv_val = _timed_tool(tracer, "compute_stroke_volume", compute_stroke_volume,
                                 {"edv_ml": edv, "esv_ml": esv}, "stroke_volume_ml")
            ef_val = _timed_tool(tracer, "compute_ejection_fraction", compute_ejection_fraction,
                                 {"edv_ml": edv, "esv_ml": esv}, "ejection_fraction_pct")

            sv_existing = values.get("stroke_volume_ml")
            if sv_existing is None or sv_existing.source == ValueSource.DEFAULT_MODEL_PRIOR:
                meas.stroke_volume_ml = _derived_measured(sv_val, "mL")
                _record_derived(source_map, derived_values, "stroke_volume_ml", sv_val, "mL", "SV = EDV - ESV")

            ef_existing = values.get("ejection_fraction_pct")
            if ef_existing is None or ef_existing.source == ValueSource.DEFAULT_MODEL_PRIOR:
                meas.ejection_fraction_pct = _derived_measured(ef_val, "%")
                _record_derived(source_map, derived_values, "ejection_fraction_pct", ef_val, "%", "EF = (SV / EDV) * 100")
            else:
                warnings.append("ejection_fraction_pct: kept as reported/extracted (EDV/ESV-derived figure not used to overwrite it)")
        else:
            warnings.append(
                f"edv_ml ({edv}) is not greater than esv_ml ({esv}) — physiologically invalid; "
                "stroke volume and ejection fraction were not derived"
            )
    else:
        warnings.append("edv_ml/esv_ml not available as real evidence — stroke volume was not derived (and not guessed from priors)")

    sv_for_co = meas.stroke_volume_ml
    co_existing = values.get("cardiac_output_l_min")
    if (
        _is_real_evidence(hr_mv)
        and _is_real_evidence(sv_for_co)
        and (co_existing is None or co_existing.source == ValueSource.DEFAULT_MODEL_PRIOR)
    ):
        co_val = _timed_tool(tracer, "compute_cardiac_output", compute_cardiac_output,
                             {"heart_rate_bpm": hr_mv.value, "stroke_volume_ml": sv_for_co.value}, "cardiac_output_l_min")
        meas.cardiac_output_l_min = _derived_measured(co_val, "L/min", confidence=0.90)
        _record_derived(source_map, derived_values, "cardiac_output_l_min", co_val, "L/min", "CO = (HR × SV) / 1000", confidence=0.90)

    if _is_real_evidence(sbp_mv) and _is_real_evidence(dbp_mv) and dbp_mv.value < sbp_mv.value:
        map_val = _timed_tool(tracer, "compute_map", compute_map,
                              {"systolic_bp": sbp_mv.value, "diastolic_bp": dbp_mv.value}, "map_mmhg")
        _record_derived(source_map, derived_values, "map_mmhg", map_val, "mmHg", "MAP = DBP + (SBP - DBP) / 3", confidence=0.90)


_EP_REPORTED_FIELDS = ["qrs_duration_ms", "qt_interval_ms", "qtc_ms", "rr_interval_ms"]


def _map_electrophysiology(
    coerced: dict[str, ValidatedField],
    priors: dict[str, Any],
    meas: Measurements,
    source_map: list[SourceMapEntry],
    warnings: list[str],
    fields_mapped: list[str],
    priors_used: list[dict[str, Any]],
    missing_values: list[str],
    derived_values: list[dict[str, Any]],
    tracer: TraceContext,
) -> Electrophysiology:
    """Map ECG report fields and derive RR/QTc placeholders deterministically."""
    adult_typical = priors.get("adult_typical", {})
    values: dict[str, Optional[MeasuredValue]] = {}

    for field in _EP_REPORTED_FIELDS:
        vf = coerced.get(field)
        mv = _build_measured_from_validated(field, vf) if vf else None
        if mv is not None:
            values[field] = mv
            fields_mapped.append(field)
            source_map.append(_source_entry(field, mv))
        else:
            values[field] = None

    hr_mv = meas.heart_rate_bpm
    if values["rr_interval_ms"] is None and _is_real_evidence(hr_mv):
        rr_val = _timed_tool(tracer, "compute_rr_from_hr", compute_rr_from_hr,
                             {"heart_rate_bpm": hr_mv.value}, "rr_interval_ms")
        values["rr_interval_ms"] = _derived_measured(rr_val, "ms", confidence=0.90)
        _record_derived(source_map, derived_values, "rr_interval_ms", rr_val, "ms", "RR interval = 60000 / HR", confidence=0.90)

    qt_v, rr_v = values.get("qt_interval_ms"), values.get("rr_interval_ms")
    if values["qtc_ms"] is None and _is_real_evidence(qt_v) and _is_real_evidence(rr_v):
        qtc_val = _timed_tool(tracer, "compute_qtc_bazett", compute_qtc_bazett,
                              {"qt_ms": qt_v.value, "rr_ms": rr_v.value}, "qtc_ms")
        values["qtc_ms"] = _derived_measured(qtc_val, "ms", confidence=0.85)
        _record_derived(source_map, derived_values, "qtc_ms", qtc_val, "ms",
                        "QTc = QT / sqrt(RR_seconds) [Bazett]", confidence=0.85)

    for field in _EP_REPORTED_FIELDS:
        if values[field] is not None:
            continue
        prior_mv = _apply_scalar_prior(
            field,
            adult_typical.get(field),
            "ms",
            note="No ECG/HR evidence available — adult population typical applied",
            source_map=source_map,
            warnings=warnings,
            priors_used=priors_used,
        )
        values[field] = prior_mv
        if prior_mv is None:
            missing_values.append(field)

    rhythm_vf = coerced.get("rhythm_label")
    rhythm_label = str(rhythm_vf.value) if rhythm_vf is not None and rhythm_vf.value else None
    if rhythm_label:
        fields_mapped.append("rhythm_label")
        source_map.append(SourceMapEntry(
            field="rhythm_label",
            value=None,
            unit="",
            source=_to_source(rhythm_vf.source),
            confidence=rhythm_vf.confidence if rhythm_vf.confidence is not None else 0.5,
            method=rhythm_vf.method,
            evidence=rhythm_vf.evidence,
        ))
    else:
        missing_values.append("rhythm_label")

    return Electrophysiology(
        rhythm_label=rhythm_label,
        rr_interval_ms=values["rr_interval_ms"],
        qrs_duration_ms=values["qrs_duration_ms"],
        qt_interval_ms=values["qt_interval_ms"],
        qtc_ms=values["qtc_ms"],
    )


def _map_patient_context(
    coerced: dict[str, ValidatedField],
    source_map: list[SourceMapEntry],
    warnings: list[str],
    fields_mapped: list[str],
    missing_values: list[str],
    derived_values: list[dict[str, Any]],
    tracer: TraceContext,
) -> PatientContext:
    """Map demographic evidence and derive BSA only from real height/weight evidence."""
    age_vf, ht_vf, wt_vf, sex_vf = (
        coerced.get("age_years"), coerced.get("height_cm"),
        coerced.get("weight_kg"), coerced.get("sex"),
    )

    age_mv = _build_measured_from_validated("age_years", age_vf) if age_vf else None
    ht_mv = _build_measured_from_validated("height_cm", ht_vf) if ht_vf else None
    wt_mv = _build_measured_from_validated("weight_kg", wt_vf) if wt_vf else None

    for field, mv in (("age_years", age_mv), ("height_cm", ht_mv), ("weight_kg", wt_mv)):
        if mv is not None:
            fields_mapped.append(field)
            source_map.append(_source_entry(field, mv))
        else:
            missing_values.append(field)

    sex_value: Optional[str] = None
    if sex_vf is not None and sex_vf.value:
        sex_value = str(sex_vf.value)
        fields_mapped.append("sex")
        source_map.append(SourceMapEntry(
            field="sex",
            value=None,
            unit="",
            source=_to_source(sex_vf.source),
            confidence=sex_vf.confidence if sex_vf.confidence is not None else 0.5,
            method=sex_vf.method,
            evidence=sex_vf.evidence,
        ))
    else:
        missing_values.append("sex")

    bsa_mv: Optional[MeasuredValue] = None
    if _is_real_evidence(ht_mv) and _is_real_evidence(wt_mv):
        bsa_val = _timed_tool(tracer, "compute_bsa_mosteller", compute_bsa_mosteller,
                              {"height_cm": ht_mv.value, "weight_kg": wt_mv.value}, "bsa_m2")
        bsa_mv = _derived_measured(bsa_val, "m²", confidence=0.90)
        _record_derived(source_map, derived_values, "bsa_m2", bsa_val, "m²",
                        "BSA = sqrt(height_cm * weight_kg / 3600) [Mosteller]", confidence=0.90)

    return PatientContext(age_years=age_mv, sex=sex_value, height_cm=ht_mv, weight_kg=wt_mv, bsa_m2=bsa_mv)


_TISSUE_DEFAULT_FIELDS: list[tuple[str, float, str]] = [
    ("scar_fraction", 0.0, "fraction"),
    ("inflammation_index", 0.1, "index"),
    ("oxygen_delivery_index", 0.85, "index"),
    ("myocardial_oxygen_demand_index", 0.6, "index"),
    ("stiffness_index", 0.3, "index"),
    ("remodeling_index", 0.1, "index"),
]


def _init_tissue_state(
    coerced: dict[str, ValidatedField],
    priors: dict[str, Any],
    source_map: list[SourceMapEntry],
    warnings: list[str],
    priors_used: list[dict[str, Any]],
) -> TissueState:
    """Initialize conservative tissue placeholders for visualization only.

    These are population priors used purely so the simulator has something
    safe to render — never a claim about this patient's tissue. Confidence is
    capped at the prior ceiling and every field is labelled and warned about.
    """
    prior_tissue = priors.get("tissue_defaults", {})
    field_values: dict[str, MeasuredValue] = {}

    for field, fallback, unit in _TISSUE_DEFAULT_FIELDS:
        prior_entry = prior_tissue.get(field, {"value": fallback, "unit": unit, "confidence": 0.3})
        confidence = min(prior_entry.get("confidence", 0.3), _PRIOR_CONFIDENCE_CAP)
        mv = MeasuredValue(
            value=float(prior_entry.get("value", fallback)),
            unit=prior_entry.get("unit", unit),
            source=ValueSource.DEFAULT_MODEL_PRIOR,
            confidence=confidence,
            method="population_tissue_prior",
            evidence="No imaging/biopsy evidence — conservative population prior for visualization only",
        )
        field_values[field] = mv
        warnings.append(f"tissue_state.{field}: conservative population prior applied (no disease implied)")
        priors_used.append({"field": f"tissue_state.{field}", "value": mv.value, "confidence": confidence, "label": "default_model_prior"})
        source_map.append(_source_entry(f"tissue_state.{field}", mv))

    damage_zone_location: Optional[str] = None
    damage_vf = coerced.get("damage_zone_location")
    if damage_vf is not None and damage_vf.value:
        damage_zone_location = str(damage_vf.value)
        source_map.append(SourceMapEntry(
            field="tissue_state.damage_zone_location",
            value=None,
            unit="",
            source=_to_source(damage_vf.source),
            confidence=damage_vf.confidence if damage_vf.confidence is not None else 0.5,
            method=damage_vf.method,
            evidence=damage_vf.evidence,
        ))
    else:
        warnings.append("tissue_state.damage_zone_location: no evidence available — left unset (no location implied)")

    return TissueState(
        scar_fraction=field_values["scar_fraction"],
        inflammation_index=field_values["inflammation_index"],
        oxygen_delivery_index=field_values["oxygen_delivery_index"],
        myocardial_oxygen_demand_index=field_values["myocardial_oxygen_demand_index"],
        stiffness_index=field_values["stiffness_index"],
        remodeling_index=field_values["remodeling_index"],
        damage_zone_location=damage_zone_location,
    )


# Each entry: (field, default_value, unit, default_kind, confidence)
# default_kind is either "simulation_default" (engineering/safety choice,
# unrelated to the patient) or "default_model_prior" (population-level
# assumption about the patient's current state).
_OPERATING_ENV_DEFAULTS: list[tuple[str, Any, str, str, float]] = [
    ("mode", OperatingMode.REST.value, "", "simulation_default", 0.45),
    ("simulation_duration_seconds", 10.0, "s", "simulation_default", 0.45),
    ("time_step_ms", 20.0, "ms", "simulation_default", 0.45),
    ("activity_level_mets", 1.0, "METs", "default_model_prior", 0.35),
    ("hydration_index", 0.7, "index", "default_model_prior", 0.35),
    ("sleep_recovery_index", 0.7, "index", "default_model_prior", 0.35),
    ("stress_catecholamine_index", 0.2, "index", "default_model_prior", 0.35),
    ("ambient_temperature_c", 22.0, "°C", "simulation_default", 0.45),
    ("altitude_m", 0.0, "m", "simulation_default", 0.45),
    ("oxygen_fraction", 0.2095, "fraction", "simulation_default", 0.45),
    ("data_uncertainty_policy", DataUncertaintyPolicy.CONSERVATIVE.value, "", "simulation_default", 0.45),
    ("missing_value_policy", MissingValuePolicy.PRIOR.value, "", "simulation_default", 0.45),
]

# The spec names policy values that have no matching schema enum member.
# We normalize to the closest supported member and say so explicitly.
_REQUESTED_POLICY_ALIASES: dict[str, tuple[str, str]] = {
    "data_uncertainty_policy": ("explicit", DataUncertaintyPolicy.CONSERVATIVE.value),
    "missing_value_policy": ("warn_and_use_priors_only_if_needed", MissingValuePolicy.PRIOR.value),
}


def _normalize_operating_environment(
    raw_environment: Optional[dict[str, Any]],
    simulation_config: Optional[SimulationConfig],
    source_map: list[SourceMapEntry],
    warnings: list[str],
    priors_used: list[dict[str, Any]],
) -> OperatingEnvironment:
    """Resolve the operating environment, falling back to safe simulation defaults.

    Precedence: explicit `operating_environment` input > an existing
    simulation_config's operating section > safe defaults. Every field that
    falls back to a default is recorded in the source map (capped confidence,
    labelled simulation_default vs default_model_prior) with a warning, so no
    operating value ever reaches the UI unsourced.
    """
    provided: dict[str, Any] = {}
    if simulation_config is not None:
        provided.update(simulation_config.operating.model_dump(mode="json"))
    if raw_environment:
        provided.update({k: v for k, v in raw_environment.items() if v is not None})

    resolved: dict[str, Any] = {}
    for field, default_value, unit, kind, confidence in _OPERATING_ENV_DEFAULTS:
        if field in provided:
            resolved[field] = provided[field]
            alias = _REQUESTED_POLICY_ALIASES.get(field)
            if alias and provided[field] == alias[0]:
                warnings.append(
                    f"operating_environment.{field}: requested '{alias[0]}' has no matching schema "
                    f"enum — normalized to '{alias[1]}'"
                )
                resolved[field] = alias[1]
            continue

        resolved[field] = default_value
        capped_confidence = min(confidence, _PRIOR_CONFIDENCE_CAP)
        source_map.append(SourceMapEntry(
            field=f"operating_environment.{field}",
            value=float(default_value) if isinstance(default_value, (int, float)) else None,
            unit=unit,
            source=ValueSource.DEFAULT_MODEL_PRIOR,
            confidence=capped_confidence,
            method=kind,
            evidence="No operating environment supplied — safe simulation default applied",
        ))
        warnings.append(f"operating_environment.{field}: not provided — applied {kind} (value={default_value})")
        priors_used.append({
            "field": f"operating_environment.{field}",
            "value": default_value,
            "confidence": capped_confidence,
            "label": kind,
        })

    return OperatingEnvironment(**resolved)


def _compute_source_coverage(source_map: list[SourceMapEntry]) -> dict[str, float]:
    """Fraction of mapped fields backed by each evidence source — a completeness signal."""
    if not source_map:
        return {}
    counts: dict[str, int] = {}
    for entry in source_map:
        counts[entry.source.value] = counts.get(entry.source.value, 0) + 1
    total = len(source_map)
    return {source: round(count / total, 4) for source, count in counts.items()}


def _assemble_warnings(
    *,
    base_warnings: list[str],
    missing_values: list[str],
    priors_used: list[dict[str, Any]],
    data_quality_score: float,
) -> list[str]:
    """De-duplicate stage warnings and append summary-level transparency notes."""
    assembled = list(dict.fromkeys(base_warnings))
    if priors_used:
        assembled.append(
            f"{len(priors_used)} field(s) rely on population priors "
            f"(source: default_model_prior, confidence capped at {_PRIOR_CONFIDENCE_CAP})"
        )
    if missing_values:
        assembled.append(
            f"{len(missing_values)} canonical field(s) remain missing and were left unset: "
            f"{', '.join(sorted(set(missing_values)))}"
        )
    if data_quality_score < 0.35:
        assembled.append(
            f"Data quality score is low ({data_quality_score:.2f}) — this state leans heavily on "
            "priors and missing evidence; treat downstream simulation as illustrative only"
        )
    return assembled


# ---------------------------------------------------------------------------
# Model routing — explanations only, never numeric derivation
# ---------------------------------------------------------------------------


def _get_state_builder_model() -> str:
    return get_state_builder_model()


async def _explain_mapping_with_openai(
    *,
    model_name: str,
    fields_mapped: list[str],
    missing_values: list[str],
    priors_used: list[dict[str, Any]],
) -> tuple[Optional[str], Optional[str]]:
    """Ask the configured model for a short schema-mapping ambiguity summary.

    Strictly explanatory — every number it might mention was already computed
    deterministically above. Returns (summary_text, warning); never raises.
    """
    try:
        import openai

        client = openai.AsyncOpenAI(api_key=os.environ["OPENAI_API_KEY"])
        response = await client.chat.completions.create(
            model=model_name,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "In two sentences or fewer, summarize how validated cardiac evidence was "
                        "mapped onto the canonical simulation-state schema, and note which fields "
                        "fell back to population priors or remain missing. Do not invent numbers, "
                        "diagnoses, or treatment language — explanation only."
                    ),
                },
                {
                    "role": "user",
                    "content": json.dumps({
                        "fields_mapped": fields_mapped[:25],
                        "fields_using_priors": [p["field"] for p in priors_used][:25],
                        "missing_fields": missing_values[:25],
                    }),
                },
            ],
            **chat_tuning(model_name, 200, 0),
        )
        text = (response.choices[0].message.content or "").strip()
        return (text or None), None
    except Exception as exc:
        return None, f"State-mapping summary model call failed: {exc}"


# ---------------------------------------------------------------------------
# Redis-backed case state memory (Upstash REST, in-memory fallback)
# ---------------------------------------------------------------------------


async def _persist_state_memory(
    case_id: str,
    state: CardiacTwinState,
    source_map: list[SourceMapEntry],
    warnings: list[str],
) -> None:
    """Best-effort write of the canonical state to case-scoped memory.

    Mirrors tools/storage.py's env-gated Upstash REST pattern: the in-memory
    fallback is always updated first, then a Redis write is attempted only
    when configured. Never raises — a memory-write failure must not fail
    state building.
    """
    key = f"hearttwin:case:{case_id}:state"
    payload = {
        "case_id": case_id,
        "state": state.model_dump(mode="json"),
        "source_map": [entry.model_dump(mode="json") for entry in source_map],
        "data_quality_score": state.data_quality_score,
        "warnings": warnings,
    }
    _STATE_MEMORY[key] = payload

    from python.hearttwin.tools import redis_client

    await redis_client.set_json(key, payload)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


async def run_state_builder_agent(
    validated_fields: dict[str, Any],
    case_id: str,
    simulation_config: Optional[SimulationConfig] = None,
    operating_environment: Optional[dict[str, Any]] = None,
    priors: Optional[dict[str, Any]] = None,
    parameter_bounds: Optional[dict[str, Any]] = None,
) -> tuple[AgentResponse, CardiacTwinState]:
    """Build the canonical CardiacTwinState from validated evidence.

    `priors` and `parameter_bounds` default to the bundled population
    reference data (data/priors.json, data/parameter_bounds.json) so existing
    callers keep working unchanged; both can be overridden for testing or
    case-specific tuning per the StateBuilderInput contract.
    """
    tracer = TraceContext(case_id=case_id, agent_name="state_builder_agent")
    t0 = time.time()

    warnings: list[str] = []
    source_map: list[SourceMapEntry] = []
    fields_mapped: list[str] = []
    priors_used: list[dict[str, Any]] = []
    derived_values: list[dict[str, Any]] = []
    missing_values: list[str] = []

    active_priors = priors if priors is not None else _PRIORS
    active_bounds = parameter_bounds if parameter_bounds is not None else _BOUNDS

    coerced_fields = {k: _coerce_validated_field(v) for k, v in validated_fields.items()}
    builder_input = StateBuilderInput(
        case_id=case_id,
        validated_fields=coerced_fields,
        operating_environment=operating_environment,
        priors=active_priors,
        parameter_bounds=active_bounds,
    )

    meas, meas_values = _map_measurements(
        builder_input.validated_fields, active_priors, source_map, warnings,
        fields_mapped, priors_used, missing_values,
    )
    _derive_measurement_metrics(meas, meas_values, source_map, warnings, derived_values, tracer)

    ep = _map_electrophysiology(
        builder_input.validated_fields, active_priors, meas, source_map, warnings,
        fields_mapped, priors_used, missing_values, derived_values, tracer,
    )

    pc = _map_patient_context(
        builder_input.validated_fields, source_map, warnings,
        fields_mapped, missing_values, derived_values, tracer,
    )

    ts = _init_tissue_state(builder_input.validated_fields, active_priors, source_map, warnings, priors_used)

    ct_segmentation = _attach_ct_segmentation(validated_fields, source_map, warnings)

    operating = _normalize_operating_environment(
        builder_input.operating_environment, simulation_config, source_map, warnings, priors_used,
    )
    sim_config = (simulation_config or SimulationConfig()).model_copy(update={"operating": operating})

    state = CardiacTwinState(
        case_id=case_id,
        patient_context=pc,
        measurements=meas,
        electrophysiology=ep,
        hemodynamics=Hemodynamics(),
        tissue_state=ts,
        operating_environment=operating,
        simulation_config=sim_config,
        source_map=source_map,
        safety_level=SafetyLevel.CLEAR,
        ct_segmentation=ct_segmentation,
    )
    state.data_quality_score = compute_data_quality_score(state.model_dump(mode="json"))

    if state.data_quality_score < 0.35:
        state.safety_level = SafetyLevel.CAUTION
        warnings.append(
            f"Safety level raised to caution — data quality score ({state.data_quality_score:.2f}) "
            "is low and the state relies heavily on priors"
        )

    source_coverage = _compute_source_coverage(source_map)

    model_used: Optional[str] = None
    mapping_summary: Optional[str] = None
    if os.environ.get("OPENAI_API_KEY") and (missing_values or priors_used):
        model_name = _get_state_builder_model()
        mapping_summary, model_warning = await _explain_mapping_with_openai(
            model_name=model_name,
            fields_mapped=fields_mapped,
            missing_values=missing_values,
            priors_used=priors_used,
        )
        if model_warning:
            warnings.append(model_warning)
        elif mapping_summary:
            model_used = model_name

    warnings = _assemble_warnings(
        base_warnings=warnings,
        missing_values=missing_values,
        priors_used=priors_used,
        data_quality_score=state.data_quality_score,
    )
    state.warnings = warnings

    stage_result = StateBuilderStageResult(
        model_used=model_used,
        fields_mapped=fields_mapped,
        priors_used=priors_used,
        derived_values_computed=derived_values,
        missing_values=missing_values,
        source_coverage=source_coverage,
        warnings=warnings,
    )

    duration_ms = (time.time() - t0) * 1000
    tracer.record_tool(
        _TRACE_TOOL,
        inputs={"case_id": case_id, "validated_field_count": len(validated_fields)},
        outputs={
            "fields_used": fields_mapped,
            "priors_used_count": len(priors_used),
            "derived_values_count": len(derived_values),
            "missing_values": missing_values,
            "data_quality_score": state.data_quality_score,
            "source_coverage": source_coverage,
            "warnings_count": len(warnings),
            "model_used": model_used,
        },
        duration_ms=duration_ms,
    )

    await _persist_state_memory(case_id, state, source_map, warnings)

    return AgentResponse(
        agent="state_builder_agent",
        status=AgentStatus.SUCCESS if not warnings else AgentStatus.WARNING,
        inputs_used=list(validated_fields.keys()),
        outputs={
            "case_id": case_id,
            "data_quality_score": state.data_quality_score,
            "safety_level": state.safety_level.value,
            "derived_fields": [d["field"] for d in derived_values],
            "prior_fields": [p["field"] for p in priors_used],
            "missing_values": missing_values,
            "source_coverage": source_coverage,
            "mapping_summary": mapping_summary,
            "model_used": model_used,
            "agent_id": _AGENT_ID,
            "agent_name": _AGENT_NAME,
            "agent_stage_result": stage_result.model_dump(mode="json"),
        },
        warnings=warnings,
        confidence=state.data_quality_score,
        trace=tracer.steps,
    ), state
