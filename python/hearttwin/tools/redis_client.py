"""Standard Redis client (async) — the single source of truth for Redis.

Uses the standard Redis protocol via ``redis.asyncio`` and a ``REDIS_URL``
(``redis://`` or ``rediss://``). This replaces the previous Upstash REST
integration: HeartTwin now talks to any standard Redis (self-hosted, Redis
Cloud, a managed rediss:// endpoint, etc.).

Policy (per the project's no-silent-fallback rule):
  * If ``REDIS_URL`` is unset, callers use in-process memory.
  * If ``REDIS_URL`` IS set, connection/command errors are allowed to surface —
    we never silently mask a configured-but-broken Redis.
"""

from __future__ import annotations

import os
from typing import Any, Optional

_CLIENT: Any | None = None
_CLIENT_URL: str | None = None


def redis_url() -> str:
    return os.environ.get("REDIS_URL", "").strip()


def is_configured() -> bool:
    return bool(redis_url())


def get_client() -> Optional[Any]:
    """Return a shared ``redis.asyncio`` client, or ``None`` if unconfigured.

    The client is recreated if ``REDIS_URL`` changes (so tests can repoint it).
    """
    global _CLIENT, _CLIENT_URL
    url = redis_url()
    if not url:
        return None
    if _CLIENT is None or _CLIENT_URL != url:
        import redis.asyncio as redis  # imported lazily so the dep is optional

        _CLIENT = redis.from_url(url, decode_responses=True)
        _CLIENT_URL = url
    return _CLIENT


async def ping() -> bool:
    """True if a configured Redis answers PING. Raises if configured-but-broken."""
    client = get_client()
    if client is None:
        return False
    return bool(await client.ping())


def reset_client() -> None:
    """Drop the cached client (tests / config changes)."""
    global _CLIENT, _CLIENT_URL
    _CLIENT = None
    _CLIENT_URL = None
