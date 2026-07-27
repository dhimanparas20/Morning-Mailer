"""
Morning Mailer - Scheduled email fetching and AI summarization.

This module contains Huey periodic tasks for:
- Fetching emails from Gmail for multiple users
- Summarizing emails using LLM
- Sending summary via email to each user
"""

import json
import os
import smtplib
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import requests
from dotenv import load_dotenv
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from huey import RedisHuey, crontab
from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich import box

from modules import get_logger, format_timestamp, now_ist
from modules.fetch_emails import fetch_emails, load_users as load_email_users, get_token_path
from modules.fetch_calendar import fetch_upcoming_events, has_valid_token as has_valid_calendar_token
from modules.agent_mod import AgentModule
from modules.prompt import WHATSAPP_SYSTEM_PROMPT

import redis

console = Console()

load_dotenv()
logger = get_logger(__name__, show_time=False)

# Huey instance for task queue
huey = RedisHuey("Morning Mailer", url=os.getenv("REDIS_URL"), utc=False)

# Configuration from environment
RETRY_COUNT = int(os.getenv("RETRY_COUNT", 3))
RETRY_DELAY = int(os.getenv("RETRY_DELAY", 60))
MAX_EMAIL_RESULTS = int(os.getenv("MAX_EMAIL_RESULTS", 10))
MAX_THREAD_WORKERS = int(os.getenv("MAX_THREAD_WORKERS", 5))
SCHEDULE_TIME = os.getenv("SCHEDULE_TIME", "08:00")  # Default time for users without schedule_time
DAYS_THRESHOLD = int(os.getenv("DAYS_THRESHOLD", 1))
SCHEDULE_CHECK_INTERVAL = int(os.getenv("SCHEDULE_CHECK_INTERVAL", 5))  # Check every N minutes

# WhatsApp (WAHA) configuration
WAHA_API_URL = os.getenv("WAHA_API_URL", "http://waha:3000")
WAHA_API_KEY = os.getenv("WAHA_API_KEY", "")
WAHA_SESSION = os.getenv("WAHA_SESSION", "default")

# Global LLM agent instance (lazy-initialized)
AGENT = None


def get_agent():
    """Lazy-initialize the LLM agent only when actually needed."""
    global AGENT
    if AGENT is None:
        AGENT = AgentModule()
        AGENT.init()
    return AGENT

# Redis client for tracking last run
redis_client = redis.from_url(os.getenv("REDIS_URL"), decode_responses=True)

# ── Audit Logging ──────────────────────────────────────────────────────────

AUDIT_LOG_KEY = "morning_mailer:audit_log"
AUDIT_LOG_TTL = 86400 * 30  # 30 days


def audit_log(
    task_name: str,
    keyword: str,
    status: str,
    details: str | None = None,
    duration: float | None = None,
) -> None:
    """Record an audit log entry in Redis (60-day TTL, fire-and-forget)."""
    try:
        entry = {
            "ts": time.time(),
            "task": task_name,
            "keyword": keyword,
            "status": status,
        }
        if details:
            entry["details"] = details
        if duration is not None:
            entry["duration"] = round(duration, 3)
        redis_client.lpush(AUDIT_LOG_KEY, json.dumps(entry))
        redis_client.expire(AUDIT_LOG_KEY, AUDIT_LOG_TTL)
    except Exception:
        pass  # never break the main task


def get_user_last_run_date(keyword: str) -> str | None:
    """Get the last run date for a user from Redis."""
    key = f"morning_mailer:last_run:{keyword}"
    return redis_client.get(key)


def set_user_last_run_date(keyword: str, date_str: str, schedule_time: str = None) -> None:
    """Set the last run date for a user in Redis."""
    key = f"morning_mailer:last_run:{keyword}"
    redis_client.set(key, date_str)
    if schedule_time:
        schedule_key = f"morning_mailer:last_schedule:{keyword}"
        redis_client.set(schedule_key, schedule_time)


def should_run_today(user: dict[str, Any], global_schedule_time: str, redis_prefix: str = "") -> bool:
    """Check if user should run today based on their schedule_time.
    
    redis_prefix: optional prefix for Redis keys (e.g., "whatsapp_" for WhatsApp task)
    """
    keyword = user.get("keyword", "default")
    user_schedule = user.get("schedule_time", global_schedule_time)

    now = now_ist()
    current_time = now.time()

    user_hour, user_minute = map(int, user_schedule.split(":"))
    scheduled_time = now.replace(hour=user_hour, minute=user_minute, second=0, microsecond=0)

    if now < scheduled_time:
        return False

    env_mode = os.getenv("ENV_MODE", "dev").lower()
    today_str = now.strftime("%Y-%m-%d")

    last_run = redis_client.get(f"morning_mailer:{redis_prefix}last_run:{keyword}")
    last_schedule_run = redis_client.get(f"morning_mailer:{redis_prefix}last_schedule:{keyword}")

    if env_mode == "dev":
        if last_schedule_run != user_schedule:
            logger.debug(f"[{keyword}] DEV: schedule changed from {last_schedule_run} to {user_schedule}, running")
            return True
        if last_run != today_str:
            return True
        logger.debug(f"[{keyword}] DEV: already ran at {user_schedule}, skipping")
        return False

    # PROD: only run once per day
    return last_run != today_str


def get_user_settings(user: dict[str, Any]) -> tuple[int, int]:
    """Get max_email_results and days_threshold for a user."""
    global_max = int(os.getenv("MAX_EMAIL_RESULTS", 10))
    global_days = int(os.getenv("DAYS_THRESHOLD", 1))

    max_results = user.get("max_email_results", global_max)
    days_threshold = user.get("days_threshold", global_days)

    return max_results, days_threshold


# =============================================================================
# Helper Functions
# =============================================================================

def get_job_status(job_id: str) -> dict:
    """Get status of a Huey job by ID."""
    logger.info(f"Checking status for job ID: {job_id}")
    res = huey.result(job_id, preserve=True)
    if res is not None:
        return {"status": "finished", "result": res}
    task_data = huey.storage.peek_data(job_id)
    if task_data:
        return {"status": "pending", "result": None}
    return {"status": "not_found", "result": None}


