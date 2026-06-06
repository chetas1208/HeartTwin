"""Safety boundary enforcement for HeartTwin Lab.

Rejects requests that cross medical/clinical boundaries.
Every orchestration response gets a mandatory disclaimer.
"""

from __future__ import annotations

import re
from typing import Any

DISCLAIMER = (
    "EDUCATIONAL SIMULATION ONLY — HeartTwin Lab is not a medical device, does not provide "
    "medical advice, does not diagnose, and does not recommend treatment. All outputs are "
    "simulated educational estimates. Consult a qualified clinician for any health decisions."
)

_BLOCKED_PATTERNS = [
    r"\b(diagnos|diagnosis|diagnose)\b",
    r"\b(prescrib|prescription)\b",
    r"\b(treat(ment)?|therapy)\b",
    r"\b(medication|drug|dose|dosage|dosing)\b",
    r"\b(emergenc(y|ies)|triage|911|ambulance)\b",
    r"\b(you (have|are|suffer|need))\b",
    r"\b(healed?|cured?|recovered)\b",
    r"\b(take this|start taking|stop taking)\b",
    r"\b(clinical(ly)?)\b",
]

_COMPILED = [re.compile(p, re.IGNORECASE) for p in _BLOCKED_PATTERNS]


class SafetyViolation(Exception):
    def __init__(self, message: str, pattern: str = "") -> None:
        self.pattern = pattern
        super().__init__(message)


def check_request_safety(text: str) -> None:
    """Raise SafetyViolation if text contains a blocked request pattern."""
    for pattern in _COMPILED:
        if pattern.search(text):
            raise SafetyViolation(
                f"Request blocked: HeartTwin Lab cannot provide diagnosis, treatment, "
                f"medication, triage, or clinical recommendations. "
                f"This is an educational simulation tool only.",
                pattern=pattern.pattern,
            )


def enforce_simulation_language(text: str) -> str:
    """Replace dangerous clinical language with simulation-safe equivalents."""
    replacements = {
        r"\bhealed\b": "simulated recovery trajectory reached target",
        r"\bcured\b": "simulation scenario completed",
        r"\brecovered\b": "simulated recovery trajectory progressed",
        r"\bdiagnosis\b": "simulated pattern",
        r"\btreatment\b": "simulated scenario",
    }
    for pattern, replacement in replacements.items():
        text = re.sub(pattern, replacement, text, flags=re.IGNORECASE)
    return text


def redact_pii(text: str) -> str:
    """Redact obvious PII patterns from trace outputs."""
    text = re.sub(r"\b\d{3}-\d{2}-\d{4}\b", "[SSN-REDACTED]", text)
    text = re.sub(r"\b\d{10,}\b", "[ID-REDACTED]", text)
    text = re.sub(
        r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b", "[EMAIL-REDACTED]", text
    )
    text = re.sub(
        r"\b(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\.?\s+\d{1,2},?\s+\d{4}\b",
        "[DATE-REDACTED]",
        text,
    )
    return text


def add_disclaimer(response: dict[str, Any]) -> dict[str, Any]:
    """Attach the mandatory safety disclaimer to any agent/API response."""
    response["safety_disclaimer"] = DISCLAIMER
    return response


def validate_simulation_outputs(outputs: dict[str, Any]) -> list[str]:
    """Return list of safety warnings for a set of simulation outputs."""
    warnings: list[str] = []

    if "diagnosis" in str(outputs).lower():
        warnings.append("Output contains the word 'diagnosis' — must use 'simulated pattern'")
    if "treatment" in str(outputs).lower():
        warnings.append("Output contains the word 'treatment' — must use 'simulated scenario'")
    if "healed" in str(outputs).lower():
        warnings.append("Output contains the word 'healed' — must use 'simulated recovery trajectory'")
    if "prescribe" in str(outputs).lower():
        warnings.append("Output contains 'prescribe' — blocked in simulation context")

    return warnings


def safe_recovery_label(scenario_type: str) -> str:
    """Return a simulation-safe label for a recovery scenario."""
    labels = {
        "load_reduction": "Simulated Load Reduction Scenario",
        "oxygen_delivery_improvement": "Simulated Oxygen Delivery Improvement Scenario",
        "contractility_support": "Simulated Contractility Support Scenario",
        "conditioning": "Simulated Conditioning Scenario",
        "stability_monitoring": "Simulated Stability Monitoring Scenario",
        "custom": "Custom Simulated Scenario",
    }
    return labels.get(scenario_type, "Simulated Recovery Scenario")
