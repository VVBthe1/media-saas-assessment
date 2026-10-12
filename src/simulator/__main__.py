import argparse
import asyncio
import json
import logging
import os
import random
import socket
import uuid

from aio_pika import DeliveryMode, ExchangeType, Message, connect_robust

from backend.models.task import TaskStatus

logger = logging.getLogger("simulator")

# Same names as backend.broker (simulator stays a separate process; copy constants)
TASKS_EXCHANGE = "tasks"
TASK_CREATED_QUEUE = "tasks.created"
TASK_CREATED_ROUTING_KEY = "task.created"
TASK_UPDATES_EXCHANGE = "task_updates"
TASK_PROGRESS_QUEUE = "task.progress"
TASK_PROGRESS_ROUTING_KEY = "task.progress"
DEFAULT_BROKER_URL = "amqp://guest:guest@localhost:5672/"


def _normalize_delay_ms(min_delay_ms: int, max_delay_ms: int) -> tuple[int, int]:
    if min_delay_ms < 0 or max_delay_ms < 0:
        raise ValueError("delay milliseconds must be non-negative")
    if min_delay_ms > max_delay_ms:
        min_delay_ms, max_delay_ms = max_delay_ms, min_delay_ms
    return min_delay_ms, max_delay_ms


async def main(fail_rate: float, min_delay_ms: int, max_delay_ms: int) -> None:
    min_delay_ms, max_delay_ms = _normalize_delay_ms(min_delay_ms, max_delay_ms)
    host = socket.gethostname()
    logger.info(
        "simulator on %s: fail_rate=%.2f delay_ms=[%d, %d] "
        "(pause after in_progress, before done/failed)",
        host,
        fail_rate,
        min_delay_ms,
        max_delay_ms,
    )

    broker_url = os.environ.get("BROKER_URL", DEFAULT_BROKER_URL)
    connection = await connect_robust(broker_url)
    async with connection:
        channel = await connection.channel()
        await channel.set_qos(prefetch_count=1)

        tasks_exchange = await channel.declare_exchange(
            TASKS_EXCHANGE,
            ExchangeType.DIRECT,
            durable=True,
        )
        tasks_queue = await channel.declare_queue(TASK_CREATED_QUEUE, durable=True)
        await tasks_queue.bind(tasks_exchange, routing_key=TASK_CREATED_ROUTING_KEY)

        updates_exchange = await channel.declare_exchange(
            TASK_UPDATES_EXCHANGE, ExchangeType.DIRECT, durable=True
        )
        progress_queue = await channel.declare_queue(TASK_PROGRESS_QUEUE, durable=True)
        await progress_queue.bind(updates_exchange, routing_key=TASK_PROGRESS_ROUTING_KEY)

        logger.info("simulator ready, consuming %s", TASK_CREATED_QUEUE)
        async with tasks_queue.iterator() as queue_iter:
            async for message in queue_iter:
                async with message.process(requeue=False):
                    await handle_task(
                        message,
                        updates_exchange,
                        fail_rate,
                        min_delay_ms,
                        max_delay_ms,
                    )


async def handle_task(
    message,
    updates_exchange,
    fail_rate: float,
    min_delay_ms: int,
    max_delay_ms: int,
) -> None:
    try:
        body = json.loads(message.body.decode())
        task_id = body["id"]
        tenant_id = body["tenant_id"]
        task_type = body["type"]
    except (json.JSONDecodeError, KeyError) as exc:
        logger.error("could not read task message: %s", exc)
        return

    logger.info("simulating task %s (%s) for tenant %s", task_id, task_type, tenant_id)

    await publish_progress(updates_exchange, task_id, TaskStatus.IN_PROGRESS.value)
    delay_s = random.uniform(min_delay_ms, max_delay_ms) / 1000.0
    if delay_s > 0:
        logger.info("task %s: pausing %.2fs before terminal status", task_id, delay_s)
        await asyncio.sleep(delay_s)
    terminal = TaskStatus.FAILED.value if random.random() < fail_rate else TaskStatus.DONE.value
    await publish_progress(updates_exchange, task_id, terminal)


async def publish_progress(updates_exchange, task_id: str, status: str) -> None:
    update_id = str(uuid.uuid4())
    payload = json.dumps(
        {
            "update_id": update_id,
            "task_id": task_id,
            "status": status,
        }
    ).encode()

    await updates_exchange.publish(
        Message(
            payload,
            content_type="application/json",
            delivery_mode=DeliveryMode.PERSISTENT,
            message_id=update_id,
        ),
        routing_key=TASK_PROGRESS_ROUTING_KEY,
    )
    logger.info("reporting task %s %s (update %s)", task_id, status, update_id)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--fail-rate", type=float, default=0.0)
    parser.add_argument(
        "--min-delay-ms",
        type=int,
        default=0,
        help="Random pause lower bound (ms) after in_progress, before done/failed",
    )
    parser.add_argument(
        "--max-delay-ms",
        type=int,
        default=0,
        help="Random pause upper bound (ms) after in_progress, before done/failed",
    )
    args = parser.parse_args()
    if not 0.0 <= args.fail_rate <= 1.0:
        parser.error("--fail-rate must be between 0 and 1")

    asyncio.run(main(args.fail_rate, args.min_delay_ms, args.max_delay_ms))
