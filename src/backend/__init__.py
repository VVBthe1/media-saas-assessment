"""Load logging configuration before other backend submodules are imported."""

import backend.logging_config  # noqa: F401 — configures logging on package import