def load_users() -> list[dict[str, Any]]:
    """Load active users — tries Redis first, falls back to users.json, then .env."""
    # 1. Try Redis ----------------------------------------------------------------
    try:
        from modules.redis_users import RedisUserManager
        mgr = RedisUserManager(r=redis_client)
        redis_users = mgr.get_all()
        if redis_users:
            active_users = []
            for user in redis_users:
                if user.get("active", True):
                    if not user.get("smtp_host_user"):
                        user["smtp_host_user"] = os.getenv("EMAIL_HOST_USER")
                    if not user.get("smtp_host_password"):
                        user["smtp_host_password"] = os.getenv("EMAIL_HOST_PASSWORD")
                    active_users.append(user)
            logger.success(f"Loaded {len(active_users)} active user(s) from Redis (from {len(redis_users)} total)")
            return active_users
    except Exception as exc:
        logger.debug("Redis user lookup skipped: %s", exc)

    # 2. Fall back to users.json -------------------------------------------------
    users_file = Path("users.json")

    if not users_file.exists():
        logger.info("users.json not found, falling back to single user from .env")
        return [{
            "name": "Default User",
            "email": os.getenv("MY_EMAIL", "unknown@example.com"),
            "keyword": "default",
            "active": True,
            "smtp_host_user": os.getenv("EMAIL_HOST_USER"),
            "smtp_host_password": os.getenv("EMAIL_HOST_PASSWORD"),
        }]

    with open(users_file, "r", encoding="utf-8") as f:
        users = json.load(f)

    if not users:
        logger.warning("No users in users.json, falling back to .env")
        return [{
            "name": "Default User",
            "email": os.getenv("MY_EMAIL", "unknown@example.com"),
            "keyword": "default",
            "active": True,
            "smtp_host_user": os.getenv("EMAIL_HOST_USER"),
            "smtp_host_password": os.getenv("EMAIL_HOST_PASSWORD"),
        }]

    # Fill in missing SMTP credentials from .env fallback and filter active users
    active_users = []
    for user in users:
        if user.get("active", True):
            if not user.get("smtp_host_user"):
                user["smtp_host_user"] = os.getenv("EMAIL_HOST_USER")
            if not user.get("smtp_host_password"):
                user["smtp_host_password"] = os.getenv("EMAIL_HOST_PASSWORD")
            active_users.append(user)

    logger.success(f"Loaded {len(active_users)} active user(s) from users.json (from {len(users)} total)")
    return active_users


def fetch_emails_with_retry(keyword: str, max_results: int = None, days_threshold: int = None) -> dict[str, Any]:
    """Fetch emails for a specific user with retry logic."""
    if max_results is None:
        max_results = MAX_EMAIL_RESULTS
    if days_threshold is None:
        days_threshold = DAYS_THRESHOLD

    last_error = None
    _t0 = time.time()

    for attempt in range(RETRY_COUNT):
        try:
            logger.info(f"[{keyword}] Attempt {attempt + 1}/{RETRY_COUNT}")

            now = now_ist()
            date_to = now.isoformat()
            days_to_fetch = days_threshold + 1
            date_from = (now - timedelta(days=days_to_fetch)).isoformat()

            date_from_ts = datetime.fromisoformat(date_from).timestamp()
            date_to_ts = datetime.fromisoformat(date_to).timestamp()
            logger.info(f"[{keyword}] Fetching emails from {format_timestamp(date_from_ts)} to {format_timestamp(date_to_ts)}")

            result = fetch_emails(
                keyword=keyword,
                max_results=max_results,
                date_from=date_from,
                date_to=date_to,
                sort_by="date",
                sort_order="desc",
            )

            if result["success"]:
                count = result.get("count", 0)
                logger.success(f"[{keyword}] Fetched {count} emails")
                audit_log("fetch_emails", keyword, "success", f"{count} emails in {attempt+1}/{RETRY_COUNT} attempts", time.time() - _t0)
                return result
            else:
                last_error = result.get("error")
                logger.warning(f"[{keyword}] Attempt {attempt + 1} failed: {last_error}")

        except Exception as e:
            last_error = str(e)
            logger.error(f"[{keyword}] Attempt {attempt + 1} exception: {e}")

        if attempt < RETRY_COUNT - 1:
            logger.info(f"[{keyword}] Retrying in {RETRY_DELAY}s...")
            time.sleep(RETRY_DELAY)

    logger.error(f"[{keyword}] All {RETRY_COUNT} attempts failed. Last error: {last_error}")
    audit_log("fetch_emails", keyword, "error", f"All {RETRY_COUNT} attempts failed: {last_error}", time.time() - _t0)
    return {"success": False, "error": last_error, "count": 0, "emails": []}


def fetch_calendar_events_with_retry(keyword: str, days: int = 2, max_results: int = 20) -> dict[str, Any]:
    """Fetch calendar events for a specific user with retry logic.

    Returns events for today and tomorrow (or N days ahead).
    """
    last_error = None
    _t0 = time.time()

    for attempt in range(RETRY_COUNT):
        try:
            logger.info(f"[{keyword}] Calendar attempt {attempt + 1}/{RETRY_COUNT}")

            result = fetch_upcoming_events(keyword=keyword, days=days, max_results=max_results)

            if result["success"]:
                count = result.get("count", 0)
                logger.success(f"[{keyword}] Fetched {count} calendar events")
                audit_log("fetch_calendar", keyword, "success", f"{count} events in {attempt+1}/{RETRY_COUNT} attempts", time.time() - _t0)
                return result
            else:
                last_error = result.get("error")
                logger.warning(f"[{keyword}] Calendar attempt {attempt + 1} failed: {last_error}")

        except Exception as e:
            last_error = str(e)
            logger.error(f"[{keyword}] Calendar attempt {attempt + 1} exception: {e}")

        if attempt < RETRY_COUNT - 1:
            logger.info(f"[{keyword}] Retrying calendar in {RETRY_DELAY}s...")
            time.sleep(RETRY_DELAY)

    logger.error(f"[{keyword}] All {RETRY_COUNT} calendar attempts failed. Last error: {last_error}")
    audit_log("fetch_calendar", keyword, "error", f"All {RETRY_COUNT} attempts failed: {last_error}", time.time() - _t0)
    return {"success": False, "error": last_error, "count": 0, "events": []}


def summarize_emails(emails: list[dict[str, Any]], user_name: str = None, calendar_events: list[dict[str, Any]] = None) -> str:
    """Summarize emails using LLM, optionally including calendar events."""
    logger.info(f"Summarizing {len(emails)} emails" + (f" + {len(calendar_events)} calendar events" if calendar_events else "") + "...")
    summary = get_agent().summarize_emails(emails, user_name=user_name, calendar_events=calendar_events)
    logger.success("Email summary generated")
    return summary


def send_email(
    to: str | list[str],
    subject: str,
    body: str,
    is_html: bool = False,
    smtp_user: str | None = None,
    smtp_password: str | None = None,
    keyword: str | None = None,
) -> str:
    """Send email via SMTP."""
    _kw = keyword or "system"
    if not smtp_user:
        smtp_user = os.getenv("EMAIL_HOST_USER")
    if not smtp_password:
        smtp_password = os.getenv("EMAIL_HOST_PASSWORD")

    if not smtp_user or not smtp_password:
        audit_log("send_email", _kw, "error", "SMTP credentials not configured")
        raise ValueError("SMTP credentials not configured. Set EMAIL_HOST_USER and EMAIL_HOST_PASSWORD in .env or users.json")

    logger.debug(f"[send_email] Sending email to {to}")
    _t0 = time.time()

    recipients = [to] if isinstance(to, str) else to

    msg = MIMEMultipart("alternative")
    msg["From"] = smtp_user
    msg["To"] = ", ".join(recipients)
    msg["Subject"] = subject

    mime_type = "html" if is_html else "plain"
    msg.attach(MIMEText(body, mime_type))

    try:
        with smtplib.SMTP("smtp.gmail.com", 587) as server:
            server.starttls()
            server.login(smtp_user, smtp_password)
            server.sendmail(smtp_user, recipients, msg.as_string())
    except Exception as e:
        audit_log("send_email", _kw, "error", f"to={recipients}: {e}", time.time() - _t0)
        raise

    logger.success(f"[send_email] Email sent successfully to {recipients}")
    audit_log("send_email", _kw, "success", f"to={recipients}", time.time() - _t0)
    return f"Email sent successfully to {recipients}"


