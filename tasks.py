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

from modules import get_logger, format_timestamp
from modules.fetch_emails import fetch_emails, load_users as load_email_users, get_token_path
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

# Global LLM agent instance
AGENT = AgentModule()
AGENT.init()

# Redis client for tracking last run
redis_client = redis.from_url(os.getenv("REDIS_URL"), decode_responses=True)


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

    now = datetime.now()
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
    """Load users from users.json, fallback to .env for single user. Only active users are returned."""
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
        # Default active to True if not specified
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

    for attempt in range(RETRY_COUNT):
        try:
            logger.info(f"[{keyword}] Attempt {attempt + 1}/{RETRY_COUNT}")

            now = datetime.now()
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
                logger.success(f"[{keyword}] Fetched {result['count']} emails")
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
    return {"success": False, "error": last_error, "count": 0, "emails": []}


def summarize_emails(emails: list[dict[str, Any]], user_name: str = None) -> str:
    """Summarize emails using LLM."""
    logger.info(f"Summarizing {len(emails)} emails...")
    summary = AGENT.summarize_emails(emails, user_name=user_name)
    logger.success("Email summary generated")
    return summary


def send_email(
    to: str | list[str],
    subject: str,
    body: str,
    is_html: bool = False,
    smtp_user: str | None = None,
    smtp_password: str | None = None,
) -> str:
    """Send email via SMTP."""
    if not smtp_user:
        smtp_user = os.getenv("EMAIL_HOST_USER")
    if not smtp_password:
        smtp_password = os.getenv("EMAIL_HOST_PASSWORD")

    if not smtp_user or not smtp_password:
        raise ValueError("SMTP credentials not configured. Set EMAIL_HOST_USER and EMAIL_HOST_PASSWORD in .env or users.json")

    logger.debug(f"[send_email] Sending email to {to}")

    recipients = [to] if isinstance(to, str) else to

    msg = MIMEMultipart("alternative")
    msg["From"] = smtp_user
    msg["To"] = ", ".join(recipients)
    msg["Subject"] = subject

    mime_type = "html" if is_html else "plain"
    msg.attach(MIMEText(body, mime_type))

    with smtplib.SMTP("smtp.gmail.com", 587) as server:
        server.starttls()
        server.login(smtp_user, smtp_password)
        server.sendmail(smtp_user, recipients, msg.as_string())

    logger.success(f"[send_email] Email sent successfully to {recipients}")
    return f"Email sent successfully to {recipients}"


def send_whatsapp(mobile: str, text: str) -> str:
    """Send WhatsApp message via WAHA API."""
    if not WAHA_API_KEY:
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
    response = requests.post(url, json=data, headers=headers, timeout=30)
    response.raise_for_status()
    logger.success(f"[send_whatsapp] WhatsApp message sent to {chat_id}")
    return f"WhatsApp message sent to {chat_id}"


def has_valid_token(keyword: str) -> bool:
    """Check if user has a valid OAuth token file."""
    try:
        token_path = get_token_path(keyword)
        return token_path.exists()
    except FileNotFoundError:
        return False


def process_user(user: dict[str, Any], global_schedule_time: str) -> dict[str, Any]:
    """Process a single user: fetch, summarize, and send email."""
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

    result = fetch_emails_with_retry(keyword, max_results, days_threshold)
    emails_fetched = result.get("count", 0) if result.get("success") else 0

    if result["success"] and result["emails"]:
        summary = summarize_emails(result["emails"], user_name=user_name)

        logger.info(f"[{keyword}] Email summary generated, sending to {user_email}")

        send_email(
            to=user_email,
            subject=f"Daily Email Summary - {user_name}",
            body=summary,
            is_html=True,
            smtp_user=smtp_user,
            smtp_password=smtp_password,
        )

        now = datetime.now()
        user_schedule = user.get("schedule_time", global_schedule_time)
        set_user_last_run_date(keyword, now.strftime("%Y-%m-%d"), user_schedule)

    return {
        "keyword": keyword,
        "name": user_name,
        "email": user_email,
        "emails_fetched": emails_fetched,
        "emails_summarized": emails_fetched,
    }


