#!/usr/bin/env python3
"""Live reachability + integration smoke for standard Redis and W&B Weave.

Loads .env, then verifies BOTH the raw service (so a memory/local fallback
can't mask a broken integration) AND the app's own code path.

Usage:  python scripts/smoke_redis_weave.py
Exit:   0 = all configured integrations reachable, 1 = a failure.
"""

from __future__ import annotations

import asyncio
import json
import os
import pathlib
import sys

# UTF-8 console so PASS/FAIL lines never crash on a legacy Windows code page.
try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except Exception:  # noqa: BLE001
    pass

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

try:
    from dotenv import load_dotenv

    load_dotenv(ROOT / ".env")
except Exception as exc:  # noqa: BLE001
    print(f"! could not load .env: {exc}")

PASS, FAIL, SKIP = "PASS", "FAIL", "SKIP"
results: list[tuple[str, str, str]] = []


def record(name: str, status: str, detail: str = "") -> None:
    results.append((name, status, detail))
    print(f"[{status}] {name}{(' - ' + detail) if detail else ''}")


async def check_redis() -> None:
    from python.hearttwin.tools import redis_client, storage

    if not redis_client.is_configured():
        record("redis: REDIS_URL", SKIP, "REDIS_URL not set (using in-memory fallback)")
        return
    url = redis_client.redis_url()
    record("redis: REDIS_URL", PASS, f"{url.split('@')[-1][:32]}")

    # 1. Raw reachability + auth via the standard client.
    try:
        if await redis_client.ping():
            record("redis: PING", PASS, "PONG")
        else:
            record("redis: PING", FAIL, "no client")
            return
    except Exception as exc:  # noqa: BLE001
        record("redis: PING", FAIL, f"{type(exc).__name__}: {exc}")
        return

    # 2. The app writes case state, and it actually lands in Redis.
    cid = f"smoke-{os.urandom(4).hex()}"
    payload = {"case_id": cid, "marker": "live-smoke", "n": 42}
    try:
        await storage.store_case(cid, payload)
        client = redis_client.get_client()
        raw = await client.get(f"case:{cid}")
        landed = raw is not None and json.loads(raw).get("marker") == "live-smoke"
        record("redis: store_case lands in Redis", PASS if landed else FAIL,
               "value present" if landed else "NOT in Redis")
    except Exception as exc:  # noqa: BLE001
        record("redis: store_case", FAIL, f"{type(exc).__name__}: {exc}")
        return

    # 3. App round-trip + list + delete.
    got = await storage.get_case(cid)
    record("redis: get_case round-trip", PASS if (got and got.get("marker") == "live-smoke") else FAIL,
           "ok" if got else "no value")
    listed = cid in (await storage.list_cases())
    record("redis: list_cases", PASS if listed else FAIL, "case listed" if listed else "missing")
    await storage.delete_case(cid)
    gone = await storage.get_case(cid)
    record("redis: delete_case", PASS if gone is None else FAIL, "deleted" if gone is None else "still present")


def check_weave() -> None:
    if not os.environ.get("WANDB_API_KEY"):
        record("weave: WANDB_API_KEY", SKIP, "not set")
        return
    project = os.environ.get("WANDB_PROJECT", "hearttwin-weavehacks")
    entity = os.environ.get("WANDB_ENTITY", "")
    record("weave: WANDB_API_KEY", PASS, f"project={project} entity={entity or '(default)'}")

    from python.hearttwin.tools import weave_trace

    try:
        ok = weave_trace._init_weave()
        record("weave: weave.init()", PASS if ok else FAIL,
               "client created" if ok else f"failed: {weave_trace._WEAVE_WARNINGS[-1] if weave_trace._WEAVE_WARNINGS else 'unknown'}")
        if not ok:
            return
    except Exception as exc:  # noqa: BLE001
        record("weave: weave.init()", FAIL, f"{type(exc).__name__}: {exc}")
        return

    try:
        sink = weave_trace.get_trace_sink()
        run_id = sink.start_run("smoke-case", "smoke", {"source": "smoke_redis_weave"})
        sink.log_agent_stage(run_id, {"agent": "smoke_agent", "status": "ok", "stage": "smoke"})
        sink.finish_run(run_id, "ok", {"note": "live smoke"})
        record("weave: start/log/finish run", PASS, f"run_id={run_id}")
    except Exception as exc:  # noqa: BLE001
        record("weave: trace run", FAIL, f"{type(exc).__name__}: {exc}")

    url = weave_trace.get_project_url()
    record("weave: project url", PASS if url else FAIL, url or "none")


def main() -> int:
    print("== HeartTwin live integration smoke (Redis + Weave) ==\n")
    asyncio.run(check_redis())
    print()
    check_weave()
    print()
    failures = [r for r in results if r[1] == FAIL]
    print(f"== {len(failures)} failure(s); "
          f"{sum(1 for r in results if r[1] == PASS)} pass; "
          f"{sum(1 for r in results if r[1] == SKIP)} skip ==")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
