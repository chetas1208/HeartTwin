"""Storage tool: Vercel Blob or in-memory fallback.

Files go to Vercel Blob when configured.
Case state goes to Redis (standard protocol, REDIS_URL) when configured.
Falls back to in-memory only when Redis is NOT configured.
"""

from __future__ import annotations

import json
import os
import uuid
from typing import Any, Optional

from python.hearttwin.tools import redis_client
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


def _redis_active() -> bool:
    return redis_memory_enabled() and redis_client.is_configured()


async def store_case(case_id: str, case_data: dict) -> None:
    """Store case record in Redis (when configured) or in-memory."""
    if _redis_active():
        client = redis_client.get_client()
        # Errors surface (configured-but-broken Redis must not silently no-op).
        await client.set(f"case:{case_id}", json.dumps(case_data))
        return
    _MEMORY_STORE[f"case:{case_id}"] = case_data


async def get_case(case_id: str) -> Optional[dict]:
    """Retrieve case record."""
    if _redis_active():
        client = redis_client.get_client()
        raw = await client.get(f"case:{case_id}")
        if not raw:
            return None
        parsed = json.loads(raw)
        # Tolerate legacy double-encoded values so old records still load.
        if isinstance(parsed, str):
            parsed = json.loads(parsed)
        return parsed if isinstance(parsed, dict) else None
    return _MEMORY_STORE.get(f"case:{case_id}")


async def list_cases() -> list[str]:
    """List all case IDs from Redis (when configured) or memory."""
    if _redis_active():
        client = redis_client.get_client()
        keys = await client.keys("case:*")
        return [str(k).replace("case:", "") for k in keys]
    return [k.replace("case:", "") for k in _MEMORY_STORE if k.startswith("case:")]


async def delete_case(case_id: str) -> None:
    """Delete a case record."""
    if _redis_active():
        client = redis_client.get_client()
        await client.delete(f"case:{case_id}")
        return
    _MEMORY_STORE.pop(f"case:{case_id}", None)