def _process_user_both_channels(
    user: dict[str, Any],
    needs_email: bool,
    needs_whatsapp: bool,
    today_str: str,
    global_schedule_time: str,
) -> dict[str, Any]:
    """Process a user for both email and WhatsApp channels. Fetches emails once."""
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

    result = fetch_emails_with_retry(keyword, max_results, days_threshold)
    emails_fetched = result.get("count", 0) if result.get("success") else 0

    if not result["success"] or not result["emails"]:
        return {"keyword": keyword, "name": user_name, "emails_fetched": 0}

    user_schedule = user.get("schedule_time", global_schedule_time)

    if needs_email:
        try:
            email_summary = AGENT.summarize_emails(result["emails"], user_name=user_name)
            send_email(
                to=user_email,
                subject=f"Daily Email Summary - {user_name}",
                body=email_summary,
                is_html=True,
                smtp_user=smtp_user,
                smtp_password=smtp_password,
            )
            set_user_last_run_date(keyword, today_str, user_schedule)
            logger.success(f"[{keyword}] Email summary sent to {user_email}")
        except Exception as e:
            logger.error(f"[{keyword}] Email send failed: {e}")

    if needs_whatsapp:
        try:
            whatsapp_summary = AGENT.summarize_emails(
                result["emails"], prompt=WHATSAPP_SYSTEM_PROMPT, user_name=user_name
            )
            send_whatsapp(mobile, whatsapp_summary)
            redis_client.set(f"morning_mailer:whatsapp_last_run:{keyword}", today_str)
            redis_client.set(f"morning_mailer:whatsapp_last_schedule:{keyword}", user_schedule)
            logger.success(f"[{keyword}] WhatsApp summary sent to {mobile}")
        except Exception as e:
            logger.error(f"[{keyword}] WhatsApp send failed: {e}")

    return {"keyword": keyword, "name": user_name, "emails_fetched": emails_fetched}


# =============================================================================
# Huey Tasks
# =============================================================================

@huey.task(retries=3, retry_delay=5)
def send_email_task(to: str | list[str], subject: str, body: str, is_html: bool = False) -> str:
    """Send email via SMTP (Huey task)."""
    return send_email(to, subject, body, is_html)


def daily_email_summary() -> dict[str, Any]:
    """
    Check and process users whose schedule_time has passed for email delivery.
    
    For each user:
    - Check if current time >= user's schedule_time (or global SCHEDULE_TIME)
    - Check if user hasn't been processed today
    - If yes, process that user in parallel
    """
    now = datetime.now()
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
    return send_whatsapp(mobile, text)


def daily_whatsapp_summary() -> dict[str, Any]:
    """
    Check and process users for WhatsApp summaries.

    Runs every SCHEDULE_CHECK_INTERVAL minutes. For each user with a mobile:
    - Check if current time >= user's schedule_time (or global SCHEDULE_TIME)
    - Check if user hasn't been processed today
    - Fetch emails, summarize with WhatsApp prompt, send via WAHA
    """
    now = datetime.now()
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

        if not result["success"] or not result["emails"]:
            return {"keyword": keyword, "name": user_name, "mobile": mobile, "emails_fetched": emails_fetched}

        summary = AGENT.summarize_emails(result["emails"], prompt=WHATSAPP_SYSTEM_PROMPT, user_name=user_name)

        try:
            send_whatsapp(mobile, summary)
            user_schedule = user.get("schedule_time", SCHEDULE_TIME)
            redis_client.set(f"morning_mailer:whatsapp_last_run:{keyword}", today_str)
            redis_client.set(f"morning_mailer:whatsapp_last_schedule:{keyword}", user_schedule)
            logger.success(f"[{keyword}] WhatsApp summary sent to {mobile}")
            return {"keyword": keyword, "name": user_name, "mobile": mobile, "emails_fetched": emails_fetched}
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
    now = datetime.now()
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

    total_emails = sum(r.get("emails_fetched", 0) for r in results if "error" not in r)
    logger.success(f"Daily summary completed: {len(results)} user(s) processed, {total_emails} emails")

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
            ready
        )

    console.print(users_table)
    console.print()


# Print startup summary
print_startup_summary()