def send_whatsapp(mobile: str, text: str, keyword: str | None = None) -> str:
    """Send WhatsApp message via WAHA API."""
    _kw = keyword or "system"
    if not WAHA_API_KEY:
        audit_log("send_whatsapp", _kw, "error", "WAHA_API_KEY not configured")
        raise ValueError("WAHA_API_KEY not configured. Set WAHA_API_KEY in .env")

    chat_id = f"{mobile}@c.us"
    url = f"{WAHA_API_URL}/api/sendText"
    headers = {
        "X-Api-Key": WAHA_API_KEY,
        "Content-Type": "application/json",
    }
    data = {
        "session": WAHA_SESSION,
        "chatId": chat_id,
        "text": text,
    }

    logger.debug(f"[send_whatsapp] Sending WhatsApp message to {chat_id}")
    _t0 = time.time()
    try:
        response = requests.post(url, json=data, headers=headers, timeout=30)
        response.raise_for_status()
    except Exception as e:
        audit_log("send_whatsapp", _kw, "error", f"to={chat_id}: {e}", time.time() - _t0)
        raise
    logger.success(f"[send_whatsapp] WhatsApp message sent to {chat_id}")
    audit_log("send_whatsapp", _kw, "success", f"to={chat_id}", time.time() - _t0)
    return f"WhatsApp message sent to {chat_id}"


def has_valid_token(keyword: str) -> bool:
    """Check if user has a valid OAuth token file."""
    try:
        token_path = get_token_path(keyword)
        return token_path.exists()
    except FileNotFoundError:
        return False


def process_user(user: dict[str, Any], global_schedule_time: str) -> dict[str, Any]:
    """Process a single user: fetch emails + calendar, summarize, and send email."""
    keyword = user.get("keyword", "default")
    user_name = user.get("name", "Unknown")
    user_email = user.get("email", "")
    smtp_user = user.get("smtp_host_user")
    smtp_password = user.get("smtp_host_password")

    max_results, days_threshold = get_user_settings(user)

    logger.success(f"Processing user: {user_name} ({keyword})")

    # Check if OAuth token exists, if not, skip user
    if not has_valid_token(keyword):
        logger.warning(f"[{keyword}] OAuth token not found. Please run OAuth setup first: uv run python -c \"from modules.fetch_emails import get_gmail_service; get_gmail_service('{keyword}')\"")
        return {
            "keyword": keyword,
            "name": user_name,
            "email": user_email,
            "emails_fetched": 0,
            "emails_summarized": 0,
            "error": "OAuth token not found. Run OAuth setup first.",
        }

    _t0 = time.time()
    result = fetch_emails_with_retry(keyword, max_results, days_threshold)
    emails_fetched = result.get("count", 0) if result.get("success") else 0

    # Fetch calendar events if enabled for this user
    calendar_events = []
    if user.get("fetch_calendar", False):
        cal_result = fetch_calendar_events_with_retry(keyword, days=days_threshold, max_results=20)
        if cal_result.get("success"):
            calendar_events = cal_result.get("events", [])
            logger.info(f"[{keyword}] Fetched {len(calendar_events)} calendar events")

    user_schedule = user.get("schedule_time", global_schedule_time)

    if result["success"] and result["emails"]:
        summary = summarize_emails(result["emails"], user_name=user_name, calendar_events=calendar_events)

        logger.info(f"[{keyword}] Email summary generated, sending to {user_email}")

        send_email(
            to=user_email,
            subject=f"Daily Email Summary - {user_name}",
            body=summary,
            is_html=True,
            smtp_user=smtp_user,
            smtp_password=smtp_password,
            keyword=keyword,
        )

        try:
            from admin.services import record_history
            record_history(keyword, "email", "sent", email_count=len(result["emails"]))
        except Exception:
            pass
    elif result["success"]:
        no_email_body = f"""<html><body style="font-family: Arial, sans-serif; padding: 20px;">
<h2>No New Emails</h2>
<p>Hello {user_name},</p>
<p>You have no new emails to summarize today.</p>
</body></html>"""
        send_email(
            to=user_email,
            subject=f"Daily Email Summary - {user_name}",
            body=no_email_body,
            is_html=True,
            smtp_user=smtp_user,
            smtp_password=smtp_password,
            keyword=keyword,
        )
        try:
            from admin.services import record_history
            record_history(keyword, "email", "sent", email_count=0, error="No emails found")
        except Exception:
            pass

    # Always mark as run to prevent re-processing on every scheduler tick
    now = now_ist()
    set_user_last_run_date(keyword, now.strftime("%Y-%m-%d"), user_schedule)

    audit_log("process_user", keyword, "success" if result.get("success") else "skipped",
              f"emails_fetched={emails_fetched}, calendar_events={len(calendar_events)}", time.time() - _t0)

    return {
        "keyword": keyword,
        "name": user_name,
        "email": user_email,
        "emails_fetched": emails_fetched,
        "emails_summarized": emails_fetched,
        "calendar_events": len(calendar_events),
    }


