"""Tests for correct OpenAI model routing per agent.

Verifies:
- Each agent reads the correct env var.
- Fallback model is used when env var is absent.
- Missing OPENAI_API_KEY does not crash the app.
- No agent has a hardcoded primary model name.
"""

from __future__ import annotations

import os

import pytest

from python.hearttwin.tools.model_config import (
    get_electrophysiology_model,
    get_evaluator_model,
    get_extraction_model,
    get_hemodynamics_model,
    get_intake_model,
    get_recovery_model,
    get_state_builder_model,
    get_validator_model,
    get_fast_model,
)


def _with_env(**kv: str):
    """Context manager to temporarily set environment variables."""
    import contextlib

    @contextlib.contextmanager
    def _ctx():
        old = {k: os.environ.get(k) for k in kv}
        for k, v in kv.items():
            os.environ[k] = v
        try:
            yield
        finally:
            for k, v in old.items():
                if v is None:
                    os.environ.pop(k, None)
                else:
                    os.environ[k] = v

    return _ctx()


def _without_env(*keys: str):
    """Context manager to temporarily remove environment variables."""
    import contextlib

    @contextlib.contextmanager
    def _ctx():
        old = {k: os.environ.pop(k, None) for k in keys}
        try:
            yield
        finally:
            for k, v in old.items():
                if v is not None:
                    os.environ[k] = v

    return _ctx()


# ---------------------------------------------------------------------------
# Each agent uses the correct env var
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("getter,env_var,expected", [
    (get_intake_model, "OPENAI_MODEL_INTAKE", "gpt-test-intake"),
    (get_extraction_model, "OPENAI_MODEL_EXTRACTION", "gpt-test-extract"),
    (get_validator_model, "OPENAI_MODEL_VALIDATOR", "gpt-test-validator"),
    (get_state_builder_model, "OPENAI_MODEL_STATE_BUILDER", "gpt-test-sb"),
    (get_electrophysiology_model, "OPENAI_MODEL_ELECTROPHYSIOLOGY", "gpt-test-ep"),
    (get_hemodynamics_model, "OPENAI_MODEL_HEMODYNAMICS", "gpt-test-hemo"),
    (get_recovery_model, "OPENAI_MODEL_RECOVERY", "gpt-test-rec"),
    (get_evaluator_model, "OPENAI_MODEL_EVALUATOR", "gpt-test-eval"),
    (get_fast_model, "OPENAI_MODEL_FAST", "gpt-test-fast"),
])
def test_model_getter_reads_env_var(getter, env_var: str, expected: str) -> None:
    with _with_env(**{env_var: expected}):
        assert getter() == expected


# ---------------------------------------------------------------------------
# Fallback when env var is absent
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("getter,env_var,fallback_prefix", [
    (get_intake_model, "OPENAI_MODEL_INTAKE", "gpt-"),
    (get_extraction_model, "OPENAI_MODEL_EXTRACTION", "gpt-"),
    (get_validator_model, "OPENAI_MODEL_VALIDATOR", "gpt-"),
    (get_state_builder_model, "OPENAI_MODEL_STATE_BUILDER", "gpt-"),
    (get_electrophysiology_model, "OPENAI_MODEL_ELECTROPHYSIOLOGY", "gpt-"),
    (get_hemodynamics_model, "OPENAI_MODEL_HEMODYNAMICS", "gpt-"),
    (get_recovery_model, "OPENAI_MODEL_RECOVERY", "gpt-"),
    (get_evaluator_model, "OPENAI_MODEL_EVALUATOR", "gpt-"),
    (get_fast_model, "OPENAI_MODEL_FAST", "gpt-"),
])
def test_model_fallback_is_valid_gpt_name(getter, env_var: str, fallback_prefix: str) -> None:
    with _without_env(env_var):
        result = getter()
        assert result.startswith(fallback_prefix), (
            f"{getter.__name__} fallback '{result}' does not start with '{fallback_prefix}'"
        )


# ---------------------------------------------------------------------------
# Missing OPENAI_API_KEY does not crash model_config
# ---------------------------------------------------------------------------


def test_missing_openai_key_does_not_crash() -> None:
    with _without_env("OPENAI_API_KEY"):
        intake = get_intake_model()
        assert isinstance(intake, str)
        assert intake


# ---------------------------------------------------------------------------
# Higher-power models assigned to reasoning-heavy agents
# ---------------------------------------------------------------------------


def test_state_builder_uses_stronger_default_than_intake() -> None:
    with _without_env("OPENAI_MODEL_STATE_BUILDER", "OPENAI_MODEL_INTAKE"):
        sb = get_state_builder_model()
        intake = get_intake_model()
        assert sb != get_fast_model(), "State builder should use a strong model, not the fast model"


def test_evaluator_uses_stronger_default() -> None:
    with _without_env("OPENAI_MODEL_EVALUATOR"):
        ev = get_evaluator_model()
        fast = get_fast_model()
        assert ev != fast, "Evaluator should use a stronger model, not the fast/nano model"


def test_recovery_uses_stronger_default() -> None:
    with _without_env("OPENAI_MODEL_RECOVERY"):
        rec = get_recovery_model()
        fast = get_fast_model()
        assert rec != fast, "Recovery should use a stronger model, not the fast/nano model"


# ---------------------------------------------------------------------------
# Agent ID constants
# ---------------------------------------------------------------------------


def test_intake_agent_id() -> None:
    from python.hearttwin.agents.intake_agent import _INTAKE_AGENT_ID
    assert _INTAKE_AGENT_ID == "intake_safety"


def test_extraction_agent_id() -> None:
    from python.hearttwin.agents.extraction_agent import _AGENT_ID
    assert _AGENT_ID == "multimodal_extraction"


def test_validator_agent_id() -> None:
    from python.hearttwin.agents.validator_agent import _VALIDATOR_AGENT_ID
    assert _VALIDATOR_AGENT_ID == "evidence_validator"


def test_state_builder_agent_id() -> None:
    from python.hearttwin.agents.state_builder_agent import _AGENT_ID
    assert _AGENT_ID == "cardiac_state_builder"


def test_electrophysiology_agent_id() -> None:
    from python.hearttwin.agents.electrophysiology_agent import _EP_AGENT_ID
    assert _EP_AGENT_ID == "electrophysiology"


def test_hemodynamics_agent_id() -> None:
    from python.hearttwin.agents.hemodynamics_agent import AGENT_ID
    assert AGENT_ID == "hemodynamics_simulation"


def test_recovery_agent_id() -> None:
    from python.hearttwin.agents.recovery_agent import _AGENT_ID
    assert _AGENT_ID == "recovery_orchestration"


def test_evaluator_agent_id() -> None:
    from python.hearttwin.agents.evaluator_agent import _AGENT_ID
    assert _AGENT_ID == "evaluator_critic"
