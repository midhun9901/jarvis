"""
plugins/gmail_agent.py — Gmail API integration for JARVIS

Prerequisites:
  1. pip install google-auth google-auth-oauthlib google-auth-httplib2 google-api-python-client
  2. Place credentials.json in the jarvis/ root (downloaded from Google Cloud Console)
  3. On first run, a browser window opens for OAuth — complete it once, token.json is saved

Scopes used:
  - gmail.readonly  (read messages)
  - gmail.send      (send replies)
"""

import base64
import html
import re
from email.mime.text import MIMEText
from pathlib import Path

from google.auth.transport.requests import Request
from google.auth.exceptions import RefreshError
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

# Unified scopes shared with calendar_agent — both write the same token.json,
# so they must always request the same scope set or they 403 each other.
SCOPES = [
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/gmail.send",
    "https://www.googleapis.com/auth/calendar",
]

_ROOT = Path(__file__).resolve().parents[2] if Path(__file__).resolve().parents[1].name == "backend" else Path(__file__).resolve().parent.parent
_CONFIG_DIR = _ROOT / "config"
CREDS_FILE = _CONFIG_DIR / "credentials.json"
TOKEN_FILE  = _CONFIG_DIR / "token.json"


class GmailAuthError(RuntimeError):
    pass


def _run_oauth_flow() -> Credentials:
    flow = InstalledAppFlow.from_client_secrets_file(str(CREDS_FILE), SCOPES)
    creds = flow.run_local_server(port=0)
    TOKEN_FILE.write_text(creds.to_json(), encoding="utf-8")
    return creds


def get_credentials() -> Credentials:
    """Return valid Google credentials, refreshing or re-running OAuth as needed.

    Shared by gmail_agent and calendar_agent so there is exactly one token flow."""
    if not CREDS_FILE.exists():
        raise FileNotFoundError(
            f"credentials.json not found at {CREDS_FILE}. "
            "Download it from Google Cloud Console → APIs & Services → Credentials."
        )

    creds = None
    if TOKEN_FILE.exists():
        try:
            creds = Credentials.from_authorized_user_file(str(TOKEN_FILE), SCOPES)
        except Exception:
            TOKEN_FILE.unlink(missing_ok=True)
            creds = None

    # Token granted with fewer scopes than we now need → force a fresh consent flow
    if creds and not set(SCOPES).issubset(set(creds.scopes or [])):
        creds = None

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            try:
                creds.refresh(Request())
                TOKEN_FILE.write_text(creds.to_json(), encoding="utf-8")
            except RefreshError as e:
                TOKEN_FILE.unlink(missing_ok=True)
                if "invalid_grant" in str(e).lower():
                    creds = _run_oauth_flow()
                else:
                    raise
        else:
            creds = _run_oauth_flow()

    return creds


def _get_service():
    """Return an authenticated Gmail API service."""
    return build("gmail", "v1", credentials=get_credentials())