def _process_user_both_channels(
    user: dict[str, Any],
    needs_email: bool,
    needs_whatsapp: bool,
    today_str: str,
    global_schedule_time: str,
) -> dict[str, Any]:
    """Process a user for both email and WhatsApp channels. Fetches emails + calendar once."""
    keyword = user.get("keyword", "default")
    user_name = user.get("name", "Unknown")
    user_email = user.get("email", "")
    mobile = user.get("mobile", "")
    smtp_user = user.get("smtp_host_user")
    smtp_password = user.get("smtp_host_password")
    max_results, days_threshold = get_user_settings(user)

    if not has_valid_token(keyword):
        logger.warning(f"[{keyword}] OAuth token not found, skipping")
        return {"keyword": keyword, "name": user_name, "emails_fetched": 0, "error": "OAuth token missing"}

    _t0 = time.time()
    result = fetch_emails_with_retry(keyword, max_results, days_threshold)
    emails_fetched = result.get("count", 0) if result.get("success") else 0

    # Fetch calendar events if enabled for this user
    calendar_events = []
    if user.get("fetch_calendar", False):
        cal_result = fetch_calendar_events_with_retry(keyword, days=days_threshold, max_results=20)
        if cal_result.get("success"):
            calendar_events = cal_result.get("events", [])
            logger.info(f"[{keyword}] Fetched {len(calendar_events)} calendar events")

    user_schedule = user.get("schedule_time", global_schedule_time)

    no_email = result["success"] and not result["emails"]
    fetch_failed = not result["success"]

    if no_email or fetch_failed:
        if fetch_failed:
            logger.warning(f"[{keyword}] Email fetch failed, will notify user")
        if needs_email:
            try:
                if fetch_failed:
                    body_text = f"""<html><body style="font-family: Arial, sans-serif; padding: 20px;">
<h2>Email Fetch Failed</h2>
<p>Hello {user_name},</p>
<p>We encountered an issue while fetching your emails today. Please check your OAuth token or try again later.</p>
</body></html>"""
                    subject_text = f"Daily Email Summary - {user_name} (Fetch Failed)"
                else:
                    body_text = f"""<html><body style="font-family: Arial, sans-serif; padding: 20px;">
<h2>No New Emails</h2>
<p>Hello {user_name},</p>
<p>You have no new emails to summarize today.</p>
</body></html>"""
                    subject_text = f"Daily Email Summary - {user_name}"
                send_email(
                    to=user_email,
                    subject=subject_text,
                    body=body_text,
                    is_html=True,
                    smtp_user=smtp_user,
                    smtp_password=smtp_password,
                    keyword=keyword,
                )
                set_user_last_run_date(keyword, today_str, user_schedule)
                logger.info(f"[{keyword}] {'Fetch failed' if fetch_failed else 'No emails'}, sent email notification")
            except Exception as e:
                logger.error(f"[{keyword}] Notification email failed: {e}")

        if needs_whatsapp:
            try:
                if fetch_failed:
                    whatsapp_text = f"*Daily Email Summary - {user_name}*\n\nHello {user_name},\n\nWe encountered an issue while fetching your emails today. Please check your OAuth token or try again later."
                else:
                    whatsapp_text = f"*Daily Email Summary - {user_name}*\n\nHello {user_name},\n\nYou have no new emails to summarize today."
                send_whatsapp(mobile, whatsapp_text, keyword=keyword)
                redis_client.set(f"morning_mailer:whatsapp_last_run:{keyword}", today_str)
                redis_client.set(f"morning_mailer:whatsapp_last_schedule:{keyword}", user_schedule)
                logger.info(f"[{keyword}] {'Fetch failed' if fetch_failed else 'No emails'}, sent WhatsApp notification")
            except Exception as e:
                logger.error(f"[{keyword}] Notification WhatsApp failed: {e}")

        _status = "partial" if fetch_failed else "success"
        _details = f"emails_fetched=0, calendar_events={len(calendar_events)}, email={'yes' if needs_email else 'no'}, whatsapp={'yes' if needs_whatsapp else 'no'}"
        if fetch_failed:
            _details += ", fetch=failed, notification_sent"
        else:
            _details += ", notification_sent"
        audit_log("process_user_both", keyword, _status, _details, time.time() - _t0)
        return {"keyword": keyword, "name": user_name, "emails_fetched": 0, "calendar_events": len(calendar_events)}

    if needs_email:
        try:
            email_summary = get_agent().summarize_emails(result["emails"], user_name=user_name, calendar_events=calendar_events)
            send_email(
                to=user_email,
                subject=f"Daily Email Summary - {user_name}",
                body=email_summary,
                is_html=True,
                smtp_user=smtp_user,
                smtp_password=smtp_password,
                keyword=keyword,
            )
            set_user_last_run_date(keyword, today_str, user_schedule)
            logger.success(f"[{keyword}] Email summary sent to {user_email}")
        except Exception as e:
            logger.error(f"[{keyword}] Email send failed: {e}")

    if needs_whatsapp:
        try:
            whatsapp_summary = get_agent().summarize_emails(
                result["emails"], prompt=WHATSAPP_SYSTEM_PROMPT, user_name=user_name, calendar_events=calendar_events
            )
            send_whatsapp(mobile, whatsapp_summary, keyword=keyword)
            redis_client.set(f"morning_mailer:whatsapp_last_run:{keyword}", today_str)
            redis_client.set(f"morning_mailer:whatsapp_last_schedule:{keyword}", user_schedule)
            logger.success(f"[{keyword}] WhatsApp summary sent to {mobile}")
        except Exception as e:
            logger.error(f"[{keyword}] WhatsApp send failed: {e}")

    audit_log("process_user_both", keyword, "success",
              f"emails_fetched={emails_fetched}, calendar_events={len(calendar_events)}, email={'yes' if needs_email else 'no'}, whatsapp={'yes' if needs_whatsapp else 'no'}", time.time() - _t0)
    return {"keyword": keyword, "name": user_name, "emails_fetched": emails_fetched, "calendar_events": len(calendar_events)}


# =============================================================================
# Huey Tasks - Individual User Actions (enqueued by admin panel)
# =============================================================================

@huey.task(retries=2, retry_delay=10)
def huey_send_email_to_user(keyword: str) -> dict[str, Any]:
    """Fetch, summarize, and send email summary to a specific user."""
    _t0 = time.time()
    users = load_users()
    user = next((u for u in users if u.get("keyword") == keyword), None)
    if not user:
        audit_log("huey_send_email_to_user", keyword, "error", "User not found", time.time() - _t0)
        return {"keyword": keyword, "error": f"User '{keyword}' not found"}

    if not has_valid_token(keyword):
        audit_log("huey_send_email_to_user", keyword, "error", "OAuth token not found", time.time() - _t0)
        return {"keyword": keyword, "error": "OAuth token not found"}

    result = process_user(user, SCHEDULE_TIME)
    status = "error" if result.get("error") else "success"
    audit_log("huey_send_email_to_user", keyword, status,
              f"emails_fetched={result.get('emails_fetched', 0)}", time.time() - _t0)
    return result


@huey.task(retries=2, retry_delay=10)
def huey_send_whatsapp_to_user(keyword: str) -> dict[str, Any]:
    """Fetch, summarize, and send WhatsApp summary to a specific user."""
    _t0 = time.time()
    users = load_users()
    user = next((u for u in users if u.get("keyword") == keyword), None)
    if not user:
        audit_log("huey_send_whatsapp_to_user", keyword, "error", "User not found", time.time() - _t0)
        return {"keyword": keyword, "error": f"User '{keyword}' not found"}

    mobile = user.get("mobile", "")
    if not mobile:
        audit_log("huey_send_whatsapp_to_user", keyword, "error", "No mobile number", time.time() - _t0)
        return {"keyword": keyword, "error": "No mobile number configured"}

    if not has_valid_token(keyword):
        audit_log("huey_send_whatsapp_to_user", keyword, "error", "OAuth token not found", time.time() - _t0)
        return {"keyword": keyword, "error": "OAuth token not found"}

    max_results, days_threshold = get_user_settings(user)
    result = fetch_emails_with_retry(keyword, max_results, days_threshold)
    if not result.get("success"):
        audit_log("huey_send_whatsapp_to_user", keyword, "error", "Email fetch failed", time.time() - _t0)
        return {"keyword": keyword, "emails_fetched": 0, "error": "Email fetch failed"}
    if not result.get("emails"):
        audit_log("huey_send_whatsapp_to_user", keyword, "skipped", "No emails to summarize", time.time() - _t0)
        return {"keyword": keyword, "emails_fetched": 0, "message": "No emails to summarize"}

    calendar_events = []
    if user.get("fetch_calendar", False):
        cal_result = fetch_calendar_events_with_retry(keyword, days=days_threshold, max_results=20)
        if cal_result.get("success"):
            calendar_events = cal_result.get("events", [])

    summary = get_agent().summarize_emails(result["emails"], prompt=WHATSAPP_SYSTEM_PROMPT, user_name=user.get("name", "Unknown"), calendar_events=calendar_events)
    send_whatsapp(mobile, summary, keyword=keyword)

    today_str = now_ist().strftime("%Y-%m-%d")
    redis_client.set(f"morning_mailer:whatsapp_last_run:{keyword}", today_str)
    redis_client.set(f"morning_mailer:whatsapp_last_schedule:{keyword}", user.get("schedule_time", SCHEDULE_TIME))

    try:
        from admin.services import record_history
        record_history(keyword, "whatsapp", "sent")
    except Exception:
        pass

    audit_log("huey_send_whatsapp_to_user", keyword, "success",
              f"emails_fetched={result.get('count', 0)}, calendar_events={len(calendar_events)}", time.time() - _t0)
    return {"keyword": keyword, "emails_fetched": result.get("count", 0), "calendar_events": len(calendar_events), "status": "sent"}


