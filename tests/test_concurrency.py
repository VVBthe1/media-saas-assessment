import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlalchemy.exc import IntegrityError

from backend.exceptions.tenant import TenantAlreadyExists, TenantVersionConflict
from backend.models.data_models.tenant import ModifyTenantInput
from backend.models.tenant import Tenant, TenantStatus
from backend.services.tenant_service import TenantSrv


@pytest.mark.asyncio
async def test_tenant_update_rejects_mismatched_version_in_payload() -> None:
    tenant_id = uuid.uuid4()
    tenant = Tenant(
        id=tenant_id,
        slug="acme-corp",
        name="Acme",
        status=TenantStatus.ACTIVE,
        version=3,
    )

    class _Session:
        async def get(self, _model, _id):
            return tenant

        async def rollback(self):
            pass

    srv = TenantSrv(_Session())  # type: ignore[arg-type]
    with pytest.raises(TenantVersionConflict):
        await srv.tenant_update(tenant_id, ModifyTenantInput(name="Acme", version=2))


@pytest.mark.asyncio
async def test_tenant_update_rejects_when_optimistic_update_affects_no_row(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tenant_id = uuid.uuid4()
    tenant = Tenant(
        id=tenant_id,
        slug="acme-corp",
        name="Acme",
        status=TenantStatus.ACTIVE,
        version=2,
    )

    class _Session:
        async def get(self, _model, _id):
            return tenant

        async def execute(self, _stmt):
            return MagicMock(scalar_one_or_none=lambda: None)

        async def rollback(self):
            pass

    monkeypatch.setattr(
        "backend.services.tenant_service.tenant_updated.send_async",
        AsyncMock(return_value=[]),
    )
    monkeypatch.setattr(
        "backend.services.tenant_service.TenantSrv.publish_task_event",
        AsyncMock(),
    )

    srv = TenantSrv(_Session())  # type: ignore[arg-type]
    with pytest.raises(TenantVersionConflict):
        await srv.tenant_update(tenant_id, ModifyTenantInput(name="Acme 2", version=2))


@pytest.mark.asyncio
async def test_tenant_create_maps_duplicate_slug_to_already_exists(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _Orig:
        sqlstate = "23505"

    class _Session:
        def add(self, _obj):
            pass

        async def flush(self):
            raise IntegrityError("insert", {}, _Orig())

        async def rollback(self):
            pass

    monkeypatch.setattr(
        "backend.services.tenant_service.tenant_created.send_async",
        AsyncMock(return_value=[]),
    )
    monkeypatch.setattr(
        "backend.services.tenant_service.SlugService.generate",
        lambda _name: "taken-slug",
    )
    monkeypatch.setattr(
        "backend.services.tenant_service.SlugService.assert_valid",
        lambda _slug: None,
    )

    from backend.models.data_models.tenant import CreateTenantInput

    srv = TenantSrv(_Session())  # type: ignore[arg-type]
    with pytest.raises(TenantAlreadyExists):
        await srv.tenant_create(CreateTenantInput(name="New", slug="taken-slug"))
