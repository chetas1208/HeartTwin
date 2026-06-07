"""Tests for Agent 2: Multimodal Extraction Agent.

Verifies:
- Correct agent ID: multimodal_extraction.
- Extracts values from CSV files.
- Returns structured extracted_fields with source, confidence, method.
- Empty file list returns default output without crashing.
- User vitals are extracted with user_input source.
- Confidence field is populated.
- No values are invented (missing fields remain absent).
"""

from __future__ import annotations

import csv
import io

import pytest

from python.hearttwin.agents.extraction_agent import (
    _AGENT_ID,
    _AGENT_NAME,
    run_extraction_agent,
)
from python.hearttwin.schemas import AgentResponse, AgentStatus


# ---------------------------------------------------------------------------
# Agent identity
# ---------------------------------------------------------------------------


def test_extraction_agent_id_is_correct() -> None:
    assert _AGENT_ID == "multimodal_extraction"


def test_extraction_agent_name_set() -> None:
    assert _AGENT_NAME
    assert "Extraction" in _AGENT_NAME or "Multimodal" in _AGENT_NAME


# ---------------------------------------------------------------------------
# Empty input
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_extraction_empty_files_no_crash() -> None:
    result = await run_extraction_agent(files=[], user_vitals=None, case_id="test-ext-empty")
    assert isinstance(result, AgentResponse)
    assert result.status in (AgentStatus.SUCCESS, AgentStatus.WARNING, AgentStatus.FAILED)


@pytest.mark.asyncio
async def test_extraction_empty_files_returns_empty_fields() -> None:
    result = await run_extraction_agent(files=[], user_vitals=None, case_id="test-ext-empty2")
    extracted = result.outputs.get("extracted_fields", {})
    assert isinstance(extracted, dict)
    assert len(extracted) == 0


# ---------------------------------------------------------------------------
# CSV extraction
# ---------------------------------------------------------------------------


def _make_csv_bytes(data: dict[str, list]) -> bytes:
    output = io.StringIO()
    fieldnames = list(data.keys())
    writer = csv.DictWriter(output, fieldnames=fieldnames)
    writer.writeheader()
    rows = [dict(zip(fieldnames, vals)) for vals in zip(*data.values())]
    writer.writerows(rows)
    return output.getvalue().encode()


@pytest.mark.asyncio
async def test_extraction_from_csv_heart_rate() -> None:
    csv_bytes = _make_csv_bytes({"heart_rate": [72, 74, 73]})
    files = [{
        "file_id": "csv-1",
        "filename": "vitals.csv",
        "content_type": "text/csv",
        "bytes": csv_bytes,
    }]
    result = await run_extraction_agent(files=files, user_vitals=None, case_id="test-csv-hr")
    extracted = result.outputs.get("extracted_fields", {})
    assert "heart_rate_bpm" in extracted
    field = extracted["heart_rate_bpm"]
    assert "value" in field
    assert "source" in field
    assert "confidence" in field
    assert field["source"] == "extracted"
    assert field["method"] == "csv_parse"


@pytest.mark.asyncio
async def test_extraction_from_csv_ejection_fraction() -> None:
    csv_bytes = _make_csv_bytes({"ejection_fraction": [45.0, 46.0, 44.0]})
    files = [{
        "file_id": "csv-2",
        "filename": "echo.csv",
        "content_type": "text/csv",
        "bytes": csv_bytes,
    }]
    result = await run_extraction_agent(files=files, user_vitals=None, case_id="test-csv-ef")
    extracted = result.outputs.get("extracted_fields", {})
    assert "ejection_fraction_pct" in extracted


@pytest.mark.asyncio
async def test_extraction_confidence_in_range() -> None:
    csv_bytes = _make_csv_bytes({"hr": [80]})
    files = [{
        "file_id": "csv-3",
        "filename": "data.csv",
        "content_type": "text/csv",
        "bytes": csv_bytes,
    }]
    result = await run_extraction_agent(files=files, user_vitals=None, case_id="test-csv-conf")
    assert 0.0 <= result.confidence <= 1.0


@pytest.mark.asyncio
async def test_extraction_missing_field_not_invented() -> None:
    csv_bytes = _make_csv_bytes({"heart_rate": [72]})
    files = [{
        "file_id": "csv-4",
        "filename": "partial.csv",
        "content_type": "text/csv",
        "bytes": csv_bytes,
    }]
    result = await run_extraction_agent(files=files, user_vitals=None, case_id="test-csv-missing")
    extracted = result.outputs.get("extracted_fields", {})
    assert "troponin_ng_l" not in extracted


# ---------------------------------------------------------------------------
# User vitals
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_extraction_from_user_vitals() -> None:
    vitals = {
        "heart_rate_bpm": 80.0,
        "systolic_bp_mmhg": 120.0,
        "diastolic_bp_mmhg": 80.0,
    }
    result = await run_extraction_agent(files=[], user_vitals=vitals, case_id="test-vitals")
    extracted = result.outputs.get("extracted_fields", {})
    assert "heart_rate_bpm" in extracted
    assert extracted["heart_rate_bpm"]["source"] == "user_input"
    assert extracted["heart_rate_bpm"]["confidence"] >= 0.9


@pytest.mark.asyncio
async def test_extraction_user_vitals_none_values_skipped() -> None:
    vitals = {"heart_rate_bpm": 75.0, "troponin_ng_l": None}
    result = await run_extraction_agent(files=[], user_vitals=vitals, case_id="test-vitals-none")
    extracted = result.outputs.get("extracted_fields", {})
    assert "troponin_ng_l" not in extracted
    assert "heart_rate_bpm" in extracted


# ---------------------------------------------------------------------------
# Unsupported file type
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_extraction_unsupported_file_type_warns() -> None:
    files = [{
        "file_id": "dicom-1",
        "filename": "scan.dcm",
        "content_type": "application/dicom",
        "bytes": b"\x00\x01",
    }]
    result = await run_extraction_agent(files=files, user_vitals=None, case_id="test-ext-unsupported")
    assert len(result.warnings) > 0


# ---------------------------------------------------------------------------
# Response shape
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_extraction_response_has_agent_field() -> None:
    result = await run_extraction_agent(files=[], user_vitals=None, case_id="test-ext-agent")
    assert result.agent == "extraction_agent" or "extraction" in result.agent


@pytest.mark.asyncio
async def test_extraction_response_has_inputs_used() -> None:
    vitals = {"heart_rate_bpm": 72.0}
    result = await run_extraction_agent(files=[], user_vitals=vitals, case_id="test-ext-inputs")
    assert isinstance(result.inputs_used, list)
