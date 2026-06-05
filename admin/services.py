import os
import sys
import json
import time
from functools import lru_cache
from pathlib import Path
from typing import Any
from concurrent.futures import ThreadPoolExecutor

import redis

from admin.config import get_settings, TOKEN_DIR
from modules.logger import get_logger

log = get_logger("Admin Services")

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


@lru_cache(maxsize=1)
def _import_user_mgr():
    from modules.redis_users import RedisUserManager
    r = get_redis()
    if r is None:
        return None
    return RedisUserManager(r=r)


@lru_cache(maxsize=1)
def _import_tasks():
    if "tasks" not in sys.modules:
        sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    import tasks
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
        log.success(f"Created user '{data['keyword']}' ({data.get('name', '')})")
    else:
        users = _list_users_json()
        if any(u.get("keyword") == data["keyword"] for u in users):
            raise ValueError(f"User '{data['keyword']}' already exists")
        users.append(data)
        _save_users_json(users)
        log.success(f"Created user '{data['keyword']}' ({data.get('name', '')}) [JSON]")


def update_user(keyword: str, data: dict[str, Any]) -> None:
    mgr = _import_user_mgr()
    if mgr is not None:
        existing = mgr.get(keyword)
        if not existing:
            raise ValueError(f"User '{keyword}' not found")
        merged = {**existing, **{k: v for k, v in data.items() if v is not None}}
        # Remove keys explicitly submitted as empty (e.g. cleared SMTP fields → use .env defaults)
        for key in ("smtp_host_user", "smtp_host_password"):
            if key in data and not data[key]:
                merged.pop(key, None)
        mgr.add_or_update(merged)
        log.success(f"Updated user '{keyword}'")
    else:
        users = _list_users_json()
        idx = next((i for i, u in enumerate(users) if u.get("keyword") == keyword), None)
        if idx is None:
            raise ValueError(f"User '{keyword}' not found")
        merged = {**users[idx], **{k: v for k, v in data.items() if v is not None}}
        for key in ("smtp_host_user", "smtp_host_password"):
            if key in data and not data[key]:
                merged.pop(key, None)
        users[idx] = merged
        _save_users_json(users)
        log.success(f"Updated user '{keyword}' [JSON]")


def delete_user(keyword: str) -> bool:
    mgr = _import_user_mgr()
    if mgr is not None:
        result = mgr.delete(keyword)
        if result:
            log.success(f"Deleted user '{keyword}'")
        return result
    else:
        users = _list_users_json()
        new_users = [u for u in users if u.get("keyword") != keyword]
        if len(new_users) == len(users):
            return False
        _save_users_json(new_users)
        log.success(f"Deleted user '{keyword}' [JSON]")
        return True


def activate_user(keyword: str) -> bool:
    mgr = _import_user_mgr()
    if mgr is not None:
        result = mgr.activate(keyword)
        if result:
            log.success(f"Activated user '{keyword}'")
        return result
    else:
        users = _list_users_json()
        for u in users:
            if u.get("keyword") == keyword:
                u["active"] = True
                _save_users_json(users)
                log.success(f"Activated user '{keyword}' [JSON]")
                return True
        return False


def deactivate_user(keyword: str) -> bool:
    mgr = _import_user_mgr()
    if mgr is not None:
        result = mgr.deactivate(keyword)
        if result:
            log.success(f"Deactivated user '{keyword}'")
        return result
    else:
        users = _list_users_json()
        for u in users:
            if u.get("keyword") == keyword:
                u["active"] = False
                _save_users_json(users)
                log.success(f"Deactivated user '{keyword}' [JSON]")
                return True
        return False


def import_users(path: str = "users.json") -> int:
    mgr = _import_user_mgr()
    if mgr is not None:
        count = mgr.import_from_json(path)
        log.success(f"Imported {count} user(s) from {path}")
        return count
    else:
        users_path = Path(path)
        if not users_path.exists():
            raise ValueError(f"File '{path}' not found")
        with open(users_path) as f:
            users = json.load(f)
        _save_users_json(users)
        log.success(f"Imported {len(users)} user(s) from {path} [JSON]")
        return len(users)


def import_users_from_list(users: list[dict[str, Any]]) -> int:
    """Import users from a list of dicts (e.g. uploaded file)."""
    mgr = _import_user_mgr()
    if mgr is not None:
        count = 0
        for user in users:
            mgr.add_or_update(user)
            count += 1
        log.success(f"Imported {count} user(s) from uploaded list")
        return count
    else:
        existing = _list_users_json()
        existing.extend(users)
        _save_users_json(existing)
        log.success(f"Imported {len(users)} user(s) from uploaded list [JSON]")
        return len(users)


