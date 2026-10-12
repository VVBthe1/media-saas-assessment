import json
import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlalchemy.exc import IntegrityError, OperationalError

from backend.models.task import TaskStatus
from backend.workers.__main__ import (
    MAX_RETRIES,
    RETRY_COUNT_HEADER,
    RetriesExhausted,
    _persist_progress,
    handle_progress,
)


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


def _progress_message(headers: dict | None = None) -> MagicMock:
    message = MagicMock()
    message.body = json.dumps(
        {
            "update_id": str(uuid.uuid4()),
            "task_id": str(uuid.uuid4()),
            "status": "in_progress",
        }
    ).encode()
    message.headers = {} if headers is None else headers
    message.content_type = "application/json"
    return message


@pytest.mark.asyncio
async def test_transient_db_error_republishes_with_retry_header(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "backend.workers.__main__._persist_progress",
        AsyncMock(side_effect=OperationalError("stmt", {}, Exception())),
    )
    sleep = AsyncMock()
    monkeypatch.setattr("backend.workers.__main__.asyncio.sleep", sleep)
    exchange = MagicMock()
    exchange.publish = AsyncMock()
    message = _progress_message()

    await handle_progress(message, exchange)

    sleep.assert_awaited_once_with(0.5)
    published = exchange.publish.await_args.args[0]
    assert published.headers[RETRY_COUNT_HEADER] == 1
    assert published.body == message.body


@pytest.mark.asyncio
async def test_retry_budget_rejects_without_republish(monkeypatch: pytest.MonkeyPatch) -> None:
    persist = AsyncMock(side_effect=OperationalError("stmt", {}, Exception()))
    monkeypatch.setattr("backend.workers.__main__._persist_progress", persist)
    sleep = AsyncMock()
    monkeypatch.setattr("backend.workers.__main__.asyncio.sleep", sleep)
    exchange = MagicMock()
    exchange.publish = AsyncMock()
    message = _progress_message({RETRY_COUNT_HEADER: MAX_RETRIES - 1})

    with pytest.raises(RetriesExhausted):
        await handle_progress(message, exchange)

    persist.assert_awaited()
    sleep.assert_not_awaited()
    exchange.publish.assert_not_awaited()


@pytest.mark.asyncio
async def test_header_at_max_retries_skips_persist(monkeypatch: pytest.MonkeyPatch) -> None:
    persist = AsyncMock()
    monkeypatch.setattr("backend.workers.__main__._persist_progress", persist)
    message = _progress_message({RETRY_COUNT_HEADER: MAX_RETRIES})

    with pytest.raises(RetriesExhausted):
        await handle_progress(message, MagicMock())

    persist.assert_not_awaited()
