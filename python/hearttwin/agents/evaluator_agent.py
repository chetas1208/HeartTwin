"""Agent 8: Evaluator & Critic Agent (production-grade).

Anti-BS layer. Scores every pipeline run on 7 dimensions, detects
hallucinations, unsafe language, and impossible physiology. Generates
harness-focused CriticFinding objects and proposes bounded self-improvement
plans.

Model routing
─────────────
  OPENAI_MODEL_EVALUATOR env → default gpt-5.5 (strongest reasoning model)
  Used only for critic-explanation text and revision-plan narrative.
  All seven dimension *scores* are deterministic Python — no LLM in the loop.

Safety guarantees
─────────────────
  Never diagnoses. Never recommends treatment. Every fix/recommendation
  targets harness configuration (parameter shifts, uncertainty weights,
  horizon length) rather than clinical decisions.
"""

from __future__ import annotations

import json
import os
import re
import time
from datetime import datetime, timezone
from typing import Any, Literal

from pydantic import BaseModel, Field

from python.hearttwin.safety import CORE_SAFETY_PHRASE, strip_allowed_safety_phrases
from python.hearttwin.schemas import AgentResponse, AgentStatus, AgentStageResult, CardiacTwinState
from python.hearttwin.tools.model_config import chat_tuning, get_evaluator_model
from python.hearttwin.tools.scoring import (
    score_extraction_completeness,
    score_hallucination_risk,
    score_physiological_plausibility,
    score_recovery_scenario_stability,
    score_safety_compliance,
    score_visualization_readiness,
)
from python.hearttwin.tools.weave_trace import TraceContext, utc_now

# ---------------------------------------------------------------------------
# Module-level constants
# ---------------------------------------------------------------------------

_AGENT_ID = "evaluator_critic"
_AGENT_NAME = "Evaluator & Critic Agent"

_REQUIRED_DISCLAIMER_FRAGMENT = "not for diagnosis or treatment decisions"

_UNSAFE_PHRASES: list[str] = [
    "you have",
    "diagnosis",
    "diagnosed",
    "treatment plan",
    "prescribe",
    "take medication",
    "cured",
    "healed",
    "recommend treatment",
    "therapy recommendation",
    "patient improved medically",
]

# Forbidden keywords in self-improvement recommendations
_FORBIDDEN_REC_KEYWORDS: list[str] = [
    "invent",
    "medication",
    "diagnos",
    "treat",
    "prescrib",
    "remove warning",
    "hide uncertainty",
]

# ---------------------------------------------------------------------------
# Schema definitions
# ---------------------------------------------------------------------------


class ExtractionOutput(BaseModel):
    extracted_fields: dict[str, Any] = Field(default_factory=dict)
    source_map: list[dict[str, Any]] = Field(default_factory=list)
    confidence: float = 0.0
    model_config = {"extra": "allow"}


class ValidatorOutput(BaseModel):
    validated_fields: dict[str, Any] = Field(default_factory=dict)
    conflicts: list[dict[str, Any]] = Field(default_factory=list)
    missing_critical_fields: list[str] = Field(default_factory=list)
    invalid_fields: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    data_quality_score: float = 0.0
    model_config = {"extra": "allow"}


class HemodynamicsOutput(BaseModel):
    preload_index: float | None = None
    afterload_index: float | None = None
    contractility_index: float | None = None
    cardiac_output_l_min: float | None = None
    pv_loop: dict[str, Any] | None = None
    warnings: list[str] = Field(default_factory=list)
    model_config = {"extra": "allow"}


class RecoveryOutput(BaseModel):
    scenarios: list[dict[str, Any]] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    model_config = {"extra": "allow"}


class EvaluatorInput(BaseModel):
    """Full input contract for the evaluator critic.

    All sub-outputs are optional so the agent degrades gracefully when
    earlier pipeline stages are absent.
    """

    case_id: str
    cardiac_state: CardiacTwinState | None = None
    extraction: ExtractionOutput | None = None
    validation: ValidatorOutput | None = None
    operation: HemodynamicsOutput | None = None
    recovery: RecoveryOutput | None = None
    trace: list[dict[str, Any]] = Field(default_factory=list)
    generated_text: list[str] = Field(default_factory=list)


class EvalScores(BaseModel):
    extraction_completeness: float = Field(ge=0.0, le=1.0)
    physiological_plausibility: float = Field(ge=0.0, le=1.0)
    safety_compliance: float = Field(ge=0.0, le=1.0)
    hallucination_risk: float = Field(ge=0.0, le=1.0)
    visualization_readiness: float = Field(ge=0.0, le=1.0)
    recovery_scenario_stability: float = Field(ge=0.0, le=1.0)
    overall_score: float = Field(ge=0.0, le=1.0)
    warnings: list[str] = Field(default_factory=list)
    failed_checks: list[str] = Field(default_factory=list)


class CriticFinding(BaseModel):
    issue: str
    severity: Literal["low", "medium", "high"]
    evidence: str
    fix: str
    category: Literal[
        "safety", "physiology", "source", "uncertainty", "visualization", "orchestration"
    ]


class EvaluatorOutput(BaseModel):
    eval_scores: EvalScores
    critic_findings: list[CriticFinding]
    safe_to_display: bool
    required_revisions: list[str]
    summary: str


# ---------------------------------------------------------------------------
# Primary backward-compatible entry point (called by orchestrator)
# ---------------------------------------------------------------------------


