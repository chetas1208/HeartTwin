#!/usr/bin/env python3
"""Verify HeartTwin Lab monorepo structure for root deployment.

Checks that all required root files, the Python package, the 8 agents, tools,
docs, fixtures, and tests exist. Warns (does not fail) on optional-but-expected
items.

Exit codes:
  0 -> required structure present
  1 -> required structure missing

Usage:
  python scripts/verify_repo_structure.py
"""

from __future__ import annotations

import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent

REQUIRED_FILES = [
    "package.json",
    "vercel.json",
    "web/package.json",
    "web/app/api/copilotkit/route.ts",
    "api/index.py",
    "python/hearttwin/api.py",
    "python/hearttwin/orchestrator.py",
    "python/hearttwin/schemas.py",
    "python/hearttwin/safety.py",
    ".env.example",
]

REQUIRED_PY_DEPS = ["pyproject.toml", "requirements.txt"]  # at least one

AGENT_FILES = [
    "python/hearttwin/agents/intake_agent.py",
    "python/hearttwin/agents/extraction_agent.py",
    "python/hearttwin/agents/validator_agent.py",
    "python/hearttwin/agents/state_builder_agent.py",
    "python/hearttwin/agents/electrophysiology_agent.py",
    "python/hearttwin/agents/hemodynamics_agent.py",
    "python/hearttwin/agents/recovery_agent.py",
    "python/hearttwin/agents/evaluator_agent.py",
]

EXPECTED_TOOLS = [
    "python/hearttwin/tools/cardiac_state.py",
    "python/hearttwin/tools/hemodynamics.py",
    "python/hearttwin/tools/recovery_sim.py",
    "python/hearttwin/tools/ecg_features.py",
    "python/hearttwin/tools/scoring.py",
    "python/hearttwin/tools/weave_trace.py",
    "python/hearttwin/tools/case_memory.py",
    "python/hearttwin/tools/storage.py",
    "python/hearttwin/tools/vista3d_client.py",
    "python/hearttwin/tools/model_config.py",
    "python/hearttwin/tools/env_config.py",
]

EXPECTED_DOCS = [
    "docs/testing.md",
    "docs/deployment-vercel.md",
    "docs/research.md",
    "docs/datasets.md",
    "docs/weavehacks-submission.md",
]

EXPECTED_FIXTURES = [
    "fixtures/hearttwin/manual_baseline.json",
    "fixtures/hearttwin/manual_reduced_function.json",
    "fixtures/hearttwin/manual_partial_data.json",
    "fixtures/hearttwin/ecg_synthetic_normal.csv",
    "fixtures/hearttwin/README.md",
]

EXPECTED_DIRS = ["web", "api", "python", "fixtures", "scripts", "docs"]


def _exists(rel: str) -> bool:
    return (ROOT / rel).exists()


def main() -> int:
    errors: list[str] = []
    warnings: list[str] = []

    for rel in REQUIRED_FILES:
        if not _exists(rel):
            errors.append(f"missing required file: {rel}")

    if not any(_exists(dep) for dep in REQUIRED_PY_DEPS):
        errors.append(f"missing Python deps file (one of: {', '.join(REQUIRED_PY_DEPS)})")

    for rel in AGENT_FILES:
        if not _exists(rel):
            errors.append(f"missing agent file: {rel}")

    for rel in EXPECTED_DIRS:
        if not _exists(rel):
            errors.append(f"missing required directory: {rel}/")

    for rel in EXPECTED_TOOLS:
        if not _exists(rel):
            warnings.append(f"expected tool missing: {rel}")

    for rel in EXPECTED_DOCS:
        if not _exists(rel):
            warnings.append(f"expected doc missing: {rel}")

    for rel in EXPECTED_FIXTURES:
        if not _exists(rel):
            warnings.append(f"expected fixture missing: {rel}")

    # api/index.py must import the app
    api_index = ROOT / "api/index.py"
    if api_index.exists():
        content = api_index.read_text()
        if "from python.hearttwin.api import app" not in content:
            errors.append("api/index.py does not import 'from python.hearttwin.api import app'")

    print("== HeartTwin repo structure verification ==")
    print(f"agents: {sum(_exists(f) for f in AGENT_FILES)}/8 present")
    print(f"tools:  {sum(_exists(f) for f in EXPECTED_TOOLS)}/{len(EXPECTED_TOOLS)} present")

    if warnings:
        print("\nWarnings:")
        for w in warnings:
            print(f"  - {w}")

    if errors:
        print("\nERRORS:")
        for e in errors:
            print(f"  - {e}")
        print("\nRESULT: FAILED")
        return 1

    print("\nRESULT: OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
