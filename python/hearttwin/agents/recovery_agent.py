"""Agent 7: Recovery Orchestration Agent (production-grade).

Generates bounded simulated recovery trajectories for cardiac digital twin cases.

Purpose:
- Produces 2–4 model scenarios with deterministic time-series.
- Never recommends treatment, prescribes, diagnoses, or mentions medication.
- Uses OPENAI_MODEL_RECOVERY to propose bounded scenario parameter sets;
  deterministic Python tools create the actual numeric trajectories.
- Redis agentic memory informs scenario selection; safe summaries are stored back.
- Every output carries a clear non-medical simulation label.

Unique orchestration logic:
1.  Read canonical cardiac state + operation output.
2.  Retrieve Redis agentic memory (critic, instability, safe templates, harness fixes).
3.  Generate 2–4 bounded scenario configs (LLM-proposed or deterministic templates).
4.  Validate and clamp all scenario configs (forbidden content + parameter bounds).
5.  Call deterministic recovery simulation tool for each config.
6.  Compare scenario tradeoffs.
7.  Build uncertainty bands (already in simulation output).
8.  Produce non-medical comparison summary.
9.  Store safe scenario history and instability patterns to Redis.
"""

from __future__ import annotations

import json
import os
import time
import uuid
from datetime import datetime, timezone
from typing import Any, Literal

from pydantic import BaseModel, Field

from python.hearttwin.schemas import (
    AgentResponse,
    AgentStatus,
    AgentStageResult,
    CardiacTwinState,
    RecoveryConfig,
)
from python.hearttwin.safety import CORE_SAFETY_PHRASE
from python.hearttwin.tools.env_config import redis_memory_enabled
from python.hearttwin.tools.model_config import get_recovery_model
from python.hearttwin.tools.recovery_sim import (
    RecoveryScenarioResult,
    build_default_scenarios,
    simulate_recovery,
)
from python.hearttwin.tools.weave_trace import TraceContext

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_AGENT_ID = "recovery_orchestration"
_AGENT_NAME = "Recovery Orchestration Agent"

SIMULATION_LABEL = "bounded educational simulation, not a treatment recommendation"

_SIMULATION_DISCLAIMER = (
    f"{CORE_SAFETY_PHRASE} Recovery trajectories are bounded model scenarios. "
    "This is a simulated recovery trajectory — not a clinical recommendation."
)

# Any of these in LLM output or config strings invalidate or sanitize the entry.
_FORBIDDEN_TERMS: frozenset[str] = frozenset({
    "medication", "medications", "drug", "drugs",
    "dose", "dosage", "mg", "mcg", "mg/kg",
    "tablet", "pill", "prescribe", "prescription",
    "recommended therapy", "clinical recommendation",
    "treatment plan", "treat the patient",
    "healed", "cured", "the patient will recover",
    "administer", "infuse", "inject",
})

_VALID_SCENARIO_TYPES: frozenset[str] = frozenset({
    "load_reduction",
    "oxygen_delivery_improvement",
    "contractility_support",
    "conditioning",
    "stability_monitoring",
    "custom",
})

# Redis memory keys
_REDIS_KEY_CRITIC_PATTERNS = "hearttwin:memory:critic_patterns"
_REDIS_KEY_INSTABILITY_PATTERNS = "hearttwin:memory:recovery_instability_patterns"
_REDIS_KEY_SAFE_TEMPLATES = "hearttwin:memory:safe_scenario_templates"
_REDIS_KEY_HARNESS_FIXES = "hearttwin:memory:successful_harness_fixes"
_REDIS_KEY_CASE_RECOVERY = "hearttwin:case:{case_id}:recovery"


# ---------------------------------------------------------------------------
# Schema-bound I/O contracts (internal to this agent)
# ---------------------------------------------------------------------------


class RecoveryInput(BaseModel):
    """Input contract for the Recovery Orchestration Agent."""

    case_id: str
    cardiac_state: CardiacTwinState
    operation: dict[str, Any]
    recovery_config: dict[str, Any]
    memory_context: dict[str, Any] | None = None


class RecoveryScenario(BaseModel):
    """Columnar representation of one simulated recovery trajectory."""

    scenario_id: str
    scenario_name: str
    scenario_type: str
    days: list[int]
    ef_pct: list[float | None]
    cardiac_output_l_min: list[float | None]
    contractility_index: list[float]
    afterload_index: list[float]
    oxygen_delivery_index: list[float]
    inflammation_index: list[float]
    uncertainty_lower: list[float]
    uncertainty_upper: list[float]
    warnings: list[str]
    tradeoffs: list[str]
    simulation_label: str


class RecoveryOutput(BaseModel):
    """Validated output of the Recovery Orchestration Agent."""

    scenarios: list[RecoveryScenario]
    comparison_summary: dict[str, Any]
    selected_default_scenario_id: str | None
    warnings: list[str]
    confidence: float = Field(ge=0.0, le=1.0)


# ---------------------------------------------------------------------------
# Redis helpers (env-gated, never raise)
# ---------------------------------------------------------------------------


