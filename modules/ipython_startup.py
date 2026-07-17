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
    """Trigger the daily email summary task (all users)."""
    from tasks import daily_email_summary, load_users
    users = load_users()
    for user in users:
        kw = user.get("keyword", "default")
        r.delete(f"morning_mailer:last_run:{kw}")
        r.delete(f"morning_mailer:last_schedule:{kw}")
    result = daily_email_summary()
    print(f"Email summary completed: {result.get('processed', 0)} user(s) processed")


@register_line_magic
def force_email_summary(line):
    """Trigger email summary for ALL users immediately (ignores schedule time)."""
    from tasks import load_users, process_user, SCHEDULE_TIME
    users = load_users()
    if not users:
        print("[yellow]No active users found[/yellow]")
        return
    print(f"[cyan]Forcing email summary for {len(users)} user(s)...[/cyan]")
    for user in users:
        kw = user.get("keyword", "default")
        r.delete(f"morning_mailer:last_run:{kw}")
        r.delete(f"morning_mailer:last_schedule:{kw}")
    for user in users:
        kw = user.get("keyword", "default")
        print(f"  Processing: {user.get('name')} ({kw})...")
        result = process_user(user, SCHEDULE_TIME)
        if result.get("error"):
            print(f"    [red]✗ {result['error']}[/red]")
        else:
            print(f"    [green]✓ Sent to {result.get('email')} ({result.get('emails_fetched')} emails)[/green]")
    print(f"[green]✓ Forced email summary completed for {len(users)} user(s)[/green]")


@register_line_magic
def force_whatsapp_summary(line):
    """Trigger WhatsApp summary for ALL users immediately (ignores schedule time)."""
    from tasks import load_users, fetch_emails_with_retry, get_user_settings, has_valid_token, send_whatsapp, get_agent, SCHEDULE_TIME, redis_client
    from modules.prompt import WHATSAPP_SYSTEM_PROMPT
    from datetime import datetime
    users = load_users()
    if not users:
        print("[yellow]No active users found[/yellow]")
        return
    wa_users = [u for u in users if u.get("mobile") and u.get("use_whatsapp", True)]
    if not wa_users:
        print("[yellow]No users with mobile + use_whatsapp enabled[/yellow]")
        return
    print(f"[cyan]Forcing WhatsApp summary for {len(wa_users)} user(s)...[/cyan]")
    for user in wa_users:
        kw = user.get("keyword", "default")
        r.delete(f"morning_mailer:whatsapp_last_run:{kw}")
        r.delete(f"morning_mailer:whatsapp_last_schedule:{kw}")
    for user in wa_users:
        kw = user.get("keyword", "default")
        mobile = user.get("mobile", "")
        user_name = user.get("name", "Unknown")
        print(f"  Processing: {user_name} ({kw}) → {mobile}...")
        if not has_valid_token(kw):
            print(f"    [red]✗ No OAuth token. Run %setup_oauth {kw}[/red]")
            continue
        max_results, days_threshold = get_user_settings(user)
        result = fetch_emails_with_retry(kw, max_results, days_threshold)
        if not result.get("success") or not result.get("emails"):
            print(f"    [yellow]No emails fetched[/yellow]")
            continue
        summary = get_agent().summarize_emails(result["emails"], prompt=WHATSAPP_SYSTEM_PROMPT, user_name=user_name)
        try:
            send_whatsapp(mobile, summary)
            today_str = datetime.now().strftime("%Y-%m-%d")
            redis_client.set(f"morning_mailer:whatsapp_last_run:{kw}", today_str)
            redis_client.set(f"morning_mailer:whatsapp_last_schedule:{kw}", user.get("schedule_time", SCHEDULE_TIME))
            print(f"    [green]✓ Sent ({result.get('count')} emails)[/green]")
        except Exception as e:
            print(f"    [red]✗ Send failed: {e}[/red]")
    print(f"[green]✓ Forced WhatsApp summary completed for {len(wa_users)} user(s)[/green]")


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
def switch_model(line):
    """Hot-switch the LLM model at runtime. Usage: %switch_model <provider> [model_name] [temperature]"""
    parts = line.strip().split()
    if not parts:
        print("Usage: %switch_model <provider> [model_name] [temperature]")
        print("Example: %switch_model openrouter gpt-4o-mini 0.3")
        print("         %switch_model openai gpt-4o")
        print("Supported providers: openai, google, openrouter, nvidia")
        return
    provider = parts[0]
    model_name = parts[1] if len(parts) > 1 else None
    temperature = float(parts[2]) if len(parts) > 2 else None
    from tasks import get_agent
    get_agent().hot_switch_model(model_provider=provider, model_name=model_name, temperature=temperature)
    print(f"[green]✓[/green] Model hot-switched to [bold]{provider}[/bold] ({model_name or 'default'}, temp: {temperature or 'default'})")


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
    recipient = os.getenv("MY_EMAIL")
    if not recipient:
        print("[red]MY_EMAIL is not set in .env[/red]")
        return
    from tasks import send_email
    send_email(recipient, subject, body)
    print(f"Test email sent to {recipient}")


