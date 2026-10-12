import logging.config

LOGGING_CONFIG = {
    "version": 1,
    # False: child loggers may be created before this module is imported.
    "disable_existing_loggers": False,
    "formatters": {
        "standard": {
            "format": "%(asctime)s %(levelname)s:%(name)s:%(message)s",
            "datefmt": "%Y-%m-%d %H:%M:%S",
        },
    },
    "handlers": {
        "stderr": {
            "class": "logging.StreamHandler",
            "formatter": "standard",
            "stream": "ext://sys.stderr",
        },
    },
    "root": {
        "level": "INFO",
        "handlers": ["stderr"],
    },
    "loggers": {
        "api": {"level": "INFO"},
        "worker": {"level": "INFO"},
        "simulator": {"level": "INFO"},
        "uvicorn": {"handlers": ["stderr"], "level": "INFO", "propagate": False},
        "uvicorn.error": {"handlers": ["stderr"], "level": "INFO", "propagate": False},
        "uvicorn.access": {"handlers": ["stderr"], "level": "INFO", "propagate": False},
    },
}


def configure_logging() -> None:
    logging.config.dictConfig(LOGGING_CONFIG)


configure_logging()