def _redis_config() -> tuple[str, str] | None:
    if not redis_memory_enabled():
        return None
    url = os.environ.get("UPSTASH_REDIS_REST_URL", "")
    token = os.environ.get("UPSTASH_REDIS_REST_TOKEN", "")
    return (url, token) if (url and token) else None


async def _redis_get(key: str) -> Any | None:
    """Read a Redis key as JSON. Returns None on any error or missing key."""
    config = _redis_config()
    if config is None:
        return None
    url, token = config
    try:
        import httpx

        resp = await httpx.AsyncClient().get(
            f"{url}/get/{key}",
            headers={"Authorization": f"Bearer {token}"},
            timeout=5.0,
        )
        result = resp.json().get("result")
        if result:
            return json.loads(result)
    except Exception:
        pass
    return None


async def _redis_set(key: str, value: Any) -> bool:
    """Write a value to Redis as a JSON string. Returns True on success."""
    config = _redis_config()
    if config is None:
        return False
    url, token = config
    try:
        import httpx

        await httpx.AsyncClient().post(
            f"{url}/set/{key}",
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "text/plain",
            },
            content=json.dumps(value),
            timeout=5.0,
        )
        return True
    except Exception:
        return False


# ---------------------------------------------------------------------------
# State extraction
# ---------------------------------------------------------------------------


def _state_to_recovery_params(state: CardiacTwinState) -> dict[str, float]:
    """Extract numeric parameters needed for recovery simulation from state."""

    def get_val(mv: Any, fallback: float) -> float:
        return mv.value if mv is not None else fallback

    meas = state.measurements
    ts = state.tissue_state
    hd = state.hemodynamics
    ep = state.electrophysiology

    return {
        "edv_ml": get_val(meas.edv_ml, 130.0),
        "esv_ml": get_val(meas.esv_ml, 50.0),
        "heart_rate_bpm": get_val(meas.heart_rate_bpm, 70.0),
        "contractility_index": get_val(hd.contractility_index, 0.65),
        "afterload_index": get_val(hd.afterload_index, 0.5),
        "preload_index": get_val(hd.preload_index, 0.55),
        "inflammation_index": get_val(ts.inflammation_index, 0.1),
        "oxygen_delivery_index": get_val(ts.oxygen_delivery_index, 0.85),
        "stiffness_index": get_val(ts.stiffness_index, 0.3),
        "scar_fraction": get_val(ts.scar_fraction, 0.0),
        "arrhythmia_instability_score": get_val(ep.arrhythmia_instability_score, 0.1),
    }


# ---------------------------------------------------------------------------
# LLM scenario config proposal
# ---------------------------------------------------------------------------


async def _llm_propose_scenario_configs(
    state_params: dict[str, float],
    horizon: int,
    memory_context: dict[str, Any] | None,
    model: str,
) -> tuple[list[dict[str, Any]], str | None]:
    """Ask OpenAI to propose 2–4 bounded recovery scenario parameter sets.

    Returns (configs, model_name) on success or ([], None) on any failure so the
    caller degrades gracefully to deterministic templates.  The LLM may only
    propose scenario parameters — it never computes the numeric trajectory.
    """
    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        return [], None

    memory_hint = ""
    if memory_context:
        instability = memory_context.get("instability_patterns") or []
        safe = memory_context.get("safe_templates") or []
        if isinstance(instability, dict):
            instability = instability.get("warnings", [])
        if isinstance(safe, dict):
            safe = [safe.get("scenario_types", [])]
        if instability:
            memory_hint += f"\nKnown instability patterns to avoid: {instability[:2]}"
        if safe:
            memory_hint += f"\nPreviously stable scenario types: {safe[:2]}"

    system_prompt = (
        "You are a cardiac simulation parameter planner for HeartTwin Lab. "
        "Your ONLY job is to propose bounded parameter sets for deterministic "
        "recovery simulation scenarios. "
        "NEVER recommend treatment, prescribe anything, diagnose, suggest clinical "
        "actions, mention medication names, dosages, or treatment plans. "
        "Never use the words: healed, cured, treatment, prescribe, medication, drug. "
        f"Valid scenario types: {sorted(_VALID_SCENARIO_TYPES)}. "
        "All per-day delta values must have absolute value ≤ 0.02. "
        "max_safe_parameter_shift must be ≤ 0.30. "
        "Return ONLY a JSON array — no prose, no markdown fences."
    )

    user_prompt = (
        f"Cardiac state parameters:\n{json.dumps(state_params, indent=2)}\n"
        f"Recovery horizon: {horizon} days\n"
        f"{memory_hint}\n\n"
        "Propose exactly 3 distinct bounded recovery simulation scenario "
        "configurations as a JSON array. Each object must include:\n"
        "  scenario_type, scenario_name,\n"
        "  contractility_delta_per_day, afterload_delta_per_day,\n"
        "  preload_delta_per_day, inflammation_decay_rate,\n"
        "  oxygen_delivery_delta_per_day, stiffness_delta_per_day,\n"
        "  scar_remodeling_rate, heart_rate_adaptation_rate,\n"
        "  arrhythmia_stability_delta, max_safe_parameter_shift,\n"
        "  uncertainty_penalty_weight.\n"
        "Return ONLY the JSON array."
    )

    try:
        import openai

        client = openai.AsyncOpenAI(api_key=api_key)
        response = await client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            temperature=0.2,
            max_tokens=1800,
        )
        content = (response.choices[0].message.content or "").strip()

        # Strip markdown fences if present
        if content.startswith("```"):
            lines = content.splitlines()
            content = "\n".join(
                line for line in lines if not line.startswith("```")
            )

        parsed = json.loads(content)

        # Handle both bare list and wrapped dict
        if isinstance(parsed, list):
            configs = parsed
        elif isinstance(parsed, dict):
            for key in ("scenarios", "configs", "parameter_sets", "results"):
                if key in parsed and isinstance(parsed[key], list):
                    configs = parsed[key]
                    break
            else:
                configs = [parsed]
        else:
            return [], model

        return [c for c in configs if isinstance(c, dict)], model

    except Exception:
        return [], None


