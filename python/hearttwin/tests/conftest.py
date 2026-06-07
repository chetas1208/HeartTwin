"""Shared pytest fixtures and helpers for HeartTwin Lab tests.

Provides access to the synthetic fixtures under fixtures/hearttwin/ and a few
convenience loaders. All fixtures are synthetic and non-PHI.
"""

from __future__ import annotations

import json
import pathlib

import pytest

REPO_ROOT = pathlib.Path(__file__).resolve().parents[3]
FIXTURE_DIR = REPO_ROOT / "fixtures" / "hearttwin"


@pytest.fixture(autouse=True)
def _hermetic_redis(monkeypatch):
    """Keep the suite hermetic: never touch a live Redis (a developer's shell
    REDIS_URL or legacy Upstash vars), and reset the cached client per test.
    A test that wants the Redis path can still set REDIS_URL in its own body."""
    for var in ("REDIS_URL", "UPSTASH_REDIS_REST_URL", "UPSTASH_REDIS_REST_TOKEN"):
        monkeypatch.delenv(var, raising=False)
    from python.hearttwin.tools import redis_client

    redis_client.reset_client()
    yield
    redis_client.reset_client()


def load_fixture_json(name: str) -> dict:
    return json.loads((FIXTURE_DIR / name).read_text())


def load_fixture_text(name: str) -> str:
    return (FIXTURE_DIR / name).read_text()


@pytest.fixture(scope="session")
def fixture_dir() -> pathlib.Path:
    return FIXTURE_DIR


@pytest.fixture(scope="session")
def baseline_vitals() -> dict:
    return load_fixture_json("manual_baseline.json")["user_vitals"]


@pytest.fixture(scope="session")
def baseline_expected() -> dict:
    return load_fixture_json("manual_baseline.json")["expected_deterministic"]


@pytest.fixture(scope="session")
def reduced_function_vitals() -> dict:
    return load_fixture_json("manual_reduced_function.json")["user_vitals"]


@pytest.fixture(scope="session")
def reduced_function_expected() -> dict:
    return load_fixture_json("manual_reduced_function.json")["expected_deterministic"]


@pytest.fixture(scope="session")
def partial_vitals() -> dict:
    return load_fixture_json("manual_partial_data.json")["user_vitals"]
