import os
from functools import lru_cache
from pathlib import Path

from dotenv import load_dotenv
from loguru import logger

load_dotenv()

ENV_MODE = os.getenv("ENV_MODE", "dev").lower()
LOG_LEVEL = "DEBUG" if ENV_MODE == "dev" else "INFO"


@lru_cache(maxsize=2)
def _setup_handler(show_time: bool = True) -> None:
    """Configure loguru handler. Cached per show_time value — runs only once per variant."""
    logger.remove(handler_id=None)

    _format = (
        "<green>{time:YYYY-MM-DD HH:mm:ss}</green> | "
        "<level>{level: <8}</level> | "
        "<cyan>{extra[name]}</cyan> | "
        "<level>{message}</level>"
    ) if show_time else (
        "<level>{level: <8}</level> | "
        "<cyan>{extra[name]}</cyan> | "
        "<level>{message}</level>"
    )

    logger.add(
        sink=lambda msg: print(msg, end=""),
        format=_format,
        colorize=True,
        level=LOG_LEVEL,
    )

    # Default extra value so first log doesn't error
    logger.configure(extra={"name": ""})


def get_logger(module_name: str, show_time: bool = False) -> logger:
    _setup_handler(show_time)
    return logger.bind(name=module_name)


def add_file_logger(log_path: Path, rotation: str = "10 MB", retention: str = "7 days") -> None:
    logger.add(
        sink=str(log_path),
        format="{time:YYYY-MM-DD HH:mm:ss} | {level: <8} | {name} | {message}",
        rotation=rotation,
        retention=retention,
        level=LOG_LEVEL,
        compression="zip",
    )