async def run_evaluator_agent(
    state: CardiacTwinState,
    all_agent_responses: list[AgentResponse],
    visualization_payload: dict[str, Any] | None,
    case_id: str,
) -> tuple[AgentResponse, dict[str, Any]]:
    """Evaluate the full run and produce a quality report.

    Preserves the original call signature required by the orchestrator.
    Delegates all logic to the production EvaluatorInput → EvaluatorOutput
    pipeline so both paths are identical.
    """
    viz = visualization_payload or {}
    recovery_scenarios = viz.get("recovery_scenarios")

    evaluator_input = EvaluatorInput(
        case_id=case_id,
        cardiac_state=state,
        recovery=RecoveryOutput(scenarios=recovery_scenarios or []) if recovery_scenarios else None,
        trace=[r.model_dump() for r in all_agent_responses],
        generated_text=_collect_generated_text(all_agent_responses),
    )

    eval_output, stage_result, tracer = await _run_evaluator_critic_internal(
        evaluator_input, viz_payload=viz
    )

    numeric_checks = _verify_numeric_claims(state, all_agent_responses)
    extra_warnings: list[str] = []
    for mismatch in numeric_checks["mismatches"]:
        extra_warnings.append(f"Numeric claim mismatch: {mismatch}")
    if len(numeric_checks["mismatches"]) >= 3:
        extra_warnings.append("NUMERIC: Multiple numeric claim mismatches detected")

    all_warnings = _dedupe_local(list(eval_output.eval_scores.warnings) + extra_warnings)
    scores = eval_output.eval_scores
    prior_fields = [
        e.field for e in state.source_map if e.source.value == "default_model_prior"
    ]

    if not eval_output.safe_to_display:
        overall_status = AgentStatus.FAILED
    elif eval_output.required_revisions:
        overall_status = AgentStatus.WARNING
    elif all_warnings:
        overall_status = AgentStatus.WARNING
    else:
        overall_status = AgentStatus.SUCCESS

    report: dict[str, Any] = {
        "scores": {
            "data_completeness": scores.extraction_completeness,
            "extraction_completeness": scores.extraction_completeness,
            "physiological_plausibility": scores.physiological_plausibility,
            "hallucination_risk": scores.hallucination_risk,
            "safety_compliance": scores.safety_compliance,
            "visualization_readiness": scores.visualization_readiness,
            "recovery_scenario_stability": scores.recovery_scenario_stability,
            "overall": scores.overall_score,
            "overall_score": scores.overall_score,
        },
        "eval_scores": scores.model_dump(),
        "passed": (
            eval_output.safe_to_display
            and not eval_output.required_revisions
            and scores.overall_score >= 0.40
            and scores.safety_compliance >= 0.70
            and not any(c.startswith("unsafe_language") for c in scores.failed_checks)
        ),
        "force_revision_issues": eval_output.required_revisions,
        "failed_checks": scores.failed_checks,
        "prior_field_count": len(prior_fields),
        "prior_fields": prior_fields,
        "numeric_checks": numeric_checks,
        "warnings": all_warnings,
        "agent_statuses": {r.agent: r.status.value for r in all_agent_responses},
        "critic_findings": [f.model_dump() for f in eval_output.critic_findings],
        "safe_to_display": eval_output.safe_to_display,
        "required_revisions": eval_output.required_revisions,
        "summary": eval_output.summary,
        "simulation_note": (
            f"{CORE_SAFETY_PHRASE} Evaluated outputs are simulated estimates."
        ),
        "agent_stage_result": stage_result.model_dump(),
    }

    return (
        AgentResponse(
            agent="evaluator_agent",
            status=overall_status,
            inputs_used=["cardiac_twin_state", "all_agent_responses"],
            outputs=report,
            warnings=all_warnings,
            confidence=scores.overall_score,
            trace=tracer.steps,
        ),
        report,
    )


# ---------------------------------------------------------------------------
# New standalone public API
# ---------------------------------------------------------------------------


async def run_evaluator_critic(
    evaluator_input: EvaluatorInput,
    viz_payload: dict[str, Any] | None = None,
) -> tuple[EvaluatorOutput, AgentStageResult]:
    """Standalone production entry point for the evaluator critic.

    Returns (EvaluatorOutput, AgentStageResult).  Does not require
    a full CardiacTwinState — degrades gracefully when sub-outputs absent.
    """
    eval_output, stage_result, _ = await _run_evaluator_critic_internal(
        evaluator_input, viz_payload=viz_payload or {}
    )
    return eval_output, stage_result


# ---------------------------------------------------------------------------
# Core implementation
# ---------------------------------------------------------------------------


