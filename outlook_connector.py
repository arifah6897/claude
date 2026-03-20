"""
Outlook connector via Microsoft Graph API.

Setup (one-time):
1. Register an app in Azure Portal → App registrations
2. Add delegated permissions: Mail.Read, Mail.ReadWrite, offline_access
3. Copy your CLIENT_ID and TENANT_ID
4. Set environment variables (see .env.example) or pass directly

Environment variables:
    OUTLOOK_CLIENT_ID   - Azure app client ID
    OUTLOOK_TENANT_ID   - Azure tenant ID (or "common" for personal accounts)
    OUTLOOK_CLIENT_SECRET - Optional, for app-only auth (service accounts)
"""

import os
import json
import webbrowser
from pathlib import Path
from datetime import datetime, timezone
from typing import Optional

import msal
import requests

# ── Config ────────────────────────────────────────────────────────────────────

GRAPH_BASE = "https://graph.microsoft.com/v1.0"
SCOPES = ["Mail.Read", "Mail.ReadWrite", "offline_access"]
TOKEN_CACHE_FILE = Path.home() / ".outlook_token_cache.json"


def _build_msal_app(client_id: str, tenant_id: str) -> msal.PublicClientApplication:
    cache = msal.SerializableTokenCache()
    if TOKEN_CACHE_FILE.exists():
        cache.deserialize(TOKEN_CACHE_FILE.read_text())

    app = msal.PublicClientApplication(
        client_id=client_id,
        authority=f"https://login.microsoftonline.com/{tenant_id}",
        token_cache=cache,
    )
    return app, cache


def _save_cache(cache: msal.SerializableTokenCache) -> None:
    if cache.has_state_changed:
        TOKEN_CACHE_FILE.write_text(cache.serialize())


# ── Authentication ────────────────────────────────────────────────────────────

def authenticate(
    client_id: Optional[str] = None,
    tenant_id: Optional[str] = None,
) -> str:
    """
    Authenticate with Microsoft and return an access token.
    Uses device flow (opens browser) on first run; reuses cached token after.
    """
    client_id = client_id or os.environ["OUTLOOK_CLIENT_ID"]
    tenant_id = tenant_id or os.environ.get("OUTLOOK_TENANT_ID", "common")

    app, cache = _build_msal_app(client_id, tenant_id)

    # Try silent auth first (cached token)
    accounts = app.get_accounts()
    result = None
    if accounts:
        result = app.acquire_token_silent(SCOPES, account=accounts[0])

    # Fall back to interactive device code flow
    if not result:
        flow = app.initiate_device_flow(scopes=SCOPES)
        if "user_code" not in flow:
            raise RuntimeError(f"Failed to start device flow: {flow}")

        print("\n" + "=" * 60)
        print("OUTLOOK AUTHENTICATION REQUIRED")
        print("=" * 60)
        print(flow["message"])
        print("=" * 60 + "\n")
        webbrowser.open(flow["verification_uri"])

        result = app.acquire_token_by_device_flow(flow)

    _save_cache(cache)

    if "access_token" not in result:
        raise RuntimeError(f"Authentication failed: {result.get('error_description')}")

    return result["access_token"]


# ── Email fetching ────────────────────────────────────────────────────────────

def _headers(token: str) -> dict:
    return {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}


def fetch_emails(
    token: str,
    subject_filter: Optional[str] = None,
    sender_filter: Optional[str] = None,
    since_date: Optional[str] = None,
    folder: str = "inbox",
    max_results: int = 50,
) -> list[dict]:
    """
    Fetch emails from Outlook.

    Args:
        token:          Access token from authenticate()
        subject_filter: Filter emails whose subject contains this string
        sender_filter:  Filter by sender email address
        since_date:     ISO date string, e.g. "2025-12-01"
        folder:         "inbox", "sentitems", or a folder ID
        max_results:    Max emails to return

    Returns:
        List of email dicts with keys: id, subject, sender, received, body, body_preview
    """
    filters = []

    if subject_filter:
        filters.append(f"contains(subject, '{subject_filter}')")
    if sender_filter:
        filters.append(f"from/emailAddress/address eq '{sender_filter}'")
    if since_date:
        filters.append(f"receivedDateTime ge {since_date}T00:00:00Z")

    params = {
        "$top": max_results,
        "$orderby": "receivedDateTime desc",
        "$select": "id,subject,from,receivedDateTime,body,bodyPreview",
    }
    if filters:
        params["$filter"] = " and ".join(filters)

    url = f"{GRAPH_BASE}/me/mailFolders/{folder}/messages"
    resp = requests.get(url, headers=_headers(token), params=params)
    resp.raise_for_status()

    emails = []
    for msg in resp.json().get("value", []):
        emails.append({
            "id": msg["id"],
            "subject": msg["subject"],
            "sender": msg["from"]["emailAddress"]["address"],
            "received": msg["receivedDateTime"],
            "body": msg["body"]["content"],
            "body_preview": msg["bodyPreview"],
        })

    return emails


def fetch_telegram_post_emails(
    token: str,
    month: int,
    year: int,
    subject_keyword: str = "Telegram",
    max_results: int = 100,
) -> list[dict]:
    """
    Convenience wrapper: fetch emails containing Telegram posts for a given month.

    Args:
        token:           Access token
        month:           Month number (e.g. 12 for December, 4 for April)
        year:            Year (e.g. 2025)
        subject_keyword: Keyword to filter email subjects
        max_results:     Max emails to return

    Returns:
        List of email dicts filtered to the specified month
    """
    since_date = f"{year}-{month:02d}-01"

    # Calculate end of month
    if month == 12:
        until_date = f"{year + 1}-01-01"
    else:
        until_date = f"{year}-{month + 1:02d}-01"

    filters = [
        f"contains(subject, '{subject_keyword}')",
        f"receivedDateTime ge {since_date}T00:00:00Z",
        f"receivedDateTime lt {until_date}T00:00:00Z",
    ]

    params = {
        "$top": max_results,
        "$orderby": "receivedDateTime asc",
        "$select": "id,subject,from,receivedDateTime,body,bodyPreview",
        "$filter": " and ".join(filters),
    }

    url = f"{GRAPH_BASE}/me/mailFolders/inbox/messages"
    resp = requests.get(url, headers=_headers(token), params=params)
    resp.raise_for_status()

    emails = []
    for msg in resp.json().get("value", []):
        emails.append({
            "id": msg["id"],
            "subject": msg["subject"],
            "sender": msg["from"]["emailAddress"]["address"],
            "received": msg["receivedDateTime"],
            "body": msg["body"]["content"],
            "body_preview": msg["bodyPreview"],
        })

    print(f"Found {len(emails)} Telegram post emails for {year}-{month:02d}")
    return emails


# ── CLI auth helper ───────────────────────────────────────────────────────────

if __name__ == "__main__":
    print("Authenticating with Outlook...")
    token = authenticate()
    print("✓ Authentication successful. Token cached.")

    # Quick test: list 5 recent emails
    emails = fetch_emails(token, max_results=5)
    print(f"\nMost recent 5 emails:")
    for e in emails:
        print(f"  [{e['received'][:10]}] {e['subject'][:60]}")
