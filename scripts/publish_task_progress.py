#!/usr/bin/env python3
"""Publish one task.progress message to RabbitMQ (same schema as the simulator).

Usage:
  python scripts/publish_task_progress.py --task-id <uuid> --status in_progress \\
    --update-id <uuid>

Env: BROKER_URL (default amqp://guest:guest@127.0.0.1:5672/)
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import uuid

from aio_pika import ExchangeType, Message, connect_robust

TASK_UPDATES_EXCHANGE = "task_updates"
TASK_PROGRESS_ROUTING_KEY = "task.progress"
BROKER_URL = os.environ.get("BROKER_URL", "amqp://guest:guest@127.0.0.1:5672/")


async def publish_progress(task_id: str, status: str, update_id: str) -> None:
    connection = await connect_robust(BROKER_URL)
    async with connection:
        channel = await connection.channel()
        exchange = await channel.declare_exchange(
            TASK_UPDATES_EXCHANGE, ExchangeType.DIRECT, durable=True
        )
        payload = json.dumps(
            {"update_id": update_id, "task_id": task_id, "status": status}
        ).encode()
        await exchange.publish(
            Message(payload, content_type="application/json"),
            routing_key=TASK_PROGRESS_ROUTING_KEY,
        )


def main() -> None:
    parser = argparse.ArgumentParser(description="Publish task.progress to RabbitMQ")
    parser.add_argument("--task-id", required=True, help="Task UUID")
    parser.add_argument(
        "--status",
        required=True,
        choices=("in_progress", "done", "failed"),
        help="Progress status",
    )
    parser.add_argument(
        "--update-id",
        default=None,
        help="Idempotency key (default: new random UUID)",
    )
    args = parser.parse_args()
    update_id = args.update_id or str(uuid.uuid4())
    asyncio.run(publish_progress(args.task_id, args.status, update_id))
    print(f"published update_id={update_id} task_id={args.task_id} status={args.status}")


if __name__ == "__main__":
    main()
