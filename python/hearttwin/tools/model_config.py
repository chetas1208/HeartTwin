"""OpenAI model configuration helpers.

Model names are resolved from environment variables so deployments can change
models without touching agent or tool logic.
"""

from __future__ import annotations

import os

_DEFAULT_INTAKE_MODEL = "gpt-5.4-mini"
_DEFAULT_EXTRACTION_MODEL = "gpt-5.4-mini"
_DEFAULT_VALIDATOR_MODEL = "gpt-5.4-mini"
_DEFAULT_STATE_BUILDER_MODEL = "gpt-5.5"
_DEFAULT_ELECTROPHYSIOLOGY_MODEL = "gpt-5.4-mini"
_DEFAULT_HEMODYNAMICS_MODEL = "gpt-5.4-mini"
_DEFAULT_RECOVERY_MODEL = "gpt-5.5"
_DEFAULT_EVALUATOR_MODEL = "gpt-5.5"
_DEFAULT_FAST_MODEL = "gpt-5.4-nano"
_DEFAULT_EMBEDDING_MODEL = "text-embedding-3-small"


def _model(name: str, fallback: str) -> str:
    return os.environ.get(name) or fallback


def get_copilot_model() -> str:
    """Return the configured model for read-only case explanation."""
    return get_fast_model()


def get_intake_model() -> str:
    """Return the configured model for intake intent classification."""
    return _model("OPENAI_MODEL_INTAKE", _DEFAULT_INTAKE_MODEL)


def get_vision_model() -> str:
    """Return the configured model for image/ECG extraction."""
    return get_extraction_model()


def get_extraction_model() -> str:
    return _model("OPENAI_MODEL_EXTRACTION", _DEFAULT_EXTRACTION_MODEL)


def get_validator_model() -> str:
    return _model("OPENAI_MODEL_VALIDATOR", _DEFAULT_VALIDATOR_MODEL)


def get_state_builder_model() -> str:
    return _model("OPENAI_MODEL_STATE_BUILDER", _DEFAULT_STATE_BUILDER_MODEL)


def get_electrophysiology_model() -> str:
    return _model("OPENAI_MODEL_ELECTROPHYSIOLOGY", _DEFAULT_ELECTROPHYSIOLOGY_MODEL)


def get_hemodynamics_model() -> str:
    return _model("OPENAI_MODEL_HEMODYNAMICS", _DEFAULT_HEMODYNAMICS_MODEL)


def get_recovery_model() -> str:
    return _model("OPENAI_MODEL_RECOVERY", _DEFAULT_RECOVERY_MODEL)


def get_evaluator_model() -> str:
    return _model("OPENAI_MODEL_EVALUATOR", _DEFAULT_EVALUATOR_MODEL)


def get_fast_model() -> str:
    return _model("OPENAI_MODEL_FAST", _DEFAULT_FAST_MODEL)


def get_embedding_model() -> str:
    return _model("OPENAI_EMBEDDING_MODEL", _DEFAULT_EMBEDDING_MODEL)
