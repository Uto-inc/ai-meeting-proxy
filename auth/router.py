"""OAuth2 flow endpoints for Google account linking."""

import logging
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse, RedirectResponse

from auth.google_oauth import (
    SCOPES,
    build_flow,
    credentials_from_token_row,
    refresh_if_needed,
    token_expiry_iso,
)

logger = logging.getLogger("meeting-proxy.auth")

router = APIRouter(prefix="/auth/google", tags=["auth"])


def _get_repo(request: Request) -> Any:
    repo = getattr(request.app.state, "repo", None)
    if repo is None:
        raise HTTPException(status_code=503, detail="Database not initialized")
    return repo


@router.get("/login")
async def google_login(request: Request) -> RedirectResponse:
    """Redirect user to Google OAuth consent screen."""
    flow = build_flow()
    auth_url, state = flow.authorization_url(
        access_type="offline",
        include_granted_scopes="true",
        prompt="consent",
    )
    request.app.state.oauth_state = state
    return RedirectResponse(url=auth_url)


@router.get("/callback")
async def google_callback(request: Request, code: str, state: str) -> RedirectResponse:
    """Handle OAuth callback, exchange code for tokens, and store them."""
    expected_state = getattr(request.app.state, "oauth_state", None)
    if not expected_state or state != expected_state:
        raise HTTPException(status_code=400, detail="Invalid OAuth state")

    flow = build_flow(state=state)
    flow.fetch_token(code=code)
    creds = flow.credentials

    repo = _get_repo(request)
    await repo.save_token(
        access_token=creds.token,
        refresh_token=creds.refresh_token or "",
        token_expiry=token_expiry_iso(creds),
        scopes=",".join(SCOPES),
    )
    logger.info("OAuth tokens saved for default user")
    return RedirectResponse(url="/static/index.html?auth=success")


@router.get("/status")
async def google_auth_status(request: Request) -> JSONResponse:
    """Check current authentication status."""
    repo = _get_repo(request)
    token_row = await repo.get_token()
    if not token_row:
        return JSONResponse({"authenticated": False})

    try:
        creds = credentials_from_token_row(token_row)
        refreshed, creds = refresh_if_needed(creds)
        if refreshed:
            await repo.update_token("default", creds.token, token_expiry_iso(creds))
        return JSONResponse(
            {
                "authenticated": True,
                "scopes": token_row["scopes"],
                "expires": token_expiry_iso(creds),
            }
        )
    except Exception as exc:
        logger.warning("Token validation failed: %s", exc)
        return JSONResponse({"authenticated": False, "error": str(exc)})


@router.post("/revoke")
async def google_revoke(request: Request) -> JSONResponse:
    """Revoke stored OAuth tokens."""
    repo = _get_repo(request)
    token_row = await repo.get_token()
    if not token_row:
        return JSONResponse({"detail": "No tokens to revoke"})

    try:
        import httpx

        async with httpx.AsyncClient() as client:
            await client.post(
                "https://oauth2.googleapis.com/revoke",
                params={"token": token_row["access_token"]},
            )
    except Exception:
        logger.warning("Remote token revocation failed (continuing with local delete)")

    await repo.delete_token()
    logger.info("OAuth tokens revoked and deleted")
    return JSONResponse({"detail": "Tokens revoked"})