# ---------------------------------------------------------------------------
# Config validation
# ---------------------------------------------------------------------------


def _validate_scenario_config(
    cfg: dict[str, Any],
    horizon: int,
) -> tuple[dict[str, Any], list[str]]:
    """Sanitize and validate a scenario config (from LLM or API input).

    Clamps all delta values within physiological bounds, rejects forbidden
    content, and ensures scenario_type is valid.  Returns (sanitized, warnings).
    """
    warnings: list[str] = []

    # Check for forbidden medical content in string fields
    for str_key in ("scenario_type", "scenario_name", "description"):
        raw_str = str(cfg.get(str_key, "")).lower()
        for term in _FORBIDDEN_TERMS:
            if term in raw_str:
                warnings.append(
                    f"Forbidden term '{term}' in LLM config field '{str_key}' — sanitized"
                )
                cfg[str_key] = "custom_scenario"
                break

    scenario_type = str(cfg.get("scenario_type", "custom")).strip()
    if scenario_type not in _VALID_SCENARIO_TYPES:
        warnings.append(f"Unknown scenario_type '{scenario_type}' → 'custom'")
        scenario_type = "custom"

    max_shift = min(float(cfg.get("max_safe_parameter_shift", 0.20)), 0.30)
    uncertainty_weight = min(0.5, max(0.05, float(cfg.get("uncertainty_penalty_weight", 0.2))))

    delta_keys = [
        "contractility_delta_per_day",
        "afterload_delta_per_day",
        "preload_delta_per_day",
        "oxygen_delivery_delta_per_day",
        "stiffness_delta_per_day",
    ]
    rate_keys = [
        ("inflammation_decay_rate", 0.0, 0.15),
        ("scar_remodeling_rate", 0.0, 0.05),
        ("heart_rate_adaptation_rate", 0.0, 0.10),
        ("arrhythmia_stability_delta", 0.0, 0.10),
    ]

    sanitized: dict[str, Any] = {
        "scenario_type": scenario_type,
        "max_safe_parameter_shift": round(max_shift, 4),
        "uncertainty_penalty_weight": round(uncertainty_weight, 4),
    }

    for k in delta_keys:
        raw = float(cfg.get(k, 0.0))
        clamped = max(-max_shift, min(max_shift, raw))
        if abs(raw - clamped) > 1e-8:
            warnings.append(f"Clamped {k}: {raw:.4f} → {clamped:.4f}")
        sanitized[k] = round(clamped, 6)

    for k, lo, hi in rate_keys:
        raw = float(cfg.get(k, 0.01))
        clamped = max(lo, min(hi, raw))
        sanitized[k] = round(clamped, 6)

    return sanitized, warnings


def _scenario_result_to_config(result: RecoveryScenarioResult) -> dict[str, Any]:
    """Extract a config dict from a pre-built RecoveryScenarioResult (for fallback)."""
    return {
        "scenario_type": result.scenario_type,
        "contractility_delta_per_day": 0.005,
        "afterload_delta_per_day": -0.005,
        "preload_delta_per_day": -0.003,
        "inflammation_decay_rate": 0.025,
        "oxygen_delivery_delta_per_day": 0.003,
        "stiffness_delta_per_day": -0.002,
        "scar_remodeling_rate": 0.001,
        "heart_rate_adaptation_rate": 0.002,
        "arrhythmia_stability_delta": 0.004,
        "max_safe_parameter_shift": 0.20,
        "uncertainty_penalty_weight": 0.2,
    }


# ---------------------------------------------------------------------------
# Confidence scoring
# ---------------------------------------------------------------------------


