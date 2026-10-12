from datetime import datetime
import enum
import uuid
from sqlalchemy import DateTime, ForeignKey, Index, func, text
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy import Enum, Uuid

from backend.models.base import Base


class TaskType(str, enum.Enum):
    DEPLOY = "deploy"
    UPDATE = "update"
    DESTROY = "destroy"


class TaskStatus(str, enum.Enum):
    ACCEPTED = "accepted"
    IN_PROGRESS = "in_progress"
    DONE = "done"
    FAILED = "failed"


class Task(Base):
    __tablename__ = "tasks"
    __table_args__ = (
        Index(
            "uq_tasks_one_open_per_tenant",
            "tenant_id",
            unique=True,
            postgresql_where=text("status IN ('accepted', 'in_progress')"),
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), default=uuid.uuid4, primary_key=True)
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("tenants.id", ondelete="RESTRICT"), index=True
    )
    type: Mapped[TaskType] = mapped_column(
        Enum(TaskType, name="task_type", values_callable=lambda e: [t.value for t in e])
    )
    status: Mapped[TaskStatus] = mapped_column(
        Enum(TaskStatus, name="task_status", values_callable=lambda e: [s.value for s in e]),
        default=TaskStatus.ACCEPTED,
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    tenant: Mapped["Tenant"] = relationship(back_populates="tasks")
