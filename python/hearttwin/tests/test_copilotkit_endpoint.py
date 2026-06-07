"""Tests for the CopilotKit (AG-UI) backend.

Covers:
  * The /copilotkit endpoint is mounted and answers the runtime handshake.
  * All five actions are exposed with correct names + parameters.
  * The deterministic actions (create_case -> extract -> operate ->
    simulate_recovery) drive the pipeline and produce the golden numbers.
  * answer_case_question performs the OpenAI call AND safety-checks both the
    incoming question and the model output. The OpenAI client is patched here
    so the gate runs offline; a separate live script exercises real OpenAI.
"""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from python.hearttwin import copilot
from python.hearttwin.api import app
from python.hearttwin.safety import SafetyViolation

GOLDEN_VITALS = {
    "heart_rate_bpm": 88.0,
    "systolic_bp_mmhg": 135.0,
    "diastolic_bp_mmhg": 85.0,
    "edv_ml": 130.0,
    "esv_ml": 70.0,
}

ACTION_NAMES = {
    "create_case",
    "extract",
    "operate",
    "simulate_recovery",
    "answer_case_question",
}


# ---------------------------------------------------------------------------
# Endpoint handshake
# ---------------------------------------------------------------------------


def _client():
    from fastapi.testclient import TestClient

    return TestClient(app)


def test_copilotkit_info_handshake():
    """CopilotKit runtime handshake at /copilotkit/info returns 200 + actions."""
    client = _client()
    resp = client.post("/copilotkit/info", json={"properties": {}})
    assert resp.status_code == 200
    body = resp.json()
    assert body["sdkVersion"]
    names = {a["name"] for a in body["actions"]}
    assert names == ACTION_NAMES


def test_copilotkit_root_handshake():
    """The root path also answers the info request (CopilotKit v2 handshake)."""
    client = _client()
    resp = client.post("/copilotkit/", json={"properties": {}})
    assert resp.status_code == 200
    names = {a["name"] for a in resp.json()["actions"]}
    assert names == ACTION_NAMES


def test_actions_have_expected_parameters():
    actions = {a.name: a for a in copilot.build_actions()}
    assert set(actions) == ACTION_NAMES

    create = actions["create_case"].dict_repr()
    assert {p["name"] for p in create["parameters"]} == {"patient_notes"}

    extract = actions["extract"].dict_repr()
    extract_params = {p["name"] for p in extract["parameters"]}
    assert "case_id" in extract_params
    assert "heart_rate_bpm" in extract_params and "esv_ml" in extract_params

    answer = actions["answer_case_question"].dict_repr()
    assert {p["name"] for p in answer["parameters"]} == {"case_id", "question"}


def test_execute_action_endpoint_creates_case():
    """Executing create_case through the HTTP action route returns a case_id."""
    client = _client()
    resp = client.post(
        "/copilotkit/action/create_case",
        json={"arguments": {}},
    )
    assert resp.status_code == 200
    result = resp.json()["result"]
    assert result["ok"] is True
    assert result["case_id"]


# ---------------------------------------------------------------------------
# Deterministic pipeline via copilot actions
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_deterministic_pipeline_golden_numbers():
    case = await copilot.create_case()
    case_id = case["case_id"]
    assert case["ok"] is True

    extracted = await copilot.extract(case_id, **GOLDEN_VITALS)
    assert extracted["ok"] is True
    assert extracted["validated_field_count"] == 5

    operated = await copilot.operate(case_id)
    assert operated["ok"] is True
    summary = operated["summary"]
    # Golden: EF ~46.15, SV 60, CO 5.28, MAP 101.67 (rounded in viz to 1 dp)
    assert abs(summary["ef_pct"] - 46.15) < 0.5
    assert abs(summary["stroke_volume_ml"] - 60.0) < 0.5
    assert abs(summary["cardiac_output_l_min"] - 5.28) < 0.05
    assert abs(summary["map_mmhg"] - 101.7) < 0.2

    recovery = await copilot.simulate_recovery(case_id)
    assert recovery["ok"] is True
    assert recovery["scenario_count"] >= 1


@pytest.mark.asyncio
async def test_operate_requires_extract():
    case = await copilot.create_case()
    with pytest.raises(ValueError):
        await copilot.operate(case["case_id"])


@pytest.mark.asyncio
async def test_recovery_requires_operate():
    case = await copilot.create_case()
    await copilot.extract(case["case_id"], **GOLDEN_VITALS)
    with pytest.raises(ValueError):
        await copilot.simulate_recovery(case["case_id"])


@pytest.mark.asyncio
async def test_extract_rejects_unsafe_vitals_keys():
    # patient_notes safety gate on create_case
    with pytest.raises(SafetyViolation):
        await copilot.create_case("please give me a diagnosis")


