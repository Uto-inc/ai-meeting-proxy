"""Google OAuth2 token management – save, refresh, validate."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from google.auth.transport.requests import Request as GoogleAuthRequest
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import Flow

from config import settings

logger = logging.getLogger("meeting-proxy.auth")

SCOPES = [
    "https://www.googleapis.com/auth/calendar.readonly",
    "https://www.googleapis.com/auth/drive.readonly",
    "https://www.googleapis.com/auth/documents",
]


def build_flow(state: str | None = None) -> Flow:
    """Build a Google OAuth2 flow from client secrets file or config."""
    client_config = {
        "web": {
            "client_id": settings.google_client_id,
            "client_secret": settings.google_client_secret,
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
            "redirect_uris": [settings.google_redirect_uri],
        }
    }
    flow = Flow.from_client_config(client_config, scopes=SCOPES, state=state)
    flow.redirect_uri = settings.google_redirect_uri
    return flow


def credentials_from_token_row(token_row: dict) -> Credentials:
    """Reconstruct google.oauth2.credentials.Credentials from a DB row."""
    return Credentials(  # nosec B106 - token_uri is a URL, not a password
        token=token_row["access_token"],
        refresh_token=token_row["refresh_token"],
        token_uri="https://oauth2.googleapis.com/token",  # noqa: S106
        client_id=settings.google_client_id,
        client_secret=settings.google_client_secret,
        scopes=token_row["scopes"].split(","),
    )


def refresh_if_needed(creds: Credentials) -> tuple[bool, Credentials]:
    """Refresh credentials if expired. Returns (was_refreshed, creds)."""
    if creds.valid:
        return False, creds
    if creds.refresh_token:
        creds.refresh(GoogleAuthRequest())
        logger.info("OAuth token refreshed")
        return True, creds
    raise ValueError("Token expired and no refresh_token available")


def token_expiry_iso(creds: Credentials) -> str:
    """Return ISO timestamp for token expiry."""
    if creds.expiry:
        return creds.expiry.isoformat()
    return (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()
