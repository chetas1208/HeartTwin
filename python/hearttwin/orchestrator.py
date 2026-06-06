"""Deterministic stage orchestrator for HeartTwin Lab.

Stage distribution per spec:
  /extract         → Stage 1 (Intake) + Stage 2 (Extraction) + Stage 3 (Validator)
  /operate         → Stage 4 (State Builder) + Stage 5a (EP) + Stage 5b (Hemodynamics) + Stage 7 (Evaluator)
  /simulate-recovery → Stage 6 (Recovery) + Stage 7 (Evaluator)

Every stage returns a strict AgentResponse. All results are stored in the case record.
"""

from __future__ import annotations

import asyncio
import time
from typing import Any

from python.hearttwin.agents.electrophysiology_agent import run_electrophysiology_agent
from python.hearttwin.agents.evaluator_agent import run_evaluator_agent
from python.hearttwin.agents.extraction_agent import run_extraction_agent
from python.hearttwin.agents.hemodynamics_agent import run_hemodynamics_agent
from python.hearttwin.agents.intake_agent import run_intake_agent
from python.hearttwin.agents.recovery_agent import run_recovery_agent
from python.hearttwin.agents.state_builder_agent import run_state_builder_agent
from python.hearttwin.agents.validator_agent import run_validator_agent
from python.hearttwin.safety import DISCLAIMER, add_disclaimer
from python.hearttwin.schemas import (
    AgentResponse,
    AgentStatus,
    CaseRecord,
    CardiacTwinState,
    RecoveryConfig,
    RecoveryScenarioType,
    SimulationConfig,
    TargetMetric,
)
from python.hearttwin.tools.scoring import evaluate_run
from python.hearttwin.tools.weave_trace import get_trace_sink, get_traces

_AGENT_STAGE_NAMES = {
    "intake_safety_agent": "extract_evidence",
    "extraction_agent": "extract_evidence",
    "validator_agent": "validate_evidence",
    "state_builder_agent": "build_cardiac_state",
    "electrophysiology_agent": "simulate_electrophysiology",
    "hemodynamics_agent": "simulate_hemodynamics",
    "recovery_agent": "simulate_recovery",
    "evaluator_agent": "evaluate_run",
}


# ---------------------------------------------------------------------------
# Stage 1-3: /extract  (Intake + Extraction + Validation)
# ---------------------------------------------------------------------------


async def run_extraction_pipeline(
    case: CaseRecord,
    files: list[dict],
    user_vitals: dict[str, Any] | None,
    patient_notes: str | None = None,
    user_request_text: str | None = None,
) -> tuple[list[AgentResponse], CaseRecord]:
    """Stages 1–3: Intake & Safety → Extraction → Validation.

    Stores validated_fields in case.  Does NOT build the cardiac state.
    """
    responses: list[AgentResponse] = []
    trace_sink = get_trace_sink()
    run_id = trace_sink.start_run(
        case.case_id,
        "extract",
        {"file_count": len(files), "has_user_vitals": bool(user_vitals)},
    )

    # Stage 1 — Intake & Safety
    intake_resp, _ = await run_intake_agent(
        files=files,
        patient_notes=patient_notes or case.patient_notes,
        user_request_text=user_request_text,
    )
    responses.append(intake_resp)
    _log_agent_response(trace_sink, run_id, intake_resp)

    if intake_resp.status == AgentStatus.FAILED:
        case.status = "blocked"
        case.stage_results = (case.stage_results or []) + responses
        trace_sink.finish_run(run_id, "failed", {"status": case.status})
        return responses, case

    # Stage 2 — Multimodal Extraction
    extraction_resp = await run_extraction_agent(
        files=files,
        user_vitals=user_vitals,
        case_id=case.case_id,
    )
    responses.append(extraction_resp)
    _log_agent_response(trace_sink, run_id, extraction_resp)

    if extraction_resp.status == AgentStatus.FAILED:
        case.status = "extraction_failed"
        case.stage_results = (case.stage_results or []) + responses
        trace_sink.finish_run(run_id, "failed", {"status": case.status})
        return responses, case

    extracted_fields: dict[str, Any] = extraction_resp.outputs.get("extracted_fields", {})

    # Stage 3 — Evidence Validation
    validator_resp = await run_validator_agent(
        extracted_fields=extracted_fields,
        case_id=case.case_id,
    )
    responses.append(validator_resp)
    _log_agent_response(trace_sink, run_id, validator_resp)

    validated_fields: dict[str, Any] = validator_resp.outputs.get("validated_fields", {})

    case.validated_fields = validated_fields
    case.status = "extracted"
    case.stage_results = (case.stage_results or []) + responses
    trace_sink.finish_run(
        run_id,
        "success" if validator_resp.status != AgentStatus.FAILED else "warning",
        {"status": case.status, "validated_field_count": len(validated_fields)},
    )

    return responses, case


