"""Agent 4: Cardiac State Builder Agent.

Builds CardiacTwinState from validated evidence.
Uses defaults only from priors.json.
Computes derived values only through deterministic Python tools.
"""

from __future__ import annotations

import json
import pathlib
import time
from typing import Any

from python.hearttwin.schemas import (
    AgentResponse,
    AgentStatus,
    CardiacTwinState,
    Electrophysiology,
    Hemodynamics,
    MeasuredValue,
    Measurements,
    PatientContext,
    SafetyLevel,
    SimulationConfig,
    SourceMapEntry,
    TissueState,
    ValueSource,
)
from python.hearttwin.tools.cardiac_state import (
    compute_afterload_index,
    compute_arterial_compliance_index,
    compute_bsa_mosteller,
    compute_cardiac_output,
    compute_contractility_index,
    compute_ejection_fraction,
    compute_filling_pressure_index,
    compute_map,
    compute_preload_index,
    compute_qtc_bazett,
    compute_rr_from_hr,
    compute_stroke_volume,
    compute_svr_index,
)
from python.hearttwin.tools.scoring import compute_data_quality_score
from python.hearttwin.tools.weave_trace import TraceContext

_PRIORS_PATH = pathlib.Path(__file__).parent.parent / "data" / "priors.json"
_PRIORS: dict = json.loads(_PRIORS_PATH.read_text())


def _make_measured(
    value: float,
    unit: str,
    source: ValueSource,
    confidence: float,
    **kwargs: Any,
) -> MeasuredValue:
    return MeasuredValue(
        value=value,
        unit=unit,
        source=source,
        confidence=confidence,
        **kwargs,
    )


def _get_validated_value(validated: dict, field: str) -> tuple[float | str | None, dict | None]:
    """Return (value, full_entry) or (None, None) if not present."""
    entry = validated.get(field)
    if entry is None:
        return None, None
    v = entry.get("value")
    return v, entry


def _to_source(source_str: str) -> ValueSource:
    mapping = {
        "file_extraction": ValueSource.FILE_EXTRACTION,
        "extracted": ValueSource.FILE_EXTRACTION,
        "user_input": ValueSource.USER_INPUT,
        "default_model_prior": ValueSource.DEFAULT_MODEL_PRIOR,
        "derived": ValueSource.DERIVED,
        "computed": ValueSource.DERIVED,
    }
    return mapping.get(source_str, ValueSource.FILE_EXTRACTION)


def _build_measured_from_validated(field: str, entry: dict) -> MeasuredValue:
    return MeasuredValue(
        value=float(entry["value"]),
        unit=entry.get("unit", ""),
        source=_to_source(entry.get("source", "file_extraction")),
        confidence=entry.get("confidence", 0.7),
        source_file_id=entry.get("source_file_id"),
        method=entry.get("method") or entry.get("extraction_method"),
        evidence=entry.get("evidence") or entry.get("raw_evidence"),
    )


