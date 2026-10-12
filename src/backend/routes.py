from typing import Annotated
import uuid
from fastapi import APIRouter, Query

from backend.models.data_models.task import TaskListResponse, TaskResponse
from backend.models.data_models.tenant import (
    CreateTenantInput,
    ModifyTenantInput,
    TenantListResponse,
    TenantResponse,
)
from backend.models.tenant import TenantStatus
from backend.services.task_service import TaskService
from backend.services.tenant_service import TenantService

router = APIRouter()
tenant_router = APIRouter(prefix="/tenants")
task_router = APIRouter(prefix="/tasks")


# general routes
@router.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


# tenant routes
@tenant_router.get("")
async def tenant_list(
    service: TenantService,
    offset: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    status: Annotated[list[TenantStatus] | None, Query()] = None,
) -> TenantListResponse:
    tenants = await service.tenant_list(offset=offset, limit=limit, statuses=status)

    return TenantListResponse(tenants=tenants, offset=offset, limit=limit)


@tenant_router.get("/{tenant_id}", response_model=TenantResponse)
async def tenant_get(tenant_id: uuid.UUID, service: TenantService):
    return await service.tenant_get(tenant_id)


@tenant_router.post("", response_model=TenantResponse, status_code=202)
async def tenant_create(payload: CreateTenantInput, service: TenantService):
    return await service.tenant_create(payload)


@tenant_router.patch("/{tenant_id}", response_model=TenantResponse, status_code=202)
async def tenant_update(tenant_id: uuid.UUID, payload: ModifyTenantInput, service: TenantService):
    return await service.tenant_update(tenant_id, payload)


@tenant_router.delete("/{tenant_id}", response_model=TenantResponse, status_code=202)
async def tenant_delete(tenant_id: uuid.UUID, service: TenantService):
    return await service.tenant_delete(tenant_id)


@tenant_router.get("/{tenant_id}/tasks")
async def tenant_task_list(
    tenant_id: uuid.UUID,
    service: TaskService,
    offset: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
) -> TaskListResponse:
    tasks = await service.task_list_by_tenant(tenant_id, offset=offset, limit=limit)

    return TaskListResponse(tasks=tasks, offset=offset, limit=limit)


# task routes
@task_router.get("")
async def task_list(
    service: TaskService,
    offset: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
) -> TaskListResponse:
    tasks = await service.task_list(offset=offset, limit=limit)

    return TaskListResponse(tasks=tasks, offset=offset, limit=limit)


@task_router.get("/{task_id}", response_model=TaskResponse)
async def task_get(task_id: uuid.UUID, service: TaskService):
    return await service.task_get(task_id)
