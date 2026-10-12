from backend.exceptions import AppError


class TenantNotFound(AppError):
    code = "tenant_not_found"
    message = "Tenant not found"
    status_code = 404


class TenantAlreadyExists(AppError):
    code = "tenant_already_exists"
    message = (
        "Tenant already exists. If you have provided the slug, it might be already used. "
        "Try adding -1 etc."
    )
    status_code = 409


class TenantUpdateNotAllowed(AppError):
    code = "tenant_update_not_allowed"
    message = "Tenant cannot be modified in its current status"
    status_code = 409


class TenantVersionConflict(AppError):
    code = "tenant_version_conflict"
    message = "Tenant was modified by another request"
    status_code = 409


class InvalidSlug(AppError):
    code = "invalid_slug"
    message = (
        "Slug must be 3-28 chars, lowercase letters, digits and '-', "
        "start with a letter and end with a letter or digit"
    )
    status_code = 422


class InvalidTenantName(AppError):
    code = "invalid_tenant_name"
    message = "Tenant name cannot be converted into a valid slug"
    status_code = 422
