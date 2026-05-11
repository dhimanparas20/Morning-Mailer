from __future__ import annotations

import base64
import json
import re
import unicodedata
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path
from typing import Any

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

from modules.logger import get_logger
from modules.generics import format_timestamp


SCOPES = ["https://www.googleapis.com/auth/gmail.readonly"]

BASE_DIR = Path("gauth")
TOKENS_DIR = BASE_DIR / "tokens"

CREDENTIALS_FILE = BASE_DIR / "client_secret.json"

logger = get_logger("[fetch_gmail]", show_time=False)


def get_credentials_path() -> Path:
    if CREDENTIALS_FILE.exists():
        return CREDENTIALS_FILE
    raise FileNotFoundError(f"Credentials file not found: {CREDENTIALS_FILE}")


def get_token_path(keyword: str) -> Path:
    return TOKENS_DIR / f"token_{keyword}.json"


def clean_text(text: str) -> str:
    if not text:
        return ""
    text = unicodedata.normalize("NFKC", text)
    text = re.sub(r"[\u200b-\u200f\u2028-\u202f\ufeff\u00a0]+", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def get_gmail_service(keyword: str = "default") -> Any:
    try:
        creds = None

        token_path = get_token_path(keyword)
        creds_path = get_credentials_path()

        if token_path.exists():
            logger.info(f"Loading credentials from {token_path}")
            creds = Credentials.from_authorized_user_file(str(token_path), SCOPES)

        if creds and creds.valid:
            logger.debug("Credentials are valid, reusing existing token")
            return build("gmail", "v1", credentials=creds)

        if creds and creds.expired and creds.refresh_token:
            logger.info("Access token expired, attempting refresh...")
            try:
                creds.refresh(Request())
                token_path.write_text(creds.to_json(), encoding="utf-8")
                logger.success("Token refreshed and saved successfully")
                return build("gmail", "v1", credentials=creds)
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

        return build("gmail", "v1", credentials=creds)

    except FileNotFoundError:
        logger.exception("Credentials file missing")
        raise
    except Exception as e:
        logger.exception(f"Failed to build Gmail service: {e}")
        raise


def get_header(headers: list[dict[str, str]], name: str) -> str:
    for header in headers:
        if header.get("name", "").lower() == name.lower():
            return header.get("value", "")
    return ""


def decode_body(data: str) -> str:
    try:
        decoded_bytes = base64.urlsafe_b64decode(data + "===")
        return decoded_bytes.decode("utf-8", errors="replace")
    except Exception:
        return ""


def extract_plain_text(payload: dict[str, Any]) -> str:
    if payload.get("mimeType") == "text/plain":
        body_data = payload.get("body", {}).get("data")
        if body_data:
            return decode_body(body_data)

    for part in payload.get("parts", []):
        text = extract_plain_text(part)
        if text:
            return text

    return ""


def parse_date(date_str: str) -> datetime | None:
    if not date_str:
        return None
    formats = [
        "%a, %d %b %Y %H:%M:%S %z",
        "%d %b %Y %H:%M:%S %z",
        "%a, %d %b %Y %H:%M:%S %Z",
        "%d %b %Y %H:%M:%S %Z",
    ]
    for fmt in formats:
        try:
            return datetime.strptime(date_str.strip(), fmt).replace(tzinfo=None)
        except ValueError:
            pass
    return None


def fetch_emails(
    keyword: str = "default",
    max_results: int = 10,
    query: str | None = None,
    sender: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    subject_contains: str | None = None,
    has_attachments: bool | None = None,
    unread_only: bool = False,
    sort_by: str = "date",
    sort_order: str = "desc",
) -> dict[str, Any]:
    result = {
        "success": False,
        "error": None,
        "count": 0,
        "filters_applied": {},
        "emails": [],
    }

    try:
        int_logger = get_logger(f"[fetch_gmail:{keyword}]", show_time=False)
        service = get_gmail_service(keyword)

        gmail_query_parts = [query] if query else []
        if sender:
            gmail_query_parts.append(f"from:{sender}")
        if unread_only:
            gmail_query_parts.append("is:unread")
        if has_attachments:
            gmail_query_parts.append("has:attachment")

        combined_query = " ".join(filter(None, gmail_query_parts))
        int_logger.info(f"Fetching up to {max_results} emails" + (f" | query: {combined_query}" if combined_query else ""))

        response = service.users().messages().list(
            userId="me",
            maxResults=max_results,
            q=combined_query,
        ).execute()

        messages = response.get("messages", [])

        if not messages:
            int_logger.warning("No emails found matching the query")
            result["success"] = True
            result["count"] = 0
            result["filters_applied"] = {
                "query": combined_query or None,
                "sender": sender,
                "date_from": date_from,
                "date_to": date_to,
                "subject_contains": subject_contains,
                "has_attachments": has_attachments,
                "unread_only": unread_only,
                "sort_by": sort_by,
                "sort_order": sort_order,
            }
            return result

        int_logger.info(f"Retrieved {len(messages)} email(s), fetching details in parallel...")

        def fetch_single_email(msg_ref: dict) -> dict | None:
            try:
                thread_service = get_gmail_service(keyword)
                msg = thread_service.users().messages().get(
                    userId="me",
                    id=msg_ref["id"],
                    format="full",
                ).execute()

                payload = msg.get("payload", {})
                headers = payload.get("headers", [])

                raw_date = get_header(headers, "Date")
                parsed_date = parse_date(raw_date)

                return {
                    "id": msg.get("id", ""),
                    "thread_id": msg.get("threadId", ""),
                    "from": get_header(headers, "From"),
                    "to": get_header(headers, "To"),
                    "subject": get_header(headers, "Subject"),
                    "date": raw_date,
                    "date_parsed": parsed_date.isoformat() if parsed_date else None,
                    "snippet": clean_text(msg.get("snippet", "")),
                    "body": clean_text(extract_plain_text(payload)),
                    "label_ids": msg.get("labelIds", []),
                    "has_attachments": any(
                        part.get("filename")
                        for part in payload.get("parts", [])
                        if part.get("filename")
                    ),
                }
            except HttpError as e:
                int_logger.error(f"HTTP error fetching email {msg_ref['id']}: {e}")
                return None
            except Exception as e:
                int_logger.error(f"Unexpected error processing email {msg_ref['id']}: {e}")
                return None

        max_workers = min(5, len(messages))
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = {executor.submit(fetch_single_email, msg): msg for msg in messages}
            for future in as_completed(futures):
                email_data = future.result()
                if email_data:
                    result["emails"].append(email_data)
                    sender_match = re.match(r"[^<]*<([^>]+)>", email_data["from"])
                    sender = sender_match.group(1) if sender_match else email_data["from"]
                    logger.debug(f"Processed: [{sender}] {email_data['subject'][:50]}")

        if date_from:
            date_from_ts = datetime.fromisoformat(date_from).timestamp()
            date_from_hr = format_timestamp(date_from_ts)
            before = len(result["emails"])
            result["emails"] = [
                e for e in result["emails"]
                if e["date_parsed"] and datetime.fromisoformat(e["date_parsed"]).timestamp() >= date_from_ts
            ]
            int_logger.info(f"Filtered by date_from={date_from_hr}: {before} -> {len(result['emails'])}")

        if date_to:
            date_to_ts = datetime.fromisoformat(date_to).timestamp()
            date_to_hr = format_timestamp(date_to_ts)
            before = len(result["emails"])
            result["emails"] = [
                e for e in result["emails"]
                if e["date_parsed"] and datetime.fromisoformat(e["date_parsed"]).timestamp() <= date_to_ts
            ]
            int_logger.info(f"Filtered by date_to={date_to_hr}: {before} -> {len(result['emails'])}")

        if subject_contains:
            before = len(result["emails"])
            subject_lower = subject_contains.lower()
            result["emails"] = [e for e in result["emails"] if subject_lower in e["subject"].lower()]
            int_logger.info(f"Filtered by subject containing '{subject_contains}': {before} -> {len(result['emails'])}")

        sort_valid = {"date", "from_addr", "subject"}
        if sort_by not in sort_valid:
            sort_by = "date"
        reverse = sort_order == "desc"

        if sort_by == "date":
            result["emails"].sort(key=lambda e: e["date_parsed"] or "", reverse=reverse)
        elif sort_by == "from_addr":
            result["emails"].sort(key=lambda e: e["from"].lower(), reverse=reverse)
        elif sort_by == "subject":
            result["emails"].sort(key=lambda e: e["subject"].lower(), reverse=reverse)

        result["count"] = len(result["emails"])
        result["success"] = True
        result["filters_applied"] = {
            "query": combined_query or None,
            "sender": sender,
            "date_from": date_from,
            "date_to": date_to,
            "subject_contains": subject_contains,
            "has_attachments": has_attachments,
            "unread_only": unread_only,
            "sort_by": sort_by,
            "sort_order": sort_order,
        }
        int_logger.success(f"Completed. {result['count']} email(s) returned")

        return result

    except FileNotFoundError as e:
        result["error"] = str(e)
        logger.exception("Credentials file not found")
        return result
    except HttpError as e:
        result["error"] = f"Gmail API error: {e}"
        logger.exception(f"Gmail API error: {e}")
        return result
    except Exception as e:
            result["error"] = f"Unexpected error: {e}"
            logger.exception(f"Unexpected error: {e}")
            return result


def load_users() -> list[dict[str, str]]:
    users_file = Path("users.json")
    if not users_file.exists():
        logger.warning("users.json not found, using default single user")
        return [{"name": "Default", "email": "unknown", "keyword": "default"}]

    with open(users_file, "r", encoding="utf-8") as f:
        users = json.load(f)

    if not users:
        logger.warning("No users found in users.json")
        return []

    return users


if __name__ == "__main__":
    import json
    import sys

    if len(sys.argv) > 1:
        command = sys.argv[1]

        if command == "setup" and len(sys.argv) > 2:
            keyword = sys.argv[2]
            print(f"Running OAuth setup for keyword: {keyword}")
            get_gmail_service(keyword)
        elif command == "users":
            users = load_users()
            print(f"Loaded {len(users)} user(s):")
            for user in users:
                active_status = "active" if user.get("active", True) else "inactive"
                print(f"  - {user.get('name', 'N/A')}: {user.get('email', 'N/A')} (keyword: {user.get('keyword', 'default')}, {active_status})")
        elif command == "check":
            users = load_users()
            print(f"Checking tokens for {len(users)} user(s):")
            for user in users:
                keyword = user.get("keyword", "default")
                name = user.get("name", "Unknown")
                try:
                    token_path = get_token_path(keyword)
                    if token_path.exists():
                        print(f"  ✓ {name} ({keyword}): token exists")
                    else:
                        print(f"  ✗ {name} ({keyword}): token MISSING - run 'python -m modules.fetch_emails setup {keyword}'")
                except FileNotFoundError:
                    print(f"  ✗ {name} ({keyword}): token MISSING - run 'python -m modules.fetch_emails setup {keyword}'")
        else:
            print("Usage:")
            print("  python -m modules.fetch_emails setup <keyword>   # Run OAuth for a specific user")
            print("  python -m modules.fetch_emails users            # List all users")
            print("  python -m modules.fetch_emails check            # Check which users have tokens")
    else:
        users = load_users()
        print(f"Loaded {len(users)} user(s):")
        for user in users:
            print(f"  - {user.get('name', 'N/A')}: {user.get('email', 'N/A')} (keyword: {user.get('keyword', 'default')})")

        if users:
            keyword = users[0].get("keyword", "default")
            print(f"\nFetching emails for user: {keyword}")
            result = fetch_emails(keyword=keyword, max_results=10, query="in:inbox")
            print(json.dumps(result, indent=2, ensure_ascii=False))