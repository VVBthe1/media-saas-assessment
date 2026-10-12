from typing import Annotated
import logging
import uuid
from fastapi import Depends
from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError, SQLAlchemyError

from backend.exceptions import AppError
from backend.db import DBSession
from backend.events import task_created, tenant_created, tenant_deleted, tenant_updated
from backend.exceptions.tenant import (
    TenantAlreadyExists,
    TenantNotFound,
    TenantUpdateNotAllowed,
    TenantVersionConflict,
)
from backend.models.data_models.tenant import CreateTenantInput, ModifyTenantInput
from backend.models.tenant import Tenant, TenantStatus
from backend.services.slug_service import SlugService

logger = logging.getLogger("api")

UNIQUE_VIOLATION = "23505"

ALLOWED_TENANT_TRANSITIONS: dict[TenantStatus, frozenset[TenantStatus]] = {
    TenantStatus.PROVISIONING: frozenset({TenantStatus.ACTIVE, TenantStatus.FAILED}),
    TenantStatus.ACTIVE: frozenset({TenantStatus.UPDATING, TenantStatus.DESTROYING}),
    TenantStatus.UPDATING: frozenset({TenantStatus.ACTIVE, TenantStatus.FAILED}),
    TenantStatus.DESTROYING: frozenset({TenantStatus.DESTROYED, TenantStatus.FAILED}),
    TenantStatus.FAILED: frozenset({TenantStatus.DESTROYING}),
    TenantStatus.DESTROYED: frozenset(),
}


class TenantSrv:
    def __init__(self, db: DBSession) -> None:
        self.session = db

    async def tenant_list(
        self,
        offset: int = 0,
        limit: int = 50,
        statuses: list[TenantStatus] | None = None,
    ) -> list[Tenant]:
        stmt = select(Tenant).order_by(Tenant.created_at, Tenant.id).limit(limit).offset(offset)
        if statuses:
            stmt = stmt.where(Tenant.status.in_(statuses))
        tenants = await self.session.scalars(stmt)

        return tenants.all()

    async def tenant_get(self, tenant_id: uuid.UUID) -> Tenant:
        tenant = await self.session.get(Tenant, tenant_id)

        if not tenant:
            raise TenantNotFound()

        return tenant

    async def tenant_create(self, data: CreateTenantInput) -> Tenant:
        try:
            tenant = Tenant()
            tenant.name = data.name
            tenant.slug = data.slug

            if not tenant.slug:
                tenant.slug = SlugService.generate(data.name)

            SlugService.assert_valid(tenant.slug)

            tenant.version = 1
            self.session.add(tenant)
            await self.session.flush()
            results = await tenant_created.send_async(self, tenant=tenant, session=self.session)
            await self.session.commit()
            await self.publish_task_event(results)
            await self.session.refresh(tenant)
            logger.info(
                "setting tenant %s to provisioning (slug=%s, version=%s)",
                tenant.id,
                tenant.slug,
                tenant.version,
            )
            return tenant
        except IntegrityError as exc:
            await self.session.rollback()
            if getattr(exc.orig, "sqlstate", None) == UNIQUE_VIOLATION:
                raise TenantAlreadyExists(
                    message=(
                        f"Tenant with slug '{tenant.slug}' already in use. "
                        "If you provided the slug, try a variant (e.g. add -1)."
                    )
                ) from exc
            raise
        except (SQLAlchemyError, AppError):
            await self.session.rollback()
            raise

    async def tenant_update(self, tenant_id: uuid.UUID, data: ModifyTenantInput) -> Tenant:
        try:
            tenant = await self.session.get(Tenant, tenant_id)
            if not tenant:
                raise TenantNotFound()
            previous_status = tenant.status
            self.assert_status_transition_valid(tenant, TenantStatus.UPDATING)
            if tenant.version != data.version:
                raise TenantVersionConflict()

            stmt = (
                update(Tenant)
                .where(
                    Tenant.id == tenant_id,
                    Tenant.version == data.version,
                    Tenant.status == TenantStatus.ACTIVE,
                )
                .values(
                    name=data.name,
                    status=TenantStatus.UPDATING,
                    version=Tenant.version + 1,
                )
                .returning(Tenant.id)
            )
            if (await self.session.execute(stmt)).scalar_one_or_none() is None:
                raise TenantVersionConflict()

            results = await tenant_updated.send_async(self, tenant=tenant, session=self.session)
            await self.session.commit()
            await self.publish_task_event(results)
            await self.session.refresh(tenant)
            logger.info(
                "setting tenant %s from %s to %s (version=%s)",
                tenant.id,
                previous_status.value,
                tenant.status.value,
                tenant.version,
            )
            return tenant
        except (SQLAlchemyError, AppError):
            await self.session.rollback()
            raise

    async def tenant_delete(self, tenant_id: uuid.UUID) -> Tenant:
        try:
            tenant = await self.session.get(Tenant, tenant_id)
            if not tenant:
                raise TenantNotFound()
            previous_status = tenant.status
            self.assert_status_transition_valid(tenant, TenantStatus.DESTROYING)

            stmt = (
                update(Tenant)
                .where(
                    Tenant.id == tenant_id,
                    Tenant.version == tenant.version,
                )
                .values(
                    status=TenantStatus.DESTROYING,
                    version=Tenant.version + 1,
                )
                .returning(Tenant.id)
            )
            if (await self.session.execute(stmt)).scalar_one_or_none() is None:
                raise TenantVersionConflict()

            results = await tenant_deleted.send_async(self, tenant=tenant, session=self.session)
            await self.session.commit()
            await self.publish_task_event(results)
            await self.session.refresh(tenant)
            logger.info(
                "setting tenant %s from %s to %s (version=%s)",
                tenant.id,
                previous_status.value,
                tenant.status.value,
                tenant.version,
            )
            return tenant
        except (SQLAlchemyError, AppError):
            await self.session.rollback()
            raise

    async def apply_tenant_status(self, tenant_id: uuid.UUID, status: TenantStatus) -> Tenant:
        tenant = await self.session.get(Tenant, tenant_id)
        if not tenant:
            raise TenantNotFound()
        self.assert_status_transition_valid(tenant, status)
        tenant.status = status
        tenant.version += 1
        return tenant

    async def tenant_update_status(self, tenant_id: uuid.UUID, status: TenantStatus) -> Tenant:
        try:
            tenant = await self.apply_tenant_status(tenant_id, status)
            await self.session.commit()
            await self.session.refresh(tenant)
            return tenant
        except (SQLAlchemyError, AppError):
            await self.session.rollback()
            raise

    @classmethod
    def assert_status_transition_valid(cls, tenant: Tenant, status: TenantStatus) -> None:
        if status not in ALLOWED_TENANT_TRANSITIONS[tenant.status]:
            logger.info(
                "setting tenant %s from %s to %s is not allowed",
                tenant.id,
                tenant.status.value,
                status.value,
            )
            raise TenantUpdateNotAllowed(
                f"Tenant cannot move from '{tenant.status.value}' to '{status.value}'"
            )

    async def publish_task_event(self, event_results: list[tuple]):
        for _, task in event_results:
            if task is not None:
                await task_created.send_async(self, task=task)


TenantService = Annotated[TenantSrv, Depends()]
