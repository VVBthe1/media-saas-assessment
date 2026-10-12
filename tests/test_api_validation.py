import uuid
from collections.abc import AsyncIterator
from unittest.mock import AsyncMock

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.exc import IntegrityError

from backend.app import app
from backend.db import get_session
from backend.models.tenant import Tenant, TenantStatus

TENANT_ID = uuid.UUID("11111111-1111-1111-1111-111111111111")


class _Session:
    def __init__(self, tenant: Tenant | None = None) -> None:
        self.tenant = tenant

    def add(self, _obj) -> None:
        return None

    async def get(self, _model, _id):
        return self.tenant

    async def flush(self) -> None:
        return None

    async def rollback(self) -> None:
        return None


def _override_session(session: _Session):
    async def _get_session() -> AsyncIterator[_Session]:
        yield session

    return _get_session


@pytest.fixture
async def client(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr("backend.app.connect", AsyncMock())
    monkeypatch.setattr("backend.app.disconnect", AsyncMock())
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as http:
        yield http
    app.dependency_overrides.clear()


def _error_code(response) -> str:
    return response.json()["error"]["code"]


@pytest.mark.asyncio
async def test_patch_while_provisioning_returns_update_not_allowed(client: AsyncClient) -> None:
    tenant = Tenant(
        id=TENANT_ID,
        slug="acme-corp",
        name="Acme",
        status=TenantStatus.PROVISIONING,
        version=1,
    )
    app.dependency_overrides[get_session] = _override_session(_Session(tenant))

    response = await client.patch(
        f"/tenants/{TENANT_ID}",
        json={"name": "New", "version": 1},
    )

    assert response.status_code == 409
    assert _error_code(response) == "tenant_update_not_allowed"


@pytest.mark.asyncio
async def test_post_empty_slug_returns_validation_error(client: AsyncClient) -> None:
    response = await client.post("/tenants", json={"name": "Acme", "slug": ""})

    assert response.status_code == 422
    assert _error_code(response) == "validation_error"


@pytest.mark.asyncio
async def test_patch_stale_version_returns_version_conflict(client: AsyncClient) -> None:
    tenant = Tenant(
        id=TENANT_ID,
        slug="acme-corp",
        name="Acme",
        status=TenantStatus.ACTIVE,
        version=5,
    )
    app.dependency_overrides[get_session] = _override_session(_Session(tenant))

    response = await client.patch(
        f"/tenants/{TENANT_ID}",
        json={"name": "Acme", "version": 2},
    )

    assert response.status_code == 409
    assert _error_code(response) == "tenant_version_conflict"


@pytest.mark.asyncio
async def test_post_duplicate_slug_returns_already_exists(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    class _Orig:
        sqlstate = "23505"

    class _DupSession(_Session):
        async def flush(self) -> None:
            raise IntegrityError("insert", {}, _Orig())

    monkeypatch.setattr(
        "backend.services.tenant_service.tenant_created.send_async",
        AsyncMock(return_value=[]),
    )
    monkeypatch.setattr(
        "backend.services.tenant_service.TenantSrv.publish_task_event",
        AsyncMock(),
    )
    app.dependency_overrides[get_session] = _override_session(_DupSession())

    response = await client.post(
        "/tenants",
        json={"name": "Acme", "slug": "taken-slug"},
    )

    assert response.status_code == 409
    assert _error_code(response) == "tenant_already_exists"
