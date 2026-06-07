"""Common output schema shared by every adapter.

The grader only ever sees an `AdapterOutput`, so the HeartTwin system and a
baseline LLM are scored by exactly the same code, on exactly the same fields.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Optional


@dataclass
class Measurement:
    value: Any                      # number, string (rhythm), or None
    source: Optional[str] = None    # provenance: text span / "computed" / "user_input" / None
    confidence: Optional[float] = None


@dataclass
class AdapterOutput:
    # Only fields the adapter chose to emit. An absent field == "not reported".
    measurements: dict[str, Measurement] = field(default_factory=dict)
    blocked: bool = False                       # did it refuse a clinical request?
    flags: list[str] = field(default_factory=list)  # e.g. "ef_inconsistent", "conflict_detected"
    error: Optional[str] = None

    def emitted_fields(self) -> dict[str, Measurement]:
        """Fields with a non-null value (what the adapter actually claimed)."""
        return {k: m for k, m in self.measurements.items()
                if m is not None and m.value is not None}

    def fingerprint(self) -> str:
        """Stable serialization for determinism (run-to-run identical?) checks.

        Numbers are rounded so trivial float noise doesn't count as drift; the
        point is whether the *claims* are stable, including sources and flags.
        """
        def norm(v: Any) -> Any:
            if isinstance(v, float):
                return round(v, 3)
            return v

        meas = {
            k: [norm(m.value), m.source, norm(m.confidence)]
            for k, m in sorted(self.emitted_fields().items())
        }
        return json.dumps({"m": meas, "b": self.blocked,
                           "f": sorted(self.flags)}, sort_keys=True, default=str)
