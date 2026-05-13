#!/usr/bin/env python3
"""CLI for managing users stored in Redis (Valkey).

Users are stored as hashes at ``USERS_CONFIG:<keyword>``.

Usage::

    python cli_users.py list
    python cli_users.py show <keyword>
    python cli_users.py add   --name "Paras" --email "..." --keyword "dhimanparas20" --active true ...
    python cli_users.py update <keyword> --name "New Name"
    python cli_users.py remove  <keyword>
    python cli_users.py activate   <keyword>
    python cli_users.py deactivate <keyword>
    python cli_users.py import    [--file users.json]
    python cli_users.py export    [--file users.json]
    python cli_users.py clear     # delete ALL Redis users
"""

import argparse
import json
import os
import sys
import textwrap
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich import box

from modules.redis_users import RedisUserManager

load_dotenv()
console = Console()


# ---------------------------------------------------------------------------
# Table rendering
# ---------------------------------------------------------------------------
def _render_users_table(users: list[dict[str, Any]], title: str) -> None:
    if not users:
        console.print("[yellow]No users found.[/yellow]")
        return

    table = Table(title=f"[bold]{title} ({len(users)})[/bold]", show_header=True,
                  header_style="bold magenta", box=box.SIMPLE)
    table.add_column("Name", style="cyan", overflow="fold", min_width=10)
    table.add_column("Email", style="yellow", overflow="fold", min_width=14)
    table.add_column("Keyword", style="green", no_wrap=True, min_width=10)
    table.add_column("Sch", style="magenta", width=6)
    table.add_column("Max", style="blue", justify="center", width=4)
    table.add_column("Days", style="blue", justify="center", width=4)
    table.add_column("Mobile", style="yellow", no_wrap=True, min_width=12)
    table.add_column("Ch", style="green", justify="center", width=3)
    table.add_column("Rdy", style="red", justify="center", width=3)

    for u in users:
        use_email = u.get("use_email", True)
        use_wa = u.get("use_whatsapp", True)
        channels = ("E" if use_email else "-") + ("W" if use_wa else "-")
        active = u.get("active", True)
        ready = "✓" if active else "✗"

        table.add_row(
            u.get("name", "?"),
            u.get("email", ""),
            u.get("keyword", ""),
            u.get("schedule_time", "-"),
            str(u.get("max_email_results", "-")),
            str(u.get("days_threshold", "-")),
            u.get("mobile", "-"),
            channels,
            ready,
        )

    console.print(table)


def _render_user_detail(user: dict[str, Any]) -> None:
    """Show a single user in a two-column table."""
    table = Table(title=f"[bold]{user.get('name', '?')}[/bold] ({user.get('keyword', '?')})",
                  show_header=False, box=box.SIMPLE)
    table.add_column("Field", style="cyan")
    table.add_column("Value", style="green")

    for field in ["name", "email", "keyword", "active", "use_email", "use_whatsapp",
                   "max_email_results", "days_threshold", "schedule_time",
                   "smtp_host_user", "smtp_host_password", "mobile"]:
        val = user.get(field, "-")
        if field == "smtp_host_password" and val:
            val = "*****"
        table.add_row(field, str(val))

    console.print(table)