# ---------------------------------------------------------------------------
# answer_case_question — safety + OpenAI (patched)
# ---------------------------------------------------------------------------


class _FakeMessage:
    def __init__(self, content: str) -> None:
        self.content = content


class _FakeChoice:
    def __init__(self, content: str) -> None:
        self.message = _FakeMessage(content)


class _FakeCompletion:
    def __init__(self, content: str) -> None:
        self.choices = [_FakeChoice(content)]


def _patch_openai(monkeypatch, content: str):
    """Patch openai.AsyncOpenAI so the action's model call returns `content`."""

    async def _create(*args, **kwargs):
        return _FakeCompletion(content)

    fake_client = SimpleNamespace(
        chat=SimpleNamespace(completions=SimpleNamespace(create=_create))
    )

    import openai

    monkeypatch.setattr(openai, "AsyncOpenAI", lambda *a, **k: fake_client)
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")


async def _prepared_case():
    case = await copilot.create_case()
    case_id = case["case_id"]
    await copilot.extract(case_id, **GOLDEN_VITALS)
    await copilot.operate(case_id)
    return case_id


@pytest.mark.asyncio
async def test_answer_returns_clean_answer(monkeypatch):
    _patch_openai(
        monkeypatch,
        "The simulated ejection fraction in this run is approximately 46%, "
        "computed deterministically from the end-diastolic and end-systolic "
        "volumes. This is an educational simulation only.",
    )
    case_id = await _prepared_case()
    result = await copilot.answer_case_question(case_id, "What is the ejection fraction?")
    assert result["ok"] is True
    assert "46" in result["answer"]
    assert result["safety_disclaimer"]


@pytest.mark.asyncio
async def test_answer_blocks_unsafe_question(monkeypatch):
    _patch_openai(monkeypatch, "irrelevant — should never be reached")
    case_id = await _prepared_case()
    with pytest.raises(SafetyViolation):
        await copilot.answer_case_question(case_id, "What treatment should I take for this?")


@pytest.mark.asyncio
async def test_answer_blocks_unsafe_model_output(monkeypatch):
    """Even a clean question must be blocked if the MODEL emits clinical advice."""
    _patch_openai(
        monkeypatch,
        "Your diagnosis is heart failure and you should take 50 milligrams of "
        "lisinopril daily.",
    )
    case_id = await _prepared_case()
    with pytest.raises(SafetyViolation):
        await copilot.answer_case_question(case_id, "Tell me about the ejection fraction")


@pytest.mark.asyncio
async def test_answer_uses_deterministic_fallback_without_openai_key(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    case_id = await _prepared_case()
    result = await copilot.answer_case_question(case_id, "What is the ejection fraction?")
    assert result["ok"] is True
    assert result["model"] == "deterministic_fallback"
    assert "simulated ejection fraction" in result["answer"]
    assert result["safety_disclaimer"]


@pytest.mark.asyncio
async def test_answer_requires_operate(monkeypatch):
    _patch_openai(monkeypatch, "n/a")
    case = await copilot.create_case()
    await copilot.extract(case["case_id"], **GOLDEN_VITALS)
    with pytest.raises(ValueError):
        await copilot.answer_case_question(case["case_id"], "What is the ejection fraction?")


def test_output_safety_guard_is_not_bypassable():
    """Direct unit test of the output guard across several evasions."""
    blocked_outputs = [
        "Your diagnosis is myocardial infarction.",
        "I recommend you take aspirin.",
        "The recommended treatment is beta blockers.",
        "Start taking your medication immediately.",
        "Clinically, this looks abnormal.",
    ]
    for out in blocked_outputs:
        with pytest.raises(SafetyViolation):
            copilot._check_output_safety(out)

    # Clean, simulation-framed answers must pass.
    copilot._check_output_safety(
        "The simulated ejection fraction is about 46% in this educational run."
    )
    copilot._check_output_safety(
        "Stroke volume in the simulation is 60 mL and cardiac output is 5.28 L/min."
    )


def test_state_snapshot_excludes_raw_notes():
    """The LLM snapshot must not leak raw patient notes."""
    from python.hearttwin.schemas import CaseRecord

    case = CaseRecord(patient_notes="John Doe SSN 123-45-6789", status="operated")
    case.simulation_result = {"summary": {"ef_pct": 46.2}}
    snapshot = copilot._build_state_snapshot(case)
    serialized = json.dumps(snapshot)
    assert "John Doe" not in serialized
    assert "123-45-6789" not in serialized
    assert snapshot["simulation_summary"]["ejection_fraction_pct"] == 46.2