@huey.task(retries=1, retry_delay=5)
def huey_force_email_all() -> dict[str, Any]:
    """Force email summary for ALL users (ignores schedule)."""
    _t0 = time.time()
    users = load_users()
    results = []
    today_str = now_ist().strftime("%Y-%m-%d")

    for user in users:
        if not user.get("use_email", True):
            continue
        result = process_user(user, SCHEDULE_TIME)
        results.append(result)
        kw = user.get("keyword", "default")
        redis_client.set(f"morning_mailer:whatsapp_last_run:{kw}", today_str)

    total_emails = sum(r.get("emails_fetched", 0) for r in results if "error" not in r)
    audit_log("huey_force_email_all", "all", "success",
              f"processed={len(results)}, emails_fetched={total_emails}", time.time() - _t0)
    return {"processed": len(results), "total_emails_fetched": total_emails, "results": results}


@huey.task(retries=1, retry_delay=5)
def huey_force_whatsapp_all() -> dict[str, Any]:
    """Force WhatsApp summary for ALL users (ignores schedule)."""
    _t0 = time.time()
    users = load_users()
    wa_users = [u for u in users if u.get("mobile") and u.get("use_whatsapp", True)]

    results = []
    today_str = now_ist().strftime("%Y-%m-%d")
    for user in wa_users:
        _f_t0 = time.time()
        keyword = user.get("keyword", "default")
        mobile = user.get("mobile", "")
        user_name = user.get("name", "Unknown")

        if not has_valid_token(keyword):
            audit_log("huey_force_whatsapp_all", keyword, "skipped", "No OAuth token", time.time() - _f_t0)
            results.append({"keyword": keyword, "error": "No OAuth token"})
            continue

        max_results, days_threshold = get_user_settings(user)
        result = fetch_emails_with_retry(keyword, max_results, days_threshold)
        if not result.get("success"):
            audit_log("huey_force_whatsapp_all", keyword, "error", "Email fetch failed", time.time() - _f_t0)
            results.append({"keyword": keyword, "emails_fetched": 0, "error": "Email fetch failed"})
            continue
        if not result.get("emails"):
            audit_log("huey_force_whatsapp_all", keyword, "skipped", "No emails to summarize", time.time() - _f_t0)
            results.append({"keyword": keyword, "emails_fetched": 0, "message": "No emails to summarize"})
            continue

        calendar_events = []
        if user.get("fetch_calendar", False):
            cal_result = fetch_calendar_events_with_retry(keyword, days=days_threshold, max_results=20)
            if cal_result.get("success"):
                calendar_events = cal_result.get("events", [])

        summary = get_agent().summarize_emails(result["emails"], prompt=WHATSAPP_SYSTEM_PROMPT, user_name=user_name, calendar_events=calendar_events)
        try:
            send_whatsapp(mobile, summary, keyword=keyword)
            redis_client.set(f"morning_mailer:whatsapp_last_run:{keyword}", today_str)
            redis_client.set(f"morning_mailer:whatsapp_last_schedule:{keyword}", user.get("schedule_time", SCHEDULE_TIME))
            redis_client.set(f"morning_mailer:last_run:{keyword}", today_str)
            audit_log("huey_force_whatsapp_all", keyword, "success",
                      f"emails_fetched={result.get('count', 0)}, calendar_events={len(calendar_events)}", time.time() - _f_t0)
            results.append({"keyword": keyword, "emails_fetched": result.get("count", 0), "status": "sent"})
        except Exception as e:
            audit_log("huey_force_whatsapp_all", keyword, "error", f"Send failed: {e}", time.time() - _f_t0)
            results.append({"keyword": keyword, "error": str(e)})

    total_emails = sum(r.get("emails_fetched", 0) for r in results if "error" not in r)
    audit_log("huey_force_whatsapp_all", "all", "success",
              f"processed={len(results)}, emails_fetched={total_emails}", time.time() - _t0)
    return {"processed": len(results), "total_emails_fetched": total_emails, "results": results}


@huey.task(retries=2, retry_delay=10)
def huey_fetch_calendar_and_send_email(keyword: str, days: int = 2) -> dict[str, Any]:
    """Fetch calendar events and send via email to a specific user."""
    _t0 = time.time()
    users = load_users()
    user = next((u for u in users if u.get("keyword") == keyword), None)
    if not user:
        audit_log("huey_fetch_calendar_and_send_email", keyword, "error", "User not found", time.time() - _t0)
        return {"keyword": keyword, "error": f"User '{keyword}' not found"}

    result = fetch_calendar_events_with_retry(keyword, days=days, max_results=20)
    if not result.get("success") or not result.get("events"):
        audit_log("huey_fetch_calendar_and_send_email", keyword, "skipped", "No events found", time.time() - _t0)
        return {"keyword": keyword, "events": 0, "message": "No events found"}

    from modules.prompt import CALENDAR_EMAIL_PROMPT
    summary = get_agent().summarize_emails(result["events"], prompt=CALENDAR_EMAIL_PROMPT, user_name=user.get("name", "Unknown"))
    send_email(
        to=user.get("email", ""),
        subject=f"Calendar Summary - {user.get('name', 'Unknown')}",
        body=summary, is_html=True,
        smtp_user=user.get("smtp_host_user"), smtp_password=user.get("smtp_host_password"),
        keyword=keyword,
    )

    try:
        from admin.services import record_history
        record_history(keyword, "email", "sent", email_count=0)
    except Exception:
        pass

    audit_log("huey_fetch_calendar_and_send_email", keyword, "success",
              f"events={len(result['events'])}", time.time() - _t0)
    return {"keyword": keyword, "events": len(result["events"]), "status": "sent"}


