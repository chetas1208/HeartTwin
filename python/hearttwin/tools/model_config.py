"""OpenAI model configuration helpers.

Model names are resolved from environment variables so deployments can change
models without touching agent or tool logic.
"""

from __future__ import annotations

import os

_DEFAULT_OPENAI_MODEL = "gpt-4o"


def get_copilot_model() -> str:
    """Return the configured model for read-only case explanation."""
    return (
        os.environ.get("HEARTTWIN_COPILOT_MODEL")
        or os.environ.get("HEARTTWIN_OPENAI_MODEL")
        or _DEFAULT_OPENAI_MODEL
    )


def get_intake_model() -> str:
    """Return the configured model for intake intent classification."""
    return (
        os.environ.get("HEARTTWIN_INTAKE_MODEL")
        or os.environ.get("HEARTTWIN_OPENAI_MODEL")
        or _DEFAULT_OPENAI_MODEL
    )


def get_vision_model() -> str:
    """Return the configured model for image/ECG extraction."""
    return (
        os.environ.get("HEARTTWIN_VISION_MODEL")
        or os.environ.get("HEARTTWIN_OPENAI_MODEL")
        or _DEFAULT_OPENAI_MODEL
    )
