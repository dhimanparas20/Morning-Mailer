import os
import sys
import json
import time
import importlib
from pathlib import Path
from typing import Any
from concurrent.futures import ThreadPoolExecutor

import redis

from admin.config import get_settings, TOKEN_DIR

settings = get_settings()
_redis_client: redis.Redis | None = None


def get_redis() -> redis.Redis | None:
    global _redis_client
    if _redis_client is None:
        try:
            _redis_client = redis.from_url(settings.REDIS_URL, decode_responses=True, socket_connect_timeout=2)
            _redis_client.ping()
        except Exception:
            _redis_client = None
    return _redis_client


def _import_user_mgr():
    from modules.redis_users import RedisUserManager
    r = get_redis()
    if r is None:
        return None
    return RedisUserManager(r=r)


def _import_tasks():
    if "tasks" not in sys.modules:
        sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    import tasks
    importlib.reload(tasks)
    return tasks


def _list_users_json() -> list[dict[str, Any]]:
    """Fallback: load users from users.json when Redis is unavailable."""
    users_path = Path(__file__).resolve().parent.parent / "users.json"
    if users_path.exists():
        with open(users_path) as f:
            return json.load(f)
    return []


def _save_users_json(users: list[dict[str, Any]]) -> None:
    users_path = Path(__file__).resolve().parent.parent / "users.json"
    with open(users_path, "w") as f:
        json.dump(users, f, indent=2)


# ── User CRUD ──────────────────────────────────────────────────────────────

def list_users() -> list[dict[str, Any]]:
    mgr = _import_user_mgr()
    if mgr is None:
        return _list_users_json()
    return mgr.get_all()


def get_user(keyword: str) -> dict[str, Any] | None:
    mgr = _import_user_mgr()
    if mgr is None:
        for u in _list_users_json():
            if u.get("keyword") == keyword:
                return u
        return None
    return mgr.get(keyword)


def create_user(data: dict[str, Any]) -> None:
    mgr = _import_user_mgr()
    if mgr is not None:
        if mgr.exists(data["keyword"]):
            raise ValueError(f"User '{data['keyword']}' already exists")
        mgr.add_or_update(data)
    else:
        users = _list_users_json()
        if any(u.get("keyword") == data["keyword"] for u in users):
            raise ValueError(f"User '{data['keyword']}' already exists")
        users.append(data)
        _save_users_json(users)


def update_user(keyword: str, data: dict[str, Any]) -> None:
    mgr = _import_user_mgr()
    if mgr is not None:
        existing = mgr.get(keyword)
        if not existing:
            raise ValueError(f"User '{keyword}' not found")
        merged = {**existing, **{k: v for k, v in data.items() if v is not None}}
        mgr.add_or_update(merged)
    else:
        users = _list_users_json()
        idx = next((i for i, u in enumerate(users) if u.get("keyword") == keyword), None)
        if idx is None:
            raise ValueError(f"User '{keyword}' not found")
        users[idx] = {**users[idx], **{k: v for k, v in data.items() if v is not None}}
        _save_users_json(users)


def delete_user(keyword: str) -> bool:
    mgr = _import_user_mgr()
    if mgr is not None:
        return mgr.delete(keyword)
    else:
        users = _list_users_json()
        new_users = [u for u in users if u.get("keyword") != keyword]
        if len(new_users) == len(users):
            return False
        _save_users_json(new_users)
        return True


def activate_user(keyword: str) -> bool:
    mgr = _import_user_mgr()
    if mgr is not None:
        return mgr.activate(keyword)
    else:
        users = _list_users_json()
        for u in users:
            if u.get("keyword") == keyword:
                u["active"] = True
                _save_users_json(users)
                return True
        return False


def deactivate_user(keyword: str) -> bool:
    mgr = _import_user_mgr()
    if mgr is not None:
        return mgr.deactivate(keyword)
    else:
        users = _list_users_json()
        for u in users:
            if u.get("keyword") == keyword:
                u["active"] = False
                _save_users_json(users)
                return True
        return False


def import_users(path: str = "users.json") -> int:
    mgr = _import_user_mgr()
    if mgr is not None:
        return mgr.import_from_json(path)
    else:
        users_path = Path(path)
        if not users_path.exists():
            raise ValueError(f"File '{path}' not found")
        with open(users_path) as f:
            users = json.load(f)
        _save_users_json(users)
        return len(users)


def export_users(path: str = "users.json") -> int:
    mgr = _import_user_mgr()
    if mgr is not None:
        return mgr.export_to_json(path)
    else:
        users = _list_users_json()
        with open(path, "w") as f:
            json.dump(users, f, indent=2)
        return len(users)


def clear_users() -> int:
    mgr = _import_user_mgr()
    if mgr is not None:
        return mgr.clear_all()
    else:
        count = len(_list_users_json())
        _save_users_json([])
        return count


