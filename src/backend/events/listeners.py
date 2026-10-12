from sqlalchemy.ext.asyncio import AsyncSession

from backend.broker import publish_task
from backend.events import task_created, tenant_created, tenant_deleted, tenant_updated
from backend.models.task import Task, TaskType
from backend.models.tenant import Tenant


@tenant_created.connect
async def on_tenant_created(_sender, tenant: Tenant, session: AsyncSession) -> Task:
    task = Task(
        tenant_id=tenant.id,
        type=TaskType.DEPLOY,
    )
    session.add(task)
    return task


@tenant_updated.connect
async def on_tenant_updated(_sender, tenant: Tenant, session: AsyncSession) -> Task:
    task = Task(
        tenant_id=tenant.id,
        type=TaskType.UPDATE,
    )
    session.add(task)
    return task


@tenant_deleted.connect
async def on_tenant_deleted(_sender, tenant: Tenant, session: AsyncSession) -> Task:
    task = Task(
        tenant_id=tenant.id,
        type=TaskType.DESTROY,
    )
    session.add(task)
    return task


@task_created.connect
async def on_task_created(_sender, task: Task) -> None:
    await publish_task(task)