def export_users(path: str = "users.json") -> int:
    mgr = _import_user_mgr()
    if mgr is not None:
        count = mgr.export_to_json(path)
        log.success(f"Exported {count} user(s) to {path}")
        return count
    else:
        users = _list_users_json()
        with open(path, "w") as f:
            json.dump(users, f, indent=2)
        log.success(f"Exported {len(users)} user(s) to {path} [JSON]")
        return len(users)


def clear_users() -> int:
    mgr = _import_user_mgr()
    if mgr is not None:
        count = mgr.clear_all()
        log.success(f"Cleared {count} user(s) from Redis")
        return count
    else:
        count = len(_list_users_json())
        _save_users_json([])
        log.success(f"Cleared {count} user(s) from JSON")
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
        "summary_template": "Custom prompt template (leave empty for default)",
    }
    return {
        "fields": ALL_FIELDS,
        "bool_fields": list(BOOL_FIELDS),
        "int_fields": list(INT_FIELDS),
        "descriptions": descriptions,
    }


# ── Token Management ───────────────────────────────────────────────────────

def check_tokens() -> list[dict[str, Any]]:
    from datetime import datetime
    users = list_users()
    result = []
    for user in users:
        kw = user.get("keyword", "default")
        token_path = TOKEN_DIR / f"token_{kw}.json"
        has_token = token_path.exists()
        expiry_status = "none"
        if has_token:
            try:
                with open(token_path) as f:
                    token_data = json.load(f)
                expiry_str = token_data.get("expiry")
                if expiry_str and expiry_str != "null" and expiry_str != "None":
                    # expiry can be ISO format string or None
                    if isinstance(expiry_str, str):
                        expiry_dt = datetime.fromisoformat(expiry_str.replace("Z", "+00:00"))
                        days_left = (expiry_dt - datetime.now(expiry_dt.tzinfo)).days
                        if days_left < 0:
                            expiry_status = "expired"
                        elif days_left <= 7:
                            expiry_status = "expiring_soon"
                        else:
                            expiry_status = "ok"
                    else:
                        expiry_status = "ok"
                else:
                    expiry_status = "ok"
            except Exception:
                expiry_status = "unknown"
        result.append({
            "keyword": kw,
            "name": user.get("name", "Unknown"),
            "has_token": has_token,
            "active": user.get("active", True),
            "expiry_status": expiry_status,
        })
    return result


def has_valid_token(keyword: str) -> bool:
    token_path = TOKEN_DIR / f"token_{keyword}.json"
    return token_path.exists()


def revoke_token(keyword: str) -> bool:
    token_path = TOKEN_DIR / f"token_{keyword}.json"
    if token_path.exists():
        token_path.unlink()
        return True
    return False


def bulk_send_email(keywords: list[str]) -> dict[str, Any]:
    """Enqueue email summary for multiple users."""
    tasks = _get_tasks()
    results = []
    for kw in keywords:
        user = get_user(kw)
        if not user:
            results.append({"keyword": kw, "status": "error", "error": "User not found"})
            continue
        try:
            r = enqueue_task(tasks.huey_send_email_to_user, kw)
            results.append({"keyword": kw, "status": "enqueued", "task_id": r.get("task_id")})
        except Exception as e:
            results.append({"keyword": kw, "status": "error", "error": str(e)})
    return {"results": results, "total": len(keywords), "enqueued": sum(1 for r in results if r["status"] == "enqueued")}


def bulk_send_whatsapp(keywords: list[str]) -> dict[str, Any]:
    """Enqueue WhatsApp summary for multiple users."""
    tasks = _get_tasks()
    results = []
    for kw in keywords:
        user = get_user(kw)
        if not user:
            results.append({"keyword": kw, "status": "error", "error": "User not found"})
            continue
        if not user.get("mobile"):
            results.append({"keyword": kw, "status": "error", "error": "No mobile number"})
            continue
        try:
            r = enqueue_task(tasks.huey_send_whatsapp_to_user, kw)
            results.append({"keyword": kw, "status": "enqueued", "task_id": r.get("task_id")})
        except Exception as e:
            results.append({"keyword": kw, "status": "error", "error": str(e)})
    return {"results": results, "total": len(keywords), "enqueued": sum(1 for r in results if r["status"] == "enqueued")}


