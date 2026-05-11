from loguru import logger
from pathlib import Path

_handler_configured = False


def _setup_handler(show_time: bool) -> None:
    global _handler_configured
    if _handler_configured:
        return

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
        level="DEBUG",
    )

    # Default extra value so first log doesn't error
    logger.configure(extra={"name": ""})
    _handler_configured = True


def get_logger(module_name: str, show_time: bool = True) -> logger:
    _setup_handler(show_time)
    return logger.bind(name=module_name)


def add_file_logger(log_path: Path, rotation: str = "10 MB", retention: str = "7 days") -> None:
    logger.add(
        sink=str(log_path),
        format="{time:YYYY-MM-DD HH:mm:ss} | {level: <8} | {name} | {message}",
        rotation=rotation,
        retention=retention,
        level="DEBUG",
        compression="zip",
    )