# ---------------------------------------------------------------------------
# Stage 4-5-7: /operate  (State Builder + EP + Hemodynamics + Evaluator)
# ---------------------------------------------------------------------------


async def run_operation_pipeline(
    case: CaseRecord,
) -> tuple[list[AgentResponse], dict[str, Any], dict[str, Any]]:
    """Stages 4 + 5a/5b + 7: State Builder → EP + Hemodynamics (parallel) → Evaluator.

    Returns (agent_responses, visualization_payload, evaluation_report).
    """
    responses: list[AgentResponse] = []
    trace_sink = get_trace_sink()
    run_id = trace_sink.start_run(
        case.case_id,
        "operate",
        {"validated_field_count": len(case.validated_fields or {})},
    )

    validated_fields = case.validated_fields or {}

    # Stage 4 — Cardiac State Builder
    builder_resp, state = await run_state_builder_agent(
        validated_fields=validated_fields,
        case_id=case.case_id,
        simulation_config=case.state.simulation_config if case.state else None,
    )
    responses.append(builder_resp)
    _log_agent_response(trace_sink, run_id, builder_resp)
    case.state = state

    # Stage 5 (parallel) — Electrophysiology + Hemodynamics
    ep_task = asyncio.create_task(
        run_electrophysiology_agent(
            state=case.state,
            validated_fields=validated_fields,
            case_id=case.case_id,
        )
    )
    hd_task = asyncio.create_task(
        run_hemodynamics_agent(
            state=case.state,
            case_id=case.case_id,
        )
    )
    (ep_resp, updated_ep), (hd_resp, updated_hd, viz_payload) = await asyncio.gather(
        ep_task, hd_task
    )

    case.state.electrophysiology = updated_ep
    case.state.hemodynamics = updated_hd
    responses.extend([ep_resp, hd_resp])
    _log_agent_response(trace_sink, run_id, ep_resp)
    _log_agent_response(trace_sink, run_id, hd_resp)

    viz_payload["electrophysiology"] = {
        "rhythm_label": updated_ep.rhythm_label,
        "rr_interval_ms": updated_ep.rr_interval_ms.value if updated_ep.rr_interval_ms else None,
        "qrs_duration_ms": updated_ep.qrs_duration_ms.value if updated_ep.qrs_duration_ms else None,
        "qtc_ms": updated_ep.qtc_ms.value if updated_ep.qtc_ms else None,
        "arrhythmia_instability_score": (
            updated_ep.arrhythmia_instability_score.value
            if updated_ep.arrhythmia_instability_score
            else None
        ),
        "r_peak_confidence": updated_ep.r_peak_confidence,
    }

    case.simulation_result = viz_payload

    # Stage 7 — Evaluator & Critic
    all_responses_so_far = (case.stage_results or []) + responses
    eval_resp, report = await run_evaluator_agent(
        state=case.state,
        all_agent_responses=all_responses_so_far,
        visualization_payload=viz_payload,
        case_id=case.case_id,
    )
    responses.append(eval_resp)
    _log_agent_response(trace_sink, run_id, eval_resp)
    _log_eval(trace_sink, run_id, report)

    case.status = "operated"
    case.stage_results = (case.stage_results or []) + responses
    trace_sink.finish_run(
        run_id,
        "success" if report.get("passed") else "warning",
        {
            "status": case.status,
            "overall_score": report.get("eval_scores", {}).get("overall_score"),
            "stage_count": len(responses),
        },
    )

    return responses, viz_payload, report


# ---------------------------------------------------------------------------
# Stage 6-7: /simulate-recovery  (Recovery + Evaluator)
# ---------------------------------------------------------------------------