@register_line_magic
def redis_status(line):
    """Check Redis connection status."""
    try:
        r.ping()
        print("[green]✓[/green] Redis connected")
        info = r.info()
        print(f"Keys: {len(r.keys('*'))}")
        print(f"Memory: {info.get('used_memory_human', 'N/A')}")
        try:
            from modules.redis_users import RedisUserManager
            mgr = RedisUserManager(r=r)
            print(f"Users: {mgr.count()}")
        except Exception:
            pass
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
    """Check which users have OAuth tokens (checks Redis first, then users.json)."""
    import json
    from pathlib import Path

    print("[bold]Token Status:[/bold]")
    print()

    # Try Redis users first
    users: list = []
    try:
        from modules.redis_users import RedisUserManager
        mgr = RedisUserManager(r=r)
        users = mgr.get_all()
        if users:
            print("[dim](from Redis)[/dim]")
    except Exception:
        pass

    # Fall back to users.json
    if not users:
        users_file = Path("users.json")
        if users_file.exists():
            with open(users_file, "r") as f:
                users = json.load(f)
            print("[dim](from users.json)[/dim]")

    if not users:
        print("No users found in Redis or users.json")
        return

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
    """Trigger the daily WhatsApp summary task (all users)."""
    from tasks import daily_whatsapp_summary, load_users
    users = load_users()
    for user in users:
        kw = user.get("keyword", "default")
        r.delete(f"morning_mailer:whatsapp_last_run:{kw}")
        r.delete(f"morning_mailer:whatsapp_last_schedule:{kw}")
    result = daily_whatsapp_summary()
    print(f"WhatsApp summary completed: {result.get('processed', 0)} user(s) processed")


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
    from tasks import fetch_emails_with_retry, get_agent
    from modules.prompt import WHATSAPP_SYSTEM_PROMPT
    result = fetch_emails_with_retry(keyword=keyword, max_results=20, days_threshold=1)
    if result.get("emails"):
        summary = get_agent().summarize_emails(result["emails"], prompt=WHATSAPP_SYSTEM_PROMPT)
        print(summary)
    else:
        print("No emails to summarize")


def _find_user_by_identifier(users, identifier):
    """Find a user by keyword, email, or mobile number."""
    user = next((u for u in users if u.get("keyword") == identifier), None)
    if user:
        return user
    user = next((u for u in users if u.get("email", "").lower() == identifier.lower()), None)
    if user:
        return user
    user = next((u for u in users if u.get("mobile", "") == identifier), None)
    return user


@register_line_magic
def send_email_summary(line):
    """Fetch, summarize, and send email summary to a specific user. Usage: %send_email_summary <keyword|email>"""
    identifier = line.strip()
    if not identifier:
        print("Usage: %send_email_summary <keyword|email>")
        print("Examples:")
        print("  %send_email_summary dhimanparas20")
        print("  %send_email_summary user@gmail.com")
        return
    from tasks import load_users, process_user, SCHEDULE_TIME
    users = load_users()
    user = _find_user_by_identifier(users, identifier)
    if not user:
        print(f"[red]No active user found for: {identifier}[/red]")
        print("Available users:")
        for u in users:
            print(f"  - {u.get('keyword')} | {u.get('email')} ({u.get('name')})")
        return
    keyword = user.get("keyword", "default")
    r.delete(f"morning_mailer:last_run:{keyword}")
    r.delete(f"morning_mailer:last_schedule:{keyword}")
    print(f"[cyan]Processing email summary for: {user.get('name')} ({keyword})[/cyan]")
    result = process_user(user, SCHEDULE_TIME)
    if result.get("error"):
        print(f"[red]Error: {result['error']}[/red]")
    else:
        print(f"[green]✓ Sent email summary to {result.get('email')} ({result.get('emails_fetched')} emails)[/green]")