def _compute_confidence(
    state: CardiacTwinState,
    scenarios: list[RecoveryScenarioResult],
    warnings: list[str],
    priors_used: int,
    model_used: str | None,
) -> float:
    """Compute confidence score from operation quality, uncertainty, and warnings.

    Factors:
    - data_quality_score: primary driver
    - priors_used: penalised when many fields came from default model priors
    - warnings: each warning reduces confidence slightly
    - uncertainty band width: wider bands reduce confidence
    - scenario count: more scenarios = slightly higher confidence
    - model_used: deterministic fallback incurs a small penalty
    """
    score = state.data_quality_score * 0.5 + 0.40  # maps [0,1] → [0.40, 0.90]

    # Penalise for prior-filled fields
    if priors_used > 0:
        score -= min(0.15, priors_used * 0.015)

    # Penalise for accumulated warnings
    if warnings:
        score -= min(0.15, len(warnings) * 0.025)

    # Penalise for wide uncertainty bands
    total_width, count = 0.0, 0
    for s in scenarios:
        for d in s.trajectory:
            width = d.uncertainty_high - d.uncertainty_low
            total_width += width
            count += 1
    if count > 0:
        avg_width = total_width / count
        if avg_width > 1.0:
            score -= min(0.10, (avg_width - 1.0) * 0.04)

    # Bonus for comparing multiple scenarios
    if len(scenarios) >= 3:
        score += 0.04
    elif len(scenarios) >= 2:
        score += 0.02

    # Small penalty if no LLM was available (pure deterministic fallback)
    if model_used is None:
        score -= 0.04

    return round(max(0.0, min(1.0, score)), 4)


# ---------------------------------------------------------------------------
# Tradeoff analysis
# ---------------------------------------------------------------------------


def _compute_scenario_tradeoffs(
    scenarios: list[RecoveryScenarioResult],
    scenario_ids: list[str],
) -> dict[str, list[str]]:
    """Return per-scenario-id tradeoff strings comparing all scenarios."""
    if len(scenarios) < 2:
        return {sid: ["Single scenario — no cross-scenario comparison available"]
                for sid in scenario_ids}

    tradeoff_rows = []
    for result, sid in zip(scenarios, scenario_ids):
        sm = result.summary_metrics
        tradeoff_rows.append({
            "sid": sid,
            "label": result.scenario_label,
            "ef_delta": sm.get("ef_delta_pct", 0.0),
            "co_delta": sm.get("co_delta_l_min", 0.0),
            "final_inflammation": sm.get("final_inflammation_index", 0.0),
            "final_arrhythmia": sm.get("final_arrhythmia_instability", 0.0),
        })

    best_ef = max(tradeoff_rows, key=lambda r: r["ef_delta"])
    best_co = max(tradeoff_rows, key=lambda r: r["co_delta"])
    least_inflam = min(tradeoff_rows, key=lambda r: r["final_inflammation"])
    least_arr = min(tradeoff_rows, key=lambda r: r["final_arrhythmia"])

    result_map: dict[str, list[str]] = {}
    for row in tradeoff_rows:
        trades: list[str] = []
        if row["sid"] == best_ef["sid"]:
            trades.append(f"Highest simulated EF gain ({row['ef_delta']:+.1f}%)")
        if row["sid"] == best_co["sid"]:
            trades.append(f"Highest simulated CO improvement ({row['co_delta']:+.3f} L/min)")
        if row["sid"] == least_inflam["sid"]:
            trades.append(
                f"Lowest simulated final inflammation index ({row['final_inflammation']:.3f})"
            )
        if row["sid"] == least_arr["sid"]:
            trades.append(
                f"Most simulated arrhythmia stabilisation ({row['final_arrhythmia']:.3f})"
            )
        if not trades:
            trades.append("Balanced simulated trajectory — no single-metric advantage")
        result_map[row["sid"]] = trades

    return result_map


def _compute_tradeoffs(scenarios: list[RecoveryScenarioResult]) -> list[dict[str, Any]]:
    """Backward-compatible tradeoff summary for AgentResponse.outputs."""
    tradeoffs: list[dict[str, Any]] = []
    for s in scenarios:
        sm = s.summary_metrics
        tradeoffs.append({
            "scenario": s.scenario_label,
            "scenario_type": s.scenario_type,
            "ef_gain_pct": sm.get("ef_delta_pct", 0),
            "co_gain_l_min": sm.get("co_delta_l_min", 0),
            "final_inflammation": sm.get("final_inflammation_index", 0),
            "final_arrhythmia": sm.get("final_arrhythmia_instability", 0),
        })

    if len(tradeoffs) >= 2:
        best_ef = max(tradeoffs, key=lambda x: x["ef_gain_pct"])
        best_co = max(tradeoffs, key=lambda x: x["co_gain_l_min"])
        lowest_inflam = min(tradeoffs, key=lambda x: x["final_inflammation"])
        for t in tradeoffs:
            t["best_for_ef"] = t["scenario"] == best_ef["scenario"]
            t["best_for_co"] = t["scenario"] == best_co["scenario"]
            t["lowest_inflammation"] = t["scenario"] == lowest_inflam["scenario"]

    return tradeoffs


def _classify_uncertainty(scenarios: list[RecoveryScenarioResult]) -> str:
    """Classify the overall uncertainty status as 'narrow', 'moderate', or 'wide'."""
    if not scenarios:
        return "unknown"

    widths: list[float] = []
    for s in scenarios:
        for d in s.trajectory:
            widths.append(d.uncertainty_high - d.uncertainty_low)

    if not widths:
        return "unknown"

    avg = sum(widths) / len(widths)
    if avg < 0.4:
        return "narrow"
    if avg < 1.0:
        return "moderate"
    return "wide"


# ---------------------------------------------------------------------------
# Comparison summary (non-medical)
# ---------------------------------------------------------------------------


