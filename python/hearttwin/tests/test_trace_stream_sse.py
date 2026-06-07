"""Tests for the live SSE trace stream (GET /cases/{id}/trace/stream).

The web frontend (useTraceStream) renders the agent pipeline live by opening an
EventSource against this endpoint. The stream polls weave_trace.get_traces (the
same in-process source as GET /trace) and emits each entry under the stable SSE
event name "trace", with the real kind carried in the JSON data payload.

The happy-path tests drive the async generator directly rather than through a
streaming TestClient: the endpoint loops forever (polling), so a real streaming
client would block. Driving the generator with a stub request that disconnects
after one poll keeps the tests deterministic and fast.
"""

from __future__ import annotations

import json

from fastapi.testclient import TestClient

import python.hearttwin.api as api
from python.hearttwin.api import app

from .conftest import load_fixture_json

client = TestClient(app)

BASELINE_VITALS = load_fixture_json("manual_baseline.json")["user_vitals"]


class _StubRequest:
    """Minimal stand-in for starlette Request: headers + disconnect control."""

    def __init__(self, headers: dict | None = None, disconnect_after: int = 1) -> None:
        self.headers = headers or {}
        self._calls = 0
        self._disconnect_after = disconnect_after

    async def is_disconnected(self) -> bool:
        self._calls += 1
        return self._calls > self._disconnect_after


def _parse_sse(text: str) -> list[dict]:
    """Parse raw SSE text into a list of {id, event, data} records."""
    records: list[dict] = []
    current: dict = {}
    for line in text.splitlines():
        if line == "":
            if current:
                records.append(current)
                current = {}
            continue
        if line.startswith(":"):  # comment / keep-alive ping
            continue
        field, _, value = line.partition(":")
        value = value[1:] if value.startswith(" ") else value
        if field == "data":
            current["data"] = json.loads(value)
        else:
            current[field] = value
    if current:
        records.append(current)
    return records


async def _drain(case_id: str, last_id: str | None, monkeypatch) -> list[dict]:
    """Run one poll of the stream generator and return parsed SSE records."""
    monkeypatch.setattr(api, "_TRACE_STREAM_POLL_SECONDS", 0)
    request = _StubRequest()
    chunks = [chunk async for chunk in api._trace_stream_events(case_id, request, last_id)]
    return _parse_sse("".join(chunks))


def _make_case_with_traces() -> str:
    cid = client.post("/api/v1/cases", json={}).json()["case_id"]
    r = client.post(
        f"/api/v1/cases/{cid}/extract",
        json={"file_ids": [], "user_vitals": BASELINE_VITALS},
    )
    assert r.status_code == 200, r.text
    r = client.post(f"/api/v1/cases/{cid}/operate", json={})
    assert r.status_code == 200, r.text
    return cid


def test_trace_stream_unknown_case_404() -> None:
    # 404 is raised before streaming begins, so a normal GET is safe here.
    r = client.get("/api/v1/cases/does-not-exist/trace/stream")
    assert r.status_code == 404


async def test_trace_stream_emits_setup_and_trace_events(monkeypatch) -> None:
    cid = _make_case_with_traces()
    records = await _drain(cid, None, monkeypatch)
    assert records, "no SSE records parsed"

    # Every record is delivered under the single stable event name "trace".
    assert all(rec["event"] == "trace" for rec in records)

    setup = records[0]
    assert setup["data"]["kind"] == "stream_setup"
    assert setup["data"]["source"] == "local"
    assert setup["id"] == f"setup:{cid}"

    trace_events = [r for r in records[1:] if r["data"]["kind"] != "stream_setup"]
    assert trace_events, "expected at least one trace event after setup"
    first = trace_events[0]
    assert first["id"].startswith("local-")
    assert first["data"]["source"] == "local"
    assert "payload" in first["data"]


async def test_trace_stream_resume_skips_seen_events(monkeypatch) -> None:
    cid = _make_case_with_traces()
    records = await _drain(cid, "local-2", monkeypatch)
    trace_ids = [r["id"] for r in records if r["data"]["kind"] != "stream_setup"]
    assert trace_ids, "expected trace events after resume"
    # Resuming from local-2 must not replay local-1 / local-2.
    assert "local-1" not in trace_ids
    assert "local-2" not in trace_ids
