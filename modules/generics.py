import time
from datetime import datetime, timezone


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def get_timestamp() -> float:
    return time.time()


def format_timestamp(ts: float) -> str:
    dt = datetime.fromtimestamp(ts)
    return dt.strftime("%H:%M:%S %d:%m:%Y")


def parse_datetime(dt_str: str) -> float:
    dt = datetime.fromisoformat(dt_str)
    return dt.timestamp()


def utc_to_local(dt_str: str | None = None) -> str:
    if dt_str is None:
        return datetime.now().isoformat()
    dt = datetime.fromisoformat(dt_str.replace("Z", "+00:00"))
    return dt.astimezone().isoformat()