# ---------------------------------------------------------------------------
# Argument parsers
# ---------------------------------------------------------------------------
def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Manage Morning Mailer users in Redis (Valkey).",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=textwrap.dedent("""\
        examples:
          python cli_users.py list
          python cli_users.py show dhimanparas20
          python cli_users.py add --name "Paras" --email "p@gmail.com" --keyword dhimanparas20 --active true
          python cli_users.py update dhimanparas20 --schedule_time "09:00"
          python cli_users.py remove dhimanparas20
          python cli_users.py activate dhimanparas20
          python cli_users.py import
        """),
    )
    sub = parser.add_subparsers(dest="command", help="Available commands")

    # ---- list ----
    sub.add_parser("list", help="List all users")

    # ---- show ----
    p_show = sub.add_parser("show", help="Show details for one user")
    p_show.add_argument("keyword", help="User keyword")

    # ---- add ----
    p_add = sub.add_parser("add", help="Add a new user")
    p_add.add_argument("--name", required=True)
    p_add.add_argument("--email", required=True)
    p_add.add_argument("--keyword", required=True)
    p_add.add_argument("--active", default="true", choices=["true", "false"])
    p_add.add_argument("--use-email", default="true", choices=["true", "false"], dest="use_email")
    p_add.add_argument("--use-whatsapp", default="true", choices=["true", "false"], dest="use_whatsapp")
    p_add.add_argument("--max-emails", type=int, dest="max_email_results")
    p_add.add_argument("--days", type=int, dest="days_threshold")
    p_add.add_argument("--schedule-time", dest="schedule_time")
    p_add.add_argument("--smtp-user", dest="smtp_host_user")
    p_add.add_argument("--smtp-pass", dest="smtp_host_password")
    p_add.add_argument("--mobile")

    # ---- update ----
    p_upd = sub.add_parser("update", help="Update an existing user's fields")
    p_upd.add_argument("keyword", help="User keyword")
    for flag, field_name, help_text in [
        ("--name", "name", "Display name"),
        ("--email", "email", "Email address"),
        ("--active", "active", "true / false"),
        ("--use-email", "use_email", "Enable email delivery (true / false)"),
        ("--use-whatsapp", "use_whatsapp", "Enable WhatsApp delivery (true / false)"),
        ("--max-emails", "max_email_results", "Max emails to fetch"),
        ("--days", "days_threshold", "Days to look back"),
        ("--schedule-time", "schedule_time", "HH:MM run time"),
        ("--smtp-user", "smtp_host_user", "Custom SMTP username"),
        ("--smtp-pass", "smtp_host_password", "Custom SMTP password"),
        ("--mobile", "mobile", "WhatsApp number (country code, no +)"),
    ]:
        p_upd.add_argument(flag, dest=field_name, help=help_text)

    # ---- remove ----
    p_rm = sub.add_parser("remove", help="Delete a user")
    p_rm.add_argument("keyword", help="User keyword to remove")

    # ---- activate / deactivate ----
    p_act = sub.add_parser("activate", help="Activate a user")
    p_act.add_argument("keyword")
    p_deact = sub.add_parser("deactivate", help="Deactivate a user")
    p_deact.add_argument("keyword")

    # ---- import / export / clear ----
    p_imp = sub.add_parser("import", help="Import users from users.json into Redis")
    p_imp.add_argument("--file", default="users.json", help="JSON file to import (default: users.json)")
    p_exp = sub.add_parser("export", help="Export Redis users to a JSON file")
    p_exp.add_argument("--file", default="users.json", help="Output file (default: users.json)")
    sub.add_parser("clear", help="Delete ALL users from Redis (requires confirmation)")

    # ---- fields ----
    sub.add_parser("fields", help="Show all available user fields and their CLI flags")

    return parser


# ---------------------------------------------------------------------------
# Command handlers
# ---------------------------------------------------------------------------
def _collect_user(args: argparse.Namespace, existing: dict[str, Any] | None = None) -> dict[str, Any]:
    """Build or merge a user dict from CLI args."""
    if existing is None:
        existing = {}
    user = dict(existing)

    for arg_name, field_name in [
        ("name", "name"),
        ("email", "email"),
        ("keyword", "keyword"),
        ("schedule_time", "schedule_time"),
        ("smtp_host_user", "smtp_host_user"),
        ("smtp_host_password", "smtp_host_password"),
        ("mobile", "mobile"),
    ]:
        val = getattr(args, arg_name, None)
        if val is not None:
            user[field_name] = val

    # Booleans
    for arg_name, field_name in (
        ("active", "active"),
        ("use_email", "use_email"),
        ("use_whatsapp", "use_whatsapp"),
    ):
        val = getattr(args, arg_name, None)
        if val is not None:
            user[field_name] = val if isinstance(val, bool) else val.lower() == "true"

    # Ints
    for arg_name, field_name in (
        ("max_email_results", "max_email_results"),
        ("days_threshold", "days_threshold"),
    ):
        val = getattr(args, arg_name, None)
        if val is not None:
            try:
                user[field_name] = int(val)
            except (ValueError, TypeError):
                pass

    return user


def cmd_list(mgr: RedisUserManager) -> None:
    users = mgr.get_all()
    _render_users_table(users, "Redis Users")


def cmd_show(mgr: RedisUserManager, keyword: str) -> None:
    user = mgr.get(keyword)
    if not user:
        console.print(f"[red]User '{keyword}' not found in Redis.[/red]")
        return
    _render_user_detail(user)


def cmd_add(mgr: RedisUserManager, args: argparse.Namespace) -> None:
    if mgr.exists(args.keyword):
        console.print(f"[red]User '{args.keyword}' already exists. Use 'update' instead.[/red]")
        return
    user = _collect_user(args)
    mgr.add_or_update(user)
    console.print(f"[green]✓ Added user '{args.keyword}'[/green]")


def cmd_update(mgr: RedisUserManager, args: argparse.Namespace) -> None:
    keyword = args.keyword
    existing = mgr.get(keyword)
    if not existing:
        console.print(f"[red]User '{keyword}' not found.[/red]")
        return
    merged = _collect_user(args, existing)
    mgr.add_or_update(merged)
    console.print(f"[green]✓ Updated user '{keyword}'[/green]")


def cmd_remove(mgr: RedisUserManager, keyword: str) -> None:
    if mgr.delete(keyword):
        console.print(f"[green]✓ Removed user '{keyword}'[/green]")
    else:
        console.print(f"[red]User '{keyword}' not found.[/red]")


def cmd_activate(mgr: RedisUserManager, keyword: str) -> None:
    if mgr.activate(keyword):
        console.print(f"[green]✓ Activated '{keyword}'[/green]")
    else:
        console.print(f"[red]User '{keyword}' not found.[/red]")


def cmd_deactivate(mgr: RedisUserManager, keyword: str) -> None:
    if mgr.deactivate(keyword):
        console.print(f"[yellow]✓ Deactivated '{keyword}'[/yellow]")
    else:
        console.print(f"[red]User '{keyword}' not found.[/red]")


def cmd_import(mgr: RedisUserManager, path: str) -> None:
    n = mgr.import_from_json(path)
    if n:
        console.print(f"[green]✓ Imported {n} user(s) from {path}[/green]")
    else:
        console.print(f"[yellow]No users imported (file may not exist or be empty)[/yellow]")


def cmd_export(mgr: RedisUserManager, path: str) -> None:
    n = mgr.export_to_json(path)
    console.print(f"[green]✓ Exported {n} user(s) to {path}[/green]")


def cmd_clear(mgr: RedisUserManager) -> None:
    user_count = mgr.count()
    if user_count == 0:
        console.print("[yellow]No users to clear.[/yellow]")
        return

    # Confirm
    console.print(f"[bold red]WARNING: This will delete ALL {user_count} user(s) from Redis![/bold red]")
    response = input("Type 'yes' to confirm: ").strip()
    if response != "yes":
        console.print("[dim]Aborted.[/dim]")
        return

    n = mgr.clear_all()
    console.print(f"[green]✓ Cleared {n} user(s) from Redis[/green]")


def cmd_fields() -> None:
    """Show all available user fields and their CLI flags."""
    from modules.redis_users import ALL_FIELDS, BOOL_FIELDS, INT_FIELDS

    table = Table(title="[bold]Available User Fields[/bold]", show_header=True,
                  header_style="bold cyan", box=box.SIMPLE)
    table.add_column("Field", style="green")
    table.add_column("Type", style="magenta", justify="center")
    table.add_column("CLI Flag", style="cyan")
    table.add_column("Description", style="white")

    descriptions = {
        "name":               "Display name",
        "email":              "Email address for delivery",
        "keyword":            "Unique ID (links to token_<keyword>.json)",
        "active":             "Enable/disable this user",
        "use_email":          "Enable email delivery",
        "use_whatsapp":       "Enable WhatsApp delivery",
        "max_email_results":  "Max emails to fetch",
        "days_threshold":     "Days to look back",
        "schedule_time":      "Run time (HH:MM, 24h)",
        "smtp_host_user":     "Custom SMTP username",
        "smtp_host_password": "Custom SMTP password",
        "mobile":             "WhatsApp number (country code, no +)",
    }

    for field in ALL_FIELDS:
        if field in BOOL_FIELDS:
            ftype = "bool"
        elif field in INT_FIELDS:
            ftype = "int"
        else:
            ftype = "str"

        flag = "--" + field.replace("_", "-")
        required = " (required)" if field in ("name", "email", "keyword") else ""
        desc = descriptions.get(field, "") + required
        table.add_row(field, ftype, flag, desc)

    console.print(table)


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------
def main(argv: list[str] | None = None) -> None:
    parser = _build_parser()
    args = parser.parse_args(argv)
    if not args.command:
        parser.print_help()
        return

    mgr = RedisUserManager()

    if args.command == "list":
        cmd_list(mgr)
    elif args.command == "show":
        cmd_show(mgr, args.keyword)
    elif args.command == "add":
        cmd_add(mgr, args)
    elif args.command == "update":
        cmd_update(mgr, args)
    elif args.command == "remove":
        cmd_remove(mgr, args.keyword)
    elif args.command == "activate":
        cmd_activate(mgr, args.keyword)
    elif args.command == "deactivate":
        cmd_deactivate(mgr, args.keyword)
    elif args.command == "import":
        cmd_import(mgr, args.file)
    elif args.command == "export":
        cmd_export(mgr, args.file)
    elif args.command == "clear":
        cmd_clear(mgr)
    elif args.command == "fields":
        cmd_fields()
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