async def _run_evaluator_critic_internal(
    inp: EvaluatorInput,
    viz_payload: dict[str, Any],
) -> tuple[EvaluatorOutput, AgentStageResult, TraceContext]:
    """Run all scoring, critic finding generation, and memory writes."""
    started = _utc_now()
    t0 = time.time()
    tracer = TraceContext(case_id=inp.case_id, agent_name=_AGENT_NAME)
    tools_called: list[str] = []
    warnings: list[str] = []
    failed_checks: list[str] = []

    state_dict = inp.cardiac_state.model_dump() if inp.cardiac_state else {}
    recovery_scenarios: list[dict[str, Any]] | None = None
    if inp.recovery:
        recovery_scenarios = inp.recovery.scenarios or None
    if not recovery_scenarios and viz_payload.get("recovery_scenarios"):
        recovery_scenarios = viz_payload["recovery_scenarios"]

    agent_outputs: list[dict[str, Any]] = list(inp.trace)

    # ------------------------------------------------------------------
    # 1. Score extraction completeness
    # ------------------------------------------------------------------
    t_sub = time.time()
    extraction_completeness = _score_extraction_completeness(
        state_dict, inp.extraction, warnings, failed_checks
    )
    tracer.record_tool(
        "hearttwin.score_extraction_completeness",
        inputs={"case_id": inp.case_id},
        outputs={"score": extraction_completeness},
        duration_ms=(time.time() - t_sub) * 1000,
    )
    tools_called.append("hearttwin.score_extraction_completeness")

    # ------------------------------------------------------------------
    # 2. Score physiological plausibility
    # ------------------------------------------------------------------
    t_sub = time.time()
    physiological_plausibility = _score_physiological_plausibility(
        state_dict, recovery_scenarios, warnings, failed_checks
    )
    tracer.record_tool(
        "hearttwin.score_physiological_plausibility",
        inputs={"recovery_scenario_count": len(recovery_scenarios or [])},
        outputs={"score": physiological_plausibility},
        duration_ms=(time.time() - t_sub) * 1000,
    )
    tools_called.append("hearttwin.score_physiological_plausibility")

    # ------------------------------------------------------------------
    # 3. Score safety compliance (including generated_text scan)
    # ------------------------------------------------------------------
    t_sub = time.time()
    combined_text_payload = _build_text_payload(agent_outputs, inp.generated_text)
    safety_compliance = _score_safety_compliance(
        combined_text_payload, viz_payload, warnings, failed_checks
    )
    unsafe_phrases_found = _detect_unsafe_phrases(
        combined_text_payload, inp.generated_text
    )
    tracer.record_tool(
        "hearttwin.score_safety_compliance",
        inputs={"unsafe_phrase_count": len(unsafe_phrases_found)},
        outputs={"score": safety_compliance, "unsafe_phrases": unsafe_phrases_found},
        duration_ms=(time.time() - t_sub) * 1000,
    )
    tools_called.append("hearttwin.score_safety_compliance")

    # ------------------------------------------------------------------
    # 4. Score hallucination risk
    # ------------------------------------------------------------------
    t_sub = time.time()
    unsupported_claims = _detect_unsupported_numeric_claims(
        agent_outputs, inp.generated_text, state_dict
    )
    hallucination_risk = _score_hallucination_risk(
        agent_outputs, state_dict, inp.generated_text, warnings, failed_checks
    )
    tracer.record_tool(
        "hearttwin.score_hallucination_risk",
        inputs={"unsupported_numeric_claim_count": len(unsupported_claims)},
        outputs={"score": hallucination_risk},
        duration_ms=(time.time() - t_sub) * 1000,
    )
    tools_called.append("hearttwin.score_hallucination_risk")

    # ------------------------------------------------------------------
    # 5. Score visualization readiness
    # ------------------------------------------------------------------
    t_sub = time.time()
    visualization_readiness = _score_visualization_readiness(
        state_dict, viz_payload, inp.operation, warnings, failed_checks
    )
    tracer.record_tool(
        "hearttwin.score_visualization_readiness",
        inputs={"has_pv_loop": bool(viz_payload.get("pv_loop"))},
        outputs={"score": visualization_readiness},
        duration_ms=(time.time() - t_sub) * 1000,
    )
    tools_called.append("hearttwin.score_visualization_readiness")

    # ------------------------------------------------------------------
    # 6. Score recovery scenario stability
    # ------------------------------------------------------------------
    t_sub = time.time()
    recovery_scenario_stability = _score_recovery_scenario_stability(
        recovery_scenarios, warnings, failed_checks
    )
    tracer.record_tool(
        "hearttwin.score_recovery_stability",
        inputs={"scenario_count": len(recovery_scenarios or [])},
        outputs={"score": recovery_scenario_stability},
        duration_ms=(time.time() - t_sub) * 1000,
    )
    tools_called.append("hearttwin.score_recovery_stability")

    # ------------------------------------------------------------------
    # 7. Overall score (spec formula, clamped to [0, 1])
    # ------------------------------------------------------------------
    overall_score = _clamp(
        0.20 * extraction_completeness
        + 0.25 * physiological_plausibility
        + 0.25 * safety_compliance
        + 0.15 * visualization_readiness
        + 0.15 * recovery_scenario_stability
        - 0.20 * hallucination_risk
    )

    prior_fields = _get_prior_fields(state_dict)
    if len(prior_fields) > 8:
        warnings.append(
            f"High prior usage: {len(prior_fields)} fields from population priors — "
            "upload more patient data for a better-calibrated simulation"
        )

    eval_scores = EvalScores(
        extraction_completeness=round(extraction_completeness, 3),
        physiological_plausibility=round(physiological_plausibility, 3),
        safety_compliance=round(safety_compliance, 3),
        hallucination_risk=round(hallucination_risk, 3),
        visualization_readiness=round(visualization_readiness, 3),
        recovery_scenario_stability=round(recovery_scenario_stability, 3),
        overall_score=round(overall_score, 3),
        warnings=_dedupe_local(warnings),
        failed_checks=_dedupe_local(failed_checks),
    )

    # ------------------------------------------------------------------
    # 8. Generate deterministic CriticFindings
    # ------------------------------------------------------------------
    t_sub = time.time()
    critic_findings = _generate_critic_findings(
        eval_scores,
        state_dict,
        agent_outputs,
        inp.generated_text,
        viz_payload,
        recovery_scenarios,
        unsupported_claims,
        unsafe_phrases_found,
    )
    tracer.record_tool(
        "hearttwin.generate_critic_findings",
        inputs={"score_count": 7},
        outputs={"finding_count": len(critic_findings)},
        duration_ms=(time.time() - t_sub) * 1000,
    )
    tools_called.append("hearttwin.generate_critic_findings")

    # ------------------------------------------------------------------
    # 9. Required revisions and safe-to-display gate
    # ------------------------------------------------------------------
    required_revisions = _generate_required_revisions(eval_scores, critic_findings)
    safe_to_display = _is_safe_to_display(eval_scores, unsafe_phrases_found)
    if not safe_to_display:
        required_revisions = _dedupe_local(
            ["SAFETY: Output contains blocked language requiring revision"] + required_revisions
        )

    # ------------------------------------------------------------------
    # 10. LLM critic summary (OpenAI, with deterministic fallback)
    # ------------------------------------------------------------------
    model_used: str | None = None
    summary = _deterministic_summary(eval_scores, critic_findings)
    if os.environ.get("OPENAI_API_KEY"):
        openai_summary, model_used = await _generate_critic_summary_openai(
            eval_scores, critic_findings, required_revisions
        )
        if openai_summary:
            summary = openai_summary
    tools_called.append("hearttwin.evaluate_run")

    # ------------------------------------------------------------------
    # 11. Weave trace finish
    # ------------------------------------------------------------------
    latency_ms = round((time.time() - t0) * 1000, 1)
    finished = _utc_now()

    tracer.record_tool(
        "hearttwin.evaluate_run",
        inputs={"case_id": inp.case_id, "tool_count": len(tools_called)},
        outputs={
            "overall_score": eval_scores.overall_score,
            "safe_to_display": safe_to_display,
            "critic_finding_count": len(critic_findings),
            "safety_compliance": eval_scores.safety_compliance,
            "hallucination_risk": eval_scores.hallucination_risk,
            "required_revision_count": len(required_revisions),
        },
        duration_ms=latency_ms,
    )

    eval_output = EvaluatorOutput(
        eval_scores=eval_scores,
        critic_findings=critic_findings,
        safe_to_display=safe_to_display,
        required_revisions=required_revisions,
        summary=summary,
    )

    # ------------------------------------------------------------------
    # 12. AgentStageResult
    # ------------------------------------------------------------------
    safety_flags: list[str] = []
    if not safe_to_display:
        safety_flags.append("unsafe_output_blocked")
    if eval_scores.hallucination_risk > 0.5:
        safety_flags.append("high_hallucination_risk")
    if eval_scores.safety_compliance < 0.70:
        safety_flags.append("safety_compliance_below_threshold")

    stage_status: Literal["success", "warning", "failed", "skipped"] = "success"
    if not safe_to_display:
        stage_status = "failed"
    elif required_revisions or eval_scores.warnings:
        stage_status = "warning"

    stage_result = AgentStageResult(
        agent_id=_AGENT_ID,
        agent_name=_AGENT_NAME,
        model_used=model_used,
        status=stage_status,
        started_at=started,
        finished_at=finished,
        latency_ms=latency_ms,
        inputs_used=_inputs_used(inp),
        tools_called=tools_called,
        output_summary=_output_summary(eval_scores, critic_findings, safe_to_display),
        structured_output={
            "eval_scores": eval_scores.model_dump(),
            "critic_finding_count": len(critic_findings),
            "safety_flags": safety_flags,
            "hallucination_risk": eval_scores.hallucination_risk,
            "safe_to_display": safe_to_display,
            "required_revisions": required_revisions,
            "warnings": eval_scores.warnings,
        },
        warnings=eval_scores.warnings,
        confidence=eval_scores.overall_score,
        safety_flags=safety_flags,
        weave_call_id=None,
        local_trace_id=tracer.trace_id,
    )

    # ------------------------------------------------------------------
    # 13. Redis memory writes (best-effort; never raises)
    # ------------------------------------------------------------------
    await _store_eval_memory(inp.case_id, eval_output, eval_scores)

    return eval_output, stage_result, tracer