@register_line_magic
def send_whatsapp_summary(line):
    """Fetch, summarize, and send WhatsApp summary to a specific user. Usage: %send_whatsapp_summary <keyword|mobile>"""
    identifier = line.strip()
    if not identifier:
        print("Usage: %send_whatsapp_summary <keyword|mobile>")
        print("Examples:")
        print("  %send_whatsapp_summary dhimanparas20")
        print("  %send_whatsapp_summary 919418168860")
        return
    from tasks import load_users, fetch_emails_with_retry, get_user_settings, has_valid_token, send_whatsapp, get_agent, SCHEDULE_TIME, redis_client
    from modules.prompt import WHATSAPP_SYSTEM_PROMPT
    from datetime import datetime
    users = load_users()
    user = _find_user_by_identifier(users, identifier)
    if not user:
        print(f"[red]No active user found for: {identifier}[/red]")
        print("Available users:")
        for u in users:
            print(f"  - {u.get('keyword')} | {u.get('mobile', 'no mobile')} ({u.get('name')})")
        return
    keyword = user.get("keyword", "default")
    mobile = user.get("mobile", "")
    if not mobile:
        print(f"[red]User {user.get('name')} has no mobile number configured[/red]")
        return
    if not has_valid_token(keyword):
        print(f"[red]OAuth token not found for {keyword}. Run: %setup_oauth {keyword}[/red]")
        return
    r.delete(f"morning_mailer:whatsapp_last_run:{keyword}")
    r.delete(f"morning_mailer:whatsapp_last_schedule:{keyword}")
    max_results, days_threshold = get_user_settings(user)
    user_name = user.get("name", "Unknown")
    print(f"[cyan]Processing WhatsApp summary for: {user_name} ({keyword})[/cyan]")
    result = fetch_emails_with_retry(keyword, max_results, days_threshold)
    if not result.get("success") or not result.get("emails"):
        print("[yellow]No emails fetched, nothing to summarize[/yellow]")
        return
    summary = get_agent().summarize_emails(result["emails"], prompt=WHATSAPP_SYSTEM_PROMPT, user_name=user_name)
    try:
        send_whatsapp(mobile, summary)
        today_str = datetime.now().strftime("%Y-%m-%d")
        user_schedule = user.get("schedule_time", SCHEDULE_TIME)
        redis_client.set(f"morning_mailer:whatsapp_last_run:{keyword}", today_str)
        redis_client.set(f"morning_mailer:whatsapp_last_schedule:{keyword}", user_schedule)
        print(f"[green]✓ Sent WhatsApp summary to {mobile} ({result.get('count')} emails)[/green]")
    except Exception as e:
        print(f"[red]✗ WhatsApp send failed: {e}[/red]")


# ---- Redis user CRUD magics ----


@register_line_magic
def fetch_calendar(line):
    """Fetch and display calendar events in shell. Usage: %fetch_calendar <keyword> [days]"""
    parts = line.strip().split()
    if not parts:
        print("Usage: %fetch_calendar <keyword> [days]")
        print("Example: %fetch_calendar dhimanparas20 2")
        return
    keyword = parts[0]
    days = int(parts[1]) if len(parts) > 1 else 2
    from modules.fetch_calendar import fetch_upcoming_events
    result = fetch_upcoming_events(keyword=keyword, days=days)
    if result.get("success"):
        events = result.get("events", [])
        if not events:
            print(f"[yellow]No events found for '{keyword}' in the next {days} day(s)[/yellow]")
            return
        print(f"[green]Found {len(events)} event(s) for '{keyword}' (next {days} day(s)):[/green]")
        for ev in events:
            all_day = " (all-day)" if ev["is_all_day"] else ""
            loc = f" @ {ev['location']}" if ev.get("location") else ""
            link = f"\n    🔗 {ev['html_link']}" if ev.get("html_link") else ""
            print(f"  [{ev['start']} → {ev['end']}]{all_day} {ev['summary']}{loc}{link}")
    else:
        print(f"[red]Error fetching calendar: {result.get('error', 'Unknown error')}[/red]")