def user_fields() -> dict[str, Any]:
    from modules.redis_users import ALL_FIELDS, BOOL_FIELDS, INT_FIELDS
    descriptions = {
        "name": "Display name", "email": "Email address",
        "keyword": "Unique ID", "active": "Enable/disable user",
        "use_email": "Enable email", "use_whatsapp": "Enable WhatsApp",
        "fetch_calendar": "Include calendar", "max_email_results": "Max emails",
        "days_threshold": "Days back", "schedule_time": "Run time (HH:MM)",
        "smtp_host_user": "SMTP username", "smtp_host_password": "SMTP password",
        "mobile": "WhatsApp number",
    }
    return {
        "fields": ALL_FIELDS,
        "bool_fields": list(BOOL_FIELDS),
        "int_fields": list(INT_FIELDS),
        "descriptions": descriptions,
    }


# ── Token Management ───────────────────────────────────────────────────────

def check_tokens() -> list[dict[str, Any]]:
    users = list_users()
    result = []
    for user in users:
        kw = user.get("keyword", "default")
        token_path = TOKEN_DIR / f"token_{kw}.json"
        result.append({
            "keyword": kw,
            "name": user.get("name", "Unknown"),
            "has_token": token_path.exists(),
            "active": user.get("active", True),
        })
    return result


def has_valid_token(keyword: str) -> bool:
    token_path = TOKEN_DIR / f"token_{keyword}.json"
    return token_path.exists()


# ── Actions ────────────────────────────────────────────────────────────────
# All actions enqueue huey tasks — the huey container does the actual work.

def _get_tasks():
    """Import tasks module (lazy, to avoid init in app container)."""
    return _import_tasks()


def enqueue_task(task_func, *args, **kwargs) -> dict[str, Any]:
    """Enqueue a huey task and return task ID."""
    task_wrapper = task_func(*args, **kwargs)
    task_id = task_wrapper.id if hasattr(task_wrapper, 'id') else str(task_wrapper)
    return {"task_id": task_id, "status": "enqueued"}


def check_task_status(task_id: str) -> dict[str, Any]:
    """Check status of a huey task by ID."""
    tasks = _get_tasks()
    try:
        res = tasks.huey.result(task_id, preserve=True)
        if res is not None:
            return {"task_id": task_id, "status": "finished", "result": res}
        task_data = tasks.huey.storage.peek_data(task_id)
        if task_data:
            return {"task_id": task_id, "status": "pending", "result": None}
        return {"task_id": task_id, "status": "not_found", "result": None}
    except Exception as e:
        return {"task_id": task_id, "status": "error", "error": str(e)}


# ── Enqueue actions ────────────────────────────────────────────────────────

def run_daily_email_summary() -> dict[str, Any]:
    """Enqueue scheduled email summary (huey picks it up)."""
    tasks = _get_tasks()
    return enqueue_task(tasks.daily_summary)


def run_daily_whatsapp_summary() -> dict[str, Any]:
    """Enqueue scheduled WhatsApp summary."""
    tasks = _get_tasks()
    return enqueue_task(tasks.daily_summary)


def run_force_email_summary() -> dict[str, Any]:
    """Enqueue force email for ALL users."""
    tasks = _get_tasks()
    return enqueue_task(tasks.huey_force_email_all)


def run_force_whatsapp_summary() -> dict[str, Any]:
    """Enqueue force WhatsApp for ALL users."""
    tasks = _get_tasks()
    return enqueue_task(tasks.huey_force_whatsapp_all)


def run_send_email_summary(keyword: str) -> dict[str, Any]:
    """Enqueue email summary for a specific user."""
    tasks = _get_tasks()
    user = get_user(keyword)
    if not user:
        raise ValueError(f"User '{keyword}' not found")
    return enqueue_task(tasks.huey_send_email_to_user, keyword)


def run_send_whatsapp_summary(keyword: str) -> dict[str, Any]:
    """Enqueue WhatsApp summary for a specific user."""
    tasks = _get_tasks()
    user = get_user(keyword)
    if not user:
        raise ValueError(f"User '{keyword}' not found")
    if not user.get("mobile"):
        raise ValueError(f"User {user.get('name')} has no mobile number")
    return enqueue_task(tasks.huey_send_whatsapp_to_user, keyword)


def run_fetch_calendar(keyword: str, days: int = 2) -> dict[str, Any]:
    """Fetch calendar events (read-only, no enqueue needed)."""
    from modules.fetch_calendar import fetch_upcoming_events
    return fetch_upcoming_events(keyword=keyword, days=days)


def run_send_calendar_email(keyword: str, days: int = 2) -> dict[str, Any]:
    """Enqueue calendar email for a specific user."""
    tasks = _get_tasks()
    user = get_user(keyword)
    if not user:
        raise ValueError(f"User '{keyword}' not found")
    return enqueue_task(tasks.huey_fetch_calendar_and_send_email, keyword, days)


def run_send_calendar_whatsapp(keyword: str, days: int = 2) -> dict[str, Any]:
    """Enqueue calendar WhatsApp for a specific user."""
    tasks = _get_tasks()
    user = get_user(keyword)
    if not user:
        raise ValueError(f"User '{keyword}' not found")
    if not user.get("mobile"):
        raise ValueError("No mobile number configured")
    return enqueue_task(tasks.huey_fetch_calendar_and_send_whatsapp, keyword, days)