# ---------------------------------------------------------------------------
# Individual scoring wrappers (call scoring.py, add local extra logic)
# ---------------------------------------------------------------------------


def _score_extraction_completeness(
    state_dict: dict[str, Any],
    extraction: ExtractionOutput | None,
    warnings: list[str],
    failed_checks: list[str],
) -> float:
    """Score extraction completeness; supplement state_dict with extraction if available."""
    # Merge extraction source_map into state for richer coverage
    if extraction and extraction.source_map:
        merged = dict(state_dict)
        existing_map = merged.get("source_map") or []
        merged["source_map"] = existing_map + list(extraction.source_map)
        return score_extraction_completeness(merged)
    return score_extraction_completeness(state_dict)


def _score_physiological_plausibility(
    state_dict: dict[str, Any],
    recovery_scenarios: list[dict[str, Any]] | None,
    warnings: list[str],
    failed_checks: list[str],
) -> float:
    return score_physiological_plausibility(
        state_dict, recovery_scenarios, warnings, failed_checks
    )


def _score_safety_compliance(
    combined_text_payload: dict[str, Any],
    viz_payload: dict[str, Any],
    warnings: list[str],
    failed_checks: list[str],
) -> float:
    return score_safety_compliance(combined_text_payload, viz_payload, warnings, failed_checks)


def _score_hallucination_risk(
    agent_outputs: list[dict[str, Any]],
    state_dict: dict[str, Any],
    generated_text: list[str],
    warnings: list[str],
    failed_checks: list[str],
) -> float:
    """Score hallucination risk; checks generated_text in addition to agent outputs."""
    risk = score_hallucination_risk(agent_outputs, state_dict, warnings, failed_checks)

    # Extra penalty if generated text contains medical claims not in state
    extra_text = " ".join(generated_text)
    for phrase in ["diagnosis", "treatment", "prescription", "healed", "cured"]:
        if phrase in strip_allowed_safety_phrases(extra_text).lower():
            risk = _clamp(risk + 0.12)
            if f"hallucination_generated_text_{phrase}" not in failed_checks:
                failed_checks.append(f"hallucination_generated_text_{phrase}")

    return _clamp(risk)


def _score_visualization_readiness(
    state_dict: dict[str, Any],
    viz_payload: dict[str, Any],
    operation: HemodynamicsOutput | None,
    warnings: list[str],
    failed_checks: list[str],
) -> float:
    """Score visualization readiness; augment viz_payload from operation output."""
    augmented = dict(viz_payload)
    if operation and operation.pv_loop and "pv_loop" not in augmented:
        augmented["pv_loop"] = operation.pv_loop
    return score_visualization_readiness(state_dict, augmented, warnings, failed_checks)


def _score_recovery_scenario_stability(
    recovery_scenarios: list[dict[str, Any]] | None,
    warnings: list[str],
    failed_checks: list[str],
) -> float:
    return score_recovery_scenario_stability(recovery_scenarios, warnings, failed_checks)


# ---------------------------------------------------------------------------
# Detection helpers
# ---------------------------------------------------------------------------


def _detect_unsafe_phrases(
    combined_payload: dict[str, Any],
    generated_text: list[str],
) -> list[str]:
    """Return list of unsafe phrases found in combined output text."""
    raw = json.dumps(combined_payload, default=str) + " " + " ".join(generated_text)
    text = strip_allowed_safety_phrases(raw).lower()
    found: list[str] = []
    for phrase in _UNSAFE_PHRASES:
        if phrase in text and phrase not in found:
            found.append(phrase)
    return found


