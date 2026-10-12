from datetime import datetime
import enum
import uuid
from sqlalchemy import Uuid, func
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy import CheckConstraint, DateTime, Enum, Integer, String

from backend.models.base import Base


class TenantStatus(str, enum.Enum):
    PROVISIONING = "provisioning"
    ACTIVE = "active"
    FAILED = "failed"
    UPDATING = "updating"
    DESTROYING = "destroying"
    DESTROYED = "destroyed"


class Tenant(Base):
    __tablename__ = "tenants"
    __table_args__ = (
        CheckConstraint("slug ~ '^[a-z][-a-z0-9]{1,26}[a-z0-9]$'", name="ck_tenants_slug_format"),
        CheckConstraint("length(trim(name)) > 0", name="ck_tenants_name_not_empty"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    slug: Mapped[str] = mapped_column(String(28), unique=True)
    name: Mapped[str] = mapped_column(String(255))
    status: Mapped[TenantStatus] = mapped_column(
        Enum(TenantStatus, name="tenant_status", values_callable=lambda e: [s.value for s in e]),
        default=TenantStatus.PROVISIONING,
    )
    version: Mapped[int] = mapped_column(Integer, default=1)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
    )

    tasks: Mapped[list["Task"]] = relationship(back_populates="tenant")
