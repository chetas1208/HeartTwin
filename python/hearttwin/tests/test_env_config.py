"""Env/config tests for HeartTwin Lab.

Covers:
- All expected env var names are known to the spec.
- Missing optional envs produce warnings, not crashes.
- /api/v1/config exposes no secrets.
- Model routing defaults exist.
- Public API base uses /api/v1 and honors NEXT_PUBLIC_API_BASE.
- Boolean/numeric env validators behave.
- Deploy-mode validation (local-dev / vercel-preview / vercel-production).
"""

from __future__ import annotations

import os
import contextlib

import pytest

from python.hearttwin.tools.env_spec import (
    DEPLOY_MODES,
    ENV_SPEC,
    EXPECTED_ENV_NAMES,
    SECRET_ENV_VARS,
    validate_env,
)


@contextlib.contextmanager
def env(**kv):
    old = {k: os.environ.get(k) for k in kv}
    try:
        for k, v in kv.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        yield
    finally:
        for k, v in old.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v


# ---------------------------------------------------------------------------
# Spec completeness — every documented env var is known
# ---------------------------------------------------------------------------

_DOCUMENTED = {
    "OPENAI_API_KEY", "OPENAI_MODEL_INTAKE", "OPENAI_MODEL_EXTRACTION",
    "OPENAI_MODEL_VALIDATOR", "OPENAI_MODEL_STATE_BUILDER",
    "OPENAI_MODEL_ELECTROPHYSIOLOGY", "OPENAI_MODEL_HEMODYNAMICS",
    "OPENAI_MODEL_RECOVERY", "OPENAI_MODEL_EVALUATOR", "OPENAI_MODEL_FAST",
    "OPENAI_EMBEDDING_MODEL", "WANDB_API_KEY", "WANDB_ENTITY", "WANDB_PROJECT",
    "NEXT_PUBLIC_WEAVE_PROJECT_URL", "BLOB_READ_WRITE_TOKEN",
    "REDIS_URL",
    "API_BASE", "NEXT_PUBLIC_API_BASE", "VISTA3D_API_BASE", "VISTA3D_API_KEY",
    "VISTA3D_TIMEOUT_SECONDS", "VISTA3D_ENABLED", "NEXT_PUBLIC_APP_NAME",
    "HEARTTWIN_SAFETY_MODE", "HEARTTWIN_TRACE_MODE", "HEARTTWIN_REDIS_MEMORY_ENABLED",
}


@pytest.mark.parametrize("name", sorted(_DOCUMENTED))
def test_documented_env_var_is_in_spec(name: str) -> None:
    assert name in EXPECTED_ENV_NAMES, f"{name} is documented but missing from ENV_SPEC"


def test_spec_has_no_unexpected_extras() -> None:
    # Spec should not invent env vars beyond what's documented.
    extras = EXPECTED_ENV_NAMES - _DOCUMENTED
    assert not extras, f"ENV_SPEC has undocumented vars: {extras}"


def test_secret_vars_marked() -> None:
    expected_secrets = {
        "OPENAI_API_KEY", "WANDB_API_KEY", "REDIS_URL",
        "BLOB_READ_WRITE_TOKEN", "VISTA3D_API_KEY",
    }
    assert expected_secrets.issubset(set(SECRET_ENV_VARS))


# ---------------------------------------------------------------------------
# Validation modes
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("mode", DEPLOY_MODES)
def test_validate_env_returns_report(mode: str) -> None:
    report = validate_env(mode)
    assert report["mode"] == mode
    assert "errors" in report and "warnings" in report
    assert isinstance(report["errors"], list)


def test_missing_optional_envs_are_warnings_not_errors() -> None:
    with env(BLOB_READ_WRITE_TOKEN=None, VISTA3D_API_KEY=None, WANDB_API_KEY=None):
        report = validate_env("local-dev")
        # No structural errors just because optional secrets are missing.
        assert report["ok"] is True
        assert report["errors"] == []


def test_invalid_numeric_env_is_error() -> None:
    with env(VISTA3D_TIMEOUT_SECONDS="not-a-number"):
        report = validate_env("local-dev")
        assert report["ok"] is False
        assert any("VISTA3D_TIMEOUT_SECONDS" in e for e in report["errors"])


def test_valid_numeric_env_ok() -> None:
    with env(VISTA3D_TIMEOUT_SECONDS="120"):
        report = validate_env("local-dev")
        assert not any("VISTA3D_TIMEOUT_SECONDS" in e for e in report["errors"])


def test_invalid_bool_env_is_error() -> None:
    with env(VISTA3D_ENABLED="maybe"):
        report = validate_env("local-dev")
        assert report["ok"] is False
        assert any("VISTA3D_ENABLED" in e for e in report["errors"])


@pytest.mark.parametrize("val", ["true", "false", "1", "0", "yes", "no", "on", "off"])
def test_valid_bool_values_ok(val: str) -> None:
    with env(VISTA3D_ENABLED=val):
        report = validate_env("local-dev")
        assert not any("VISTA3D_ENABLED" in e for e in report["errors"])