def _detect_unsupported_numeric_claims(
    agent_outputs: list[dict[str, Any]],
    generated_text: list[str],
    state_dict: dict[str, Any],
) -> list[float]:
    """Return numeric values found in outputs that don't appear in the state."""
    known_numbers: set[float] = set()
    for container_key in ("measurements", "hemodynamics", "electrophysiology", "tissue_state"):
        container = state_dict.get(container_key) or {}
        for v in container.values():
            if isinstance(v, dict) and isinstance(v.get("value"), (int, float)):
                known_numbers.add(round(float(v["value"]), 1))

    # Harmless small numbers to exclude from unsupported set
    _HARMLESS = {0.0, 1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0, 8.0, 9.0, 10.0}

    all_text = (
        json.dumps(agent_outputs, default=str)
        + " "
        + " ".join(generated_text)
    )
    claims = {
        round(float(n), 1)
        for n in re.findall(r"\b\d+(?:\.\d+)?\b", all_text)
    }
    return [n for n in claims if n not in known_numbers and n not in _HARMLESS]


def _is_safe_to_display(
    scores: EvalScores,
    unsafe_phrases_found: list[str],
) -> bool:
    """Return False when safety compliance is critically low or blocking phrases found."""
    if scores.safety_compliance < 0.50:
        return False
    critical_phrases = {"you have", "diagnosed", "prescribe", "take medication"}
    for phrase in unsafe_phrases_found:
        if phrase in critical_phrases:
            return False
    return True


# ---------------------------------------------------------------------------
# Critic finding generation (fully deterministic)
# ---------------------------------------------------------------------------

_HARNESS_IMPROVEMENTS = [
    "reduce max_safe_parameter_shift",
    "increase uncertainty_penalty_weight",
    "switch target_metric to balanced",
    "shorten recovery_horizon_days",
    "preserve all warnings in rerun",
    "ask for missing EDV/ESV evidence",
    "mark prior-heavy scenario low-confidence",
    "add missing source/confidence labels",
    "request additional patient data",
]


