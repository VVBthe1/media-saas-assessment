import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlalchemy.exc import IntegrityError

from backend.models.task import TaskStatus
from backend.workers.__main__ import _persist_progress


def _session_mock() -> MagicMock:
    """SQLAlchemy async session: sync add, awaited flush/rollback/commit/get."""
    session = MagicMock()
    session.add = MagicMock()
    session.flush = AsyncMock()
    session.rollback = AsyncMock()
    session.commit = AsyncMock()
    session.get = AsyncMock(return_value=MagicMock())
    return session


@pytest.mark.asyncio
async def test_duplicate_update_id_does_not_apply_progress(monkeypatch: pytest.MonkeyPatch) -> None:
    session = _session_mock()
    orig = MagicMock()
    orig.sqlstate = "23505"
    dup_exc = IntegrityError("stmt", {}, Exception())
    dup_exc.orig = orig
    session.flush = AsyncMock(side_effect=dup_exc)

    class _SessionCtx:
        async def __aenter__(self):
            return session

        async def __aexit__(self, *args):
            return False

    monkeypatch.setattr("backend.workers.__main__.SessionLocal", lambda: _SessionCtx())

    task_srv = MagicMock()
    monkeypatch.setattr("backend.workers.__main__.TaskSrv", lambda _s: task_srv)

    update_id = str(uuid.uuid4())
    task_id = str(uuid.uuid4())
    await _persist_progress(update_id, task_id, TaskStatus.DONE)

    session.rollback.assert_awaited()
    task_srv.apply_task_progress.assert_not_called()


@pytest.mark.asyncio
async def test_new_update_id_applies_progress(monkeypatch: pytest.MonkeyPatch) -> None:
    session = _session_mock()

    class _SessionCtx:
        async def __aenter__(self):
            return session

        async def __aexit__(self, *args):
            return False

    monkeypatch.setattr("backend.workers.__main__.SessionLocal", lambda: _SessionCtx())

    apply = AsyncMock(return_value=None)
    task_srv = MagicMock()
    task_srv.apply_task_progress = apply
    monkeypatch.setattr("backend.workers.__main__.TaskSrv", lambda _s: task_srv)

    update_id = str(uuid.uuid4())
    task_id = str(uuid.uuid4())
    await _persist_progress(update_id, task_id, TaskStatus.IN_PROGRESS)

    apply.assert_awaited_once_with(uuid.UUID(task_id), TaskStatus.IN_PROGRESS)
    session.commit.assert_awaited()
