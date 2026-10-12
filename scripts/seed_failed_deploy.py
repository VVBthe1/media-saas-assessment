#!/usr/bin/env python3
"""Mark a tenant's deploy task and the tenant as failed (test harness).

Prefer reproducing failure via the simulator (--fail-rate=1) when demoing manually.
This script is for deterministic automation (e2e) without changing simulator flags.

Usage:
  python scripts/seed_failed_deploy.py <tenant-uuid>

Env: E2E_DATABASE_URL or DATABASE_URL (asyncpg DSN is normalized to plain postgres).
"""

from __future__ import annotations

import asyncio
import os
import sys

import asyncpg


def pg_dsn() -> str:
    raw = os.environ.get(
        "E2E_DATABASE_URL",
        os.environ.get(
            "DATABASE_URL",
            "postgresql://postgres:postgres@127.0.0.1:5432/control_plane",
        ),
    )
    return raw.replace("postgresql+asyncpg://", "postgresql://")


def mark_tenant_failed(tenant_id: str) -> None:
    asyncio.run(_mark_tenant_failed(tenant_id))


async def _mark_tenant_failed(tenant_id: str) -> None:
    conn = await asyncpg.connect(pg_dsn())
    try:
        async with conn.transaction():
            await conn.execute(
                """
                UPDATE tasks
                SET status = 'failed'::task_status, updated_at = NOW()
                WHERE tenant_id = $1::uuid AND type = 'deploy'::task_type
                """,
                tenant_id,
            )
            await conn.execute(
                """
                UPDATE tenants
                SET status = 'failed'::tenant_status,
                    version = version + 1,
                    updated_at = NOW()
                WHERE id = $1::uuid
                """,
                tenant_id,
            )
    finally:
        await conn.close()


def main() -> None:
    if len(sys.argv) != 2:
        print("usage: seed_failed_deploy.py <tenant-uuid>", file=sys.stderr)
        sys.exit(2)
    tenant_id = sys.argv[1]
    mark_tenant_failed(tenant_id)
    print(f"tenant {tenant_id[:8]}… deploy failed (task + tenant set to failed)")


if __name__ == "__main__":
    main()