def _clean(text: str) -> str:
    """Decode HTML entities and strip leftover tags."""
    text = html.unescape(text)
    text = re.sub(r"<[^>]+>", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def _headers_dict(payload: dict) -> dict:
    return {h["name"]: h["value"] for h in payload.get("headers", [])}


def _extract_body(payload: dict) -> str:
    """Walk MIME parts and return plain-text body, up to 4000 chars."""
    def _walk(part):
        if part.get("mimeType") == "text/plain":
            data = part.get("body", {}).get("data", "")
            if data:
                return base64.urlsafe_b64decode(data).decode("utf-8", errors="replace")
        for sub in part.get("parts", []):
            result = _walk(sub)
            if result:
                return result
        return ""

    body = _walk(payload)
    # Collapse excessive whitespace
    body = _clean(body)
    body = re.sub(r"\n{3,}", "\n\n", body).strip()
    return body[:4000]


# ── Public API ──────────────────────────────────────────────────────────────────

def get_unread_mails(max_results: int = 10) -> list[dict]:
    """Return list of unread inbox messages: {id, sender, subject, snippet, date}."""
    service = _get_service()
    resp = service.users().messages().list(
        userId="me", labelIds=["INBOX", "UNREAD"], maxResults=max_results
    ).execute()

    mails = []
    for msg in resp.get("messages", []):
        m = service.users().messages().get(
            userId="me", id=msg["id"], format="metadata",
            metadataHeaders=["From", "Subject", "Date"],
        ).execute()
        h = _headers_dict(m["payload"])
        mails.append({
            "id": msg["id"],
            "sender":  h.get("From", ""),
            "subject": h.get("Subject", "(no subject)"),
            "snippet": _clean(m.get("snippet", "")),
            "date":    h.get("Date", ""),
            "timestamp": int(m.get("internalDate", "0") or 0),
            "unread": "UNREAD" in m.get("labelIds", []),
        })
    return sorted(mails, key=lambda mail: mail.get("timestamp", 0), reverse=True)


def get_recent_mails(max_results: int = 10) -> list[dict]:
    """Return latest inbox messages, read or unread: {id, sender, subject, snippet, date}."""
    service = _get_service()
    resp = service.users().messages().list(
        userId="me", q="in:inbox", maxResults=max_results
    ).execute()

    mails = []
    for msg in resp.get("messages", []):
        m = service.users().messages().get(
            userId="me", id=msg["id"], format="metadata",
            metadataHeaders=["From", "Subject", "Date"],
        ).execute()
        h = _headers_dict(m["payload"])
        mails.append({
            "id": msg["id"],
            "sender":  h.get("From", ""),
            "subject": h.get("Subject", "(no subject)"),
            "snippet": _clean(m.get("snippet", "")),
            "date":    h.get("Date", ""),
            "timestamp": int(m.get("internalDate", "0") or 0),
            "unread": "UNREAD" in m.get("labelIds", []),
        })
    return sorted(mails, key=lambda mail: mail.get("timestamp", 0), reverse=True)


def get_important_mails(max_results: int = 10) -> list[dict]:
    """Return relevant inbox messages while excluding obvious promo/social noise."""
    service = _get_service()
    query = (
        "in:inbox "
        "-category:promotions -category:social -category:forums "
        "-from:(no-reply OR noreply) "
        "-subject:(sale OR offer OR premium OR deal OR discount OR newsletter)"
    )
    resp = service.users().messages().list(
        userId="me", q=query, maxResults=max_results
    ).execute()

    mails = []
    for msg in resp.get("messages", []):
        m = service.users().messages().get(
            userId="me", id=msg["id"], format="metadata",
            metadataHeaders=["From", "Subject", "Date"],
        ).execute()
        h = _headers_dict(m["payload"])
        mails.append({
            "id": msg["id"],
            "sender":  h.get("From", ""),
            "subject": h.get("Subject", "(no subject)"),
            "snippet": _clean(m.get("snippet", "")),
            "date":    h.get("Date", ""),
            "timestamp": int(m.get("internalDate", "0") or 0),
            "unread": "UNREAD" in m.get("labelIds", []),
        })
    return sorted(mails, key=lambda mail: mail.get("timestamp", 0), reverse=True)


def get_mail_by_id(mail_id: str) -> dict:
    """Return full mail: {id, sender, subject, date, body}."""
    service = _get_service()
    m = service.users().messages().get(
        userId="me", id=mail_id.strip(), format="full"
    ).execute()
    h = _headers_dict(m["payload"])
    return {
        "id":      mail_id,
        "sender":  h.get("From", ""),
        "subject": h.get("Subject", "(no subject)"),
        "date":    h.get("Date", ""),
        "body":    _extract_body(m["payload"]),
        "thread_id": m.get("threadId", mail_id),
    }


def search_mails(query: str, max_results: int = 10) -> list[dict]:
    """Search Gmail with a query string. Returns same shape as get_unread_mails."""
    service = _get_service()
    resp = service.users().messages().list(
        userId="me", q=query.strip(), maxResults=max_results
    ).execute()

    mails = []
    for msg in resp.get("messages", []):
        m = service.users().messages().get(
            userId="me", id=msg["id"], format="metadata",
            metadataHeaders=["From", "Subject", "Date"],
        ).execute()
        h = _headers_dict(m["payload"])
        mails.append({
            "id":      msg["id"],
            "sender":  h.get("From", ""),
            "subject": h.get("Subject", "(no subject)"),
            "snippet": _clean(m.get("snippet", "")),
            "date":    h.get("Date", ""),
            "timestamp": int(m.get("internalDate", "0") or 0),
            "unread": "UNREAD" in m.get("labelIds", []),
        })
    return sorted(mails, key=lambda mail: mail.get("timestamp", 0), reverse=True)


def send_reply(mail_id: str, body: str) -> str:
    """Send a reply to the given mail. Returns a confirmation string."""
    service = _get_service()

    # Fetch original headers to build a proper reply
    orig = service.users().messages().get(
        userId="me", id=mail_id.strip(), format="metadata",
        metadataHeaders=["From", "Subject", "Message-ID", "References", "To"],
    ).execute()
    h = _headers_dict(orig["payload"])

    to      = h.get("From", "")
    subject = h.get("Subject", "")
    if not subject.lower().startswith("re:"):
        subject = f"Re: {subject}"
    msg_id  = h.get("Message-ID", "")
    refs    = h.get("References", "")

    mime = MIMEText(body, "plain", "utf-8")
    mime["To"]      = to
    mime["Subject"] = subject
    if msg_id:
        mime["In-Reply-To"] = msg_id
        mime["References"]  = f"{refs} {msg_id}".strip()

    raw = base64.urlsafe_b64encode(mime.as_bytes()).decode()
    service.users().messages().send(
        userId="me",
        body={"raw": raw, "threadId": orig.get("threadId", "")},
    ).execute()

    return f"Reply sent to {to}."