async def run_recovery_pipeline(
    case: CaseRecord,
    recovery_configs: list[RecoveryConfig] | None = None,
) -> tuple[list[AgentResponse], list[dict[str, Any]], dict[str, Any]]:
    """Stages 6 + 7: Recovery Orchestration → Evaluator.

    Returns (agent_responses, scenario_payloads, evaluation_report).
    """
    responses: list[AgentResponse] = []
    trace_sink = get_trace_sink()
    run_id = trace_sink.start_run(
        case.case_id,
        "recovery",
        {"scenario_config_count": len(recovery_configs or [])},
    )

    if not case.state:
        empty_report = {"passed": False, "warnings": ["No cardiac state — run /operate first"]}
        trace_sink.finish_run(run_id, "failed", empty_report)
        return responses, [], empty_report

    # Stage 6 — Recovery Orchestration
    recovery_resp, scenario_payloads = await run_recovery_agent(
        state=case.state,
        recovery_configs=recovery_configs,
        case_id=case.case_id,
    )
    responses.append(recovery_resp)
    _log_agent_response(trace_sink, run_id, recovery_resp)
    case.recovery_scenarios = scenario_payloads

    # Stage 7 — Evaluator & Critic (recovery context)
    all_responses_so_far = (case.stage_results or []) + responses
    eval_resp, report = await run_evaluator_agent(
        state=case.state,
        all_agent_responses=all_responses_so_far,
        visualization_payload={"recovery_scenarios": scenario_payloads},
        case_id=case.case_id,
    )
    responses.append(eval_resp)
    _log_agent_response(trace_sink, run_id, eval_resp)
    _log_eval(trace_sink, run_id, report)

    case.status = "recovery_simulated"
    case.stage_results = (case.stage_results or []) + responses
    trace_sink.finish_run(
        run_id,
        "success" if report.get("passed") else "warning",
        {
            "status": case.status,
            "scenario_count": len(scenario_payloads),
            "overall_score": report.get("eval_scores", {}).get("overall_score"),
        },
    )

    return responses, scenario_payloads, report


async def run_self_improvement_pipeline(case: CaseRecord) -> dict[str, Any]:
    """Run one bounded harness improvement rerun without changing evidence values."""
    trace_sink = get_trace_sink()
    run_id = trace_sink.start_run(
        case.case_id,
        "self_improve",
        {"has_state": bool(case.state), "has_recovery": bool(case.recovery_scenarios)},
    )

    if not case.state:
        trace_sink.finish_run(run_id, "failed", {"reason": "No cardiac state"})
        return _self_improve_failed(case.case_id, "No cardiac state — call /operate first", trace_sink, run_id)

    if not case.recovery_scenarios:
        trace_sink.finish_run(run_id, "failed", {"reason": "No recovery scenarios"})
        return _self_improve_failed(
            case.case_id,
            "No simulated recovery trajectory exists — call /simulate-recovery first",
            trace_sink,
            run_id,
        )

    before_scores = evaluate_run(
        case.state.model_dump(),
        [r.model_dump() for r in (case.stage_results or [])],
        {"recovery_scenarios": case.recovery_scenarios or []},
    )
    before_warnings = _collect_case_warnings(case)
    before_summary = _recovery_summary(case.recovery_scenarios or [])

    trace_sink.log_agent_stage(
        run_id,
        {
            "stage": "self_improve_run",
            "agent": "evaluator_agent",
            "status": "running",
            "inputs_used": ["latest_cardiac_state", "latest_recovery_result", "eval_scores"],
            "confidence": before_scores["overall_score"],
            "warnings": before_scores["warnings"],
        },
    )
    trace_sink.log_tool_call(
        run_id,
        "score_plausibility",
        inputs={"scenario_count": len(case.recovery_scenarios or [])},
        outputs={"physiological_plausibility": before_scores["physiological_plausibility"]},
    )
    trace_sink.log_tool_call(
        run_id,
        "score_safety",
        inputs={"stage_result_count": len(case.stage_results or [])},
        outputs={"safety_compliance": before_scores["safety_compliance"]},
    )

    findings, plan, improved_config = _build_improvement_plan(case, before_scores)

    original_measurements = case.state.measurements.model_dump()
    previous_config = case.state.simulation_config.recovery
    case.state.simulation_config.recovery = improved_config

    improved_scenarios = _scenario_configs_from(improved_config)
    _, after_scenarios, after_report = await run_recovery_pipeline(
        case=case,
        recovery_configs=improved_scenarios,
    )

    if case.state.measurements.model_dump() != original_measurements:
        case.state.measurements = type(case.state.measurements).model_validate(original_measurements)
        case.state.warnings.append("Self-improvement attempted to alter measurements and was reverted")

    preserved = _dedupe([*before_warnings, *_collect_case_warnings(case)])
    after_scores = after_report.get("eval_scores") or evaluate_run(
        case.state.model_dump(),
        [r.model_dump() for r in (case.stage_results or [])],
        {"recovery_scenarios": after_scenarios},
    )
    case.state.simulation_config.recovery = improved_config or previous_config
    case.recovery_scenarios = after_scenarios
    case.status = "self_improved"

    score_delta = {
        "overall_score": round(after_scores["overall_score"] - before_scores["overall_score"], 3),
        "physiological_plausibility": round(
            after_scores["physiological_plausibility"] - before_scores["physiological_plausibility"],
            3,
        ),
        "safety_compliance": round(after_scores["safety_compliance"] - before_scores["safety_compliance"], 3),
        "hallucination_risk": round(after_scores["hallucination_risk"] - before_scores["hallucination_risk"], 3),
    }

    status = "success"
    if after_scores["overall_score"] < before_scores["overall_score"] or after_scores["safety_compliance"] < before_scores["safety_compliance"]:
        status = "warning"

    trace_sink.log_eval_scores(run_id, after_scores, after_scores.get("warnings", []))
    trace_sink.finish_run(
        run_id,
        status,
        {
            "before_overall": before_scores["overall_score"],
            "after_overall": after_scores["overall_score"],
            "score_delta": score_delta,
            "plan_count": len(plan),
        },
    )

    return add_disclaimer(
        {
            "case_id": case.case_id,
            "status": status,
            "before": {
                "eval_scores": before_scores,
                "recovery_summary": before_summary,
                "warnings": before_warnings,
            },
            "critic_findings": findings,
            "improvement_plan": plan,
            "after": {
                "eval_scores": after_scores,
                "recovery_summary": _recovery_summary(after_scenarios),
                "warnings": preserved,
            },
            "score_delta": score_delta,
            "trace": get_traces(case.case_id),
            "weave": trace_sink.weave_info(run_id),
        }
    )


