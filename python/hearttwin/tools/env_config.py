"""Runtime environment helpers for optional integrations.

Missing external services must degrade to deterministic/local behavior.
These helpers keep that behavior consistent across API, agents, and tools.
"""

from __future__ import annotations

import os
from typing import Any

from python.hearttwin.tools.model_config import (
    get_electrophysiology_model,
    get_embedding_model,
    get_evaluator_model,
    get_extraction_model,
    get_fast_model,
    get_hemodynamics_model,
    get_intake_model,
    get_recovery_model,
    get_state_builder_model,
    get_validator_model,
)

TRUE_VALUES = {"1", "true", "yes", "on", "enabled"}
FALSE_VALUES = {"0", "false", "no", "off", "disabled"}

DEFAULT_WANDB_PROJECT = "hearttwin-weavehacks"
DEFAULT_TRACE_MODE = "weave_with_local_fallback"
DEFAULT_SAFETY_MODE = "strict"


def env_bool(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    normalized = raw.strip().lower()
    if normalized in TRUE_VALUES:
        return True
    if normalized in FALSE_VALUES:
        return False
    return default


def redis_memory_enabled() -> bool:
    return env_bool("HEARTTWIN_REDIS_MEMORY_ENABLED", True)


def trace_mode() -> str:
    return os.environ.get("HEARTTWIN_TRACE_MODE", DEFAULT_TRACE_MODE).strip() or DEFAULT_TRACE_MODE


def weave_enabled() -> bool:
    return trace_mode() not in {"disabled", "local_only", "off"}


def vista3d_enabled() -> bool:
    return env_bool("VISTA3D_ENABLED", False)


def validate_environment() -> dict[str, Any]:
    """Return a non-secret environment snapshot for health/config validation."""
    vista_enabled = vista3d_enabled()
    vista_configured = bool(os.environ.get("VISTA3D_API_BASE") and os.environ.get("VISTA3D_API_KEY"))
    redis_enabled = redis_memory_enabled()
    redis_configured = bool(
        os.environ.get("UPSTASH_REDIS_REST_URL") and os.environ.get("UPSTASH_REDIS_REST_TOKEN")
    )
    weave_is_enabled = weave_enabled()
    weave_configured = bool(os.environ.get("WANDB_API_KEY"))

    warnings: list[str] = []
    if vista_enabled and not vista_configured:
        warnings.append("VISTA3D_ENABLED=true but VISTA3D_API_BASE or VISTA3D_API_KEY is missing")
    if redis_enabled and not redis_configured:
        warnings.append("Redis memory is enabled but Upstash credentials are missing; using local memory fallback")
    if weave_is_enabled and not weave_configured:
        warnings.append("Weave tracing is enabled but WANDB_API_KEY is missing; using local trace fallback")
    if not os.environ.get("OPENAI_API_KEY"):
        warnings.append("OPENAI_API_KEY is missing; LLM-backed features use deterministic fallbacks where available")

    return {
        "openai": {
            "configured": bool(os.environ.get("OPENAI_API_KEY")),
            "models": {
                "intake": get_intake_model(),
                "extraction": get_extraction_model(),
                "validator": get_validator_model(),
                "state_builder": get_state_builder_model(),
                "electrophysiology": get_electrophysiology_model(),
                "hemodynamics": get_hemodynamics_model(),
                "recovery": get_recovery_model(),
                "evaluator": get_evaluator_model(),
                "fast": get_fast_model(),
                "embedding": get_embedding_model(),
            },
        },
        "weave": {
            "enabled": weave_is_enabled,
            "configured": weave_configured,
            "trace_mode": trace_mode(),
            "project": os.environ.get("WANDB_PROJECT", DEFAULT_WANDB_PROJECT),
            "entity_configured": bool(os.environ.get("WANDB_ENTITY")),
        },
        "redis": {
            "enabled": redis_enabled,
            "configured": redis_configured,
            "mode": "upstash" if redis_enabled and redis_configured else "local_memory",
        },
        "vista3d": {
            "enabled": vista_enabled,
            "configured": vista_configured,
            "timeout_seconds": os.environ.get("VISTA3D_TIMEOUT_SECONDS", "120"),
            "mode": "external_endpoint" if vista_enabled and vista_configured else "disabled",
        },
        "api": {
            "public_base": os.environ.get("NUXT_PUBLIC_API_BASE", "/api/v1"),
            "server_base": os.environ.get("API_BASE", "/api/v1"),
            "next_public_api_base_fallback_configured": bool(os.environ.get("NEXT_PUBLIC_API_BASE")),
        },
        "app": {
            "safety_mode": os.environ.get("HEARTTWIN_SAFETY_MODE", DEFAULT_SAFETY_MODE),
        },
        "warnings": warnings,
    }
