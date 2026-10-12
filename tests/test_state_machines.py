import uuid

import pytest

from backend.exceptions.tenant import TenantUpdateNotAllowed
from backend.models.task import Task, TaskStatus, TaskType
from backend.models.tenant import Tenant, TenantStatus
from backend.services.task_service import ALLOWED_TASK_TRANSITIONS, TaskSrv
from backend.services.tenant_service import ALLOWED_TENANT_TRANSITIONS, TenantSrv


def _fake_session(task: Task):
    class _Session:
        async def get(self, _model, _id):
            return task

    return _Session()


@pytest.mark.parametrize(
    ("from_status", "to_status"),
    [
        (TenantStatus.PROVISIONING, TenantStatus.ACTIVE),
        (TenantStatus.PROVISIONING, TenantStatus.FAILED),
        (TenantStatus.ACTIVE, TenantStatus.UPDATING),
        (TenantStatus.ACTIVE, TenantStatus.DESTROYING),
        (TenantStatus.UPDATING, TenantStatus.ACTIVE),
        (TenantStatus.UPDATING, TenantStatus.FAILED),
        (TenantStatus.DESTROYING, TenantStatus.DESTROYED),
        (TenantStatus.DESTROYING, TenantStatus.FAILED),
        (TenantStatus.FAILED, TenantStatus.DESTROYING),
    ],
)
def test_tenant_allowed_transitions(from_status: TenantStatus, to_status: TenantStatus) -> None:
    assert to_status in ALLOWED_TENANT_TRANSITIONS[from_status]
    tenant = Tenant(status=from_status)
    TenantSrv.assert_status_transition_valid(tenant, to_status)


def test_tenant_destroyed_has_no_outbound_transitions() -> None:
    assert not ALLOWED_TENANT_TRANSITIONS[TenantStatus.DESTROYED]


def test_tenant_invalid_transition_raises() -> None:
    tenant = Tenant(status=TenantStatus.PROVISIONING)
    with pytest.raises(TenantUpdateNotAllowed):
        TenantSrv.assert_status_transition_valid(tenant, TenantStatus.UPDATING)


@pytest.mark.parametrize(
    ("from_status", "to_status"),
    [
        (TaskStatus.ACCEPTED, TaskStatus.IN_PROGRESS),
        (TaskStatus.IN_PROGRESS, TaskStatus.DONE),
        (TaskStatus.IN_PROGRESS, TaskStatus.FAILED),
    ],
)
@pytest.mark.asyncio
async def test_task_allowed_progress(from_status: TaskStatus, to_status: TaskStatus) -> None:
    task = Task(
        id=uuid.uuid4(),
        tenant_id=uuid.uuid4(),
        type=TaskType.DEPLOY,
        status=from_status,
    )
    srv = TaskSrv(_fake_session(task))  # type: ignore[arg-type]
    result = await srv.apply_task_progress(task.id, to_status)
    assert result is task
    assert task.status == to_status


@pytest.mark.parametrize(
    ("from_status", "to_status"),
    [
        (TaskStatus.DONE, TaskStatus.IN_PROGRESS),
        (TaskStatus.FAILED, TaskStatus.DONE),
        (TaskStatus.ACCEPTED, TaskStatus.DONE),
        (TaskStatus.DONE, TaskStatus.FAILED),
    ],
)
@pytest.mark.asyncio
async def test_task_stale_progress_is_no_op(from_status: TaskStatus, to_status: TaskStatus) -> None:
    task = Task(
        id=uuid.uuid4(),
        tenant_id=uuid.uuid4(),
        type=TaskType.DEPLOY,
        status=from_status,
    )
    srv = TaskSrv(_fake_session(task))  # type: ignore[arg-type]
    assert await srv.apply_task_progress(task.id, to_status) is None
    assert task.status == from_status


def test_task_terminal_states_allow_no_outbound() -> None:
    assert not ALLOWED_TASK_TRANSITIONS[TaskStatus.DONE]
    assert not ALLOWED_TASK_TRANSITIONS[TaskStatus.FAILED]


@pytest.mark.parametrize(
    ("task_type", "task_status", "expected"),
    [
        (TaskType.DEPLOY, TaskStatus.DONE, TenantStatus.ACTIVE),
        (TaskType.UPDATE, TaskStatus.DONE, TenantStatus.ACTIVE),
        (TaskType.DESTROY, TaskStatus.DONE, TenantStatus.DESTROYED),
        (TaskType.DEPLOY, TaskStatus.FAILED, TenantStatus.FAILED),
        (TaskType.DEPLOY, TaskStatus.IN_PROGRESS, None),
    ],
)
def test_tenant_status_for_terminal(
    task_type: TaskType, task_status: TaskStatus, expected: TenantStatus | None
) -> None:
    task = Task(type=task_type, status=task_status)
    assert TaskSrv.tenant_status_for_terminal(task) == expected
