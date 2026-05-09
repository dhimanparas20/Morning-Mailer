import os
import redis
from IPython.core.getipython import get_ipython
from IPython.core.magic import register_line_magic
from dotenv import load_dotenv
from rich import print

load_dotenv()

ip = get_ipython()
r = redis.from_url(os.getenv("REDIS_URL"), decode_responses=True)

# Enable autoreload
if ip is not None:
    try:
        ip.run_line_magic("alias", "cls clear")
    except Exception:
        pass
    ip.run_line_magic("load_ext", "autoreload")
    ip.run_line_magic("autoreload", "2")


@register_line_magic
def daily_email_summary(line):
    """Enqueue the daily email fetch and summarize task."""
    from tasks import daily_email_summary
    job = daily_email_summary()
    print(f"Job enqueued: {job.id}")


@register_line_magic
def check_job_status(job_id):
    """Check status of a Huey job by ID."""
    from tasks import get_job_status
    status = get_job_status(job_id)
    print(status)


@register_line_magic
def run_fetch(line):
    """Run email fetch directly (no Huey)."""
    from tasks import fetch_emails_with_retry
    result = fetch_emails_with_retry()
    print(f"Fetched: {result.get('count')} emails")
    return result


@register_line_magic
def run_summarize(line):
    """Run email summary on last fetched emails."""
    from tasks import fetch_emails_with_retry, summarize_emails
    result = fetch_emails_with_retry()
    if result.get("emails"):
        summary = summarize_emails(result["emails"])
        print(summary)
    else:
        print("No emails to summarize")


@register_line_magic
def send_test_email(line):
    """Send a test email. Usage: %send_test_email subject body"""
    parts = line.strip().split(None, 1)
    if len(parts) < 2:
        print("Usage: %send_test_email <subject> <body>")
        return
    subject, body = parts[0], parts[1]
    from tasks import send_email
    send_email(os.getenv("MY_EMAIL"), subject, body)
    print(f"Test email sent to {os.getenv('MY_EMAIL')}")


@register_line_magic
def redis_status(line):
    """Check Redis connection status."""
    try:
        r = redis.from_url(os.getenv("REDIS_URL"), decode_responses=True)
        r.ping()
        print("[green]✓[/green] Redis connected")
        info = r.info()
        print(f"Keys: {len(r.keys('*'))}")
        print(f"Memory: {info.get('used_memory_human', 'N/A')}")
    except Exception as e:
        print(f"[red]✗[/red] Redis error: {e}")


print("[green]✓[/green] Morning Mailer magic functions loaded")
print("Available: %daily_email_summary, %check_job_status, %run_fetch, %run_summarize, %send_test_email, %redis_status")