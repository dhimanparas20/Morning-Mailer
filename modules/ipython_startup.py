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
def clear_last_run(line):
    """Clear last run date for a user (or all users) to allow re-running. Usage: %clear_last_run [keyword|all]"""
    from tasks import load_users, get_user_last_run_date, set_user_last_run_date

    users = load_users()
    keyword = line.strip()

    if not keyword or keyword == "all":
        print("[yellow]Clearing last_run for ALL users...[/yellow]")
        for user in users:
            kw = user.get("keyword", "default")
            r.delete(f"morning_mailer:last_run:{kw}")
            print(f"  ✓ Cleared: {user.get('name')} ({kw})")
    else:
        r.delete(f"morning_mailer:last_run:{keyword}")
        print(f"[green]Cleared last_run for keyword: {keyword}[/green]")


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


@register_line_magic
def setup_oauth(line):
    """Setup OAuth token for a user. Usage: %setup_oauth <keyword>"""
    keyword = line.strip()
    if not keyword:
        print("Usage: %setup_oauth <keyword>")
        print("Example: %setup_oauth bobyHP07")
        return

    print(f"Running OAuth setup for keyword: {keyword}")
    from modules.fetch_emails import get_gmail_service
    get_gmail_service(keyword)
    print(f"✓ Token should be created at gauth/tokens/token_{keyword}.json")


@register_line_magic
def setup_web_oauth(line):
    """Setup OAuth using web browser flow. Usage: %setup_web_oauth <keyword>"""
    keyword = line.strip()
    if not keyword:
        print("Usage: %setup_web_oauth <keyword>")
        print("Example: %setup_web_oauth friend")
        print("\nNote: Requires web app credentials in gauth/client_secret.json")
        return

    print(f"[yellow]Starting web OAuth for: {keyword}[/yellow]")
    print("(Make sure you have web app credentials in gauth/client_secret.json)")
    print("")
    from modules.web_auth import setup_web_oauth as do_web_auth
    do_web_auth(keyword)


@register_line_magic
def check_tokens(line):
    """Check which users have tokens."""
    import json
    from pathlib import Path

    print("[bold]Token Status:[/bold]")
    print()

    users_file = Path("users.json")
    if not users_file.exists():
        print("No users.json found")
        return

    with open(users_file, "r") as f:
        users = json.load(f)

    for user in users:
        keyword = user.get("keyword", "default")
        name = user.get("name", "Unknown")
        active = user.get("active", True)

        token_path = Path(f"gauth/tokens/token_{keyword}.json")
        if token_path.exists():
            status = "[green]✓[/green]" if active else "[yellow]⚠[/yellow] (inactive)"
            print(f"  {status} {name} ({keyword})")
        else:
            status = "[red]✗[/red]" if active else "[gray]-[/gray] (inactive)"
            print(f"  {status} {name} ({keyword}) - run '%setup_oauth {keyword}'")

    print()
    print("Run '%setup_oauth <keyword>' to create a new token")


print("[green]✓[/green] Morning Mailer magic functions loaded")
print("Available: %daily_email_summary, %check_job_status, %run_fetch, %run_summarize, %send_test_email, %redis_status, %setup_oauth, %check_tokens")