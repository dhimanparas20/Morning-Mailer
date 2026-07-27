from __future__ import annotations

import json
from datetime import datetime, timedelta
from modules.generics import now_ist
from functools import lru_cache
from pathlib import Path
from typing import Any

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

from modules.logger import get_logger


SCOPES = ["https://www.googleapis.com/auth/calendar.readonly"]

BASE_DIR = Path("gauth")
TOKENS_DIR = BASE_DIR / "tokens"
CREDENTIALS_FILE = BASE_DIR / "client_secret.json"

logger = get_logger("[fetch_calendar]", show_time=False)


@lru_cache(maxsize=1)
def get_credentials_path() -> Path:
    if CREDENTIALS_FILE.exists():
        return CREDENTIALS_FILE
    raise FileNotFoundError(f"Credentials file not found: {CREDENTIALS_FILE}")


@lru_cache(maxsize=256)
def get_token_path(keyword: str) -> Path:
    return TOKENS_DIR / f"token_{keyword}.json"


def get_calendar_service(keyword: str = "default") -> Any:
    """Initialize and return a Google Calendar API service.

    Uses the same token file as Gmail (token_<keyword>.json).
    Since the token was created with gmail.readonly scope only,
    calendar calls will fail unless the token includes calendar.readonly.

    To add calendar scope to an existing token, re-run OAuth setup:
        python -m modules.fetch_emails setup <keyword>
    or
        python -m modules.web_auth <keyword>
    """
    try:
        creds = None
        token_path = get_token_path(keyword)
        creds_path = get_credentials_path()

        if token_path.exists():
            logger.debug(f"Loading credentials from {token_path}")
            creds = Credentials.from_authorized_user_file(str(token_path), SCOPES)

        if creds and creds.valid:
            logger.debug("Credentials are valid, reusing existing token")
            return build("calendar", "v3", credentials=creds)

        if creds and creds.expired and creds.refresh_token:
            logger.info("Access token expired, attempting refresh...")
            try:
                creds.refresh(Request())
                token_path.write_text(creds.to_json(), encoding="utf-8")
                logger.success("Token refreshed and saved successfully")
                return build("calendar", "v3", credentials=creds)
            except Exception as refresh_error:
                logger.error(f"Token refresh failed: {refresh_error}")
                raise

        if not creds_path.exists():
            raise FileNotFoundError(
                f"{creds_path} not found. Download OAuth Desktop credentials "
                "from Google Cloud Console and place it as gauth/client_secret.json"
            )

        logger.info("No valid credentials found, initiating OAuth flow...")

        try:
            flow = InstalledAppFlow.from_client_secrets_file(str(creds_path), SCOPES)
            creds = flow.run_local_server(port=0)
        except Exception as browser_error:
            logger.warning("=" * 60)
            logger.warning("No browser detected. Using manual OAuth flow.")
            logger.warning("Follow these steps:")
            logger.warning("")

            flow = InstalledAppFlow.from_client_secrets_file(str(creds_path), SCOPES)
            auth_url, _ = flow.authorization_url(access_type='offline', prompt='consent')

            logger.warning(f"1. Visit this URL in your browser:")
            logger.warning(f"   {auth_url}")
            logger.warning("")
            logger.warning("2. Sign in with your Google account")
            logger.warning("")
            logger.warning("3. After sign-in, you'll be redirected to a URL like:")
            logger.warning("   http://localhost:8080/?code=XXXXX&state=YYYY")
            logger.warning("")
            logger.warning("4. Copy the code value (everything after 'code=' until '&')")
            logger.warning("")

            code = input("Enter the authorization code: ").strip()

            flow.fetch_token(code=code)
            creds = flow.credentials

        token_path.write_text(creds.to_json(), encoding="utf-8")
        logger.success("OAuth flow completed and token saved")

        return build("calendar", "v3", credentials=creds)

    except FileNotFoundError:
        logger.exception("Credentials file missing")
        raise
    except Exception as e:
        logger.exception(f"Failed to build Calendar service: {e}")
        raise


@lru_cache(maxsize=256)
def _format_datetime(dt_str: str) -> str:
    """Format a datetime string to a readable format."""
    if not dt_str:
        return ""
    try:
        dt = datetime.fromisoformat(dt_str.replace("Z", "+00:00"))
        return dt.strftime("%Y-%m-%d %H:%M")
    except Exception:
        return dt_str


@lru_cache(maxsize=256)
def _get_event_datetime(event: dict[str, Any]) -> datetime | None:
    """Extract datetime from a calendar event (handles all-day and timed events)."""
    start = event.get("start", {})
    dt_str = start.get("dateTime") or start.get("date")
    if not dt_str:
        return None
    try:
        return datetime.fromisoformat(dt_str.replace("Z", "+00:00")).replace(tzinfo=None)
    except Exception:
        return None