@huey.task(retries=2, retry_delay=10)
def huey_fetch_calendar_and_send_whatsapp(keyword: str, days: int = 2) -> dict[str, Any]:
    """Fetch calendar events and send via WhatsApp to a specific user."""
    _t0 = time.time()
    users = load_users()
    user = next((u for u in users if u.get("keyword") == keyword), None)
    if not user:
        audit_log("huey_fetch_calendar_and_send_whatsapp", keyword, "error", "User not found", time.time() - _t0)
        return {"keyword": keyword, "error": f"User '{keyword}' not found"}

    mobile = user.get("mobile", "")
    if not mobile:
        audit_log("huey_fetch_calendar_and_send_whatsapp", keyword, "error", "No mobile number", time.time() - _t0)
        return {"keyword": keyword, "error": "No mobile number configured"}

    result = fetch_calendar_events_with_retry(keyword, days=days, max_results=20)
    if not result.get("success") or not result.get("events"):
        audit_log("huey_fetch_calendar_and_send_whatsapp", keyword, "skipped", "No events found", time.time() - _t0)
        return {"keyword": keyword, "events": 0, "message": "No events found"}

    from modules.prompt import CALENDAR_WHATSAPP_PROMPT
    summary = get_agent().summarize_emails(result["events"], prompt=CALENDAR_WHATSAPP_PROMPT, user_name=user.get("name", "Unknown"))
    send_whatsapp(mobile, summary, keyword=keyword)

    try:
        from admin.services import record_history
        record_history(keyword, "whatsapp", "sent")
    except Exception:
        pass

    audit_log("huey_fetch_calendar_and_send_whatsapp", keyword, "success",
              f"events={len(result['events'])}", time.time() - _t0)
    return {"keyword": keyword, "events": len(result["events"]), "status": "sent"}


@huey.task(retries=2, retry_delay=10)
def huey_fetch_calendar_and_send_both(keyword: str, days: int = 2) -> dict[str, Any]:
    """Fetch calendar events and send via both email and WhatsApp."""
    _t0 = time.time()
    users = load_users()
    user = next((u for u in users if u.get("keyword") == keyword), None)
    if not user:
        audit_log("huey_fetch_calendar_and_send_both", keyword, "error", "User not found", time.time() - _t0)
        return {"keyword": keyword, "error": f"User '{keyword}' not found"}

    result = fetch_calendar_events_with_retry(keyword, days=days, max_results=20)
    if not result.get("success") or not result.get("events"):
        audit_log("huey_fetch_calendar_and_send_both", keyword, "skipped", "No events found", time.time() - _t0)
        return {"keyword": keyword, "events": 0, "message": "No events found"}

    events = result["events"]
    email_status = None
    wa_status = None

    from modules.prompt import CALENDAR_EMAIL_PROMPT, CALENDAR_WHATSAPP_PROMPT

    try:
        email_summary = get_agent().summarize_emails(events, prompt=CALENDAR_EMAIL_PROMPT, user_name=user.get("name", "Unknown"))
        send_email(
            to=user.get("email", ""),
            subject=f"Calendar Summary - {user.get('name', 'Unknown')}",
            body=email_summary, is_html=True,
            smtp_user=user.get("smtp_host_user"), smtp_password=user.get("smtp_host_password"),
            keyword=keyword,
        )
        email_status = "sent"
        try:
            from admin.services import record_history
            record_history(keyword, "email", "sent", email_count=0)
        except Exception:
            pass
    except Exception as e:
        email_status = f"error: {e}"

    mobile = user.get("mobile", "")
    if mobile:
        try:
            wa_summary = get_agent().summarize_emails(events, prompt=CALENDAR_WHATSAPP_PROMPT, user_name=user.get("name", "Unknown"))
            send_whatsapp(mobile, wa_summary, keyword=keyword)
            wa_status = "sent"
            try:
                from admin.services import record_history
                record_history(keyword, "whatsapp", "sent")
            except Exception:
                pass
        except Exception as e:
            wa_status = f"error: {e}"

    _both_ok = email_status == "sent" and (wa_status == "sent" or not mobile)
    _both_failed = (email_status and email_status != "sent") and (not mobile or (wa_status and wa_status != "sent"))
    _final_status = "success" if _both_ok else ("error" if _both_failed else "partial")
    audit_log("huey_fetch_calendar_and_send_both", keyword, _final_status,
              f"events={len(events)}, email={email_status}, whatsapp={wa_status}", time.time() - _t0)
    return {"keyword": keyword, "events": len(events), "email_status": email_status, "whatsapp_status": wa_status}


@huey.task(retries=1, retry_delay=5)
def huey_test_send_email(subject: str, body: str) -> str:
    """Send test email via SMTP."""
    _t0 = time.time()
    email = os.getenv("MY_EMAIL", "")
    if not email:
        audit_log("huey_test_send_email", "system", "error", "MY_EMAIL not set", time.time() - _t0)
        raise ValueError("MY_EMAIL not set in .env")
    result = send_email(email, subject, body)
    audit_log("huey_test_send_email", "system", "success", f"to={email}", time.time() - _t0)
    return result


@huey.task(retries=1, retry_delay=5)
def huey_test_send_whatsapp(mobile: str, message: str) -> str:
    """Send test WhatsApp message."""
    _t0 = time.time()
    result = send_whatsapp(mobile, message)
    audit_log("huey_test_send_whatsapp", mobile, "success", "", time.time() - _t0)
    return result


# =============================================================================
# Huey Tasks - Scheduled (periodic)
# =============================================================================

@huey.task(retries=3, retry_delay=5)
def send_email_task(to: str | list[str], subject: str, body: str, is_html: bool = False) -> str:
    """Send email via SMTP (Huey task)."""
    _t0 = time.time()
    result = send_email(to, subject, body, is_html)
    audit_log("send_email_task", "system", "success", f"to={to}", time.time() - _t0)
    return result