def run_send_calendar_both(keyword: str, days: int = 2) -> dict[str, Any]:
    """Enqueue calendar both channels for a specific user."""
    tasks = _get_tasks()
    user = get_user(keyword)
    if not user:
        raise ValueError(f"User '{keyword}' not found")
    return enqueue_task(tasks.huey_fetch_calendar_and_send_both, keyword, days)


def run_send_test_email(subject: str, body: str) -> dict[str, Any]:
    """Enqueue test email."""
    tasks = _get_tasks()
    return enqueue_task(tasks.huey_test_send_email, subject, body)


def run_send_test_whatsapp(mobile: str, message: str) -> dict[str, Any]:
    """Enqueue test WhatsApp message."""
    tasks = _get_tasks()
    return enqueue_task(tasks.huey_test_send_whatsapp, mobile, message)


def run_switch_model(provider: str, model_name: str | None = None, temperature: float | None = None) -> str:
    """Switch LLM model (runs in app container, no enqueue needed)."""
    tasks = _get_tasks()
    tasks.AGENT.hot_switch_model(model_provider=provider, model_name=model_name, temperature=temperature)
    return f"Model switched to {provider} ({model_name or 'default'})"


def run_clear_last_run(keyword: str | None = None) -> str:
    """Clear last_run dates in Redis."""
    r = get_redis()
    if not r:
        return "Redis unavailable - cannot clear last_run"
    if not keyword or keyword == "all":
        users = list_users()
        for user in users:
            kw = user.get("keyword", "default")
            r.delete(f"morning_mailer:last_run:{kw}")
            r.delete(f"morning_mailer:last_schedule:{kw}")
        return f"Cleared last_run for {len(users)} user(s)"
    r.delete(f"morning_mailer:last_run:{keyword}")
    r.delete(f"morning_mailer:last_schedule:{keyword}")
    return f"Cleared last_run for {keyword}"


def get_redis_status() -> dict[str, Any]:
    r = get_redis()
    if r is None:
        return {"connected": False, "error": "Redis unavailable (using users.json fallback)"}
    try:
        r.ping()
        info = r.info()
        mgr = _import_user_mgr()
        return {
            "connected": True,
            "keys": len(r.keys("*")),
            "memory": info.get("used_memory_human", "N/A"),
            "users": mgr.count() if mgr else 0,
        }
    except Exception as e:
        return {"connected": False, "error": str(e)}


def get_scheduler_status() -> dict[str, Any]:
    tasks = _import_tasks()
    return {
        "check_interval": tasks.SCHEDULE_CHECK_INTERVAL,
        "schedule_time": tasks.SCHEDULE_TIME,
        "max_email_results": tasks.MAX_EMAIL_RESULTS,
        "days_threshold": tasks.DAYS_THRESHOLD,
        "max_workers": tasks.MAX_THREAD_WORKERS,
        "retry_count": tasks.RETRY_COUNT,
        "env_mode": os.getenv("ENV_MODE", "dev"),
    }


def generate_oauth_url(keyword: str) -> str | None:
    from admin.config import CLIENT_SECRET_WEB_PATH, CLIENT_SECRET_PATH, get_settings
    settings = get_settings()

    config_path = CLIENT_SECRET_WEB_PATH if CLIENT_SECRET_WEB_PATH.exists() else CLIENT_SECRET_PATH
    if not config_path.exists():
        return None

    with open(config_path) as f:
        client_config = json.load(f)

    from modules.web_auth import get_credential_type, get_client_id, get_auth_url
    try:
        auth_url = get_auth_url(client_config, keyword)
        return auth_url
    except Exception:
        return None


def exchange_oauth_code(code: str, keyword: str) -> bool:
    from admin.config import CLIENT_SECRET_WEB_PATH, CLIENT_SECRET_PATH
    config_path = CLIENT_SECRET_WEB_PATH if CLIENT_SECRET_WEB_PATH.exists() else CLIENT_SECRET_PATH
    if not config_path.exists():
        return False

    with open(config_path) as f:
        client_config = json.load(f)

    from modules.web_auth import exchange_code_for_token, get_token_path, get_client_id, get_client_secret
    try:
        tokens = exchange_code_for_token(code, client_config)
        token_path = get_token_path(keyword)
        client_id = get_client_id(client_config)
        client_secret = get_client_secret(client_config)

        converted_token = {
            "token": tokens.get("access_token"),
            "refresh_token": tokens.get("refresh_token"),
            "token_uri": "https://oauth2.googleapis.com/token",
            "client_id": client_id,
            "client_secret": client_secret,
            "scopes": [tokens.get("scope", "https://www.googleapis.com/auth/gmail.readonly https://www.googleapis.com/auth/calendar.readonly")],
            "universe_domain": "googleapis.com",
            "account": "",
            "expiry": None,
        }
        with open(token_path, "w") as f:
            json.dump(converted_token, f, indent=2)
        return True
    except Exception:
        return False