def _build_comparison_summary(
    scenarios: list[RecoveryScenarioResult],
    scenario_ids: list[str],
) -> dict[str, Any]:
    """Build a structured non-medical comparison across all simulated scenarios."""
    if not scenarios:
        return {"scenario_count": 0}

    rows = []
    for result, sid in zip(scenarios, scenario_ids):
        sm = result.summary_metrics
        rows.append({
            "scenario_id": sid,
            "scenario_type": result.scenario_type,
            "label": result.scenario_label,
            "initial_ef_pct": sm.get("initial_ef_pct"),
            "final_ef_pct": sm.get("final_ef_pct"),
            "ef_delta_pct": sm.get("ef_delta_pct"),
            "initial_co_l_min": sm.get("initial_co_l_min"),
            "final_co_l_min": sm.get("final_co_l_min"),
            "co_delta_l_min": sm.get("co_delta_l_min"),
            "final_inflammation_index": sm.get("final_inflammation_index"),
            "final_arrhythmia_instability": sm.get("final_arrhythmia_instability"),
            "horizon_days": sm.get("horizon_days"),
            "warning_count": len(result.warnings),
            "simulation_label": SIMULATION_LABEL,
        })

    ef_deltas = [r["ef_delta_pct"] for r in rows if r["ef_delta_pct"] is not None]
    co_deltas = [r["co_delta_l_min"] for r in rows if r["co_delta_l_min"] is not None]
    inflammations = [
        r["final_inflammation_index"]
        for r in rows
        if r["final_inflammation_index"] is not None
    ]

    return {
        "scenario_count": len(rows),
        "scenarios": rows,
        "ef_delta_range": {
            "min": round(min(ef_deltas), 2) if ef_deltas else None,
            "max": round(max(ef_deltas), 2) if ef_deltas else None,
        },
        "co_delta_range": {
            "min": round(min(co_deltas), 3) if co_deltas else None,
            "max": round(max(co_deltas), 3) if co_deltas else None,
        },
        "inflammation_range": {
            "min": round(min(inflammations), 4) if inflammations else None,
            "max": round(max(inflammations), 4) if inflammations else None,
        },
        "simulation_label": SIMULATION_LABEL,
    }


def _select_default_scenario(
    scenarios: list[RecoveryScenario],
    comparison_summary: dict[str, Any],
) -> str | None:
    """Select the scenario with the most balanced simulated trajectory."""
    if not scenarios:
        return None
    if len(scenarios) == 1:
        return scenarios[0].scenario_id

    rows = comparison_summary.get("scenarios", [])
    if not rows:
        return scenarios[0].scenario_id

    # Prefer the scenario with the best EF delta among those with < 2 warnings
    low_warn = [r for r in rows if r.get("warning_count", 99) < 2]
    candidates = low_warn if low_warn else rows

    best = max(candidates, key=lambda r: r.get("ef_delta_pct") or 0.0)
    return best["scenario_id"]


# ---------------------------------------------------------------------------
# Payload builders
# ---------------------------------------------------------------------------


def _scenario_to_recovery_scenario(
    result: RecoveryScenarioResult,
    scenario_id: str,
    tradeoffs: list[str],
) -> RecoveryScenario:
    """Convert a RecoveryScenarioResult to the RecoveryScenario Pydantic model."""
    trajectory = result.trajectory
    return RecoveryScenario(
        scenario_id=scenario_id,
        scenario_name=result.scenario_label,
        scenario_type=result.scenario_type,
        days=[d.day for d in trajectory],
        ef_pct=[d.ef_pct for d in trajectory],
        cardiac_output_l_min=[d.cardiac_output_l_min for d in trajectory],
        contractility_index=[d.contractility_index for d in trajectory],
        afterload_index=[d.afterload_index for d in trajectory],
        oxygen_delivery_index=[d.oxygen_delivery_index for d in trajectory],
        inflammation_index=[d.inflammation_index for d in trajectory],
        uncertainty_lower=[d.uncertainty_low for d in trajectory],
        uncertainty_upper=[d.uncertainty_high for d in trajectory],
        warnings=result.warnings,
        tradeoffs=tradeoffs,
        simulation_label=SIMULATION_LABEL,
    )


def _build_scenario_payloads(
    sim_results: list[RecoveryScenarioResult],
    recovery_scenarios: list[RecoveryScenario],
) -> list[dict[str, Any]]:
    """Build backward-compatible dict payloads for the orchestrator."""
    payloads: list[dict[str, Any]] = []
    for result, scenario in zip(sim_results, recovery_scenarios):
        trajectory_payload = [
            {
                "day": d.day,
                "ef_pct": d.ef_pct,
                "cardiac_output_l_min": d.cardiac_output_l_min,
                "stroke_volume_ml": d.stroke_volume_ml,
                "heart_rate_bpm": d.heart_rate_bpm,
                "contractility_index": d.contractility_index,
                "inflammation_index": d.inflammation_index,
                "oxygen_delivery_index": d.oxygen_delivery_index,
                "uncertainty_low": d.uncertainty_low,
                "uncertainty_high": d.uncertainty_high,
            }
            for d in result.trajectory
        ]
        payloads.append({
            "scenario_id": scenario.scenario_id,
            "scenario_type": result.scenario_type,
            "scenario_label": result.scenario_label,
            "summary_metrics": result.summary_metrics,
            "trajectory": trajectory_payload,
            "warnings": result.warnings,
            "tradeoffs": scenario.tradeoffs,
            "simulation_disclaimer": _SIMULATION_DISCLAIMER,
            "simulation_label": SIMULATION_LABEL,
            "simulation_note": result.simulation_note,
        })
    return payloads


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------


