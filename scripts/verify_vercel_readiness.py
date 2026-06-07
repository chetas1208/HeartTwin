#!/usr/bin/env python3
"""Verify HeartTwin Lab is ready to deploy from the repo root to Vercel.

Checks root deploy structure, vercel.json rewrite of /api to the Python
entrypoint, api/index.py app import, no hardcoded localhost as the primary
production API base, presence of dependency/lock files, and that no secrets or
large datasets are committed.

Exit codes:
  0 -> ready
  1 -> root deployment broken

Usage:
  python scripts/verify_vercel_readiness.py
"""

from __future__ import annotations

import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
MAX_COMMITTED_FILE_MB = 25


def _exists(rel: str) -> bool:
    return (ROOT / rel).exists()


def _check_vercel_json(errors: list[str], warnings: list[str]) -> None:
    path = ROOT / "vercel.json"
    if not path.exists():
        errors.append("vercel.json missing")
        return
    try:
        cfg = json.loads(path.read_text())
    except Exception as exc:  # noqa: BLE001
        errors.append(f"vercel.json is not valid JSON: {exc}")
        return

    rewrites = cfg.get("rewrites") or []
    routes = cfg.get("routes") or []
    api_routed = False
    for r in rewrites:
        src = str(r.get("source", ""))
        dest = str(r.get("destination", ""))
        if src.startswith("/api") and "api/index" in dest:
            api_routed = True
    for r in routes:
        src = str(r.get("src", ""))
        dest = str(r.get("dest", ""))
        if "/api" in src and "api/index" in dest:
            api_routed = True
    if not api_routed:
        errors.append("vercel.json does not rewrite/route /api(.*) to api/index.py")

    if not cfg.get("buildCommand"):
        warnings.append("vercel.json has no explicit buildCommand")
    if not cfg.get("installCommand"):
        warnings.append("vercel.json has no explicit installCommand")


def _check_api_entry(errors: list[str]) -> None:
    path = ROOT / "api/index.py"
    if not path.exists():
        errors.append("api/index.py missing")
        return
    content = path.read_text()
    if "from python.hearttwin.api import app" not in content:
        errors.append("api/index.py does not import the FastAPI app correctly")


def _check_no_hardcoded_localhost(errors: list[str], warnings: list[str]) -> None:
    """Production code must not require http://localhost:8000 as the primary base.

    It is allowed only as a documented fallback (NEXT_PUBLIC_API_BASE).
    """
    offenders: list[str] = []
    scan_dirs = ["web", "python/hearttwin"]
    allowed_substrings = (
        "NEXT_PUBLIC_API_BASE",  # documented fallback line
        "DEFAULT_API_BASE",  # named dev default in the CopilotKit route
    )
    # Prune dependency/build dirs so we only scan source (never node_modules).
    skip_dirs = {"node_modules", ".next", ".nuxt", ".output", ".vercel",
                 "__pycache__", ".pytest_cache", ".git"}
    import os

    for d in scan_dirs:
        base = ROOT / d
        if not base.exists():
            continue
        for dirpath, dirnames, filenames in os.walk(base):
            dirnames[:] = [dn for dn in dirnames if dn not in skip_dirs]
            for name in filenames:
                p = pathlib.Path(dirpath) / name
                if p.suffix not in {".ts", ".tsx", ".vue", ".js", ".py"}:
                    continue
                try:
                    text = p.read_text(errors="ignore")
                except Exception:  # noqa: BLE001
                    continue
                for lineno, line in enumerate(text.splitlines(), 1):
                    if "localhost:8000" in line:
                        if any(a in line for a in allowed_substrings):
                            continue
                        offenders.append(f"{p.relative_to(ROOT)}:{lineno}")
    if offenders:
        errors.append(
            "hardcoded localhost:8000 found as non-fallback API base: " + ", ".join(offenders)
        )


def _check_deps_and_locks(errors: list[str]) -> None:
    if not (_exists("pyproject.toml") or _exists("requirements.txt")):
        errors.append("no Python dependency file (pyproject.toml or requirements.txt)")
    if not (_exists("pnpm-lock.yaml") or _exists("package-lock.json") or _exists("yarn.lock")):
        errors.append("no Node lockfile committed")


def _check_no_committed_secrets_or_data(errors: list[str], warnings: list[str]) -> None:
    if _exists(".env"):
        # .env existing locally is fine ONLY if gitignored.
        gitignore = ROOT / ".gitignore"
        ignored = gitignore.exists() and ".env" in gitignore.read_text()
        if not ignored:
            errors.append(".env exists and is not gitignored (risk of committing secrets)")
    if not _exists(".env.example"):
        errors.append(".env.example missing")

    # Large files (committed datasets / binaries). Prune heavy build/dep dirs
    # from the walk itself so we never enumerate node_modules etc.
    skip_dirs = {"node_modules", ".git", ".next", ".nuxt", ".output", ".vercel",
                 "__pycache__", ".pytest_cache"}
    import os

    for dirpath, dirnames, filenames in os.walk(ROOT):
        dirnames[:] = [d for d in dirnames if d not in skip_dirs]
        for name in filenames:
            p = pathlib.Path(dirpath) / name
            try:
                size_mb = p.stat().st_size / (1024 * 1024)
            except OSError:
                continue
            if size_mb > MAX_COMMITTED_FILE_MB:
                warnings.append(f"large file committed ({size_mb:.1f} MB): {p.relative_to(ROOT)}")


def main() -> int:
    errors: list[str] = []
    warnings: list[str] = []

    required_root = ["package.json", "vercel.json", "api/index.py",
                     "python/hearttwin/api.py", ".env.example"]
    for rel in required_root:
        if not _exists(rel):
            errors.append(f"missing root deploy file: {rel}")

    _check_vercel_json(errors, warnings)
    _check_api_entry(errors)
    _check_no_hardcoded_localhost(errors, warnings)
    _check_deps_and_locks(errors)
    _check_no_committed_secrets_or_data(errors, warnings)

    print("== HeartTwin Vercel root-deploy readiness ==")
    if warnings:
        print("\nWarnings:")
        for w in warnings:
            print(f"  - {w}")

    if errors:
        print("\nERRORS:")
        for e in errors:
            print(f"  - {e}")
        print("\nRESULT: NOT READY")
        return 1

    print("\nRESULT: READY")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
