"""Agent 8: Evaluator & Critic Agent.

Scores the run and catches hallucinations.
Checks every numeric claim against canonical state or simulation result.
Forces revision if unsafe or unsupported.
"""

from __future__ import annotations

import time
from typing import Any

from python.hearttwin.schemas import AgentResponse, AgentStatus, CardiacTwinState, SafetyLevel
from python.hearttwin.tools.scoring import evaluate_run
from python.hearttwin.tools.weave_trace import TraceContext


async def run_evaluator_agent(
    state: CardiacTwinState,
    all_agent_responses: list[AgentResponse],
    visualization_payload: dict[str, Any] | None,
    case_id: str,
) -> tuple[AgentResponse, dict[str, Any]]:
    """Evaluate the full run and produce a quality report."""
    tracer = TraceContext(case_id=case_id, agent_name="evaluator_agent")
    t0 = time.time()
    warnings: list[str] = []
    force_revision_issues: list[str] = []

    state_dict = state.model_dump()
    agent_output_list = [r.model_dump() for r in all_agent_responses]

    eval_result = evaluate_run(state_dict, agent_output_list, visualization_payload)

    tracer.record_tool(
        "evaluate_run",
        inputs={"agent_count": len(all_agent_responses)},
        outputs=eval_result,
        duration_ms=(time.time() - t0) * 1000,
    )

    if not eval_result["passed"]:
        if eval_result["safety_compliance"] < 0.70:
            force_revision_issues.append("SAFETY: Output contains blocked language")
        if eval_result["hallucination_risk"] > 0.5:
            force_revision_issues.append("HALLUCINATION: Suspected invented values in output")
        if eval_result["physiological_plausibility"] < 0.3:
            force_revision_issues.append("PHYSIOLOGY: State appears physiologically implausible")

    numeric_checks = _verify_numeric_claims(state, all_agent_responses)
    if numeric_checks["mismatches"]:
        for mismatch in numeric_checks["mismatches"]:
            warnings.append(f"Numeric claim mismatch: {mismatch}")
            if len(numeric_checks["mismatches"]) >= 3:
                force_revision_issues.append("NUMERIC: Multiple numeric claim mismatches detected")

    tracer.record_tool(
        "verify_numeric_claims",
        inputs={"check_count": numeric_checks["checks_performed"]},
        outputs={"mismatches": len(numeric_checks["mismatches"])},
        duration_ms=1.0,
    )

    prior_fields = [e.field for e in state.source_map if e.source.value == "default_model_prior"]
    if len(prior_fields) > 8:
        warnings.append(
            f"High prior usage: {len(prior_fields)} fields from population priors — "
            f"upload more patient data for a better-calibrated simulation"
        )

    overall_status = AgentStatus.SUCCESS
    if force_revision_issues:
        overall_status = AgentStatus.FAILED
        warnings.extend(force_revision_issues)
    elif eval_result.get("warnings"):
        overall_status = AgentStatus.WARNING
        warnings.extend(eval_result["warnings"])

    report = {
        "scores": {
            "data_completeness": eval_result["extraction_completeness"],
            "extraction_completeness": eval_result["extraction_completeness"],
            "physiological_plausibility": eval_result["physiological_plausibility"],
            "hallucination_risk": eval_result["hallucination_risk"],
            "safety_compliance": eval_result["safety_compliance"],
            "visualization_readiness": eval_result["visualization_readiness"],
            "recovery_scenario_stability": eval_result["recovery_scenario_stability"],
            "overall": eval_result["overall_score"],
            "overall_score": eval_result["overall_score"],
        },
        "eval_scores": {
            "extraction_completeness": eval_result["extraction_completeness"],
            "physiological_plausibility": eval_result["physiological_plausibility"],
            "safety_compliance": eval_result["safety_compliance"],
            "hallucination_risk": eval_result["hallucination_risk"],
            "visualization_readiness": eval_result["visualization_readiness"],
            "recovery_scenario_stability": eval_result["recovery_scenario_stability"],
            "overall_score": eval_result["overall_score"],
            "warnings": eval_result["warnings"],
            "failed_checks": eval_result["failed_checks"],
        },
        "passed": eval_result["passed"] and not force_revision_issues,
        "force_revision_issues": force_revision_issues,
        "failed_checks": eval_result["failed_checks"],
        "prior_field_count": len(prior_fields),
        "prior_fields": prior_fields,
        "numeric_checks": numeric_checks,
        "warnings": warnings,
        "agent_statuses": {
            r.agent: r.status.value for r in all_agent_responses
        },
        "simulation_note": (
            "All outputs are simulated educational estimates. "
            "No clinical interpretation should be made from these results."
        ),
    }

    return AgentResponse(
        agent="evaluator_agent",
        status=overall_status,
        inputs_used=["cardiac_twin_state", "all_agent_responses"],
        outputs=report,
        warnings=warnings,
        confidence=eval_result["overall_score"],
        trace=tracer.steps,
    ), report


def _verify_numeric_claims(
    state: CardiacTwinState, agent_responses: list[AgentResponse]
) -> dict[str, Any]:
    """Cross-check numeric outputs against canonical state values."""
    mismatches: list[str] = []
    checks = 0

    state_ef = state.measurements.ejection_fraction_pct.value if state.measurements.ejection_fraction_pct else None
    state_co = state.measurements.cardiac_output_l_min.value if state.measurements.cardiac_output_l_min else None

    for resp in agent_responses:
        outputs = resp.outputs or {}
        checks += 1

        out_ef = outputs.get("ef_pct")
        if out_ef is not None and state_ef is not None:
            if abs(float(out_ef) - state_ef) > 5.0:
                mismatches.append(
                    f"Agent '{resp.agent}' EF {out_ef:.1f}% differs from state EF {state_ef:.1f}%"
                )

        out_co = outputs.get("cardiac_output_l_min")
        if out_co is not None and state_co is not None:
            if abs(float(out_co) - state_co) > 1.0:
                mismatches.append(
                    f"Agent '{resp.agent}' CO {out_co:.2f} differs from state CO {state_co:.2f}"
                )

    return {
        "checks_performed": checks,
        "mismatches": mismatches,
        "all_consistent": len(mismatches) == 0,
    }
