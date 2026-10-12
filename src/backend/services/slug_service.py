import re
import unicodedata

from backend.exceptions.tenant import InvalidSlug, InvalidTenantName

SLUG_MAX_LENGTH = 28
SLUG_REGEX = r"^[a-z][-a-z0-9]{1,26}[a-z0-9]$"
SLUG_PATTERN = re.compile(SLUG_REGEX)


class SlugService:
    @staticmethod
    def generate(name: str) -> str:
        slug = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode("ascii")
        slug = slug.lower()
        slug = re.sub(r"[^a-z0-9]+", "-", slug)
        slug = re.sub(r"^[-0-9]+", "", slug)
        slug = slug[:SLUG_MAX_LENGTH].rstrip("-")

        if not SlugService.validate(slug):
            raise InvalidTenantName(f"Cannot derive a valid slug from name {name!r}")

        return slug

    @staticmethod
    def validate(slug: str) -> bool:
        return SLUG_PATTERN.fullmatch(slug) is not None

    @staticmethod
    def assert_valid(slug: str) -> None:
        if not SlugService.validate(slug):
            raise InvalidSlug()