@register_line_magic
def send_calendar_email(line):
    """Fetch calendar events and send HTML summary via email. Usage: %send_calendar_email <keyword> [days]"""
    parts = line.strip().split()
    if not parts:
        print("Usage: %send_calendar_email <keyword> [days]")
        print("Example: %send_calendar_email paras_premagic 2")
        return
    keyword = parts[0]
    days = int(parts[1]) if len(parts) > 1 else 2

    from tasks import load_users, send_email
    from modules.fetch_calendar import fetch_upcoming_events
    from modules.prompt import CALENDAR_EMAIL_PROMPT

    users = load_users()
    user = next((u for u in users if u.get("keyword") == keyword), None)
    if not user:
        print(f"[red]User '{keyword}' not found[/red]")
        return

    user_name = user.get("name", "Unknown")
    user_email = user.get("email", "")
    smtp_user = user.get("smtp_host_user")
    smtp_password = user.get("smtp_host_password")

    print(f"[cyan]Fetching calendar events for {user_name} ({keyword})...[/cyan]")
    result = fetch_upcoming_events(keyword=keyword, days=days)
    if not result.get("success") or not result.get("events"):
        print("[yellow]No calendar events found[/yellow]")
        return

    print(f"[cyan]Summarizing {len(result['events'])} event(s)...[/cyan]")
    from tasks import get_agent
    summary = get_agent().summarize_emails(result["events"], prompt=CALENDAR_EMAIL_PROMPT, user_name=user_name)

    send_email(
        to=user_email,
        subject=f"Calendar Summary - {user_name}",
        body=summary,
        is_html=True,
        smtp_user=smtp_user,
        smtp_password=smtp_password,
    )
    print(f"[green]✓ Calendar summary sent to {user_email} ({len(result['events'])} events)[/green]")


@register_line_magic
def send_calendar_whatsapp(line):
    """Fetch calendar events and send WhatsApp summary. Usage: %send_calendar_whatsapp <keyword> [days]"""
    parts = line.strip().split()
    if not parts:
        print("Usage: %send_calendar_whatsapp <keyword> [days]")
        print("Example: %send_calendar_whatsapp paras_premagic 2")
        return
    keyword = parts[0]
    days = int(parts[1]) if len(parts) > 1 else 2

    from tasks import load_users, send_whatsapp
    from modules.fetch_calendar import fetch_upcoming_events
    from modules.prompt import CALENDAR_WHATSAPP_PROMPT

    users = load_users()
    user = next((u for u in users if u.get("keyword") == keyword), None)
    if not user:
        print(f"[red]User '{keyword}' not found[/red]")
        return

    mobile = user.get("mobile", "")
    if not mobile:
        print(f"[red]User {user.get('name')} has no mobile number configured[/red]")
        return

    user_name = user.get("name", "Unknown")

    print(f"[cyan]Fetching calendar events for {user_name} ({keyword})...[/cyan]")
    result = fetch_upcoming_events(keyword=keyword, days=days)
    if not result.get("success") or not result.get("events"):
        print("[yellow]No calendar events found[/yellow]")
        return

    print(f"[cyan]Summarizing {len(result['events'])} event(s)...[/cyan]")
    from tasks import get_agent
    summary = get_agent().summarize_emails(result["events"], prompt=CALENDAR_WHATSAPP_PROMPT, user_name=user_name)

    try:
        send_whatsapp(mobile, summary)
        print(f"[green]✓ Calendar summary sent to {mobile} ({len(result['events'])} events)[/green]")
    except Exception as e:
        print(f"[red]✗ WhatsApp send failed: {e}[/red]")


