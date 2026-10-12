#!/usr/bin/env python3
"""Assignment end-to-end suite. Stack must be running (docker compose up --build).

Run via: python scripts/e2e_suite.py (local) or docker compose --profile testing run --rm e2e.

Expects the compose simulator with fail-rate=0.

Covers: HTTP lifecycle (create → active → patch → delete → destroyed), failed →
DELETE → destroyed (`scripts/seed_failed_deploy.py` after HTTP create; DELETE/waits are HTTP),
concurrent slug/PATCH (expected 409s), and out-of-order/duplicate progress via
`scripts/publish_task_progress.py`.

Install: pip install -r requirements.txt (asyncpg + aio-pika).
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
import time
import urllib.error
import urllib.request
import uuid
from pathlib import Path

_SCRIPT_DIR = Path(__file__).resolve().parent
if str(_SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPT_DIR))

from publish_task_progress import publish_progress  # noqa: E402
from seed_failed_deploy import mark_tenant_failed  # noqa: E402

API_BASE = os.environ.get("API_BASE", "http://127.0.0.1:8000").rstrip("/")
POLL_TIMEOUT_SEC = float(os.environ.get("E2E_TIMEOUT_SEC", "120"))
POLL_INTERVAL_SEC = float(os.environ.get("E2E_POLL_INTERVAL_SEC", "1"))

SIMULATOR_HINT = "E2E expects the compose simulator with fail-rate=0."


def request(method: str, path: str, body: dict | None = None) -> tuple[int, dict]:
    url = f"{API_BASE}{path}"
    headers = {"Accept": "application/json"}
    data = None
    if body is not None:
        headers["Content-Type"] = "application/json"
        data = json.dumps(body).encode()
    req = urllib.request.Request(url, data=data, method=method, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            raw = resp.read().decode()
            return resp.status, json.loads(raw) if raw else {}
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode()
        try:
            return exc.code, json.loads(raw) if raw else {}
        except json.JSONDecodeError:
            return exc.code, {"raw": raw}


def log(step: str, status: int, payload: dict) -> None:
    print(f"\n=== {step} (HTTP {status}) ===")
    print(json.dumps(payload, indent=2, sort_keys=True))


def get_tenant(tenant_id: str) -> dict:
    code, body = request("GET", f"/tenants/{tenant_id}")
    if code != 200:
        raise RuntimeError(f"GET tenant {tenant_id} returned HTTP {code}: {body}")
    return body


def wait_tenant(
    tenant_id: str,
    want: str,
    *,
    timeout_sec: float | None = None,
) -> tuple[str, int]:
    timeout = timeout_sec if timeout_sec is not None else POLL_TIMEOUT_SEC
    deadline = time.monotonic() + timeout
    last: str | None = None
    while time.monotonic() < deadline:
        tenant = get_tenant(tenant_id)
        status = tenant["status"]
        version = int(tenant["version"])
        if status != last:
            print(f"  tenant {tenant_id[:8]}… status={status} version={version}")
            last = status
        if status == want:
            return status, version
        if status == "failed" and want != "failed":
            raise RuntimeError(f"tenant became failed while waiting for {want}. {SIMULATOR_HINT}")
        time.sleep(POLL_INTERVAL_SEC)
    raise TimeoutError(f"tenant did not reach {want} within {timeout}s (last status={last})")


def latest_deploy_task(tenant_id: str) -> dict | None:
    code, body = request("GET", f"/tenants/{tenant_id}/tasks?limit=50")
    if code != 200:
        raise RuntimeError(f"GET tasks returned HTTP {code}: {body}")
    deploys = [t for t in body["tasks"] if t["type"] == "deploy"]
    if not deploys:
        return None
    return max(deploys, key=lambda t: t["created_at"])


def wait_for_deploy_task(tenant_id: str, *, timeout_sec: float = 30) -> dict:
    deadline = time.monotonic() + timeout_sec
    while time.monotonic() < deadline:
        task = latest_deploy_task(tenant_id)
        if task is not None:
            return task
        time.sleep(0.1)
    raise TimeoutError(f"no deploy task for tenant {tenant_id} within {timeout_sec}s")


def wait_deploy_task(tenant_id: str, want: str, *, timeout_sec: float = 30) -> str:
    deadline = time.monotonic() + timeout_sec
    last: str | None = None
    while time.monotonic() < deadline:
        task = latest_deploy_task(tenant_id)
        if task is None:
            time.sleep(POLL_INTERVAL_SEC)
            continue
        task_id = str(task["id"])
        status = task["status"]
        if status != last:
            print(f"  deploy task {task_id[:8]}… status={status}")
            last = status
        if status == want:
            return task_id
        time.sleep(POLL_INTERVAL_SEC)
    raise TimeoutError(f"deploy task did not reach {want} within {timeout_sec}s")


def get_task(task_id: str) -> dict:
    code, body = request("GET", f"/tasks/{task_id}")
    if code != 200:
        raise RuntimeError(f"GET task {task_id} returned HTTP {code}: {body}")
    return body


def wait_task(task_id: str, want: str, *, timeout_sec: float | None = None) -> str:
    timeout = timeout_sec if timeout_sec is not None else POLL_TIMEOUT_SEC
    deadline = time.monotonic() + timeout
    last: str | None = None
    while time.monotonic() < deadline:
        status = get_task(task_id)["status"]
        if status != last:
            print(f"  task {task_id[:8]}… status={status}")
            last = status
        if status == want:
            return status
        time.sleep(POLL_INTERVAL_SEC)
    raise TimeoutError(f"task did not reach {want} within {timeout}s (last={last})")


def create_tenant(name: str, slug: str) -> dict:
    code, body = request("POST", "/tenants", {"name": name, "slug": slug})
    log("create tenant", code, body)
    if code != 202:
        raise RuntimeError("create failed")
    return body


async def concurrent_create_same_slug() -> None:
    slug = f"slug-race-{uuid.uuid4().hex[:8]}"
    payload = {"name": "Slug Race", "slug": slug}
    loop = asyncio.get_event_loop()

    async def create() -> tuple[int, dict]:
        return await loop.run_in_executor(
            None,
            lambda: request("POST", "/tenants", payload),
        )

    results = await asyncio.gather(create(), create())
    codes = [r[0] for r in results]
    already_exists = sum(
        1
        for r in results
        if r[0] == 409 and r[1].get("error", {}).get("code") == "tenant_already_exists"
    )
    successes = sum(1 for c in codes if c == 202)
    print("concurrent POST /tenants HTTP statuses:", codes)
    if successes != 1 or already_exists != 1:
        raise RuntimeError(f"expected one 202 and one tenant_already_exists, got {codes}")


async def concurrent_patch_race() -> None:
    slug = f"race-{uuid.uuid4().hex[:8]}"
    created = create_tenant("Race Test", slug)
    tenant_id = created["id"]
    _, version = wait_tenant(tenant_id, "active")

    async def patch(suffix: str) -> tuple[int, dict]:
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(
            None,
            lambda: request(
                "PATCH",
                f"/tenants/{tenant_id}",
                {"name": f"Race {suffix}", "version": version},
            ),
        )

    results = await asyncio.gather(patch("a"), patch("b"))
    codes = [r[0] for r in results]
    conflicts = sum(
        1
        for r in results
        if r[0] == 409 and r[1].get("error", {}).get("code") == "tenant_version_conflict"
    )
    successes = sum(1 for c in codes if c == 202)
    print("concurrent PATCH HTTP statuses:", codes)
    if successes != 1 or conflicts != 1:
        raise RuntimeError(f"expected one 202 and one version_conflict, got {codes}")


async def _publish_progress_logged(task_id: str, status: str, update_id: str) -> None:
    await publish_progress(task_id, status, update_id)
    print(f"published update_id={update_id} task_id={task_id} status={status}")


async def out_of_order_progress() -> None:
    slug = f"ooo-{uuid.uuid4().hex[:8]}"
    created = create_tenant("Out Of Order", slug)
    tenant_id = created["id"]
    wait_tenant(tenant_id, "active")

    task_id = wait_deploy_task(tenant_id, "done")
    wait_task(task_id, "done")

    stale_id = str(uuid.uuid4())
    await _publish_progress_logged(task_id, "in_progress", stale_id)
    wait_task(task_id, "done", timeout_sec=15)
    wait_tenant(tenant_id, "active", timeout_sec=15)
    print("OK: stale in_progress did not regress state")

    await _publish_progress_logged(task_id, "in_progress", stale_id)
    wait_task(task_id, "done", timeout_sec=15)
    print("OK: duplicate update_id ignored")

    await _publish_progress_logged(task_id, "in_progress", str(uuid.uuid4()))
    wait_task(task_id, "done", timeout_sec=15)
    wait_tenant(tenant_id, "active", timeout_sec=15)
    print("OK: out-of-order progress handling")


def failed_tenant_delete_destroyed() -> None:
    print("\n=== failed tenant → DELETE → destroyed ===")
    slug = f"fail-{uuid.uuid4().hex[:8]}"
    created = create_tenant("Failed Deploy", slug)
    tenant_id = created["id"]
    wait_for_deploy_task(tenant_id)
    mark_tenant_failed(tenant_id)
    print(f"  seeded Postgres: tenant {tenant_id[:8]}… → failed (deploy task failed)")
    wait_tenant(tenant_id, "failed")

    code, deleted = request("DELETE", f"/tenants/{tenant_id}")
    log("delete failed tenant", code, deleted)
    if code != 202:
        raise RuntimeError("DELETE from failed failed")
    wait_tenant(tenant_id, "destroyed")


async def run_async_checks() -> None:
    print("\n=== out-of-order / duplicate progress ===")
    await out_of_order_progress()

    print("\n=== concurrent create (same slug) ===")
    await concurrent_create_same_slug()

    print("\n=== concurrent PATCH (same version) ===")
    await concurrent_patch_race()


def main() -> int:
    print(f"API_BASE={API_BASE}")
    print(f"({SIMULATOR_HINT})")

    code, health = request("GET", "/health")
    if code != 200:
        log("health", code, health)
        return 1
    log("health", code, health)

    slug = f"e2e-{uuid.uuid4().hex[:8]}"
    created = create_tenant("E2E Lifecycle", slug)
    tenant_id = created["id"]
    _, version = wait_tenant(tenant_id, "active")

    code, updated = request(
        "PATCH",
        f"/tenants/{tenant_id}",
        {"name": "E2E Lifecycle Updated", "version": version},
    )
    log("update tenant", code, updated)
    if code != 202:
        return 1
    wait_tenant(tenant_id, "active")

    code, deleted = request("DELETE", f"/tenants/{tenant_id}")
    log("delete tenant", code, deleted)
    if code != 202:
        return 1
    wait_tenant(tenant_id, "destroyed")

    failed_tenant_delete_destroyed()

    asyncio.run(run_async_checks())

    print("\nFull E2E suite passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
