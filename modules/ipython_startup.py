import os
import redis
from IPython.core.getipython import get_ipython
from IPython.core.magic import register_line_magic
from dotenv import load_dotenv
from rich import print
from rich.console import Console
from rich.table import Table

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
    from tasks import daily_email_summary, load_users
    users = load_users()
    for user in users:
        kw = user.get("keyword", "default")
        r.delete(f"morning_mailer:last_run:{kw}")
        r.delete(f"morning_mailer:last_schedule:{kw}")
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
    result = fetch_emails_with_retry(keyword=line,max_results=20,days_threshold=1)
    print(f"Fetched: {result.get('count')} emails")
    return result


@register_line_magic
def run_summarize(line):
    """Run email summary on last fetched emails."""
    from tasks import fetch_emails_with_retry, summarize_emails
    result = fetch_emails_with_retry(keyword=line,max_results=20,days_threshold=1)
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


@register_line_magic
def daily_whatsapp_summary(line):
    """Enqueue the daily WhatsApp summary task."""
    from tasks import daily_whatsapp_summary, load_users
    users = load_users()
    for user in users:
        kw = user.get("keyword", "default")
        r.delete(f"morning_mailer:whatsapp_last_run:{kw}")
        r.delete(f"morning_mailer:whatsapp_last_schedule:{kw}")
    job = daily_whatsapp_summary()
    print(f"WhatsApp job enqueued: {job.id}")


@register_line_magic
def send_test_whatsapp(line):
    """Send a test WhatsApp message. Usage: %send_test_whatsapp <mobile_number> <message>"""
    parts = line.strip().split(None, 1)
    if len(parts) < 2:
        print("Usage: %send_test_whatsapp <mobile_number> <message>")
        print("Example: %send_test_whatsapp 919418168860 Hello from Morning Mailer!")
        return
    mobile, text = parts[0], parts[1]
    from tasks import send_whatsapp
    try:
        result = send_whatsapp(mobile, text)
        print(f"[green]✓ {result}[/green]")
    except Exception as e:
        print(f"[red]✗ WhatsApp send failed: {e}[/red]")


@register_line_magic
def summarize_whatsapp(line):
    """Fetch and summarize emails in WhatsApp format. Usage: %summarize_whatsapp <keyword>"""
    keyword = line.strip()
    if not keyword:
        print("Usage: %summarize_whatsapp <keyword>")
        return
    from tasks import fetch_emails_with_retry, summarize_emails
    from modules.prompt import WHATSAPP_SYSTEM_PROMPT
    result = fetch_emails_with_retry(keyword=keyword, max_results=20, days_threshold=1)
    if result.get("emails"):
        summary = summarize_emails(result["emails"])
        print(summary)
    else:
        print("No emails to summarize")


print("[green]✓[/green] Morning Mailer magic functions loaded")

console = Console()

magics = [
    ("%daily_email_summary", "", "Trigger the daily email summary task"),
    ("%daily_whatsapp_summary", "", "Trigger the daily WhatsApp summary task"),
    ("%send_test_email", "<subject> <body>", "Send a test email"),
    ("%send_test_whatsapp", "<mobile> <message>", "Send a test WhatsApp message"),
    ("%summarize_whatsapp", "<keyword>", "Fetch & summarize in WhatsApp format"),
    ("%run_summarize", "<keyword>", "Fetch & summarize in HTML email format"),
    ("%check_job_status", "<job_id>", "Check Huey job status by ID"),
    ("%run_fetch", "<keyword>", "Fetch emails directly (no Huey)"),
    ("%setup_oauth", "<keyword>", "OAuth token setup (desktop app)"),
    ("%setup_web_oauth", "<keyword>", "OAuth token setup (web app)"),
    ("%check_tokens", "", "Show token status for all users"),
    ("%redis_status", "", "Check Redis connection health"),
    ("%clear_last_run", "[keyword|all]", "Clear last run tracking in Redis"),
    ("%cls", "", "Clear terminal screen"),
]

table = Table(title="[bold]Available Magic Functions[/bold]", show_header=True, header_style="bold cyan")
table.add_column("Command", style="green", no_wrap=True)
table.add_column("Parameters", style="yellow")
table.add_column("Description", style="white")

for cmd, params, desc in magics:
    table.add_row(cmd, params, desc)

console.print(table)