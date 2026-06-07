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
