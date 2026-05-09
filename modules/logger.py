from loguru import logger
from pathlib import Path


def get_logger(module_name: str, show_time: bool = True) -> logger:
    _remove_default_handler()

    _format = (
        "<green>{time:YYYY-MM-DD HH:mm:ss}</green> | "
        "<level>{level: <8}</level> | "
        f"<cyan>{module_name}</cyan> | "
        "<level>{message}</level>"
    ) if show_time else (
        "<level>{level: <8}</level> | "
        f"<cyan>{module_name}</cyan> | "
        "<level>{message}</level>"
    )

    logger.add(
        sink=lambda msg: print(msg, end=""),
        format=_format,
        colorize=True,
        level="DEBUG",
    )

    return logger


def _remove_default_handler() -> None:
    logger.remove(handler_id=None)


def add_file_logger(log_path: Path, rotation: str = "10 MB", retention: str = "7 days") -> None:
    logger.add(
        sink=str(log_path),
        format="{time:YYYY-MM-DD HH:mm:ss} | {level: <8} | {message}",
        rotation=rotation,
        retention=retention,
        level="DEBUG",
        compression="zip",
    )