# ---------------------------------------------------------------------------
# Standalone evaluator (used by /operate and /simulate-recovery when needed)
# ---------------------------------------------------------------------------


async def run_evaluation(
    case: CaseRecord,
    viz_payload: dict[str, Any] | None = None,
) -> tuple[AgentResponse, dict[str, Any]]:
    """Run stage 7 in isolation (backward-compatible helper)."""
    if not case.state:
        empty_report = {"passed": False, "warnings": ["No state available"]}
        return AgentResponse(
            agent="evaluator_agent",
            status=AgentStatus.FAILED,
            outputs=empty_report,
            warnings=["No cardiac state available"],
            confidence=0.0,
        ), empty_report

    return await run_evaluator_agent(
        state=case.state,
        all_agent_responses=case.stage_results or [],
        visualization_payload=viz_payload,
        case_id=case.case_id,
    )


# ---------------------------------------------------------------------------
# Full pipeline (one-shot, for testing / direct invocations)
# ---------------------------------------------------------------------------


async def run_full_pipeline(
    files: list[dict],
    patient_notes: str | None = None,
    user_vitals: dict[str, Any] | None = None,
    user_request_text: str | None = None,
    simulation_config: SimulationConfig | None = None,
    recovery_configs: list[RecoveryConfig] | None = None,
) -> dict[str, Any]:
    """Run the full 7-stage pipeline end-to-end.

    Convenience wrapper — not used by the HTTP API which calls stages individually.
    """
    t_start = time.time()

    intake_resp, case = await run_intake_agent(
        files=files,
        patient_notes=patient_notes,
        user_request_text=user_request_text,
    )
    case.stage_results = [intake_resp]

    if intake_resp.status == AgentStatus.FAILED:
        return add_disclaimer({
            "status": "blocked",
            "error": intake_resp.outputs.get("reason"),
            "case_id": case.case_id,
            "agent_responses": [intake_resp.model_dump()],
        })

    if simulation_config:
        if case.state is None:
            case.state = CardiacTwinState(
                case_id=case.case_id, simulation_config=simulation_config
            )
        else:
            case.state.simulation_config = simulation_config

    _, case = await run_extraction_pipeline(
        case=case,
        files=files,
        user_vitals=user_vitals,
    )

    op_responses, viz_payload, eval_report = await run_operation_pipeline(case=case)

    _, scenarios, _ = await run_recovery_pipeline(
        case=case, recovery_configs=recovery_configs
    )

    total_ms = round((time.time() - t_start) * 1000, 1)

    return add_disclaimer({
        "status": "success" if eval_report.get("passed") else "warning",
        "case_id": case.case_id,
        "data_quality_score": case.state.data_quality_score if case.state else 0.0,
        "state": case.state.model_dump() if case.state else None,
        "visualization": viz_payload,
        "recovery_scenarios": scenarios,
        "evaluation_report": eval_report,
        "agent_responses": [r.model_dump() for r in (case.stage_results or [])],
        "traces": get_traces(case.case_id),
        "pipeline_duration_ms": total_ms,
    })


