"""Storage tool: Vercel Blob or in-memory fallback.

Files go to Vercel Blob when configured.
Case state goes to Upstash Redis when configured.
Falls back to in-memory for local development.
"""

from __future__ import annotations

import json
import os
import uuid
from typing import Any, Optional

from python.hearttwin.tools.env_config import redis_memory_enabled

_MEMORY_STORE: dict[str, Any] = {}
_FILE_STORE: dict[str, bytes] = {}


async def store_file(
    file_bytes: bytes,
    filename: str,
    content_type: str,
) -> tuple[str, Optional[str]]:
    """Store file. Returns (file_id, storage_url or None)."""
    file_id = str(uuid.uuid4())
    blob_token = os.environ.get("BLOB_READ_WRITE_TOKEN", "")

    if blob_token:
        try:
            import httpx
            response = await httpx.AsyncClient().put(
                f"https://blob.vercel-storage.com/{file_id}/{filename}",
                headers={
                    "Authorization": f"Bearer {blob_token}",
                    "x-content-type": content_type,
                },
                content=file_bytes,
                timeout=30.0,
            )
            if response.status_code == 200:
                data = response.json()
                return file_id, data.get("url")
        except Exception:
            pass

    _FILE_STORE[file_id] = file_bytes
    return file_id, None


async def get_file(file_id: str) -> Optional[bytes]:
    """Retrieve file bytes by ID."""
    blob_token = os.environ.get("BLOB_READ_WRITE_TOKEN", "")

    if blob_token:
        pass

    return _FILE_STORE.get(file_id)


async def store_case(case_id: str, case_data: dict) -> None:
    """Store case record in Redis or memory."""
    redis_url = os.environ.get("UPSTASH_REDIS_REST_URL", "")
    redis_token = os.environ.get("UPSTASH_REDIS_REST_TOKEN", "")

    if redis_memory_enabled() and redis_url and redis_token:
        try:
            import httpx
            payload = json.dumps(case_data)
            # Upstash REST stores the request body verbatim as the value.
            # Send the serialized JSON as raw content (NOT json=, which would
            # wrap it in an extra layer of JSON quoting and corrupt round-trips).
            response = await httpx.AsyncClient().post(
                f"{redis_url}/set/case:{case_id}",
                headers={
                    "Authorization": f"Bearer {redis_token}",
                    "Content-Type": "text/plain",
                },
                content=payload,
                timeout=10.0,
            )
            response.raise_for_status()
            return
        except Exception:
            pass

    _MEMORY_STORE[f"case:{case_id}"] = case_data


async def get_case(case_id: str) -> Optional[dict]:
    """Retrieve case record."""
    redis_url = os.environ.get("UPSTASH_REDIS_REST_URL", "")
    redis_token = os.environ.get("UPSTASH_REDIS_REST_TOKEN", "")

    if redis_memory_enabled() and redis_url and redis_token:
        try:
            import httpx
            response = await httpx.AsyncClient().get(
                f"{redis_url}/get/case:{case_id}",
                headers={"Authorization": f"Bearer {redis_token}"},
                timeout=10.0,
            )
            if response.status_code == 200:
                data = response.json()
                result = data.get("result")
                if result:
                    parsed = json.loads(result)
                    # Tolerate legacy double-encoded values (a JSON string that
                    # itself contains JSON) so old records still deserialize.
                    if isinstance(parsed, str):
                        parsed = json.loads(parsed)
                    if isinstance(parsed, dict):
                        return parsed
        except Exception:
            pass

    return _MEMORY_STORE.get(f"case:{case_id}")


async def list_cases() -> list[str]:
    """List all case IDs (memory only for now)."""
    return [k.replace("case:", "") for k in _MEMORY_STORE if k.startswith("case:")]


async def delete_case(case_id: str) -> None:
    """Delete a case record."""
    _MEMORY_STORE.pop(f"case:{case_id}", None)