def _generate_critic_findings(
    scores: EvalScores,
    state_dict: dict[str, Any],
    agent_outputs: list[dict[str, Any]],
    generated_text: list[str],
    viz_payload: dict[str, Any],
    recovery_scenarios: list[dict[str, Any]] | None,
    unsupported_claims: list[float],
    unsafe_phrases_found: list[str],
) -> list[CriticFinding]:
    """Generate harness-focused CriticFinding objects from scores and state analysis."""
    findings: list[CriticFinding] = []

    # --- Safety findings ---
    for phrase in unsafe_phrases_found:
        findings.append(
            CriticFinding(
                issue=f"Output contains blocked phrase: '{phrase}'.",
                severity="high",
                evidence=f"Blocked phrase detected in output text.",
                fix=(
                    "Remove or rephrase the output to use simulation-safe language "
                    "(e.g. 'simulated pattern' or 'harness output'). "
                    "Do not include assertions about patient condition or blocked terms."
                ),
                category="safety",
            )
        )

    if scores.safety_compliance < 0.80 and not unsafe_phrases_found:
        findings.append(
            CriticFinding(
                issue="Safety disclaimer is missing or incomplete.",
                severity="medium",
                evidence=f"safety_compliance={scores.safety_compliance:.2f}; required disclaimer fragment absent.",
                fix=(
                    "Ensure every agent output includes the required simulation-only disclaimer. "
                    "See CORE_SAFETY_PHRASE in python/hearttwin/safety.py."
                ),
                category="safety",
            )
        )

    # --- Physiology findings ---
    meas = state_dict.get("measurements") or {}
    edv = _get_meas_val(meas, "edv_ml")
    esv = _get_meas_val(meas, "esv_ml")
    if edv is not None and esv is not None and esv >= edv:
        findings.append(
            CriticFinding(
                issue="ESV is not less than EDV — physiologically impossible.",
                severity="high",
                evidence=f"ESV={esv:.1f} mL, EDV={edv:.1f} mL; ESV must be < EDV.",
                fix=(
                    "Check source evidence for volume measurements. "
                    "Request re-upload or re-extraction of echocardiogram data."
                ),
                category="physiology",
            )
        )

    hr = _get_meas_val(meas, "heart_rate_bpm")
    if hr is not None and not (30 <= hr <= 250):
        findings.append(
            CriticFinding(
                issue="Heart rate is outside physiological bounds.",
                severity="high",
                evidence=f"heart_rate_bpm={hr:.1f} bpm (expected 30–250).",
                fix="Re-check source evidence; add bounds validation at extraction stage.",
                category="physiology",
            )
        )

    sbp = _get_meas_val(meas, "systolic_bp_mmhg")
    dbp = _get_meas_val(meas, "diastolic_bp_mmhg")
    if sbp is not None and dbp is not None and dbp >= sbp:
        findings.append(
            CriticFinding(
                issue="Diastolic BP is not lower than systolic BP.",
                severity="high",
                evidence=f"SBP={sbp:.1f}, DBP={dbp:.1f} mmHg; DBP must be < SBP.",
                fix="Verify extracted BP values; check for field-swap at extraction.",
                category="physiology",
            )
        )

    ef = _get_meas_val(meas, "ejection_fraction_pct")
    if ef is not None and not (0 <= ef <= 100):
        findings.append(
            CriticFinding(
                issue="Ejection fraction is outside valid range [0, 100].",
                severity="high",
                evidence=f"ejection_fraction_pct={ef:.1f}%.",
                fix="Verify EF extraction; check for unit mismatch (fraction vs percent).",
                category="physiology",
            )
        )

    if scores.physiological_plausibility < 0.50 and len(findings) == 0:
        findings.append(
            CriticFinding(
                issue="Physiological plausibility score is critically low.",
                severity="high",
                evidence=f"physiological_plausibility={scores.physiological_plausibility:.2f}.",
                fix=(
                    "Review extraction quality; consider requesting additional "
                    "evidence before simulation."
                ),
                category="physiology",
            )
        )

    # --- Source / uncertainty findings ---
    prior_fields = _get_prior_fields(state_dict)
    if len(prior_fields) > 8:
        findings.append(
            CriticFinding(
                issue="Many fields rely on population priors rather than extracted evidence.",
                severity="medium",
                evidence=(
                    f"{len(prior_fields)} fields using default_model_prior: "
                    f"{', '.join(prior_fields[:6])}{'...' if len(prior_fields) > 6 else ''}."
                ),
                fix=(
                    "Increase uncertainty_penalty_weight in RecoveryConfig. "
                    "Mark prior-heavy scenarios as low-confidence. "
                    "Ask for missing EDV/ESV evidence."
                ),
                category="uncertainty",
            )
        )

    if scores.hallucination_risk > 0.40:
        findings.append(
            CriticFinding(
                issue="Hallucination risk is elevated due to unsupported numeric claims or missing provenance.",
                severity="high" if scores.hallucination_risk > 0.60 else "medium",
                evidence=(
                    f"hallucination_risk={scores.hallucination_risk:.2f}; "
                    f"{len(unsupported_claims)} unsupported numeric value(s) found."
                ),
                fix="Add source/confidence labels to all MeasuredValue fields. Remove fabricated numeric claims.",
                category="source",
            )
        )

    if "hallucination_missing_sources" in scores.failed_checks:
        findings.append(
            CriticFinding(
                issue="Fewer than half of measurement fields have a source map entry.",
                severity="medium",
                evidence="source_map coverage below 50% of measurements.",
                fix=(
                    "Ensure every extracted MeasuredValue carries source and confidence. "
                    "add missing source/confidence labels to all fields."
                ),
                category="source",
            )
        )

    data_quality = state_dict.get("data_quality_score", 1.0)
    cfg = (state_dict.get("simulation_config") or {}).get("recovery") or {}
    max_shift = cfg.get("max_safe_parameter_shift", 0.30)
    if isinstance(data_quality, (int, float)) and data_quality < 0.50 and max_shift > 0.15:
        findings.append(
            CriticFinding(
                issue="Recovery scenario uses wide parameter shifts with low data quality.",
                severity="medium",
                evidence=(
                    f"data_quality_score={data_quality:.2f} and "
                    f"max_safe_parameter_shift={max_shift:.2f}."
                ),
                fix=(
                    "Reduce max_safe_parameter_shift and increase uncertainty_penalty_weight "
                    "to keep simulated trajectories within evidence-supported bounds."
                ),
                category="uncertainty",
            )
        )

    # --- Visualization findings ---
    if scores.visualization_readiness < 0.40:
        findings.append(
            CriticFinding(
                issue="Visualization payload is incomplete or missing key data.",
                severity="medium",
                evidence=f"visualization_readiness={scores.visualization_readiness:.2f}.",
                fix=(
                    "Ensure PV loop, cardiac cycle, and summary metrics are populated. "
                    "Check hemodynamics agent output."
                ),
                category="visualization",
            )
        )
    elif "visualization_missing_pv_loop" in scores.failed_checks:
        findings.append(
            CriticFinding(
                issue="PV loop data is absent from the visualization payload.",
                severity="low",
                evidence="pv_loop key missing or empty in visualization_payload.",
                fix="Confirm hemodynamics_agent ran successfully and returned pv_loop.",
                category="visualization",
            )
        )

    # --- Orchestration / recovery findings ---
    if scores.recovery_scenario_stability < 0.70:
        findings.append(
            CriticFinding(
                issue="Recovery scenario stability is below acceptable threshold.",
                severity="medium",
                evidence=f"recovery_scenario_stability={scores.recovery_scenario_stability:.2f}.",
                fix=(
                    "Reduce max_safe_parameter_shift. "
                    "Switch target_metric to balanced. "
                    "Shorten recovery_horizon_days if uncertainty expands."
                ),
                category="orchestration",
            )
        )

    if recovery_scenarios and all(not s.get("warnings") for s in recovery_scenarios):
        findings.append(
            CriticFinding(
                issue="Recovery scenarios have no explicit warning or tradeoff notes.",
                severity="low",
                evidence="Every scenario has an empty warnings list.",
                fix=(
                    "Preserve all warnings in rerun; ensure recovery_agent "
                    "populates scenario.warnings with uncertainty tradeoffs."
                ),
                category="orchestration",
            )
        )

    if not recovery_scenarios and viz_payload:
        findings.append(
            CriticFinding(
                issue="No recovery scenarios present in this run.",
                severity="low",
                evidence="recovery_scenarios is empty or absent.",
                fix=(
                    "Run /simulate-recovery to generate bounded scenario trajectories "
                    "before requesting visualization."
                ),
                category="orchestration",
            )
        )

    return findings


# ---------------------------------------------------------------------------
# Required revisions and safe-to-display
# ---------------------------------------------------------------------------


def _generate_required_revisions(
    scores: EvalScores,
    findings: list[CriticFinding],
) -> list[str]:
    """Return a bounded list of harness-safe required revisions."""
    revisions: list[str] = []

    if scores.safety_compliance < 0.70:
        revisions.append("SAFETY: Safety compliance below 0.70 — blocked language must be removed")

    if scores.hallucination_risk > 0.50:
        revisions.append(
            "HALLUCINATION: Suspected invented values in output — add source/confidence to all fields"
        )

    if scores.physiological_plausibility < 0.30:
        revisions.append(
            "PHYSIOLOGY: State appears physiologically implausible — verify extracted volumes and rates"
        )

    high_findings = [f for f in findings if f.severity == "high"]
    for finding in high_findings:
        if finding.category == "safety":
            revisions.append(f"SAFETY: {finding.issue}")
        elif finding.category == "physiology":
            revisions.append(f"PHYSIOLOGY: {finding.issue}")
        elif finding.category == "source":
            revisions.append(f"SOURCE: {finding.issue}")

    # Filter out any accidentally forbidden recommendation keywords
    clean: list[str] = []
    for rev in revisions:
        rev_lower = rev.lower()
        if not any(kw in rev_lower for kw in _FORBIDDEN_REC_KEYWORDS):
            clean.append(rev)
        else:
            clean.append(rev.split(":")[0] + ": Harness review required — see critic findings")

    return _dedupe_local(clean)


