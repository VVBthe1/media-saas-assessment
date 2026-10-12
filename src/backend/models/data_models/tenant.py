from datetime import datetime
import uuid

from pydantic import BaseModel, ConfigDict, Field, field_serializer

from backend.models.data_models.datetime_format import format_utc_millis_z
from backend.models.tenant import TenantStatus
from backend.services.slug_service import SLUG_REGEX


class TenantResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    slug: str
    name: str
    status: TenantStatus
    version: int
    created_at: datetime
    updated_at: datetime

    @field_serializer("created_at", "updated_at")
    def serialize_timestamps(self, dt: datetime) -> str:
        return format_utc_millis_z(dt)


class TenantListResponse(BaseModel):
    tenants: list[TenantResponse]
    limit: int
    offset: int


class CreateTenantInput(BaseModel):
    name: str = Field(max_length=255, min_length=1)
    slug: str | None = Field(default=None, pattern=SLUG_REGEX)


class ModifyTenantInput(BaseModel):
    name: str = Field(max_length=255, min_length=1)
    version: int = Field(ge=1)
