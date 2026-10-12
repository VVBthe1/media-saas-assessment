from typing import Annotated
import uuid
from fastapi import Depends
from sqlalchemy import select
from backend.db import DBSession
from backend.exceptions.task import TaskNotFound
from backend.exceptions.tenant import TenantNotFound
from backend.models.task import Task, TaskStatus, TaskType
from backend.models.tenant import Tenant, TenantStatus

ALLOWED_TASK_TRANSITIONS: dict[TaskStatus, frozenset[TaskStatus]] = {
    TaskStatus.ACCEPTED: frozenset({TaskStatus.IN_PROGRESS}),
    TaskStatus.IN_PROGRESS: frozenset({TaskStatus.DONE, TaskStatus.FAILED}),
    TaskStatus.DONE: frozenset(),
    TaskStatus.FAILED: frozenset(),
}


class TaskSrv:
    def __init__(self, db: DBSession) -> None:
        self.session = db

    async def task_list(self, offset: int = 0, limit: int = 50) -> list[Task]:
        stmt = select(Task).order_by(Task.created_at, Task.id).limit(limit).offset(offset)
        tasks = await self.session.scalars(stmt)

        return tasks.all()

    async def task_list_by_tenant(
        self,
        tenant_id: uuid.UUID,
        offset: int = 0,
        limit: int = 50,
    ) -> list[Task]:
        tenant = await self.session.get(Tenant, tenant_id)

        if not tenant:
            raise TenantNotFound()

        stmt = (
            select(Task)
            .where(Task.tenant_id == tenant_id)
            .order_by(Task.created_at, Task.id)
            .limit(limit)
            .offset(offset)
        )
        tasks = await self.session.scalars(stmt)

        return tasks.all()

    async def task_get(self, task_id: uuid.UUID) -> Task:
        task = await self.session.get(Task, task_id)

        if not task:
            raise TaskNotFound()

        return task

    async def apply_task_progress(self, task_id: uuid.UUID, status: TaskStatus) -> Task | None:
        task = await self.session.get(Task, task_id)
        if not task:
            raise TaskNotFound()
        if status not in ALLOWED_TASK_TRANSITIONS[task.status]:
            return None
        task.status = status
        return task

    @staticmethod
    def tenant_status_for_terminal(task: Task) -> TenantStatus | None:
        if task.status not in (TaskStatus.DONE, TaskStatus.FAILED):
            return None
        if task.status == TaskStatus.FAILED:
            return TenantStatus.FAILED
        if task.type == TaskType.DESTROY:
            return TenantStatus.DESTROYED
        return TenantStatus.ACTIVE


TaskService = Annotated[TaskSrv, Depends()]
