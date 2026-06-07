#!/usr/bin/env python3
"""Verify HeartTwin Lab environment variables.

Loads .env if present, validates the current environment against the canonical
spec in python/hearttwin/tools/env_spec.py, and reports missing/invalid vars.

Exit codes:
  0  -> no structural errors (warnings about optional vars are fine in local-dev)
  1  -> structural errors or invalid values

Usage:
  python scripts/verify_env.py [--mode local-dev|vercel-preview|vercel-production]
"""

from __future__ import annotations

import argparse
import os
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def _load_dotenv(path: pathlib.Path) -> None:
    """Minimal .env loader (no external dependency). Does not overwrite real env."""
    if not path.exists():
        return
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


def _check_env_example(path: pathlib.Path) -> list[str]:
    """Warn if .env.example appears to contain real secret values."""
    problems: list[str] = []
    if not path.exists():
        problems.append(".env.example is missing")
        return problems
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip()
        # Secrets in .env.example must be blank placeholders.
        if any(s in key for s in ("API_KEY", "TOKEN")) and value and not value.startswith("gpt-"):
            # Heuristic: real OpenAI keys start with sk-, Upstash tokens are long.
            if value.startswith("sk-") or len(value) > 24:
                problems.append(f".env.example: {key} appears to contain a real secret value")
    return problems


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", default=os.environ.get("HEARTTWIN_DEPLOY_MODE", "local-dev"))
    args = parser.parse_args()

    _load_dotenv(ROOT / ".env")

    from python.hearttwin.tools.env_spec import validate_env

    report = validate_env(args.mode)

    print(f"== HeartTwin env verification (mode={report['mode']}) ==")
    print(f"present: {len(report['present'])} vars")

    example_problems = _check_env_example(ROOT / ".env.example")

    # NUXT_PUBLIC_API_BASE presence (default exists, but warn if neither set)
    if not (os.environ.get("NUXT_PUBLIC_API_BASE") or os.environ.get("API_BASE")):
        report["warnings"].append(
            "Neither NUXT_PUBLIC_API_BASE nor API_BASE set; defaulting to /api/v1"
        )

    if report["warnings"]:
        print("\nWarnings (non-fatal):")
        for w in report["warnings"]:
            print(f"  - {w}")

    errors = list(report["errors"]) + example_problems
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
