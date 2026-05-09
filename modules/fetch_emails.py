from __future__ import annotations

import base64
import re
import unicodedata
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

CREDENTIALS_FILE = Path("gauth/client_secret.json")
TOKEN_FILE = Path("gauth/token.json")

logger = get_logger("[fetch_gmail]", show_time=True)


def clean_text(text: str) -> str:
    if not text:
        return ""
    text = unicodedata.normalize("NFKC", text)
    text = re.sub(r"[\u200b-\u200f\u2028-\u202f\ufeff\u00a0]+", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def get_gmail_service() -> Any:
    try:
        creds = None

        if TOKEN_FILE.exists():
            logger.info(f"Loading credentials from {TOKEN_FILE}")
            creds = Credentials.from_authorized_user_file(str(TOKEN_FILE), SCOPES)

        if creds and creds.valid:
            logger.debug("Credentials are valid, reusing existing token")
            return build("gmail", "v1", credentials=creds)

        if creds and creds.expired and creds.refresh_token:
            logger.info("Access token expired, attempting refresh...")
            try:
                creds.refresh(Request())
                TOKEN_FILE.write_text(creds.to_json(), encoding="utf-8")
                logger.success("Token refreshed and saved successfully")
                return build("gmail", "v1", credentials=creds)
            except Exception as refresh_error:
                logger.error(f"Token refresh failed: {refresh_error}")
                raise

        if not CREDENTIALS_FILE.exists():
            raise FileNotFoundError(
                f"{CREDENTIALS_FILE} not found. Download OAuth Desktop credentials "
                "from Google Cloud Console and place it beside this script."
            )

        logger.info("No valid credentials found, initiating OAuth flow...")
        
        try:
            flow = InstalledAppFlow.from_client_secrets_file(str(CREDENTIALS_FILE), SCOPES)
            creds = flow.run_local_server(port=0)
        except Exception as browser_error:
            # No browser available - use manual OAuth flow
            logger.warning("=" * 60)
            logger.warning("No browser detected. Using manual OAuth flow.")
            logger.warning("Follow these steps:")
            logger.warning("")
            
            # Re-create flow to get authorization URL
            flow = InstalledAppFlow.from_client_secrets_file(str(CREDENTIALS_FILE), SCOPES)
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
            
            # This works in IPython but not in Huey worker
            code = input("Enter the authorization code: ").strip()
            
            # Fetch token using the code
            flow.fetch_token(code=code)
            creds = flow.credentials
        
        TOKEN_FILE.write_text(creds.to_json(), encoding="utf-8")
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
        service = get_gmail_service()

        gmail_query_parts = [query] if query else []
        if sender:
            gmail_query_parts.append(f"from:{sender}")
        if unread_only:
            gmail_query_parts.append("is:unread")
        if has_attachments:
            gmail_query_parts.append("has:attachment")

        combined_query = " ".join(filter(None, gmail_query_parts))
        logger.info(f"Fetching up to {max_results} emails" + (f" | query: {combined_query}" if combined_query else ""))

        response = service.users().messages().list(
            userId="me",
            maxResults=max_results,
            q=combined_query,
        ).execute()

        messages = response.get("messages", [])

        if not messages:
            logger.warning("No emails found matching the query")
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

        logger.info(f"Retrieved {len(messages)} email(s), fetching details...")

        for msg_ref in messages:
            try:
                msg = service.users().messages().get(
                    userId="me",
                    id=msg_ref["id"],
                    format="full",
                ).execute()

                payload = msg.get("payload", {})
                headers = payload.get("headers", [])

                raw_date = get_header(headers, "Date")
                parsed_date = parse_date(raw_date)

                email_data = {
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
                result["emails"].append(email_data)
                sender_match = re.match(r"[^<]*<([^>]+)>", email_data["from"])
                sender = sender_match.group(1) if sender_match else email_data["from"]
                logger.debug(f"Processed: [{sender}] {email_data['subject'][:50]}")

            except HttpError as e:
                logger.error(f"HTTP error fetching email {msg_ref['id']}: {e}")
                continue
            except Exception as e:
                logger.error(f"Unexpected error processing email {msg_ref['id']}: {e}")
                continue

        if date_from:
            date_from_ts = datetime.fromisoformat(date_from).timestamp()
            date_from_hr = format_timestamp(date_from_ts)
            before = len(result["emails"])
            result["emails"] = [
                e for e in result["emails"]
                if e["date_parsed"] and datetime.fromisoformat(e["date_parsed"]).timestamp() >= date_from_ts
            ]
            logger.info(f"Filtered by date_from={date_from_hr}: {before} -> {len(result['emails'])}")

        if date_to:
            date_to_ts = datetime.fromisoformat(date_to).timestamp()
            date_to_hr = format_timestamp(date_to_ts)
            before = len(result["emails"])
            result["emails"] = [
                e for e in result["emails"]
                if e["date_parsed"] and datetime.fromisoformat(e["date_parsed"]).timestamp() <= date_to_ts
            ]
            logger.info(f"Filtered by date_to={date_to_hr}: {before} -> {len(result['emails'])}")

        if subject_contains:
            before = len(result["emails"])
            subject_lower = subject_contains.lower()
            result["emails"] = [e for e in result["emails"] if subject_lower in e["subject"].lower()]
            logger.info(f"Filtered by subject containing '{subject_contains}': {before} -> {len(result['emails'])}")

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
        logger.success(f"Completed. {result['count']} email(s) returned")

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


if __name__ == "__main__":
    import json
    result = fetch_emails(max_results=10, query="in:inbox")
    print(json.dumps(result, indent=2, ensure_ascii=False))