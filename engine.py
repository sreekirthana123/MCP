"""
engine.py — Gmail Inbox Thread Fetcher

Dual-path architecture:
  Path 1 — MCP Execution Plan: returns a structured plan for the Gmail MCP server
  Path 2 — Direct Standalone:   uses the Google Gmail API directly (when credentials exist)

Returns a list of dicts with keys: thread_id, sender, subject, snippet, date
"""

import socket
_original_getaddrinfo = socket.getaddrinfo


def ipv4_only_getaddrinfo(host, port, family=0, type=0, proto=0, flags=0):
    return _original_getaddrinfo(host, port, socket.AF_INET, type, proto, flags)


socket.getaddrinfo = ipv4_only_getaddrinfo

import os
from datetime import datetime, timezone
from email.utils import getaddresses, parsedate_to_datetime
from typing import Any
import json
import sys

here = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(here, "Gmail-MCP-Server"))
from triage import triage_inbox, format_digest

# ── Constants ─────────────────────────────────────────────────────────────────

DEFAULT_MAX_RESULTS = 20
GMAIL_USER_ID = "me"

# ── Header extraction utilities ───────────────────────────────────────────────


def _extract_sender(headers: list[dict]) -> str:
    """Extract the From header value from a list of Gmail API headers."""
    for h in headers:
        if h.get("name", "").lower() == "from":
            return h.get("value", "")
    return ""


def _extract_subject(headers: list[dict]) -> str:
    """Extract the Subject header value from a list of Gmail API headers."""
    for h in headers:
        if h.get("name", "").lower() == "subject":
            return h.get("value", "")
    return ""


def _extract_date(headers: list[dict]) -> str:
    """Extract and normalize the Date header to an ISO-8601 UTC string."""
    for h in headers:
        if h.get("name", "").lower() == "date":
            raw = h.get("value", "")
            try:
                dt = parsedate_to_datetime(raw)
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
                return dt.isoformat()
            except Exception:
                return raw
    return ""


def normalize_message(message: dict, thread_id: str) -> dict:
    """
    Transform a raw Gmail API message dict into a clean thread dict.

    Parameters
    ----------
    message : dict
        A Gmail API message resource (from users.messages.get).
    thread_id : str
        The Gmail thread ID this message belongs to.

    Returns
    -------
    dict with keys: thread_id, sender, subject, snippet, date
    """
    payload = message.get("payload", {})
    headers = payload.get("headers", [])
    snippet = message.get("snippet", "")
    return {
        "thread_id": thread_id,
        "sender": _extract_sender(headers),
        "subject": _extract_subject(headers),
        "snippet": snippet,
        "date": _extract_date(headers),
    }


# ── Path 1: MCP Execution Plan ───────────────────────────────────────────────


def build_mcp_plan(max_results: int = DEFAULT_MAX_RESULTS) -> dict:
    """
    Build a structured execution plan for the Gmail MCP server.

    The plan contains two steps:
      1. search_emails  — fetch message IDs from the inbox
      2. read_email     — fetch full details for each message

    Returns a dict that can be consumed by an MCP orchestrator.
    """
    return {
        "tool": "gmail",
        "steps": [
            {
                "name": "search_emails",
                "arguments": {
                    "query": "in:inbox",
                    "maxResults": max_results,
                },
                "args_for_each_message": False,
            },
            {
                "name": "read_email",
                "arguments": {},
                "args_for_each_message": True,
            },
        ],
    }


def materialize_threads(messages: list[dict]) -> list[dict]:
    """
    Convert raw Gmail API message dicts into a deduplicated list of
    normalized thread dicts.

    Each dict contains: thread_id, sender, subject, snippet, date
    """
    threads: list[dict] = []
    seen_threads: set[str] = set()

    for msg in messages:
        thread_id = msg.get("threadId", "")
        if not thread_id or thread_id in seen_threads:
            continue
        seen_threads.add(thread_id)

        threads.append(normalize_message(msg, thread_id=thread_id))

    return threads


# ── Path 2: Direct Standalone Fallback (Google API client) ────────────────────