@register_line_magic
def send_calendar_both(line):
    """Fetch calendar events and send via BOTH email and WhatsApp. Usage: %send_calendar_both <keyword> [days]"""
    parts = line.strip().split()
    if not parts:
        print("Usage: %send_calendar_both <keyword> [days]")
        print("Example: %send_calendar_both paras_premagic 2")
        return
    keyword = parts[0]
    days = int(parts[1]) if len(parts) > 1 else 2

    from tasks import load_users, send_email, send_whatsapp
    from modules.fetch_calendar import fetch_upcoming_events
    from modules.prompt import CALENDAR_EMAIL_PROMPT, CALENDAR_WHATSAPP_PROMPT

    users = load_users()
    user = next((u for u in users if u.get("keyword") == keyword), None)
    if not user:
        print(f"[red]User '{keyword}' not found[/red]")
        return

    user_name = user.get("name", "Unknown")
    user_email = user.get("email", "")
    mobile = user.get("mobile", "")
    smtp_user = user.get("smtp_host_user")
    smtp_password = user.get("smtp_host_password")

    print(f"[cyan]Fetching calendar events for {user_name} ({keyword})...[/cyan]")
    result = fetch_upcoming_events(keyword=keyword, days=days)
    if not result.get("success") or not result.get("events"):
        print("[yellow]No calendar events found[/yellow]")
        return

    events = result["events"]
    print(f"[cyan]Summarizing {len(events)} event(s)...[/cyan]")
    from tasks import get_agent

    # Send email
    try:
        email_summary = get_agent().summarize_emails(events, prompt=CALENDAR_EMAIL_PROMPT, user_name=user_name)
        send_email(
            to=user_email,
            subject=f"Calendar Summary - {user_name}",
            body=email_summary,
            is_html=True,
            smtp_user=smtp_user,
            smtp_password=smtp_password,
        )
        print(f"[green]✓ Email sent to {user_email}[/green]")
    except Exception as e:
        print(f"[red]✗ Email send failed: {e}[/red]")

    # Send WhatsApp
    if mobile:
        try:
            wa_summary = get_agent().summarize_emails(events, prompt=CALENDAR_WHATSAPP_PROMPT, user_name=user_name)
            send_whatsapp(mobile, wa_summary)
            print(f"[green]✓ WhatsApp sent to {mobile}[/green]")
        except Exception as e:
            print(f"[red]✗ WhatsApp send failed: {e}[/red]")
    else:
        print("[yellow]⚠ No mobile number, skipping WhatsApp[/yellow]")

    print(f"[green]✓ Calendar summary completed ({len(events)} events)[/green]")


@register_line_magic
def redis_users_list(line):
    """List all users stored in Redis."""
    from modules.redis_users import RedisUserManager
    from rich.table import Table
    mgr = RedisUserManager(r=r)
    users = mgr.get_all()
    if not users:
        print("[yellow]No users found in Redis.[/yellow]")
        return

    table = Table(title=f"[bold]Redis Users ({len(users)})[/bold]", show_header=True,
                  header_style="bold magenta", box=None)
    table.add_column("Name", style="cyan")
    table.add_column("Email", style="yellow")
    table.add_column("Keyword", style="green")
    table.add_column("Sch", style="magenta")
    table.add_column("Max", style="blue", justify="center")
    table.add_column("Days", style="blue", justify="center")
    table.add_column("Mobile", style="yellow")
    table.add_column("Ch", style="green", justify="center")
    table.add_column("Cal", style="cyan", justify="center")
    table.add_column("Rdy", style="red", justify="center")

    for u in users:
        use_e = u.get("use_email", True)
        use_w = u.get("use_whatsapp", True)
        ch = ("E" if use_e else "-") + ("W" if use_w else "-")
        rdy = "✓" if u.get("active", True) else "✗"
        fetch_cal = u.get("fetch_calendar", False)
        cal = "✓" if fetch_cal else "-"
        table.add_row(
            u.get("name", "?"), u.get("email", ""), u.get("keyword", ""),
            u.get("schedule_time", "-"), str(u.get("max_email_results", "-")),
            str(u.get("days_threshold", "-")), u.get("mobile", "-"),
            ch, cal, rdy,
        )
    console = Console()
    console.print(table)


@register_line_magic
def redis_users_show(line):
    """Show a single user's full details from Redis. Usage: %redis_users_show <keyword>"""
    keyword = line.strip()
    if not keyword:
        print("Usage: %redis_users_show <keyword>")
        return
    from modules.redis_users import RedisUserManager
    mgr = RedisUserManager(r=r)
    user = mgr.get(keyword)
    if not user:
        print(f"[red]User '{keyword}' not found in Redis[/red]")
        return
    for f in ["name", "email", "keyword", "active", "use_email", "use_whatsapp", "fetch_calendar",
              "max_email_results", "days_threshold", "schedule_time",
              "smtp_host_user", "smtp_host_password", "mobile"]:
        val = user.get(f, "-")
        if f == "smtp_host_password" and val:
            val = "*****"
        print(f"  [cyan]{f:<20}[/cyan] {val}")