# ---------------------------------------------------------------------------
# Harness improvement recommendations (allowed set)
# ---------------------------------------------------------------------------


def _harness_improvement_recommendations(
    scores: EvalScores,
    state_dict: dict[str, Any],
    recovery_scenarios: list[dict[str, Any]] | None,
) -> list[str]:
    """Return bounded harness improvement suggestions (never medical advice)."""
    recs: list[str] = []

    cfg = (state_dict.get("simulation_config") or {}).get("recovery") or {}
    max_shift = cfg.get("max_safe_parameter_shift", 0.30)
    uncertainty_weight = cfg.get("uncertainty_penalty_weight", 0.20)
    horizon_days = cfg.get("recovery_horizon_days", 30)

    if scores.recovery_scenario_stability < 0.85 and max_shift > 0.15:
        recs.append(
            f"reduce max_safe_parameter_shift (current {max_shift:.2f} → suggest ≤ 0.15)"
        )

    if scores.extraction_completeness < 0.65 or len(_get_prior_fields(state_dict)) > 6:
        recs.append(
            f"increase uncertainty_penalty_weight (current {uncertainty_weight:.2f} → suggest ≥ 0.35)"
        )

    if scores.recovery_scenario_stability < 0.85:
        recs.append("switch target_metric to balanced")

    if horizon_days > 14 and scores.recovery_scenario_stability < 0.80:
        recs.append(
            f"shorten recovery_horizon_days (current {horizon_days}d → suggest ≤ 14d)"
        )

    prior_fields = _get_prior_fields(state_dict)
    volume_priors = [f for f in prior_fields if f in ("edv_ml", "esv_ml")]
    if volume_priors:
        recs.append(f"ask for missing EDV/ESV evidence (fields from prior: {volume_priors})")

    if len(prior_fields) > 4:
        recs.append("mark prior-heavy scenario low-confidence in output labels")

    if "hallucination_missing_sources" in scores.failed_checks:
        recs.append("add missing source/confidence labels to all MeasuredValue fields")

    if recovery_scenarios and all(not s.get("warnings") for s in recovery_scenarios):
        recs.append("preserve warnings in rerun — every scenario should carry tradeoff notes")

    # Safety-check: strip any accidentally forbidden content
    clean: list[str] = [
        r for r in recs
        if not any(kw in r.lower() for kw in _FORBIDDEN_REC_KEYWORDS)
    ]
    return _dedupe_local(clean)


# ---------------------------------------------------------------------------
# LLM-assisted critic summary (OpenAI, deterministic fallback)
# ---------------------------------------------------------------------------


async def _generate_critic_summary_openai(
    scores: EvalScores,
    findings: list[CriticFinding],
    required_revisions: list[str],
) -> tuple[str | None, str | None]:
    """Return (summary_text, model_used) or (None, None) on failure."""
    model_name = get_evaluator_model()
    if not os.environ.get("OPENAI_API_KEY"):
        return None, None

    top_findings = [
        {"issue": f.issue, "severity": f.severity, "fix": f.fix, "category": f.category}
        for f in findings[:6]
    ]
    prompt_payload = {
        "eval_scores": scores.model_dump(),
        "top_findings": top_findings,
        "required_revisions": required_revisions[:4],
    }

    system_prompt = (
        "You are the HeartTwin evaluator critic. "
        "You explain simulation harness quality issues clearly and concisely. "
        "You NEVER diagnose, prescribe medication, recommend treatment, or provide clinical advice. "
        "You ONLY suggest harness configuration improvements (parameter shifts, uncertainty weights, data quality). "
        "Write 2–3 sentences. Be specific about scores. Do not repeat 'not for diagnosis'."
    )

    try:
        import openai

        client = openai.AsyncOpenAI(api_key=os.environ["OPENAI_API_KEY"])
        response = await client.chat.completions.create(
            model=model_name,
            messages=[
                {"role": "system", "content": system_prompt},
                {
                    "role": "user",
                    "content": (
                        "Summarize the evaluation results for this simulation run:\n"
                        + json.dumps(prompt_payload, indent=2)
                    ),
                },
            ],
            **chat_tuning(model_name, 280, 0),
        )
        text = (response.choices[0].message.content or "").strip()
        if not text:
            return None, None
        # Safety guard: strip any generated clinical advice
        if any(phrase in text.lower() for phrase in _FORBIDDEN_REC_KEYWORDS):
            return None, None
        return text, model_name
    except Exception:
        return None, None


def _deterministic_summary(
    scores: EvalScores,
    findings: list[CriticFinding],
) -> str:
    """Build a plain-language summary without any LLM call."""
    high_count = sum(1 for f in findings if f.severity == "high")
    med_count = sum(1 for f in findings if f.severity == "medium")
    parts: list[str] = [
        f"Overall score: {scores.overall_score:.2f}.",
        f"Safety: {scores.safety_compliance:.2f}, "
        f"Plausibility: {scores.physiological_plausibility:.2f}, "
        f"Hallucination risk: {scores.hallucination_risk:.2f}.",
    ]
    if high_count:
        parts.append(f"{high_count} high-severity finding(s) require revision.")
    elif med_count:
        parts.append(f"{med_count} medium-severity finding(s) flagged for review.")
    else:
        parts.append("No blocking issues found.")
    if scores.failed_checks:
        parts.append(
            f"Failed checks: {', '.join(scores.failed_checks[:3])}"
            + ("..." if len(scores.failed_checks) > 3 else ".")
        )
    return " ".join(parts)