def bulk_revoke_tokens(keywords: list[str]) -> dict[str, Any]:
    """Revoke tokens for multiple users."""
    results = []
    for kw in keywords:
        revoked = revoke_token(kw)
        results.append({"keyword": kw, "status": "revoked" if revoked else "not_found"})
    return {"results": results, "total": len(keywords), "revoked": sum(1 for r in results if r["status"] == "revoked")}


def export_users_csv() -> str:
    """Export all users as CSV string."""
    import csv
    import io
    users = list_users()
    if not users:
        return ""
    output = io.StringIO()
    # Collect all unique keys across all users
    all_keys = []
    for u in users:
        for k in u.keys():
            if k not in all_keys:
                all_keys.append(k)
    writer = csv.DictWriter(output, fieldnames=all_keys, extrasaction='ignore')
    writer.writeheader()
    for u in users:
        # Convert booleans to strings for CSV
        row = {}
        for k, v in u.items():
            if isinstance(v, bool):
                row[k] = "true" if v else "false"
            elif v is None:
                row[k] = ""
            else:
                row[k] = v
        writer.writerow(row)
    return output.getvalue()


# ── Audit Log ──────────────────────────────────────────────────────────────

AUDIT_LOG_KEY = "morning_mailer:audit_log"


def get_audit_log(limit: int = 50, offset: int = 0, task: str | None = None,
                  keyword: str | None = None, status_filter: str | None = None,
                  q: str | None = None) -> dict[str, Any]:
    """Get audit log entries from Redis with filtering and pagination."""
    r = get_redis()
    if not r:
        return {"entries": [], "total": 0, "limit": limit, "offset": offset,
                "tasks": [], "keywords": [], "statuses": []}

    # Fetch a generous window for filtering — enough for most pagination + filter needs
    FETCH_WINDOW = 5000
    raw = r.lrange(AUDIT_LOG_KEY, 0, FETCH_WINDOW - 1)
    all_entries = []
    tasks_set: set[str] = set()
    keywords_set: set[str] = set()
    statuses_set: set[str] = set()

    for item in raw:
        try:
            entry = json.loads(item)
        except (json.JSONDecodeError, TypeError):
            continue
        all_entries.append(entry)
        tasks_set.add(entry.get("task", ""))
        keywords_set.add(entry.get("keyword", ""))
        statuses_set.add(entry.get("status", ""))

    # Apply filters
    filtered = all_entries
    if task:
        filtered = [e for e in filtered if e.get("task") == task]
    if keyword:
        filtered = [e for e in filtered if e.get("keyword") == keyword]
    if status_filter:
        filtered = [e for e in filtered if e.get("status") == status_filter]
    if q:
        ql = q.lower()
        filtered = [e for e in filtered if
                    ql in (e.get("task", "") or "").lower()
                    or ql in (e.get("keyword", "") or "").lower()
                    or ql in (e.get("details", "") or "").lower()
                    or ql in (e.get("status", "") or "").lower()]

    total = len(filtered)
    page = filtered[offset:offset + limit]

    return {
        "entries": page,
        "total": total,
        "limit": limit,
        "offset": offset,
        "tasks": sorted(tasks_set - {""}),
        "keywords": sorted(keywords_set - {""}),
        "statuses": sorted(statuses_set - {""}),
    }


# ── History Tracking ──────────────────────────────────────────────────────

HISTORY_PREFIX = "morning_mailer:history"
HISTORY_MAX_ENTRIES = 50  # per user


def record_history(keyword: str, channel: str, status: str, email_count: int = 0,
                   error: str | None = None) -> None:
    """Record a summary event in Redis (called after task completes)."""
    r = get_redis()
    if not r:
        return
    import time as _time
    entry = json.dumps({
        "ts": _time.time(),
        "channel": channel,
        "status": status,
        "email_count": email_count,
        "error": error,
    })
    key = f"{HISTORY_PREFIX}:{keyword}"
    r.lpush(key, entry)
    r.ltrim(key, 0, HISTORY_MAX_ENTRIES - 1)
    r.expire(key, 86400 * 90)  # 90 days TTL


def get_history(keyword: str, limit: int = 20) -> list[dict[str, Any]]:
    """Get recent history entries for a user."""
    r = get_redis()
    if not r:
        return []
    key = f"{HISTORY_PREFIX}:{keyword}"
    entries = r.lrange(key, 0, limit - 1)
    result = []
    for e in entries:
        try:
            result.append(json.loads(e))
        except (json.JSONDecodeError, TypeError):
            pass
    return result


