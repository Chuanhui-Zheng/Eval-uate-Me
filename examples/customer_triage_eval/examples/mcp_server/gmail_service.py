"""Gmail API helpers for the MCP server.

Thin wrapper over the Gmail REST API: authenticate once (OAuth installed-app
flow), then list unread mail, read a message body, send a threaded reply, and
mark a message read. The MCP server in `server.py` exposes these as tools.

Auth files (both git-ignored — never commit them):
    credentials.json  OAuth *client* secret you download from Google Cloud.
    token.json        Your *user* token, written on first run after consent.

Paths resolve next to this file by default, so the server works no matter what
working directory the MCP client launches it from. Override with the
GMAIL_CREDENTIALS_PATH / GMAIL_TOKEN_PATH env vars if you keep them elsewhere.
"""

from __future__ import annotations

import base64
import os
from email.message import EmailMessage

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

# modify = read + change labels (mark read); send = send the reply.
# If you previously consented to only readonly+modify, delete token.json and
# re-run so Google re-prompts for the send scope.
SCOPES = [
    "https://www.googleapis.com/auth/gmail.modify",
    "https://www.googleapis.com/auth/gmail.send",
]

_HERE = os.path.dirname(os.path.abspath(__file__))
_SERVICE = None  # lazy singleton so we authenticate once, not per tool call


def get_service():
    """Return an authenticated Gmail API service, running the consent flow once."""
    global _SERVICE
    if _SERVICE is not None:
        return _SERVICE

    creds_path = os.getenv("GMAIL_CREDENTIALS_PATH") or os.path.join(_HERE, "credentials.json")
    token_path = os.getenv("GMAIL_TOKEN_PATH") or os.path.join(_HERE, "token.json")

    creds = None
    if os.path.exists(token_path):
        creds = Credentials.from_authorized_user_file(token_path, SCOPES)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            if not os.path.exists(creds_path):
                raise FileNotFoundError(
                    f"Missing OAuth client secret at {creds_path}. Download it from "
                    "Google Cloud Console → APIs & Services → Credentials → OAuth "
                    "client ID (Desktop app), and save it as credentials.json."
                )
            flow = InstalledAppFlow.from_client_secrets_file(creds_path, SCOPES)
            creds = flow.run_local_server(port=0)
        with open(token_path, "w") as fh:
            fh.write(creds.to_json())

    _SERVICE = build("gmail", "v1", credentials=creds, cache_discovery=False)
    return _SERVICE


# ---- header + body parsing ---------------------------------------------------


def _header(headers: list[dict], name: str) -> str:
    """Case-insensitive lookup of a single header value."""
    name = name.lower()
    for h in headers:
        if h.get("name", "").lower() == name:
            return h.get("value", "")
    return ""


def _decode(data: str) -> str:
    return base64.urlsafe_b64decode(data).decode("utf-8", errors="replace")


def _extract_body(payload: dict) -> str:
    """Walk a (possibly multipart) payload and return the first text/plain body."""
    if payload.get("mimeType", "").startswith("text/plain"):
        data = payload.get("body", {}).get("data")
        if data:
            return _decode(data)
    for part in payload.get("parts") or []:
        text = _extract_body(part)
        if text:
            return text
    data = payload.get("body", {}).get("data")
    return _decode(data) if data else ""


# ---- operations --------------------------------------------------------------


def list_unread(service, max_results: int = 10) -> list[dict]:
    """Return unread inbox messages as [{id, thread_id, from, subject, snippet}]."""
    resp = (
        service.users()
        .messages()
        .list(userId="me", q="is:unread in:inbox", maxResults=max_results)
        .execute()
    )
    out = []
    for ref in resp.get("messages", []):
        msg = (
            service.users()
            .messages()
            .get(userId="me", id=ref["id"], format="metadata",
                 metadataHeaders=["From", "Subject"])
            .execute()
        )
        headers = msg.get("payload", {}).get("headers", [])
        out.append({
            "id": ref["id"],
            "thread_id": msg.get("threadId"),
            "from": _header(headers, "From"),
            "subject": _header(headers, "Subject"),
            "snippet": msg.get("snippet", ""),
        })
    return out


def get_message(service, message_id: str) -> dict:
    """Return the full sender, subject, plain-text body, and threading headers."""
    msg = service.users().messages().get(userId="me", id=message_id, format="full").execute()
    payload = msg.get("payload", {})
    headers = payload.get("headers", [])
    return {
        "id": message_id,
        "thread_id": msg.get("threadId"),
        "from": _header(headers, "From"),
        "subject": _header(headers, "Subject"),
        "message_id_header": _header(headers, "Message-ID"),
        "body": _extract_body(payload),
    }


def send_reply(service, message_id: str, body: str) -> dict:
    """Send a plain-text reply to `message_id`, kept in the original thread."""
    orig = get_message(service, message_id)

    subject = orig["subject"] or ""
    if not subject.lower().startswith("re:"):
        subject = f"Re: {subject}"

    reply = EmailMessage()
    reply["To"] = orig["from"]  # sender From is filled in by Gmail automatically
    reply["Subject"] = subject
    if orig["message_id_header"]:
        reply["In-Reply-To"] = orig["message_id_header"]
        reply["References"] = orig["message_id_header"]
    reply.set_content(body)

    raw = base64.urlsafe_b64encode(reply.as_bytes()).decode()
    sent = (
        service.users()
        .messages()
        .send(userId="me", body={"raw": raw, "threadId": orig["thread_id"]})
        .execute()
    )
    return {"sent_id": sent.get("id"), "thread_id": sent.get("threadId")}


def mark_as_read(service, message_id: str) -> dict:
    """Remove the UNREAD label so the message no longer shows as unread."""
    service.users().messages().modify(
        userId="me", id=message_id, body={"removeLabelIds": ["UNREAD"]}
    ).execute()
    return {"id": message_id, "status": "read"}