def daily_email_summary() -> dict[str, Any]:
    """
    Check and process users whose schedule_time has passed for email delivery.
    
    For each user:
    - Check if current time >= user's schedule_time (or global SCHEDULE_TIME)
    - Check if user hasn't been processed today
    - If yes, process that user in parallel
    """
    now = now_ist()
    current_time_str = now.strftime("%H:%M")
    today_str = now.strftime("%Y-%m-%d")

    logger.debug(f"Checking schedule at {current_time_str}...")

    users = load_users()

    eligible_users = []
    for user in users:
        if not user.get("active", True):
            logger.debug(f"User {user.get('name', 'unknown')} skipped: inactive")
            continue
        if not user.get("use_email", True):
            logger.debug(f"User {user.get('name', 'unknown')} skipped: use_email=false")
            continue
        keyword = user.get("keyword", "default")
        user_schedule = user.get("schedule_time", SCHEDULE_TIME)
        should_run = should_run_today(user, SCHEDULE_TIME)
        logger.debug(f"User check: {user.get('name')} ({keyword}): schedule={user_schedule}, should_run={should_run}")
        if should_run:
            eligible_users.append(user)

    if not eligible_users:
        logger.debug(f"No users eligible to run at {current_time_str}")
        return {
            "date": today_str,
            "time": now.strftime("%H:%M:%S"),
            "eligible_users": 0,
            "processed": 0,
        }

    logger.success(f"Found {len(eligible_users)} user(s) eligible to run at {current_time_str}")

    results = []
    logger.debug(f"Processing {len(eligible_users)} user(s) in parallel...")
    with ThreadPoolExecutor(max_workers=min(MAX_THREAD_WORKERS, len(eligible_users))) as executor:
        futures = {executor.submit(process_user, user, SCHEDULE_TIME): user for user in eligible_users}
        for future in as_completed(futures):
            try:
                user_result = future.result()
                results.append(user_result)
            except Exception as e:
                logger.error(f"Error processing user: {e}")
                results.append({"error": str(e)})

    total_emails = sum(r.get("emails_fetched", 0) for r in results if "error" not in r)

    logger.success(f"Scheduled task completed: {len(eligible_users)} user(s) processed, {total_emails} emails")

    return {
        "date": today_str,
        "time": now.strftime("%H:%M:%S"),
        "eligible_users": len(eligible_users),
        "processed": len(results),
        "total_emails_fetched": total_emails,
        "results": results,
    }


@huey.task(retries=3, retry_delay=5)
def send_whatsapp_task(mobile: str, text: str) -> str:
    """Send WhatsApp message via WAHA API (Huey task)."""
    _t0 = time.time()
    result = send_whatsapp(mobile, text)
    audit_log("send_whatsapp_task", mobile, "success", "", time.time() - _t0)
    return result


def daily_whatsapp_summary() -> dict[str, Any]:
    """
    Check and process users for WhatsApp summaries.

    Runs every SCHEDULE_CHECK_INTERVAL minutes. For each user with a mobile:
    - Check if current time >= user's schedule_time (or global SCHEDULE_TIME)
    - Check if user hasn't been processed today
    - Fetch emails, summarize with WhatsApp prompt, send via WAHA
    """
    now = now_ist()
    current_time_str = now.strftime("%H:%M")
    today_str = now.strftime("%Y-%m-%d")

    if not WAHA_API_KEY:
        logger.warning("WAHA_API_KEY not set, skipping WhatsApp summary")
        return {"date": today_str, "time": now.strftime("%H:%M:%S"), "error": "WAHA_API_KEY not configured"}

    logger.debug(f"Checking WhatsApp schedule at {current_time_str}...")

    users = load_users()

    eligible_users = []
    for user in users:
        if not user.get("active", True):
            continue
        mobile = user.get("mobile", "")
        if not mobile:
            logger.debug(f"User {user.get('name', 'unknown')} skipped: no mobile number")
            continue
        if not user.get("use_whatsapp", True):
            logger.debug(f"User {user.get('name', 'unknown')} skipped: use_whatsapp=false")
            continue
        keyword = user.get("keyword", "default")
        user_schedule = user.get("schedule_time", SCHEDULE_TIME)
        should_run = should_run_today(user, SCHEDULE_TIME, redis_prefix="whatsapp_")
        logger.debug(f"WhatsApp user check: {user.get('name')} ({keyword}): schedule={user_schedule}, should_run={should_run}")
        if should_run:
            eligible_users.append(user)

    if not eligible_users:
        logger.debug(f"No WhatsApp users eligible to run at {current_time_str}")
        return {
            "date": today_str,
            "time": now.strftime("%H:%M:%S"),
            "eligible_users": 0,
            "processed": 0,
        }

    logger.success(f"Found {len(eligible_users)} WhatsApp user(s) eligible at {current_time_str}")

    def process_whatsapp_user(user: dict[str, Any]) -> dict[str, Any]:
        keyword = user.get("keyword", "default")
        user_name = user.get("name", "Unknown")
        mobile = user.get("mobile", "")
        max_results, days_threshold = get_user_settings(user)

        if not has_valid_token(keyword):
            logger.warning(f"[{keyword}] WhatsApp: OAuth token not found, skipping")
            return {"keyword": keyword, "name": user_name, "mobile": mobile, "error": "OAuth token missing"}

        result = fetch_emails_with_retry(keyword, max_results, days_threshold)
        emails_fetched = result.get("count", 0) if result.get("success") else 0

        # Fetch calendar events if enabled for this user
        calendar_events = []
        if user.get("fetch_calendar", False):
            cal_result = fetch_calendar_events_with_retry(keyword, days=days_threshold, max_results=20)
            if cal_result.get("success"):
                calendar_events = cal_result.get("events", [])

        if not result["success"] or not result["emails"]:
            return {"keyword": keyword, "name": user_name, "mobile": mobile, "emails_fetched": emails_fetched, "calendar_events": len(calendar_events)}

        summary = get_agent().summarize_emails(result["emails"], prompt=WHATSAPP_SYSTEM_PROMPT, user_name=user_name, calendar_events=calendar_events)

        try:
            send_whatsapp(mobile, summary, keyword=keyword)
            user_schedule = user.get("schedule_time", SCHEDULE_TIME)
            redis_client.set(f"morning_mailer:whatsapp_last_run:{keyword}", today_str)
            redis_client.set(f"morning_mailer:whatsapp_last_schedule:{keyword}", user_schedule)
            logger.success(f"[{keyword}] WhatsApp summary sent to {mobile}")
            return {"keyword": keyword, "name": user_name, "mobile": mobile, "emails_fetched": emails_fetched, "calendar_events": len(calendar_events)}
        except Exception as e:
            logger.error(f"[{keyword}] WhatsApp send failed: {e}")
            return {"keyword": keyword, "name": user_name, "mobile": mobile, "error": str(e)}

    results = []
    with ThreadPoolExecutor(max_workers=min(MAX_THREAD_WORKERS, len(eligible_users))) as executor:
        futures = {executor.submit(process_whatsapp_user, user): user for user in eligible_users}
        for future in as_completed(futures):
            try:
                user_result = future.result()
                results.append(user_result)
            except Exception as e:
                logger.error(f"Error processing WhatsApp user: {e}")
                results.append({"error": str(e)})

    total_emails = sum(r.get("emails_fetched", 0) for r in results if "error" not in r)
    logger.success(f"WhatsApp scheduled task completed: {len(results)} user(s) processed, {total_emails} emails")

    return {
        "date": today_str,
        "time": now.strftime("%H:%M:%S"),
        "eligible_users": len(eligible_users),
        "processed": len(results),
        "total_emails_fetched": total_emails,
        "results": results,
    }