def _log_agent_response(trace_sink: Any, run_id: str | None, response: AgentResponse) -> None:
    stage_name = _AGENT_STAGE_NAMES.get(response.agent, response.agent)
    trace_sink.log_agent_stage(
        run_id,
        {
            "stage": stage_name,
            "agent": response.agent,
            "status": response.status.value,
            "inputs_used": response.inputs_used,
            "tools_called": [step.tool for step in response.trace],
            "confidence": response.confidence,
            "warnings": response.warnings,
            "trace_link": trace_sink.weave_info(run_id).get("run_url"),
        },
    )
    for step in response.trace:
        trace_sink.log_tool_call(
            run_id,
            step.tool,
            step.inputs,
            step.outputs,
            {"duration_ms": step.duration_ms},
        )


def _log_eval(trace_sink: Any, run_id: str | None, report: dict[str, Any]) -> None:
    eval_scores = report.get("eval_scores") or report.get("scores") or {}
    trace_sink.log_eval_scores(run_id, eval_scores, report.get("warnings", []))


def _collect_case_warnings(case: CaseRecord) -> list[str]:
    warnings: list[str] = []
    if case.state:
        warnings.extend(case.state.warnings)
    for response in case.stage_results or []:
        warnings.extend(response.warnings)
    for scenario in case.recovery_scenarios or []:
        warnings.extend(scenario.get("warnings") or [])
    return _dedupe(warnings)


def _recovery_summary(scenarios: list[dict[str, Any]]) -> dict[str, Any]:
    if not scenarios:
        return {"scenario_count": 0, "horizon_days": None, "labels": []}
    return {
        "scenario_count": len(scenarios),
        "horizon_days": max(
            (
                sc.get("summary_metrics", {}).get("horizon_days", 0)
                for sc in scenarios
            ),
            default=0,
        ),
        "labels": [sc.get("scenario_label") for sc in scenarios],
        "warnings_count": sum(len(sc.get("warnings") or []) for sc in scenarios),
    }