def _format_event(event: dict[str, Any]) -> dict[str, Any]:
    """Format a raw Google Calendar event into a clean dict."""
    start = event.get("start", {})
    end = event.get("end", {})
    start_dt = start.get("dateTime") or start.get("date")
    end_dt = end.get("dateTime") or end.get("date")

    is_all_day = "date" in start and "dateTime" not in start

    return {
        "id": event.get("id", ""),
        "summary": event.get("summary", "(No title)"),
        "description": event.get("description", ""),
        "location": event.get("location", ""),
        "start": _format_datetime(start_dt),
        "end": _format_datetime(end_dt),
        "start_raw": start_dt,
        "end_raw": end_dt,
        "is_all_day": is_all_day,
        "attendees": [
            a.get("email", "") for a in event.get("attendees", [])
        ],
        "creator": event.get("creator", {}).get("email", ""),
        "organizer": event.get("organizer", {}).get("email", ""),
        "status": event.get("status", ""),
        "html_link": event.get("htmlLink", ""),
        "recurring_event_id": event.get("recurringEventId", ""),
    }


def fetch_events(
    keyword: str = "default",
    calendar_id: str = "primary",
    time_min: str | None = None,
    time_max: str | None = None,
    max_results: int = 20,
    query: str | None = None,
    single_events: bool = True,
    order_by: str = "startTime",
) -> dict[str, Any]:
    """Fetch calendar events.

    Args:
        keyword: User keyword for OAuth token lookup.
        calendar_id: Calendar ID (default: "primary").
        time_min: Start of time range (ISO format). Defaults to now.
        time_max: End of time range (ISO format). Defaults to 7 days ahead.
        max_results: Maximum number of events to return.
        query: Free text search term for events.
        single_events: Expand recurring events into individual instances.
        order_by: Sort order (startTime or updated).

    Returns:
        dict with keys: success, error, count, events, time_min, time_max.
    """
    result = {
        "success": False,
        "error": None,
        "count": 0,
        "events": [],
        "time_min": time_min,
        "time_max": time_max,
    }

    try:
        service = get_calendar_service(keyword)

        now = now_ist()
        if not time_min:
            time_min = now.isoformat()
            result["time_min"] = time_min
        if not time_max:
            future = now + timedelta(days=7)
            time_max = future.isoformat()
            result["time_max"] = time_max

        logger.info(f"Fetching up to {max_results} events from {result['time_min']} to {result['time_max']}")

        kwargs: dict[str, Any] = {
            "calendarId": calendar_id,
            "timeMin": time_min,
            "timeMax": time_max,
            "maxResults": max_results,
            "singleEvents": single_events,
            "orderBy": order_by,
        }
        if query:
            kwargs["q"] = query

        response = service.events().list(**kwargs).execute()
        items = response.get("items", [])

        if not items:
            logger.info("No events found in the given time range")
            result["success"] = True
            result["count"] = 0
            return result

        logger.info(f"Retrieved {len(items)} event(s)")

        for event in items:
            formatted = _format_event(event)
            result["events"].append(formatted)

        result["count"] = len(result["events"])
        result["success"] = True
        logger.success(f"Completed. {result['count']} event(s) returned")

        return result

    except FileNotFoundError as e:
        result["error"] = str(e)
        logger.exception("Credentials file not found")
        return result
    except HttpError as e:
        result["error"] = f"Calendar API error: {e}"
        logger.exception(f"Calendar API error: {e}")
        return result
    except Exception as e:
        result["error"] = f"Unexpected error: {e}"
        logger.exception(f"Unexpected error: {e}")
        return result


def fetch_upcoming_events(keyword: str = "default", days: int = 2, max_results: int = 20) -> dict[str, Any]:
    """Convenience function: fetch events from now through the next N days.

    This is the main function used by the summarization pipeline.
    """
    now = now_ist()
    time_min = now.isoformat()
    time_max = (now + timedelta(days=days)).isoformat()

    return fetch_events(
        keyword=keyword,
        time_min=time_min,
        time_max=time_max,
        max_results=max_results,
        single_events=True,
        order_by="startTime",
    )


def has_valid_token(keyword: str) -> bool:
    """Check if user has a valid OAuth token file."""
    token_path = get_token_path(keyword)
    return token_path.exists()


if __name__ == "__main__":
    import sys

    if len(sys.argv) > 1:
        command = sys.argv[1]

        if command == "check":
            from modules.fetch_emails import load_users
            users = load_users()
            print(f"Checking calendar tokens for {len(users)} user(s):")
            for user in users:
                kw = user.get("keyword", "default")
                name = user.get("name", "Unknown")
                if has_valid_token(kw):
                    print(f"  ✓ {name} ({kw}): token exists")
                else:
                    print(f"  ✗ {name} ({kw}): token MISSING")

        elif command == "fetch":
            keyword = sys.argv[2] if len(sys.argv) > 2 else "default"
            days = int(sys.argv[3]) if len(sys.argv) > 3 else 2
            print(f"Fetching events for '{keyword}' (next {days} days)...")
            result = fetch_upcoming_events(keyword=keyword, days=days)
            if result["success"]:
                print(f"Found {result['count']} event(s):")
                for ev in result["events"]:
                    all_day = " (all-day)" if ev["is_all_day"] else ""
                    print(f"  [{ev['start']} → {ev['end']}]{all_day} {ev['summary']}")
            else:
                print(f"Error: {result['error']}")

        else:
            print("Usage:")
            print("  python -m modules.fetch_calendar check     # Check token status")
            print("  python -m modules.fetch_calendar fetch [keyword] [days]  # Fetch events")
    else:
        print("Usage:")
        print("  python -m modules.fetch_calendar check     # Check token status")
        print("  python -m modules.fetch_calendar fetch [keyword] [days]  # Fetch events")