@register_line_magic
def redis_users_add(line):
    """Add a user to Redis. Usage: %redis_users_add --name X --email Y --keyword Z [--active true] ..."""
    import shlex
    try:
        args_list = shlex.split(line)
    except ValueError:
        args_list = line.split()

    from modules.redis_users import RedisUserManager
    mgr = RedisUserManager(r=r)

    # Parse key=value or --flag value
    kwargs: dict = {}
    i = 0
    while i < len(args_list):
        arg = args_list[i]
        if arg.startswith("--"):
            key = arg[2:].replace("-", "_")
            if i + 1 < len(args_list) and not args_list[i + 1].startswith("--"):
                i += 1
                kwargs[key] = args_list[i]
            else:
                kwargs[key] = True
        i += 1

    if "keyword" not in kwargs:
        print("[red]--keyword is required[/red]")
        return
    if "name" not in kwargs or "email" not in kwargs:
        print("[red]--name and --email are required[/red]")
        return

    mgr.add_or_update(kwargs)
    print(f"[green]✓ Added user '{kwargs['keyword']}'[/green]")


@register_line_magic
def redis_users_update(line):
    """Update a user in Redis. Usage: %redis_users_update <keyword> --field value ..."""
    import shlex
    try:
        args_list = shlex.split(line)
    except ValueError:
        args_list = line.split()
    if not args_list or args_list[0].startswith("--"):
        print("Usage: %redis_users_update <keyword> [--field value ...]")
        return
    keyword = args_list[0]
    from modules.redis_users import RedisUserManager
    mgr = RedisUserManager(r=r)
    existing = mgr.get(keyword)
    if not existing:
        print(f"[red]User '{keyword}' not found in Redis[/red]")
        return
    kwargs = dict(existing)
    i = 1
    while i < len(args_list):
        arg = args_list[i]
        if arg.startswith("--"):
            key = arg[2:].replace("-", "_")
            if i + 1 < len(args_list) and not args_list[i + 1].startswith("--"):
                i += 1
                kwargs[key] = args_list[i]
            else:
                kwargs[key] = True
        i += 1
    mgr.add_or_update(kwargs)
    print(f"[green]✓ Updated user '{keyword}'[/green]")


@register_line_magic
def redis_users_remove(line):
    """Remove a user from Redis. Usage: %redis_users_remove <keyword>"""
    keyword = line.strip()
    if not keyword:
        print("Usage: %redis_users_remove <keyword>")
        return
    from modules.redis_users import RedisUserManager
    mgr = RedisUserManager(r=r)
    if mgr.delete(keyword):
        print(f"[green]✓ Removed user '{keyword}'[/green]")
    else:
        print(f"[red]User '{keyword}' not found in Redis[/red]")


@register_line_magic
def redis_users_import(line):
    """Import users from users.json into Redis. Usage: %redis_users_import [file.json]"""
    path = line.strip() or "users.json"
    from modules.redis_users import RedisUserManager
    mgr = RedisUserManager(r=r)
    n = mgr.import_from_json(path)
    if n > 0:
        print(f"[green]✓ Imported {n} user(s) from {path}[/green]")
    else:
        print(f"[yellow]No users imported from {path}[/yellow]")


@register_line_magic
def redis_users_export(line):
    """Export Redis users to a JSON file. Usage: %redis_users_export [file.json]"""
    path = line.strip() or "users.json"
    from modules.redis_users import RedisUserManager
    mgr = RedisUserManager(r=r)
    n = mgr.export_to_json(path)
    print(f"[green]✓ Exported {n} user(s) to {path}[/green]")


@register_line_magic
def redis_users_activate(line):
    """Activate a user in Redis. Usage: %redis_users_activate <keyword>"""
    keyword = line.strip()
    if not keyword:
        print("Usage: %redis_users_activate <keyword>")
        return
    from modules.redis_users import RedisUserManager
    mgr = RedisUserManager(r=r)
    if mgr.activate(keyword):
        print(f"[green]✓ Activated '{keyword}'[/green]")
    else:
        print(f"[red]User '{keyword}' not found in Redis[/red]")


@register_line_magic
def redis_users_deactivate(line):
    """Deactivate a user in Redis. Usage: %redis_users_deactivate <keyword>"""
    keyword = line.strip()
    if not keyword:
        print("Usage: %redis_users_deactivate <keyword>")
        return
    from modules.redis_users import RedisUserManager
    mgr = RedisUserManager(r=r)
    if mgr.deactivate(keyword):
        print(f"[yellow]✓ Deactivated '{keyword}'[/yellow]")
    else:
        print(f"[red]User '{keyword}' not found in Redis[/red]")