def _build_gmail_service():
    """
    Build and return an authenticated Gmail API service object.

    Uses OAuth 2.0 credentials stored in token.json (refreshed automatically).
    Falls back to the OAuth flow if no valid token exists.
    """
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials
    from google_auth_oauthlib.flow import InstalledAppFlow
    from googleapiclient.discovery import build

    creds_path = os.path.join(here, "credentials.json")
    token_path = os.path.join(here, "token.json")

    creds = None
    if os.path.exists(token_path):
        try:
            creds = Credentials.from_authorized_user_file(token_path)
        except ValueError:
            creds = None

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())  # type: ignore[union-attr]
        else:
            flow = InstalledAppFlow.from_client_secrets_file(
                creds_path,
                ["https://www.googleapis.com/auth/gmail.readonly"],
            )
            creds = flow.run_local_server(port=0)
        with open(token_path, "w") as f:
            f.write(creds.to_json())

    return build("gmail", "v1", credentials=creds)


def fetch_threads_direct(max_results: int = DEFAULT_MAX_RESULTS) -> list[dict]:
    """
    Fetch inbox threads directly via the Google Gmail REST API.

    This is the standalone fallback path that does not require the MCP server.
    """
    service = _build_gmail_service()

    response = (
        service.users()
        .messages()
        .list(userId=GMAIL_USER_ID, maxResults=max_results, q="in:inbox")
        .execute()
    )

    messages_meta = response.get("messages", [])
    raw_messages: list[dict] = []

    for msg_meta in messages_meta:
        msg_id = msg_meta["id"]
        msg = (
            service.users()
            .messages()
            .get(
                userId=GMAIL_USER_ID,
                id=msg_id,
                format="metadata",
                metadataHeaders=["From", "Subject", "Date"],
            )
            .execute()
        )
        raw_messages.append(msg)

    return materialize_threads(raw_messages)


# ── Unified entry point ───────────────────────────────────────────────────────


def fetch_threads(
    max_results: int = DEFAULT_MAX_RESULTS,
    use_mcp: bool | None = None,
) -> list[dict] | dict:
    """
    Fetch the most recent inbox threads.

    Auto-routing logic:
      - If use_mcp is True  → return the MCP execution plan (no API call).
      - If use_mcp is False → use the direct Google Gmail API.
      - If use_mcp is None  → check for local credential files:
          * If credentials.json exists → use direct API.
          * If missing or an error occurs → gracefully return the MCP plan.

    Parameters
    ----------
    max_results : int
        Maximum number of threads to return (default 20).
    use_mcp : bool or None
        Whether to force MCP plan mode (default None = auto-detect).

    Returns
    -------
    list[dict] | dict
        If direct path was used: a list of thread dicts.
        If MCP path was chosen: the MCP execution plan dict.
    """
    # ── Forced MCP plan mode ────────────────────────────────────────────
    if use_mcp is True:
        return build_mcp_plan(max_results)

    # ── Forced direct mode ──────────────────────────────────────────────
    if use_mcp is False:
        return fetch_threads_direct(max_results)

    # ── Auto-detect (use_mcp is None) ───────────────────────────────────
    creds_path = os.path.join(here, "credentials.json")
    if not os.path.exists(creds_path):
        return build_mcp_plan(max_results)

    try:
        return fetch_threads_direct(max_results)
    except FileNotFoundError:
        return build_mcp_plan(max_results)
    except Exception:
        import traceback
        print("\n" + "="*20 + " FULL TRACEBACK " + "="*20 + "\n")
        traceback.print_exc()
        print("\n" + "="*56 + "\n")
        return build_mcp_plan(max_results)


# ── Pipeline ──────────────────────────────────────────────────────────────────


def run_pipeline(max_results: int = DEFAULT_MAX_RESULTS) -> None:
    """
    Fetch `max_results` inbox threads from Gmail and classify each one
    via `triage_inbox()`. Returns the prioritized list of triaged threads.
    """
    threads = fetch_threads(max_results=max_results)
    if not isinstance(threads, list):
        # MCP-plan or error dict from auto mode -> nothing to triage.
        return

    format_digest(triage_inbox(threads))


# ── CLI entry point ───────────────────────────────────────────────────────────

if __name__ == "__main__":
    run_pipeline(2)
