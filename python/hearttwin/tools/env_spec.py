"""Canonical specification of HeartTwin Lab environment variables.

Single source of truth shared by:
  * scripts/verify_env.py (CLI validator)
  * python/hearttwin/tests/test_env_config.py (test suite)

Each entry declares the variable name, category, whether it is required for a
production deployment, whether it is a secret (must never be exposed), an
optional default, and a short description. Optional integrations degrade to
local/deterministic fallbacks, so very few vars are strictly required.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Callable, Optional


@dataclass(frozen=True)
class EnvVarSpec:
    name: str
    category: str
    required_for_production: bool = False
    secret: bool = False
    default: Optional[str] = None
    description: str = ""
    # Optional validator returning an error string, or None when valid.
    validator: Optional[Callable[[str], Optional[str]]] = field(default=None, compare=False)


def _is_numeric(value: str) -> Optional[str]:
    try:
        float(value)
        return None
    except (TypeError, ValueError):
        return f"expected a numeric value, got {value!r}"


def _is_bool(value: str) -> Optional[str]:
    if value.strip().lower() in {
        "1", "true", "yes", "on", "enabled",
        "0", "false", "no", "off", "disabled",
    }:
        return None
    return f"expected a boolean-like value, got {value!r}"


# Canonical env var specification.
ENV_SPEC: list[EnvVarSpec] = [
    # --- OpenAI ---
    EnvVarSpec("OPENAI_API_KEY", "openai", required_for_production=False, secret=True,
               description="OpenAI API key; missing → deterministic fallbacks."),
    EnvVarSpec("OPENAI_MODEL_INTAKE", "openai", default="gpt-5.4-mini",
               description="Model for the Intake & Safety agent."),
    EnvVarSpec("OPENAI_MODEL_EXTRACTION", "openai", default="gpt-5.4-mini",
               description="Model for the Multimodal Extraction agent."),
    EnvVarSpec("OPENAI_MODEL_VALIDATOR", "openai", default="gpt-5.4-mini",
               description="Model for the Evidence Validator agent."),
    EnvVarSpec("OPENAI_MODEL_STATE_BUILDER", "openai", default="gpt-5.5",
               description="Model for the Cardiac State Builder agent."),
    EnvVarSpec("OPENAI_MODEL_ELECTROPHYSIOLOGY", "openai", default="gpt-5.4-mini",
               description="Model for the Electrophysiology agent."),
    EnvVarSpec("OPENAI_MODEL_HEMODYNAMICS", "openai", default="gpt-5.4-mini",
               description="Model for the Hemodynamics Simulation agent."),
    EnvVarSpec("OPENAI_MODEL_RECOVERY", "openai", default="gpt-5.5",
               description="Model for the Recovery Orchestration agent."),
    EnvVarSpec("OPENAI_MODEL_EVALUATOR", "openai", default="gpt-5.5",
               description="Model for the Evaluator & Critic agent."),
    EnvVarSpec("OPENAI_MODEL_FAST", "openai", default="gpt-5.4-nano",
               description="Fast/utility model for cheap tasks."),
    EnvVarSpec("OPENAI_EMBEDDING_MODEL", "openai", default="text-embedding-3-small",
               description="Embedding model for case memory vectors."),
    # --- W&B / Weave ---
    EnvVarSpec("WANDB_API_KEY", "weave", secret=True,
               description="W&B key; missing → local trace fallback."),
    EnvVarSpec("WANDB_ENTITY", "weave",
               description="W&B entity (optional)."),
    EnvVarSpec("WANDB_PROJECT", "weave", default="hearttwin-weavehacks",
               description="W&B project; should be hearttwin-weavehacks."),
    EnvVarSpec("NEXT_PUBLIC_WEAVE_PROJECT_URL", "weave",
               description="Public Weave project URL (safe to expose)."),
    # --- Storage ---
    EnvVarSpec("BLOB_READ_WRITE_TOKEN", "storage", secret=True,
               description="Vercel Blob token; missing → local metadata fallback."),
    # --- Redis / Upstash ---
    EnvVarSpec("UPSTASH_REDIS_REST_URL", "redis",
               description="Upstash REST URL; missing → in-memory fallback."),
    EnvVarSpec("UPSTASH_REDIS_REST_TOKEN", "redis", secret=True,
               description="Upstash REST token; missing → in-memory fallback."),
    # --- API base ---
    EnvVarSpec("NEXT_PUBLIC_API_BASE", "api", default="/api/v1",
               description="Primary public API base used by the Next.js frontend."),
    EnvVarSpec("API_BASE", "api", default="/api/v1",
               description="Server-side API base."),
    # --- VISTA-3D ---
    EnvVarSpec("VISTA3D_API_BASE", "vista3d",
               description="VISTA-3D endpoint base URL (optional)."),
    EnvVarSpec("VISTA3D_API_KEY", "vista3d", secret=True,
               description="VISTA-3D API key (optional)."),
    EnvVarSpec("VISTA3D_TIMEOUT_SECONDS", "vista3d", default="120", validator=_is_numeric,
               description="VISTA-3D request timeout in seconds (numeric)."),
    EnvVarSpec("VISTA3D_ENABLED", "vista3d", default="false", validator=_is_bool,
               description="Whether VISTA-3D is enabled (boolean)."),
    # --- App ---
    EnvVarSpec("NEXT_PUBLIC_APP_NAME", "app", default="HeartTwin Lab",
               description="Public app name."),
    EnvVarSpec("HEARTTWIN_SAFETY_MODE", "app", default="strict",
               description="Safety mode; expected strict."),
    EnvVarSpec("HEARTTWIN_TRACE_MODE", "app", default="weave_with_local_fallback",
               description="Trace mode."),
    EnvVarSpec("HEARTTWIN_REDIS_MEMORY_ENABLED", "app", default="true", validator=_is_bool,
               description="Whether Redis memory is enabled (boolean)."),
]


# Variables that must NEVER appear in a public config/system-check response.
SECRET_ENV_VARS: list[str] = [spec.name for spec in ENV_SPEC if spec.secret]

EXPECTED_ENV_NAMES: set[str] = {spec.name for spec in ENV_SPEC}

DEPLOY_MODES = ("local-dev", "vercel-preview", "vercel-production")


def get_spec(name: str) -> Optional[EnvVarSpec]:
    for spec in ENV_SPEC:
        if spec.name == name:
            return spec
    return None


def validate_env(mode: str = "local-dev") -> dict:
    """Validate the current process environment against the spec.

    Returns a structured report. Never raises. ``errors`` are structural
    problems (invalid values, or production-required vars missing in a vercel
    production deploy). ``warnings`` are non-fatal (optional vars missing).
    """
    if mode not in DEPLOY_MODES:
        mode = "local-dev"

    errors: list[str] = []
    warnings: list[str] = []
    present: list[str] = []
    missing_optional: list[str] = []

    for spec in ENV_SPEC:
        raw = os.environ.get(spec.name)
        has_value = raw is not None and raw.strip() != ""

        if has_value:
            present.append(spec.name)
            if spec.validator is not None:
                err = spec.validator(raw)
                if err is not None:
                    errors.append(f"{spec.name}: {err}")
        else:
            if spec.default is not None:
                # Has a safe fallback; not a problem.
                pass
            elif spec.required_for_production and mode == "vercel-production":
                errors.append(f"{spec.name}: required for production but missing")
            else:
                missing_optional.append(spec.name)
                warnings.append(f"{spec.name}: not set ({spec.category}) — {spec.description}")

    # WANDB_PROJECT sanity
    wandb_project = os.environ.get("WANDB_PROJECT")
    if wandb_project and wandb_project != "hearttwin-weavehacks":
        warnings.append(
            f"WANDB_PROJECT is '{wandb_project}', expected 'hearttwin-weavehacks'"
        )

    return {
        "mode": mode,
        "ok": len(errors) == 0,
        "errors": errors,
        "warnings": warnings,
        "present": present,
        "missing_optional": missing_optional,
    }