@register_line_magic
def redis_users_clear(line):
    """Delete ALL users from Redis. Requires 'yes' typed inline. Usage: %redis_users_clear yes"""
    if line.strip().lower() != "yes":
        print("[bold red]WARNING: This will delete ALL users from Redis![/bold red]")
        print("Type %redis_users_clear yes to confirm")
        return
    from modules.redis_users import RedisUserManager
    mgr = RedisUserManager(r=r)
    n = mgr.clear_all()
    print(f"[green]✓ Cleared {n} user(s) from Redis[/green]")


@register_line_magic
def redis_users_fields(line):
    """Show all available user fields with types and descriptions."""
    from modules.redis_users import ALL_FIELDS, BOOL_FIELDS, INT_FIELDS
    from rich.table import Table

    desc = {
        "name": "Display name",
        "email": "Email address for delivery",
        "keyword": "Unique ID (links to token_<keyword>.json)",
        "active": "Enable/disable this user",
        "use_email": "Enable email delivery",
        "use_whatsapp": "Enable WhatsApp delivery",
        "fetch_calendar": "Include Google Calendar events in summary",
        "max_email_results": "Max emails to fetch",
        "days_threshold": "Days to look back",
        "schedule_time": "Run time (HH:MM, 24h)",
        "smtp_host_user": "Custom SMTP username",
        "smtp_host_password": "Custom SMTP password",
        "mobile": "WhatsApp number (country code, no +)",
    }

    table = Table(title="[bold]Available User Fields[/bold]", show_header=True,
                  header_style="bold cyan")
    table.add_column("Field", style="green")
    table.add_column("Type", style="magenta", justify="center")
    table.add_column("CLI Flag", style="cyan")
    table.add_column("Description", style="white")

    for field in ALL_FIELDS:
        if field in BOOL_FIELDS:
            t = "bool"
        elif field in INT_FIELDS:
            t = "int"
        else:
            t = "str"
        flag = "--" + field.replace("_", "-")
        table.add_row(field, t, flag, desc.get(field, ""))

    console = Console()
    console.print(table)


    print("[green]✓[/green] Morning Mailer magic functions loaded")

console = Console()

magics = [
    ("%daily_email_summary", "", "Trigger the daily email summary task (all users)"),
    ("%daily_whatsapp_summary", "", "Trigger the daily WhatsApp summary task (all users)"),
    ("%force_email_summary", "", "Force email summary for ALL users (ignores schedule)"),
    ("%force_whatsapp_summary", "", "Force WhatsApp summary for ALL users (ignores schedule)"),
    ("%send_email_summary", "<keyword|email>", "Send email summary to a specific user"),
    ("%send_whatsapp_summary", "<keyword|mobile>", "Send WhatsApp summary to a specific user"),
    ("%fetch_calendar", "<keyword> [days]", "Fetch & display calendar events in shell"),
    ("%send_calendar_email", "<keyword> [days]", "Fetch calendar & send HTML summary via email"),
    ("%send_calendar_whatsapp", "<keyword> [days]", "Fetch calendar & send WhatsApp summary"),
    ("%send_calendar_both", "<keyword> [days]", "Fetch calendar & send via both email + WhatsApp"),
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
    ("%redis_users_list", "", "List all users stored in Redis"),
    ("%redis_users_show", "<keyword>", "Show one user's details from Redis"),
    ("%redis_users_add", "--name X --email Y --keyword Z ...", "Add a user to Redis"),
    ("%redis_users_update", "<keyword> --field value ...", "Update a user in Redis"),
    ("%redis_users_remove", "<keyword>", "Remove a user from Redis"),
    ("%redis_users_import", "[file.json]", "Import users from JSON file to Redis"),
    ("%redis_users_export", "[file.json]", "Export Redis users to JSON file"),
    ("%redis_users_activate", "<keyword>", "Activate a user in Redis"),
    ("%redis_users_deactivate", "<keyword>", "Deactivate a user in Redis"),
    ("%redis_users_clear", "yes", "Delete ALL users from Redis"),
    ("%redis_users_fields", "", "Show all available user fields and types"),
    ("%switch_model", "<provider> [model] [temp]", "Hot-switch LLM model at runtime"),
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