def get_last_summary_stats() -> dict[str, dict[str, Any]]:
    """Get last summary stats for all users (for dashboard)."""
    r = get_redis()
    if not r:
        return {}
    users = list_users()
    stats = {}
    for user in users:
        kw = user.get("keyword", "")
        if not kw:
            continue
        # Check last_run from tasks
        last_run = r.get(f"morning_mailer:last_run:{kw}")
        wa_last_run = r.get(f"morning_mailer:whatsapp_last_run:{kw}")
        # Get first history entry
        history = get_history(kw, limit=1)
        last_entry = history[0] if history else None
        stats[kw] = {
            "last_email_run": last_run,
            "last_whatsapp_run": wa_last_run,
            "last_status": last_entry.get("status") if last_entry else None,
            "last_channel": last_entry.get("channel") if last_entry else None,
            "last_email_count": last_entry.get("email_count", 0) if last_entry else 0,
        }
    return stats


# ── Actions ────────────────────────────────────────────────────────────────
# All actions enqueue huey tasks — the huey container does the actual work.

def _get_tasks():
    """Import tasks module (lazy, to avoid init in app container)."""
    return _import_tasks()


def enqueue_task(task_func, *args, **kwargs) -> dict[str, Any]:
    """Enqueue a huey task and return task ID."""
    raw_func = getattr(task_func, 'func', task_func)
    task_name = getattr(raw_func, '__name__', str(task_func))
    task_wrapper = task_func(*args, **kwargs)
    task_id = task_wrapper.id if hasattr(task_wrapper, 'id') else str(task_wrapper)
    log.info(f"Enqueued task {task_name} → {task_id}")
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
    log.info(f"Test email enqueued: subject='{subject}'")
    return enqueue_task(tasks.huey_test_send_email, subject, body)


def run_send_test_whatsapp(mobile: str, message: str) -> dict[str, Any]:
    """Enqueue test WhatsApp message."""
    tasks = _get_tasks()
    log.info(f"Test WhatsApp enqueued: mobile='{mobile}'")
    return enqueue_task(tasks.huey_test_send_whatsapp, mobile, message)


def run_switch_model(provider: str, model_name: str | None = None, temperature: float | None = None) -> str:
    """Switch LLM model (runs in app container, no enqueue needed)."""
    tasks = _get_tasks()
    tasks.get_agent().hot_switch_model(model_provider=provider, model_name=model_name, temperature=temperature)
    msg = f"Model switched to {provider} ({model_name or 'default'})"
    log.success(msg)
    return msg


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
        log.success(f"Cleared last_run for {len(users)} user(s)")
        return f"Cleared last_run for {len(users)} user(s)"
    r.delete(f"morning_mailer:last_run:{keyword}")
    r.delete(f"morning_mailer:last_schedule:{keyword}")
    log.success(f"Cleared last_run for {keyword}")
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
        log.warning(f"OAuth URL generation failed: no client_secret file found")
        return None

    with open(config_path) as f:
        client_config = json.load(f)

    from modules.web_auth import get_credential_type, get_client_id, get_auth_url
    try:
        auth_url = get_auth_url(client_config, keyword)
        log.info(f"Generated OAuth URL for '{keyword}'")
        return auth_url
    except Exception as e:
        log.error(f"OAuth URL generation failed for '{keyword}': {e}")
        return None


def exchange_oauth_code(code: str, keyword: str) -> bool:
    from admin.config import CLIENT_SECRET_WEB_PATH, CLIENT_SECRET_PATH
    config_path = CLIENT_SECRET_WEB_PATH if CLIENT_SECRET_WEB_PATH.exists() else CLIENT_SECRET_PATH
    if not config_path.exists():
        log.warning(f"OAuth exchange failed: no client_secret file found")
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
            "scopes": tokens.get("scope", "https://www.googleapis.com/auth/gmail.readonly https://www.googleapis.com/auth/calendar.readonly").split(),
            "universe_domain": "googleapis.com",
            "account": "",
            "expiry": None,
        }
        with open(token_path, "w") as f:
            json.dump(converted_token, f, indent=2)
        log.success(f"OAuth token saved for '{keyword}'")
        return True
    except Exception as e:
        log.error(f"OAuth exchange failed for '{keyword}': {e}")
        return False