async def run_state_builder_agent(
    validated_fields: dict[str, Any],
    case_id: str,
    simulation_config: SimulationConfig | None = None,
) -> tuple[AgentResponse, CardiacTwinState]:
    """Build the canonical CardiacTwinState from validated evidence."""
    tracer = TraceContext(case_id=case_id, agent_name="state_builder_agent")
    t0 = time.time()
    warnings: list[str] = []
    source_map: list[SourceMapEntry] = []

    def get_val(field: str) -> tuple[float | None, dict | None]:
        v, entry = _get_validated_value(validated_fields, field)
        if v is not None and isinstance(v, (int, float)):
            return float(v), entry
        return None, None

    def get_prior(section: str, field: str) -> MeasuredValue:
        p = _PRIORS.get(section, {}).get(field, {})
        return _make_measured(
            p.get("value", 0.0),
            p.get("unit", ""),
            ValueSource.DEFAULT_MODEL_PRIOR,
            p.get("confidence", 0.3),
        )

    meas = Measurements()
    ep = Electrophysiology()
    ts = TissueState()
    pc = PatientContext()

    scalar_fields = {
        "heart_rate_bpm": ("adult_typical", "heart_rate_bpm"),
        "systolic_bp_mmhg": ("adult_typical", "systolic_bp_mmhg"),
        "diastolic_bp_mmhg": ("adult_typical", "diastolic_bp_mmhg"),
        "edv_ml": ("adult_typical", "edv_ml"),
        "esv_ml": ("adult_typical", "esv_ml"),
        "ejection_fraction_pct": ("adult_typical", "ejection_fraction_pct"),
        "stroke_volume_ml": ("adult_typical", "stroke_volume_ml"),
        "cardiac_output_l_min": ("adult_typical", "cardiac_output_l_min"),
        "troponin_ng_l": (None, None),
        "bnp_pg_ml": (None, None),
        "oxygen_saturation_pct": ("adult_typical", "oxygen_saturation_pct"),
    }

    meas_values: dict[str, MeasuredValue | None] = {}
    for field, prior_key in scalar_fields.items():
        v, entry = get_val(field)
        if v is not None and entry is not None:
            mv = _build_measured_from_validated(field, entry)
            meas_values[field] = mv
            source_map.append(SourceMapEntry(
                field=field,
                value=float(entry["value"]),
                unit=entry.get("unit", ""),
                source=_to_source(entry.get("source", "file_extraction")),
                source_file_id=entry.get("source_file_id"),
                confidence=entry.get("confidence", 0.7),
                method=entry.get("method") or entry.get("extraction_method"),
                evidence=entry.get("evidence") or entry.get("raw_evidence"),
            ))
        elif prior_key[0] is not None:
            mv = get_prior(*prior_key)
            warnings.append(f"{field}: using population prior (source: default_model_prior)")
            meas_values[field] = mv
            source_map.append(SourceMapEntry(
                field=field,
                value=mv.value,
                unit=mv.unit,
                source=ValueSource.DEFAULT_MODEL_PRIOR,
                confidence=0.3,
                method="prior",
            ))
        else:
            meas_values[field] = None

    meas = Measurements(
        heart_rate_bpm=meas_values.get("heart_rate_bpm"),
        systolic_bp_mmhg=meas_values.get("systolic_bp_mmhg"),
        diastolic_bp_mmhg=meas_values.get("diastolic_bp_mmhg"),
        edv_ml=meas_values.get("edv_ml"),
        esv_ml=meas_values.get("esv_ml"),
        ejection_fraction_pct=meas_values.get("ejection_fraction_pct"),
        stroke_volume_ml=meas_values.get("stroke_volume_ml"),
        cardiac_output_l_min=meas_values.get("cardiac_output_l_min"),
        troponin_ng_l=meas_values.get("troponin_ng_l"),
        bnp_pg_ml=meas_values.get("bnp_pg_ml"),
        oxygen_saturation_pct=meas_values.get("oxygen_saturation_pct"),
    )

    edv = meas_values.get("edv_ml") and meas_values["edv_ml"].value
    esv = meas_values.get("esv_ml") and meas_values["esv_ml"].value
    hr = meas_values.get("heart_rate_bpm") and meas_values["heart_rate_bpm"].value
    sbp = meas_values.get("systolic_bp_mmhg") and meas_values["systolic_bp_mmhg"].value
    dbp = meas_values.get("diastolic_bp_mmhg") and meas_values["diastolic_bp_mmhg"].value

    if edv and esv and esv < edv:
        formula_t0 = time.time()
        sv_computed = compute_stroke_volume(edv, esv)
        tracer.record_tool(
            "compute_stroke_volume",
            inputs={"edv_ml": edv, "esv_ml": esv},
            outputs={"stroke_volume_ml": sv_computed},
            duration_ms=(time.time() - formula_t0) * 1000,
        )
        formula_t0 = time.time()
        ef_computed = compute_ejection_fraction(edv, esv)
        tracer.record_tool(
            "compute_ejection_fraction",
            inputs={"edv_ml": edv, "esv_ml": esv},
            outputs={"ejection_fraction_pct": ef_computed},
            duration_ms=(time.time() - formula_t0) * 1000,
        )

        if meas.stroke_volume_ml is None or meas.stroke_volume_ml.source == ValueSource.DEFAULT_MODEL_PRIOR:
            meas.stroke_volume_ml = _make_measured(sv_computed, "mL", ValueSource.DERIVED, 0.95)
            source_map.append(SourceMapEntry(field="stroke_volume_ml", value=sv_computed, unit="mL", source=ValueSource.DERIVED, confidence=0.95, method="deterministic_formula", evidence="SV = EDV - ESV"))

        if meas.ejection_fraction_pct is None or meas.ejection_fraction_pct.source == ValueSource.DEFAULT_MODEL_PRIOR:
            meas.ejection_fraction_pct = _make_measured(ef_computed, "%", ValueSource.DERIVED, 0.95)
            source_map.append(SourceMapEntry(field="ejection_fraction_pct", value=ef_computed, unit="%", source=ValueSource.DERIVED, confidence=0.95, method="deterministic_formula", evidence="EF = (SV / EDV) * 100"))

    if hr and meas.stroke_volume_ml and (meas.cardiac_output_l_min is None or meas.cardiac_output_l_min.source == ValueSource.DEFAULT_MODEL_PRIOR):
        formula_t0 = time.time()
        co_computed = compute_cardiac_output(hr, meas.stroke_volume_ml.value)
        tracer.record_tool(
            "compute_cardiac_output",
            inputs={"heart_rate_bpm": hr, "stroke_volume_ml": meas.stroke_volume_ml.value},
            outputs={"cardiac_output_l_min": co_computed},
            duration_ms=(time.time() - formula_t0) * 1000,
        )
        meas.cardiac_output_l_min = _make_measured(co_computed, "L/min", ValueSource.DERIVED, 0.90)
        source_map.append(SourceMapEntry(field="cardiac_output_l_min", value=co_computed, unit="L/min", source=ValueSource.DERIVED, confidence=0.90, method="deterministic_formula", evidence="CO = (HR × SV) / 1000"))

    ep_field_map = {
        "qrs_duration_ms": ("adult_typical", "qrs_duration_ms"),
        "qt_interval_ms": ("adult_typical", "qt_interval_ms"),
        "qtc_ms": ("adult_typical", "qtc_ms"),
        "rr_interval_ms": ("adult_typical", "rr_interval_ms"),
    }
    ep_values: dict[str, MeasuredValue | None] = {}
    for field, prior_key in ep_field_map.items():
        v, entry = get_val(field)
        if v is not None and entry is not None:
            ep_values[field] = _build_measured_from_validated(field, entry)
        else:
            ep_values[field] = None

    if ep_values.get("rr_interval_ms") is None and hr:
        rr_c = compute_rr_from_hr(hr)
        ep_values["rr_interval_ms"] = _make_measured(rr_c, "ms", ValueSource.DERIVED, 0.90)

    if ep_values.get("qtc_ms") is None:
        qt_v = ep_values.get("qt_interval_ms")
        rr_v = ep_values.get("rr_interval_ms")
        if qt_v and rr_v:
            qtc_c = compute_qtc_bazett(qt_v.value, rr_v.value)
            ep_values["qtc_ms"] = _make_measured(qtc_c, "ms", ValueSource.DERIVED, 0.85)

    rhythm_v, rhythm_entry = _get_validated_value(validated_fields, "rhythm_label")
    ep = Electrophysiology(
        rhythm_label=str(rhythm_v) if rhythm_v else None,
        rr_interval_ms=ep_values.get("rr_interval_ms"),
        qrs_duration_ms=ep_values.get("qrs_duration_ms"),
        qt_interval_ms=ep_values.get("qt_interval_ms"),
        qtc_ms=ep_values.get("qtc_ms"),
        r_peak_confidence=None,
        conduction_delay_score=None,
        arrhythmia_instability_score=None,
    )

    prior_tissue = _PRIORS.get("tissue_defaults", {})
    ts = TissueState(
        scar_fraction=_make_measured(prior_tissue.get("scar_fraction", {}).get("value", 0.0), "fraction", ValueSource.DEFAULT_MODEL_PRIOR, 0.3),
        inflammation_index=_make_measured(prior_tissue.get("inflammation_index", {}).get("value", 0.1), "index", ValueSource.DEFAULT_MODEL_PRIOR, 0.3),
        oxygen_delivery_index=_make_measured(prior_tissue.get("oxygen_delivery_index", {}).get("value", 0.85), "index", ValueSource.DEFAULT_MODEL_PRIOR, 0.3),
        myocardial_oxygen_demand_index=_make_measured(prior_tissue.get("myocardial_oxygen_demand_index", {}).get("value", 0.6), "index", ValueSource.DEFAULT_MODEL_PRIOR, 0.3),
        stiffness_index=_make_measured(prior_tissue.get("stiffness_index", {}).get("value", 0.3), "index", ValueSource.DEFAULT_MODEL_PRIOR, 0.3),
        remodeling_index=_make_measured(prior_tissue.get("remodeling_index", {}).get("value", 0.1), "index", ValueSource.DEFAULT_MODEL_PRIOR, 0.3),
    )

    age_v, age_entry = get_val("age_years")
    ht_v, ht_entry = get_val("height_cm")
    wt_v, wt_entry = get_val("weight_kg")

    bsa = None
    if ht_v and wt_v:
        bsa = compute_bsa_mosteller(ht_v, wt_v)

    pc = PatientContext(
        age_years=_build_measured_from_validated("age_years", age_entry) if age_entry else None,
        sex=validated_fields.get("sex", {}).get("value") if isinstance(validated_fields.get("sex"), dict) else validated_fields.get("sex"),
        height_cm=_build_measured_from_validated("height_cm", ht_entry) if ht_entry else None,
        weight_kg=_build_measured_from_validated("weight_kg", wt_entry) if wt_entry else None,
        bsa_m2=_make_measured(bsa, "m²", ValueSource.DERIVED, 0.9) if bsa else None,
    )

    state = CardiacTwinState(
        case_id=case_id,
        patient_context=pc,
        measurements=meas,
        electrophysiology=ep,
        hemodynamics=Hemodynamics(),
        tissue_state=ts,
        simulation_config=simulation_config or SimulationConfig(),
        source_map=source_map,
        warnings=warnings,
        safety_level=SafetyLevel.CLEAR,
    )

    state_dict = state.model_dump()
    state.data_quality_score = compute_data_quality_score(state_dict)

    tracer.record_tool(
        "build_cardiac_state",
        inputs={"validated_field_count": len(validated_fields)},
        outputs={
            "data_quality_score": state.data_quality_score,
            "source_map_entries": len(source_map),
        },
        duration_ms=(time.time() - t0) * 1000,
    )

    return AgentResponse(
        agent="state_builder_agent",
        status=AgentStatus.SUCCESS,
        inputs_used=list(validated_fields.keys()),
        outputs={
            "case_id": case_id,
            "data_quality_score": state.data_quality_score,
            "derived_fields": [e.field for e in source_map if e.source == ValueSource.DERIVED],
            "prior_fields": [e.field for e in source_map if e.source == ValueSource.DEFAULT_MODEL_PRIOR],
        },
        warnings=warnings,
        confidence=state.data_quality_score,
        trace=tracer.steps,
    ), state
