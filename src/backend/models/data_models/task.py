from datetime import datetime
import uuid

from pydantic import BaseModel, ConfigDict, field_serializer

from backend.models.data_models.datetime_format import format_utc_millis_z
from backend.models.task import TaskStatus, TaskType


class TaskResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    tenant_id: uuid.UUID
    type: TaskType
    status: TaskStatus
    created_at: datetime
    updated_at: datetime

    @field_serializer("created_at", "updated_at")
    def serialize_timestamps(self, dt: datetime) -> str:
        return format_utc_millis_z(dt)


class TaskListResponse(BaseModel):
    tasks: list[TaskResponse]
    limit: int
    offset: int