async def run_recovery_agent(
    state: CardiacTwinState,
    recovery_configs: list[RecoveryConfig] | None,
    case_id: str,
) -> tuple[AgentResponse, list[dict[str, Any]]]:
    """Generate bounded recovery scenarios from cardiac twin state.

    Unique orchestration steps:
    1.  Read canonical state + operation output.
    2.  Retrieve Redis agentic memory (4 keys).
    3.  Generate 2–4 bounded scenario configs via LLM or deterministic templates.
    4.  Validate and clamp all configs (forbidden content + parameter bounds).
    5.  Call deterministic simulation tool for each config.
    6.  Compare scenario tradeoffs.
    7.  Uncertainty bands come from deterministic simulation.
    8.  Build non-medical comparison summary.
    9.  Store safe scenario history and instability patterns to Redis.
    """
    tracer = TraceContext(case_id=case_id, agent_name=_AGENT_ID)
    t0 = time.time()
    started_at = datetime.now(timezone.utc).isoformat()
    all_warnings: list[str] = []
    tools_called: list[str] = []
    memory_patterns_used: list[str] = []
    deterministic_tool_calls = 0
    model_used: str | None = None

    model_name = get_recovery_model()
    base_params = _state_to_recovery_params(state)
    sim_config = state.simulation_config
    horizon = sim_config.recovery.recovery_horizon_days
    seed = sim_config.random_seed

    priors_used = sum(
        1 for entry in state.source_map
        if entry.source.value == "default_model_prior"
    )

    # ---- Step 2: Retrieve Redis agentic memory ----
    t_mem = time.time()
    critic_patterns = await _redis_get(_REDIS_KEY_CRITIC_PATTERNS)
    instability_patterns = await _redis_get(_REDIS_KEY_INSTABILITY_PATTERNS)
    safe_templates = await _redis_get(_REDIS_KEY_SAFE_TEMPLATES)
    harness_fixes = await _redis_get(_REDIS_KEY_HARNESS_FIXES)

    memory_context: dict[str, Any] = {}
    if critic_patterns:
        memory_context["critic_patterns"] = critic_patterns
        memory_patterns_used.append("critic_patterns")
    if instability_patterns:
        memory_context["instability_patterns"] = instability_patterns
        memory_patterns_used.append("recovery_instability_patterns")
    if safe_templates:
        memory_context["safe_templates"] = safe_templates
        memory_patterns_used.append("safe_scenario_templates")
    if harness_fixes:
        memory_context["harness_fixes"] = harness_fixes
        memory_patterns_used.append("successful_harness_fixes")

    tracer.record_tool(
        "hearttwin.redis_memory_read",
        inputs={
            "keys": [
                _REDIS_KEY_CRITIC_PATTERNS,
                _REDIS_KEY_INSTABILITY_PATTERNS,
                _REDIS_KEY_SAFE_TEMPLATES,
                _REDIS_KEY_HARNESS_FIXES,
            ]
        },
        outputs={
            "patterns_found": memory_patterns_used,
            "memory_context_keys": list(memory_context.keys()),
            "redis_available": _redis_config() is not None,
        },
        duration_ms=(time.time() - t_mem) * 1000,
    )
    tools_called.append("hearttwin.redis_memory_read")

    # ---- Steps 3–4: Generate and validate scenario configs ----
    validated_configs: list[dict[str, Any]] = []

    if recovery_configs:
        # Use caller-provided configs (from API request); still validate/clamp them.
        for cfg in recovery_configs[:4]:
            cfg_dict: dict[str, Any] = {
                "scenario_type": cfg.scenario_type.value,
                "contractility_delta_per_day": cfg.contractility_delta_per_day,
                "afterload_delta_per_day": cfg.afterload_delta_per_day,
                "preload_delta_per_day": cfg.preload_delta_per_day,
                "inflammation_decay_rate": cfg.inflammation_decay_rate,
                "oxygen_delivery_delta_per_day": cfg.oxygen_delivery_delta_per_day,
                "stiffness_delta_per_day": cfg.stiffness_delta_per_day,
                "scar_remodeling_rate": cfg.scar_remodeling_rate,
                "heart_rate_adaptation_rate": cfg.heart_rate_adaptation_rate,
                "arrhythmia_stability_delta": cfg.arrhythmia_stability_delta,
                "max_safe_parameter_shift": cfg.max_safe_parameter_shift,
                "uncertainty_penalty_weight": cfg.uncertainty_penalty_weight,
            }
            sanitized, cfg_warnings = _validate_scenario_config(cfg_dict, horizon)
            all_warnings.extend(cfg_warnings)
            validated_configs.append(sanitized)
    else:
        # Try OpenAI first to propose bounded scenario configs.
        t_llm = time.time()
        llm_configs, model_used = await _llm_propose_scenario_configs(
            state_params=base_params,
            horizon=horizon,
            memory_context=memory_context or None,
            model=model_name,
        )

        tracer.record_tool(
            "hearttwin.simulate_recovery",
            inputs={
                "model": model_name,
                "state_params_summary": {k: round(v, 3) for k, v in base_params.items()},
                "horizon_days": horizon,
                "memory_context_keys": list(memory_context.keys()),
            },
            outputs={
                "llm_configs_proposed": len(llm_configs),
                "model_used": model_used,
                "llm_available": model_used is not None,
            },
            duration_ms=(time.time() - t_llm) * 1000,
        )
        tools_called.append("hearttwin.simulate_recovery")

        for cfg in llm_configs[:4]:
            sanitized, cfg_warnings = _validate_scenario_config(cfg, horizon)
            all_warnings.extend(cfg_warnings)
            validated_configs.append(sanitized)

        # Fill to ≥ 2 configs using deterministic templates if LLM gave too few.
        if len(validated_configs) < 2:
            if model_used is not None:
                all_warnings.append(
                    "LLM returned fewer than 2 valid configs — supplementing with "
                    "deterministic scenario templates"
                )
            default_results = build_default_scenarios(
                state_params=base_params,
                recovery_horizon_days=horizon,
                random_seed=seed,
            )
            existing_types = {c.get("scenario_type") for c in validated_configs}
            for default_result in default_results:
                if default_result.scenario_type not in existing_types:
                    validated_configs.append(_scenario_result_to_config(default_result))
                    existing_types.add(default_result.scenario_type)
                if len(validated_configs) >= 4:
                    break

    # ---- Step 5: Call deterministic recovery simulation tool ----
    t_sim = time.time()
    sim_results: list[RecoveryScenarioResult] = []

    for i, cfg in enumerate(validated_configs):
        try:
            result = simulate_recovery(
                **base_params,
                recovery_horizon_days=horizon,
                random_seed=seed + i,
                scenario_type=cfg.get("scenario_type", "custom"),
                contractility_delta_per_day=float(cfg.get("contractility_delta_per_day", 0.003)),
                afterload_delta_per_day=float(cfg.get("afterload_delta_per_day", -0.005)),
                preload_delta_per_day=float(cfg.get("preload_delta_per_day", -0.003)),
                inflammation_decay_rate=float(cfg.get("inflammation_decay_rate", 0.025)),
                oxygen_delivery_delta_per_day=float(cfg.get("oxygen_delivery_delta_per_day", 0.003)),
                stiffness_delta_per_day=float(cfg.get("stiffness_delta_per_day", -0.002)),
                scar_remodeling_rate=float(cfg.get("scar_remodeling_rate", 0.001)),
                heart_rate_adaptation_rate=float(cfg.get("heart_rate_adaptation_rate", 0.002)),
                arrhythmia_stability_delta=float(cfg.get("arrhythmia_stability_delta", 0.004)),
                max_safe_parameter_shift=float(cfg.get("max_safe_parameter_shift", 0.20)),
                uncertainty_penalty_weight=float(cfg.get("uncertainty_penalty_weight", 0.2)),
            )
            sim_results.append(result)
            all_warnings.extend(result.warnings)
            deterministic_tool_calls += 1
        except Exception as exc:
            all_warnings.append(f"Scenario {i} simulation error: {exc}")

    tracer.record_tool(
        "hearttwin.simulate_recovery_scenarios",
        inputs={
            "scenario_count": len(validated_configs),
            "horizon_days": horizon,
            "scenario_types": [c.get("scenario_type") for c in validated_configs],
            "seed_base": seed,
        },
        outputs={
            "simulated_count": len(sim_results),
            "deterministic_tool_calls": deterministic_tool_calls,
            "total_warnings": len(all_warnings),
        },
        duration_ms=(time.time() - t_sim) * 1000,
    )
    tools_called.append("hearttwin.simulate_recovery_scenarios")

    # Ultimate fallback: if all simulation attempts failed, use prebuilt defaults.
    if not sim_results:
        all_warnings.append(
            "All simulation attempts failed — falling back to default scenarios"
        )
        sim_results = build_default_scenarios(
            state_params=base_params,
            recovery_horizon_days=horizon,
            random_seed=seed,
        )[:2]
        deterministic_tool_calls = len(sim_results)

    # ---- Steps 6–7: Tradeoffs and RecoveryScenario objects ----
    scenario_ids = [str(uuid.uuid4())[:8] for _ in sim_results]
    tradeoff_map = _compute_scenario_tradeoffs(sim_results, scenario_ids)

    recovery_scenarios: list[RecoveryScenario] = []
    for result, sid in zip(sim_results, scenario_ids):
        rs = _scenario_to_recovery_scenario(result, sid, tradeoff_map.get(sid, []))
        recovery_scenarios.append(rs)

    uncertainty_status = _classify_uncertainty(sim_results)

    # ---- Step 8: Non-medical comparison summary ----
    comparison_summary = _build_comparison_summary(sim_results, scenario_ids)
    selected_id = _select_default_scenario(recovery_scenarios, comparison_summary)

    confidence = _compute_confidence(
        state, sim_results, all_warnings, priors_used, model_used
    )

    recovery_output = RecoveryOutput(
        scenarios=recovery_scenarios,
        comparison_summary=comparison_summary,
        selected_default_scenario_id=selected_id,
        warnings=all_warnings,
        confidence=confidence,
    )

    # ---- Step 9: Store safe scenario history to Redis ----
    t_write = time.time()
    case_key = _REDIS_KEY_CASE_RECOVERY.format(case_id=case_id)
    redis_write_keys: list[str] = []

    case_recovery_summary: dict[str, Any] = {
        "case_id": case_id,
        "scenario_count": len(recovery_scenarios),
        "scenario_types": [s.scenario_type for s in recovery_scenarios],
        "horizon_days": horizon,
        "confidence": confidence,
        "uncertainty_status": uncertainty_status,
        "warnings_count": len(all_warnings),
        "simulation_label": SIMULATION_LABEL,
        "timestamp": started_at,
    }
    case_written = await _redis_set(case_key, case_recovery_summary)
    if case_written:
        redis_write_keys.append(case_key)

    # Store safe templates when scenarios ran without physiological errors.
    esv_errors = [w for w in all_warnings if "ESV" in w and "EDV" in w]
    if not esv_errors and len(sim_results) >= 2:
        safe_entry: dict[str, Any] = {
            "scenario_types": [s.scenario_type for s in recovery_scenarios],
            "horizon_days": horizon,
            "confidence": confidence,
            "stability": uncertainty_status,
            "timestamp": started_at,
        }
        safe_written = await _redis_set(_REDIS_KEY_SAFE_TEMPLATES, safe_entry)
        if safe_written:
            redis_write_keys.append(_REDIS_KEY_SAFE_TEMPLATES)

    # Store instability patterns when physiological clamping was triggered.
    clamp_warnings = [
        w for w in all_warnings
        if "clamped" in w.lower() or ("ESV" in w and "EDV" in w)
    ]
    if clamp_warnings:
        instability_entry: dict[str, Any] = {
            "warnings": clamp_warnings[:5],
            "state_params_summary": {
                k: round(v, 3) for k, v in list(base_params.items())[:4]
            },
            "timestamp": started_at,
        }
        instab_written = await _redis_set(_REDIS_KEY_INSTABILITY_PATTERNS, instability_entry)
        if instab_written:
            redis_write_keys.append(_REDIS_KEY_INSTABILITY_PATTERNS)

    tracer.record_tool(
        "hearttwin.redis_memory_write",
        inputs={"keys": redis_write_keys},
        outputs={
            "keys_written": len(redis_write_keys),
            "case_key": case_key,
            "safe_templates_stored": _REDIS_KEY_SAFE_TEMPLATES in redis_write_keys,
            "instability_stored": _REDIS_KEY_INSTABILITY_PATTERNS in redis_write_keys,
        },
        duration_ms=(time.time() - t_write) * 1000,
    )
    tools_called.append("hearttwin.redis_memory_write")

    finished_at = datetime.now(timezone.utc).isoformat()
    latency_ms = round((time.time() - t0) * 1000, 1)

    stage_result = AgentStageResult(
        agent_id=_AGENT_ID,
        agent_name=_AGENT_NAME,
        model_used=model_used,
        status="warning" if all_warnings else "success",
        started_at=started_at,
        finished_at=finished_at,
        latency_ms=latency_ms,
        inputs_used=["cardiac_twin_state", "recovery_config", "redis_memory"],
        tools_called=tools_called,
        output_summary=(
            f"{len(recovery_scenarios)} bounded simulation scenarios generated "
            f"over {horizon} days. "
            f"Types: {[s.scenario_type for s in recovery_scenarios]}. "
            f"{SIMULATION_LABEL}."
        ),
        structured_output=recovery_output.model_dump(),
        warnings=all_warnings,
        confidence=confidence,
        scenario_count=len(recovery_scenarios),
        scenario_types=[s.scenario_type for s in recovery_scenarios],
        deterministic_tool_calls=deterministic_tool_calls,
        memory_patterns_used=memory_patterns_used,
        uncertainty_status=uncertainty_status,
        weave_call_id=tracer.trace_id,
        local_trace_id=tracer.trace_id,
    )

    scenario_payloads = _build_scenario_payloads(sim_results, recovery_scenarios)

    return AgentResponse(
        agent=_AGENT_ID,
        status=AgentStatus.SUCCESS if not all_warnings else AgentStatus.WARNING,
        inputs_used=["cardiac_twin_state", "recovery_config"],
        outputs={
            "agent_stage_result": stage_result.model_dump(),
            "scenario_count": len(recovery_scenarios),
            "scenario_types": [s.scenario_type for s in recovery_scenarios],
            "tradeoffs": _compute_tradeoffs(sim_results),
            "simulation_disclaimer": _SIMULATION_DISCLAIMER,
            "simulation_label": SIMULATION_LABEL,
            "model_used": model_used,
            "memory_patterns_used": memory_patterns_used,
            "uncertainty_status": uncertainty_status,
            "deterministic_tool_calls": deterministic_tool_calls,
            "confidence": confidence,
        },
        warnings=all_warnings,
        confidence=confidence,
        trace=tracer.steps,
    ), scenario_payloads