# ---------------------------------------------------------------------------
# Redis memory writes (best-effort; never raises)
# ---------------------------------------------------------------------------


async def _store_eval_memory(
    case_id: str,
    eval_output: EvaluatorOutput,
    scores: EvalScores,
) -> None:
    """Write eval result and agentic memory to Redis (Upstash REST)."""
    from python.hearttwin.tools import redis_client

    if not redis_client.is_configured():
        return

    # Per-case eval result.
    case_payload = {
        "overall_score": scores.overall_score,
        "safety_compliance": scores.safety_compliance,
        "hallucination_risk": scores.hallucination_risk,
        "physiological_plausibility": scores.physiological_plausibility,
        "safe_to_display": eval_output.safe_to_display,
        "required_revision_count": len(eval_output.required_revisions),
        "critic_finding_count": len(eval_output.critic_findings),
        "failed_checks": scores.failed_checks[:10],
        "warnings": scores.warnings[:10],
    }

    # Redacted agentic memory payloads.
    critic_patterns_payload = {
        "failed_checks": scores.failed_checks[:10],
        "top_finding_categories": [f.category for f in eval_output.critic_findings[:5]],
    }
    failed_checks_payload = {
        "failed_checks": scores.failed_checks[:15],
        "overall_score": scores.overall_score,
    }
    harness_fixes_payload = {
        "improvements": _harness_improvement_recommendations(scores, {}, None)[:5],
        "safe_to_display": eval_output.safe_to_display,
    }

    await redis_client.set_json(f"hearttwin:case:{case_id}:eval", case_payload)
    await redis_client.set_json("hearttwin:memory:critic_patterns", critic_patterns_payload)
    await redis_client.set_json("hearttwin:memory:failed_checks", failed_checks_payload)
    await redis_client.set_json(
        "hearttwin:memory:successful_harness_fixes", harness_fixes_payload
    )


# ---------------------------------------------------------------------------
# Numeric claim cross-check (backward-compatible helper)
# ---------------------------------------------------------------------------


def _verify_numeric_claims(
    state: CardiacTwinState,
    agent_responses: list[AgentResponse],
) -> dict[str, Any]:
    """Cross-check numeric outputs against canonical state values."""
    mismatches: list[str] = []
    checks = 0

    state_ef = (
        state.measurements.ejection_fraction_pct.value
        if state.measurements.ejection_fraction_pct
        else None
    )
    state_co = (
        state.measurements.cardiac_output_l_min.value
        if state.measurements.cardiac_output_l_min
        else None
    )

    for resp in agent_responses:
        outputs = resp.outputs or {}
        checks += 1

        out_ef = outputs.get("ef_pct")
        if out_ef is not None and state_ef is not None:
            if abs(float(out_ef) - state_ef) > 5.0:
                mismatches.append(
                    f"Agent '{resp.agent}' EF {float(out_ef):.1f}% differs from state EF {state_ef:.1f}%"
                )

        out_co = outputs.get("cardiac_output_l_min")
        if out_co is not None and state_co is not None:
            if abs(float(out_co) - state_co) > 1.0:
                mismatches.append(
                    f"Agent '{resp.agent}' CO {float(out_co):.2f} differs from state CO {state_co:.2f}"
                )

    return {
        "checks_performed": checks,
        "mismatches": mismatches,
        "all_consistent": len(mismatches) == 0,
    }


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------


def _collect_generated_text(agent_responses: list[AgentResponse]) -> list[str]:
    """Pull free-text summary/narrative fields from agent outputs for safety scanning."""
    texts: list[str] = []
    for resp in agent_responses:
        for key in ("summary", "narrative", "interpretation", "analysis", "simulation_note"):
            val = (resp.outputs or {}).get(key)
            if isinstance(val, str) and val:
                texts.append(val)
        for w in resp.warnings or []:
            if isinstance(w, str):
                texts.append(w)
    return texts


def _build_text_payload(
    agent_outputs: list[dict[str, Any]],
    generated_text: list[str],
) -> dict[str, Any]:
    """Combine agent outputs and generated text into a single payload for safety scoring."""
    return {
        "agent_outputs": agent_outputs,
        "generated_text": " ".join(generated_text),
    }


def _get_meas_val(measurements: dict[str, Any], field: str) -> float | None:
    v = measurements.get(field)
    if isinstance(v, dict) and isinstance(v.get("value"), (int, float)):
        return float(v["value"])
    if isinstance(v, (int, float)):
        return float(v)
    return None


def _get_prior_fields(state_dict: dict[str, Any]) -> list[str]:
    return [
        entry.get("field", "")
        for entry in state_dict.get("source_map") or []
        if isinstance(entry, dict) and entry.get("source") == "default_model_prior"
    ]


def _inputs_used(inp: EvaluatorInput) -> list[str]:
    used = ["cardiac_twin_state"] if inp.cardiac_state else []
    if inp.extraction:
        used.append("extraction_output")
    if inp.validation:
        used.append("validator_output")
    if inp.operation:
        used.append("hemodynamics_output")
    if inp.recovery:
        used.append("recovery_output")
    if inp.trace:
        used.append("agent_trace")
    if inp.generated_text:
        used.append("generated_text")
    return used or ["no_inputs"]


def _output_summary(
    scores: EvalScores,
    findings: list[CriticFinding],
    safe_to_display: bool,
) -> str:
    return (
        f"overall={scores.overall_score:.2f} "
        f"safety={scores.safety_compliance:.2f} "
        f"hallucination_risk={scores.hallucination_risk:.2f} "
        f"findings={len(findings)} "
        f"safe_to_display={safe_to_display}"
    )


def _clamp(value: float, min_val: float = 0.0, max_val: float = 1.0) -> float:
    return max(min_val, min(max_val, value))


def _dedupe_local(values: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for v in values:
        if v not in seen:
            out.append(v)
            seen.add(v)
    return out


_utc_now = utc_now