@huey.periodic_task(crontab(minute=f"*/{SCHEDULE_CHECK_INTERVAL}"))
def daily_summary() -> dict[str, Any]:
    """Unified daily task: fetch emails once per user, deliver via email and/or WhatsApp."""
    global _startup_summary_printed
    if not _startup_summary_printed:
        _startup_summary_printed = True
        print_startup_summary()

    _t0 = time.time()
    now = now_ist()
    current_time_str = now.strftime("%H:%M")
    today_str = now.strftime("%Y-%m-%d")

    logger.info(f"Checking schedule at {current_time_str}...")

    users = load_users()

    email_eligible: dict[str, dict[str, Any]] = {}
    whatsapp_eligible: dict[str, dict[str, Any]] = {}

    for user in users:
        if not user.get("active", True):
            continue
        keyword = user.get("keyword", "default")

        if user.get("use_email", True):
            if should_run_today(user, SCHEDULE_TIME):
                email_eligible[keyword] = user

        if user.get("use_whatsapp", True) and user.get("mobile"):
            if WAHA_API_KEY and should_run_today(user, SCHEDULE_TIME, redis_prefix="whatsapp_"):
                whatsapp_eligible[keyword] = user

    all_keywords = set(email_eligible.keys()) | set(whatsapp_eligible.keys())

    if not all_keywords:
        logger.info(f"No users eligible to run at {current_time_str}")
        audit_log("daily_summary", "system", "skipped", "No eligible users", time.time() - _t0)
        return {
            "date": today_str,
            "time": now.strftime("%H:%M:%S"),
            "eligible_users": 0,
            "processed": 0,
        }

    active_users_dict = {u.get("keyword", "default"): u for u in users}
    eligible_list = []
    for kw in all_keywords:
        if kw in active_users_dict:
            eligible_list.append((
                active_users_dict[kw],
                kw in email_eligible,
                kw in whatsapp_eligible,
            ))

    logger.success(f"Found {len(eligible_list)} user(s) eligible at {current_time_str}")

    results = []
    with ThreadPoolExecutor(max_workers=min(MAX_THREAD_WORKERS, len(eligible_list))) as executor:
        futures = {
            executor.submit(_process_user_both_channels, user, needs_email, needs_whatsapp, today_str, SCHEDULE_TIME): user
            for user, needs_email, needs_whatsapp in eligible_list
        }
        for future in as_completed(futures):
            try:
                results.append(future.result())
            except Exception as e:
                logger.error(f"Error processing user: {e}")
                results.append({"error": str(e)})
                try:
                    _user = futures[future]
                    _kw = _user.get("keyword", "unknown")
                except Exception:
                    _kw = "unknown"
                audit_log("daily_summary", _kw, "error", f"exception={e}", time.time() - _t0)

    total_emails = sum(r.get("emails_fetched", 0) for r in results if "error" not in r)
    logger.success(f"Daily summary completed: {len(results)} user(s) processed, {total_emails} emails")

    audit_log("daily_summary", "system", "success",
              f"eligible={len(eligible_list)}, processed={len(results)}, emails_fetched={total_emails}", time.time() - _t0)

    return {
        "date": today_str,
        "time": now.strftime("%H:%M:%S"),
        "eligible_users": len(eligible_list),
        "processed": len(results),
        "total_emails_fetched": total_emails,
        "results": results,
    }


logger.success(f"Scheduler: checking every {SCHEDULE_CHECK_INTERVAL} min, default time {SCHEDULE_TIME}, max_results {MAX_EMAIL_RESULTS}, days {DAYS_THRESHOLD}")


def print_startup_summary():
    """Print startup summary with users table and scheduler info."""
    console.print()
    console.print(Panel.fit(
        "[bold cyan]Morning Mailer[/bold cyan] - Multi-User Email Summarization",
        border_style="cyan"
    ))

    # Scheduler Info
    scheduler_table = Table(title="[bold]Scheduler Configuration[/bold]", show_header=True, header_style="bold magenta")
    scheduler_table.add_column("Setting", style="cyan")
    scheduler_table.add_column("Value", style="green")
    scheduler_table.add_column("Description", style="dim")
    scheduler_table.add_row("Check Interval", f"{SCHEDULE_CHECK_INTERVAL} minutes", "How often the scheduler checks for eligible users")
    scheduler_table.add_row("Default Time", SCHEDULE_TIME, "Default run time for users without schedule_time")
    scheduler_table.add_row("Max Emails/User", str(MAX_EMAIL_RESULTS), "Max emails fetched per user (default)")
    scheduler_table.add_row("Days Threshold", str(DAYS_THRESHOLD), "Days to look back for emails (default)")
    scheduler_table.add_row("Max Workers", str(MAX_THREAD_WORKERS), "Max parallel users processed at once")
    scheduler_table.add_row("Retry Count", str(RETRY_COUNT), "Retry attempts on failure")
    scheduler_table.add_row("Retry Delay", f"{RETRY_DELAY}s", "Seconds between retries")
    scheduler_table.add_row("Env Mode", os.getenv("ENV_MODE", "dev").upper(), "dev=run multiple times, prod=once/day")
    scheduler_table.add_row("WAHA URL", WAHA_API_URL, "WhatsApp HTTP API endpoint")
    scheduler_table.add_row("WAHA Session", WAHA_SESSION, "WAHA session name")
    scheduler_table.add_row("WAHA Key", "*****" if WAHA_API_KEY else "(not set)", "WAHA API key (masked)")
    console.print(scheduler_table)

    # Users Table
    users = load_users()

    users_table = Table(title=f"[bold]Users ({len(users)} active)[/bold]", show_header=True, header_style="bold magenta", box=box.SIMPLE)
    users_table.add_column("Name", style="cyan", overflow="fold", min_width=10)
    users_table.add_column("Email", style="yellow", overflow="fold", min_width=14)
    users_table.add_column("Keyword", style="green", no_wrap=True, min_width=10)
    users_table.add_column("Sch", style="magenta", width=6)
    users_table.add_column("Max", style="blue", justify="center", width=4)
    users_table.add_column("Days", style="blue", justify="center", width=4)
    users_table.add_column("Mobile", style="yellow", no_wrap=True, min_width=12)
    users_table.add_column("Ch", style="green", justify="center", width=3)
    users_table.add_column("Cal", style="cyan", justify="center", width=3)
    users_table.add_column("Rdy", style="red", justify="center", width=3)

    for idx, user in enumerate(users, 1):
        keyword = user.get("keyword", "default")
        schedule = user.get("schedule_time", SCHEDULE_TIME)
        max_emails = user.get("max_email_results", MAX_EMAIL_RESULTS)
        days = user.get("days_threshold", DAYS_THRESHOLD)
        is_active = user.get("active", True)
        has_token = has_valid_token(keyword)
        ready = "✓" if (is_active and has_token) else "✗"
        use_email = user.get("use_email", True)
        use_whatsapp = user.get("use_whatsapp", True)
        channels = ("E" if use_email else "-") + ("W" if use_whatsapp else "-")
        fetch_cal = user.get("fetch_calendar", False)
        calendar = "✓" if fetch_cal else "-"
        mobile = user.get("mobile", "-")

        users_table.add_row(
            user.get("name", "Unknown"),
            user.get("email", "N/A"),
            keyword,
            schedule,
            str(max_emails),
            str(days),
            mobile,
            channels,
            calendar,
            ready
        )

    console.print(users_table)
    console.print()


# Print startup summary only once (guard against re-imports from admin panel)
_startup_summary_printed = False