def test_wandb_project_warns_when_unexpected() -> None:
    with env(WANDB_PROJECT="some-other-project"):
        report = validate_env("local-dev")
        assert any("WANDB_PROJECT" in w for w in report["warnings"])


def test_wandb_project_default_is_expected() -> None:
    with env(WANDB_PROJECT=None):
        report = validate_env("local-dev")
        assert not any("WANDB_PROJECT" in w for w in report["warnings"])


# ---------------------------------------------------------------------------
# Model routing defaults exist
# ---------------------------------------------------------------------------


def test_model_routing_defaults_exist() -> None:
    from python.hearttwin.tools.model_config import (
        get_electrophysiology_model,
        get_evaluator_model,
        get_extraction_model,
        get_hemodynamics_model,
        get_intake_model,
        get_recovery_model,
        get_state_builder_model,
        get_validator_model,
    )

    keys = [
        "OPENAI_MODEL_INTAKE", "OPENAI_MODEL_EXTRACTION", "OPENAI_MODEL_VALIDATOR",
        "OPENAI_MODEL_STATE_BUILDER", "OPENAI_MODEL_ELECTROPHYSIOLOGY",
        "OPENAI_MODEL_HEMODYNAMICS", "OPENAI_MODEL_RECOVERY", "OPENAI_MODEL_EVALUATOR",
    ]
    with env(**{k: None for k in keys}):
        for getter in (
            get_intake_model, get_extraction_model, get_validator_model,
            get_state_builder_model, get_electrophysiology_model,
            get_hemodynamics_model, get_recovery_model, get_evaluator_model,
        ):
            model = getter()
            assert isinstance(model, str) and model, f"{getter.__name__} returned empty default"


# ---------------------------------------------------------------------------
# API base resolution
# ---------------------------------------------------------------------------


def test_validate_environment_api_base_defaults_to_v1() -> None:
    from python.hearttwin.tools.env_config import validate_environment

    with env(NEXT_PUBLIC_API_BASE=None, API_BASE=None):
        snap = validate_environment()
        assert snap["api"]["public_base"] == "/api/v1"


def test_next_public_api_base_is_honored() -> None:
    """The public API base comes from NEXT_PUBLIC_API_BASE (the Next.js frontend)."""
    from python.hearttwin.tools.env_config import validate_environment

    with env(NEXT_PUBLIC_API_BASE="https://api.example.com/api/v1", API_BASE=None):
        snap = validate_environment()
        assert snap["api"]["public_base"] == "https://api.example.com/api/v1"


# ---------------------------------------------------------------------------
# Config endpoint exposes no secrets
# ---------------------------------------------------------------------------


async def test_config_endpoint_exposes_no_secrets() -> None:
    from python.hearttwin.api import get_config

    fake_secrets = {
        "OPENAI_API_KEY": "sk-fake-openai-key-1234567890",
        "WANDB_API_KEY": "wandb-fake-key-1234567890",
        "REDIS_URL": "redis://default:fake-redis-pw-1234567890@example.com:6379",
        "BLOB_READ_WRITE_TOKEN": "blob-fake-token-1234567890",
        "VISTA3D_API_KEY": "vista-fake-key-1234567890",
    }
    with env(**fake_secrets):
        cfg = await get_config()
        blob = str(cfg)
        for name, value in fake_secrets.items():
            assert value not in blob, f"{name} value leaked into /config response"


async def test_config_endpoint_returns_expected_shape() -> None:
    from python.hearttwin.api import get_config

    cfg = await get_config()
    assert cfg["app_name"] == "HeartTwin Lab"
    assert cfg["api_base"] == "/api/v1"
    assert "weave" in cfg and "configured" in cfg["weave"]
    assert "redis" in cfg and "configured" in cfg["redis"]
    assert "vista3d" in cfg and "enabled" in cfg["vista3d"]
    assert "models" in cfg
    for agent_key in ("intake", "extraction", "validator", "state_builder",
                       "electrophysiology", "hemodynamics", "recovery", "evaluator"):
        assert agent_key in cfg["models"]


def test_app_safety_mode_default_strict() -> None:
    from python.hearttwin.tools.env_config import validate_environment

    with env(HEARTTWIN_SAFETY_MODE=None):
        snap = validate_environment()
        assert snap["app"]["safety_mode"] == "strict"


def test_redis_memory_enabled_honored_but_safe_without_creds() -> None:
    from python.hearttwin.tools.env_config import redis_memory_enabled

    with env(HEARTTWIN_REDIS_MEMORY_ENABLED="true", REDIS_URL=None):
        assert redis_memory_enabled() is True
        from python.hearttwin.tools.env_config import validate_environment
        snap = validate_environment()
        assert snap["redis"]["mode"] == "local_memory"


def test_trace_mode_honored() -> None:
    from python.hearttwin.tools.env_config import trace_mode, weave_enabled

    with env(HEARTTWIN_TRACE_MODE="weave_with_local_fallback"):
        assert trace_mode() == "weave_with_local_fallback"
        assert weave_enabled() is True
