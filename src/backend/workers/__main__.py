import asyncio
import json
import logging
import uuid

from aio_pika import DeliveryMode, ExchangeType, Message
from sqlalchemy.exc import DBAPIError, IntegrityError, OperationalError, SQLAlchemyError

from backend.broker import get_channel, get_connection
from backend.exceptions import AppError
from backend.db import SessionLocal
from backend.exceptions.task import TaskNotFound
from backend.exceptions.tenant import TenantNotFound
from backend.models.processed_update import ProcessedUpdate
from backend.models.task import Task, TaskStatus, TaskType
from backend.models.tenant import Tenant, TenantStatus
from backend.services.task_service import TaskSrv
from backend.services.tenant_service import TenantSrv

logger = logging.getLogger("worker")

TASK_UPDATES_EXCHANGE = "task_updates"
TASK_PROGRESS_QUEUE = "task.progress"
TASK_PROGRESS_ROUTING_KEY = "task.progress"

UNIQUE_VIOLATION = "23505"

MAX_RETRIES = 5
INITIAL_BACKOFF_S = 0.5
MAX_BACKOFF_S = 30.0
RETRY_COUNT_HEADER = "x-retry-count"


class RetriesExhausted(Exception):
    """Raised when a progress message has used its retry budget."""


def _retry_count(message) -> int:
    headers = message.headers or {}
    raw = headers.get(RETRY_COUNT_HEADER, 0)
    try:
        return int(raw)
    except (TypeError, ValueError):
        return 0


def _backoff_seconds(count: int) -> float:
    return min(INITIAL_BACKOFF_S * (2**count), MAX_BACKOFF_S)


async def main() -> None:
    connection = await get_connection()
    async with connection:
        channel = await get_channel(connection)
        await channel.set_qos(prefetch_count=1)
        logger.info("worker ready")

        updates_exchange = await channel.declare_exchange(
            TASK_UPDATES_EXCHANGE, ExchangeType.DIRECT, durable=True
        )
        progress_queue = await channel.declare_queue(TASK_PROGRESS_QUEUE, durable=True)
        await progress_queue.bind(updates_exchange, routing_key=TASK_PROGRESS_ROUTING_KEY)

        async with progress_queue.iterator() as queue_iter:
            async for message in queue_iter:
                try:
                    await handle_progress(message, updates_exchange)
                    await message.ack()
                except RetriesExhausted:
                    logger.warning("retries exhausted, dropping message")
                    await message.reject(requeue=False)
                except (SQLAlchemyError, AppError):
                    logger.exception("could not process message, dropping")
                    await message.reject(requeue=False)
                except Exception:
                    # Unexpected bugs: drop message so one bad payload cannot stall the worker.
                    logger.exception("unexpected error, dropping message")
                    await message.reject(requeue=False)


async def handle_progress(message, exchange) -> None:
    count = _retry_count(message)
    if count >= MAX_RETRIES:
        raise RetriesExhausted()

    try:
        body = json.loads(message.body.decode())
        update_id = body["update_id"]
        task_id = body["task_id"]
        status = body["status"]
    except (json.JSONDecodeError, KeyError) as exc:
        logger.error("could not read progress message: %s", exc)
        return

    try:
        task_status = TaskStatus(status)
    except ValueError:
        logger.error("unknown status %r for task %s", status, task_id)
        return

    try:
        await _persist_progress(update_id, task_id, task_status)
    except TaskNotFound:
        logger.error("no task %s", task_id)
    except IntegrityError:
        raise
    except OperationalError as exc:
        await _republish_or_exhaust(
            message, exchange, count, exc, update_id=update_id, task_id=task_id
        )
    except DBAPIError as exc:
        if not exc.connection_invalidated:
            raise
        await _republish_or_exhaust(
            message, exchange, count, exc, update_id=update_id, task_id=task_id
        )


async def _republish_or_exhaust(message, exchange, count, exc, *, update_id, task_id) -> None:
    next_count = count + 1
    if next_count >= MAX_RETRIES:
        logger.warning(
            "update %s for task %s failed after %s attempts: %s",
            update_id,
            task_id,
            MAX_RETRIES,
            exc,
        )
        raise RetriesExhausted() from exc

    delay = _backoff_seconds(count)
    logger.warning(
        "retrying update %s for task %s in %.1fs (%s/%s): %s",
        update_id,
        task_id,
        delay,
        next_count,
        MAX_RETRIES,
        exc,
    )
    await asyncio.sleep(delay)
    headers = dict(message.headers or {})
    headers[RETRY_COUNT_HEADER] = next_count
    await exchange.publish(
        Message(
            body=message.body,
            content_type=message.content_type or "application/json",
            delivery_mode=DeliveryMode.PERSISTENT,
            headers=headers,
        ),
        routing_key=TASK_PROGRESS_ROUTING_KEY,
    )


async def _persist_progress(update_id: str, task_id: str, task_status: TaskStatus) -> None:
    async with SessionLocal() as session:
        try:
            session.add(ProcessedUpdate(id=uuid.UUID(update_id)))
            await session.flush()
        except IntegrityError as exc:
            await session.rollback()
            if getattr(exc.orig, "sqlstate", None) == UNIQUE_VIOLATION:
                logger.info("update %s already applied, skipping", update_id)
                return
            raise

        try:
            task_srv = TaskSrv(session)
            tenant_srv = TenantSrv(session)

            task_row = await session.get(Task, uuid.UUID(task_id))
            if not task_row:
                raise TaskNotFound()

            previous_task_status = task_row.status
            task = await task_srv.apply_task_progress(uuid.UUID(task_id), task_status)
            if task is None:
                logger.info(
                    "setting task %s from %s to %s is not allowed",
                    task_id,
                    previous_task_status.value,
                    task_status.value,
                )
                await session.commit()
                return

            if task.status == TaskStatus.FAILED:
                logger.info(
                    "setting task %s from %s to failed, failing task",
                    task.id,
                    previous_task_status.value,
                )
            else:
                logger.info(
                    "setting task %s from %s to %s",
                    task.id,
                    previous_task_status.value,
                    task.status.value,
                )

            tenant_status = TaskSrv.tenant_status_for_terminal(task)
            if tenant_status is not None:
                tenant = await session.get(Tenant, task.tenant_id)
                if tenant is None:
                    raise TenantNotFound()
                previous_tenant_status = tenant.status
                if tenant_status == TenantStatus.FAILED:
                    goal = "destroyed" if task.type == TaskType.DESTROY else "active"
                    logger.info(
                        "setting tenant %s from %s to %s failed, marking tenant failed",
                        task.tenant_id,
                        previous_tenant_status.value,
                        goal,
                    )
                else:
                    logger.info(
                        "setting tenant %s from %s to %s",
                        task.tenant_id,
                        previous_tenant_status.value,
                        tenant_status.value,
                    )
                await tenant_srv.apply_tenant_status(task.tenant_id, tenant_status)

            await session.commit()
        except (SQLAlchemyError, AppError):
            await session.rollback()
            raise


if __name__ == "__main__":
    asyncio.run(main())
