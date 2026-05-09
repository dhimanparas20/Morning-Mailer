"""
Morning Mailer - Scheduled email fetching and AI summarization.

This module contains Huey periodic tasks for:
- Fetching emails from Gmail
- Summarizing emails using LLM
- Sending summary via email
"""

import os
import smtplib
import time
from datetime import datetime, timedelta
from typing import Any

from dotenv import load_dotenv
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from huey import RedisHuey, crontab
from rich import print

from modules import get_logger, fetch_emails, format_timestamp
from modules.agent_mod import MCPAgentModule

load_dotenv()
logger = get_logger(__name__, show_time=True)

# Huey instance for task queue
huey = RedisHuey("Morning Mailer", url=os.getenv("REDIS_URL"), utc=False)

# Configuration from environment
RETRY_COUNT = int(os.getenv("RETRY_COUNT", 3))
RETRY_DELAY = int(os.getenv("RETRY_DELAY", 60))
MAX_EMAIL_RESULTS = int(os.getenv("MAX_EMAIL_RESULTS", 10))
SCHEDULE_TIME = os.getenv("SCHEDULE_TIME", "08:00")
DAYS_THRESHOLD = int(os.getenv("DAYS_THRESHOLD", 1))

hour, minute = map(int, SCHEDULE_TIME.split(":"))

# Global LLM agent instance
AGENT = MCPAgentModule()
AGENT.init()


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


def fetch_emails_with_retry() -> dict[str, Any]:
    """Fetch emails with retry logic."""
    last_error = None

    for attempt in range(RETRY_COUNT):
        try:
            logger.info(f"Attempt {attempt + 1}/{RETRY_COUNT}")

            now = datetime.now()
            date_to = now.isoformat()
            date_from = (now - timedelta(days=DAYS_THRESHOLD)).isoformat()

            date_from_ts = datetime.fromisoformat(date_from).timestamp()
            date_to_ts = datetime.fromisoformat(date_to).timestamp()
            logger.info(f"Fetching emails from {format_timestamp(date_from_ts)} to {format_timestamp(date_to_ts)}")

            result = fetch_emails(
                max_results=MAX_EMAIL_RESULTS,
                date_from=date_from,
                date_to=date_to,
                sort_by="date",
                sort_order="desc",
            )

            if result["success"]:
                logger.success(f"Fetched {result['count']} emails")
                return result
            else:
                last_error = result.get("error")
                logger.warning(f"Attempt {attempt + 1} failed: {last_error}")

        except Exception as e:
            last_error = str(e)
            logger.error(f"Attempt {attempt + 1} exception: {e}")

        if attempt < RETRY_COUNT - 1:
            logger.info(f"Retrying in {RETRY_DELAY}s...")
            time.sleep(RETRY_DELAY)

    logger.error(f"All {RETRY_COUNT} attempts failed. Last error: {last_error}")
    return {"success": False, "error": last_error, "count": 0, "emails": []}


def summarize_emails(emails: list[dict[str, Any]]) -> str:
    """Summarize emails using LLM."""
    logger.info(f"Summarizing {len(emails)} emails...")
    summary = AGENT.summarize_emails(emails)
    logger.success("Email summary generated")
    return summary


def send_email(
    to: str | list[str],
    subject: str,
    body: str,
    is_html: bool = False,
) -> str:
    """Send email via SMTP."""
    logger.info(f"[send_email] Sending email to {to}")

    email_host = os.getenv("EMAIL_HOST_USER")
    email_password = os.getenv("EMAIL_HOST_PASSWORD")

    if not email_host or not email_password:
        raise ValueError("SMTP credentials not configured. Set EMAIL_HOST_USER and EMAIL_HOST_PASSWORD.")

    recipients = [to] if isinstance(to, str) else to

    msg = MIMEMultipart("alternative")
    msg["From"] = email_host
    msg["To"] = ", ".join(recipients)
    msg["Subject"] = subject

    mime_type = "html" if is_html else "plain"
    msg.attach(MIMEText(body, mime_type))

    with smtplib.SMTP("smtp.gmail.com", 587) as server:
        server.starttls()
        server.login(email_host, email_password)
        server.sendmail(email_host, recipients, msg.as_string())

    logger.info(f"[send_email] Email sent successfully to {recipients}")
    return f"Email sent successfully to {recipients}"


# =============================================================================
# Huey Tasks
# =============================================================================

@huey.task(retries=3, retry_delay=5)
def send_email_task(to: str | list[str], subject: str, body: str, is_html: bool = False) -> str:
    """Send email via SMTP (Huey task)."""
    return send_email(to, subject, body, is_html)


@huey.periodic_task(crontab(hour=hour, minute=minute))
def daily_email_summary() -> dict[str, Any]:
    """
    Main scheduled task: Fetch, summarize, and email daily email summary.
    
    Runs daily at SCHEDULE_TIME. Fetches emails from the past DAYS_THRESHOLD,
    generates an HTML summary using LLM, and emails it to MY_EMAIL.
    """
    logger.info(f"Starting daily email fetch (last {DAYS_THRESHOLD} day(s))...")

    result = fetch_emails_with_retry()
    emails_fetched = result.get("count", 0) if result.get("success") else 0
    now = datetime.now()

    if result["success"] and result["emails"]:
        # Generate summary
        summary = summarize_emails(result["emails"])

        # Print to console
        # print("\n" + "=" * 60)
        # print("[bold green]EMAIL SUMMARY[/bold green]")
        # print("=" * 60)
        # print(summary)
        # print("=" * 60 + "\n")

        # Send via email
        logger.info(f"Daily email fetch completed at {now.strftime('%Y-%m-%d %H:%M:%S')}")
        logger.info(f"Emailing the summary to {os.getenv('MY_EMAIL')}")
        send_email_task(
            to=os.getenv("MY_EMAIL"),
            subject="Daily Email Summary",
            body=summary,
            is_html=True,
        )

    return {
        "date": now.strftime("%Y-%m-%d"),
        "time": now.strftime("%H:%M:%S"),
        "emails_fetched": emails_fetched,
        "emails_summarized": emails_fetched,
    }


logger.info(f"Scheduled daily email fetch at {SCHEDULE_TIME} ({DAYS_THRESHOLD} day(s))")