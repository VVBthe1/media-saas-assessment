import json
import logging

from aio_pika import DeliveryMode, ExchangeType, Message, connect_robust
from aio_pika.abc import AbstractRobustChannel, AbstractRobustConnection

from backend.models.task import Task
from backend.settings import settings

logger = logging.getLogger("api")

TASKS_EXCHANGE = "tasks"
TASK_CREATED_QUEUE = "tasks.created"
TASK_CREATED_ROUTING_KEY = "task.created"

connection: AbstractRobustConnection | None = None
channel: AbstractRobustChannel | None = None


async def get_connection() -> AbstractRobustConnection:
    return await connect_robust(settings.broker_url)


async def get_channel(conn: AbstractRobustConnection) -> AbstractRobustChannel:
    return await conn.channel()


async def connect() -> None:
    # Shared broker handles for the API process (opened on startup, used when publishing tasks).
    global connection, channel
    connection = await get_connection()
    channel = await get_channel(connection)
    exchange = await channel.declare_exchange(
        TASKS_EXCHANGE,
        ExchangeType.DIRECT,
        durable=True,
    )
    queue = await channel.declare_queue(TASK_CREATED_QUEUE, durable=True)
    await queue.bind(exchange, routing_key=TASK_CREATED_ROUTING_KEY)


async def disconnect() -> None:
    # Clear module-level handles on shutdown.
    global connection, channel
    if connection is not None:
        await connection.close()
    connection = None
    channel = None


async def publish_task(task: Task) -> None:
    if channel is None:
        raise RuntimeError("Broker channel is not connected")

    body = json.dumps(
        {
            "id": str(task.id),
            "type": task.type.value,
            "tenant_id": str(task.tenant_id),
            "status": task.status.value,
        }
    ).encode()

    exchange = await channel.get_exchange(TASKS_EXCHANGE)
    await exchange.publish(
        Message(
            body,
            content_type="application/json",
            delivery_mode=DeliveryMode.PERSISTENT,
            message_id=str(task.id),
        ),
        routing_key=TASK_CREATED_ROUTING_KEY,
    )
    logger.info(
        "queued task %s (%s) for tenant %s",
        task.id,
        task.type.value,
        task.tenant_id,
    )