def _build_improvement_plan(
    case: CaseRecord,
    before_scores: dict[str, Any],
) -> tuple[list[dict[str, str]], list[dict[str, Any]], RecoveryConfig]:
    assert case.state is not None
    cfg = case.state.simulation_config.recovery.model_copy(deep=True)
    findings: list[dict[str, str]] = []
    plan: list[dict[str, Any]] = []
    prior_fields = [
        entry.field
        for entry in case.state.source_map
        if entry.source.value == "default_model_prior"
    ]

    if before_scores["recovery_scenario_stability"] < 0.85:
        old_shift = cfg.max_safe_parameter_shift
        cfg.max_safe_parameter_shift = max(0.05, min(old_shift, old_shift * 0.5))
        cfg.target_metric = TargetMetric.BALANCED
        findings.append(
            {
                "issue": "Recovery scenario stability was below target",
                "severity": "medium",
                "evidence": f"recovery_scenario_stability={before_scores['recovery_scenario_stability']:.2f}",
                "fix": "Reduced max_safe_parameter_shift and used a balanced target metric",
            }
        )
        plan.append(
            {
                "change": f"max_safe_parameter_shift {old_shift:.2f} -> {cfg.max_safe_parameter_shift:.2f}",
                "reason": "Keep simulated recovery trajectory changes bounded",
                "bounded": True,
            }
        )
        plan.append(
            {
                "change": "target_metric -> balanced",
                "reason": "Avoid optimizing a single metric when trajectory stability is uncertain",
                "bounded": True,
            }
        )

    if before_scores["extraction_completeness"] < 0.65 or len(prior_fields) > 6:
        old_weight = cfg.uncertainty_penalty_weight
        cfg.uncertainty_penalty_weight = min(0.6, max(old_weight, old_weight + 0.15))
        findings.append(
            {
                "issue": "Case relies on incomplete evidence or model priors",
                "severity": "medium",
                "evidence": f"{len(prior_fields)} fields use default_model_prior",
                "fix": "Increased uncertainty penalty and preserved low-confidence warnings",
            }
        )
        plan.append(
            {
                "change": f"uncertainty_penalty_weight {old_weight:.2f} -> {cfg.uncertainty_penalty_weight:.2f}",
                "reason": "Make uncertainty bands more conservative when source coverage is limited",
                "bounded": True,
            }
        )
        missing_volumes = [
            f
            for f in ("edv_ml", "esv_ml")
            if f in prior_fields
        ]
        if missing_volumes:
            warning = (
                "Missing EDV/ESV should be requested as evidence for future runs; "
                "self-improvement did not invent replacement values"
            )
            case.state.warnings.append(warning)
            plan.append(
                {
                    "change": "request missing EDV/ESV evidence instead of changing cardiac values",
                    "reason": ", ".join(missing_volumes) + " came from model priors",
                    "bounded": True,
                }
            )

    if _uncertainty_expands(case.recovery_scenarios or []) and cfg.recovery_horizon_days > 14:
        old_horizon = cfg.recovery_horizon_days
        cfg.recovery_horizon_days = max(7, min(14, old_horizon))
        findings.append(
            {
                "issue": "Recovery uncertainty expands over the horizon",
                "severity": "low",
                "evidence": "Uncertainty bands widen across the simulated recovery trajectory",
                "fix": "Shortened the recovery horizon for the rerun",
            }
        )
        plan.append(
            {
                "change": f"recovery_horizon_days {old_horizon} -> {cfg.recovery_horizon_days}",
                "reason": "Keep bounded model scenario uncertainty inspectable",
                "bounded": True,
            }
        )

    if not findings:
        findings.append(
            {
                "issue": "No fixable harness issue above threshold",
                "severity": "low",
                "evidence": "Eval scores were already within configured bounds",
                "fix": "Reran recovery with the same bounded configuration",
            }
        )
        plan.append(
            {
                "change": "rerun simulated recovery trajectory without changing evidence",
                "reason": "Provide before/after harness comparison while preserving warnings",
                "bounded": True,
            }
        )

    return findings, plan, cfg


def _scenario_configs_from(base: RecoveryConfig) -> list[RecoveryConfig]:
    scenario_types = [
        RecoveryScenarioType.LOAD_REDUCTION,
        RecoveryScenarioType.OXYGEN_DELIVERY_IMPROVEMENT,
        RecoveryScenarioType.CONTRACTILITY_SUPPORT,
        RecoveryScenarioType.CONDITIONING,
    ]
    return [
        base.model_copy(update={"scenario_type": scenario_type}, deep=True)
        for scenario_type in scenario_types
    ]


def _uncertainty_expands(scenarios: list[dict[str, Any]]) -> bool:
    for scenario in scenarios:
        trajectory = scenario.get("trajectory") or []
        if len(trajectory) < 2:
            continue
        first = trajectory[0]
        last = trajectory[-1]
        first_width = (first.get("uncertainty_high") or 0) - (first.get("uncertainty_low") or 0)
        last_width = (last.get("uncertainty_high") or 0) - (last.get("uncertainty_low") or 0)
        if last_width > first_width * 1.8:
            return True
    return False


def _self_improve_failed(
    case_id: str,
    reason: str,
    trace_sink: Any,
    run_id: str | None,
) -> dict[str, Any]:
    return add_disclaimer(
        {
            "case_id": case_id,
            "status": "failed",
            "before": {"eval_scores": {}, "recovery_summary": {}, "warnings": [reason]},
            "critic_findings": [
                {
                    "issue": reason,
                    "severity": "high",
                    "evidence": "Required run artifact missing",
                    "fix": "Run the prerequisite simulation stage",
                }
            ],
            "improvement_plan": [],
            "after": {"eval_scores": {}, "recovery_summary": {}, "warnings": [reason]},
            "score_delta": {
                "overall_score": 0.0,
                "physiological_plausibility": 0.0,
                "safety_compliance": 0.0,
                "hallucination_risk": 0.0,
            },
            "trace": get_traces(case_id),
            "weave": trace_sink.weave_info(run_id),
        }
    )


def _dedupe(values: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for value in values:
        if value not in seen:
            out.append(value)
            seen.add(value)
    return out
