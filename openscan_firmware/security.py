"""Security helpers for protecting privileged API operations."""

from __future__ import annotations

import os
import secrets
from typing import Optional

from fastapi import HTTPException, Request, status


ADMIN_TOKEN_ENV = "OPENSCAN_ADMIN_TOKEN"
ALLOW_INSECURE_ADMIN_ENV = "OPENSCAN_ALLOW_INSECURE_ADMIN"
ADMIN_HEADER_NAME = "X-OpenScan-Token"


def _get_admin_token() -> Optional[str]:
    token = os.getenv(ADMIN_TOKEN_ENV)
    if token is None:
        return None
    token = token.strip()
    return token or None


def _allow_insecure_admin() -> bool:
    value = os.getenv(ALLOW_INSECURE_ADMIN_ENV, "")
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _extract_request_token(request: Request) -> Optional[str]:
    header_token = request.headers.get(ADMIN_HEADER_NAME)
    if header_token:
        return header_token.strip()

    auth_header = request.headers.get("Authorization", "")
    if auth_header.lower().startswith("bearer "):
        return auth_header[7:].strip()
    return None


def require_admin(request: Request) -> None:
    """Enforce admin token for privileged operations."""
    admin_token = _get_admin_token()
    if not admin_token:
        if _allow_insecure_admin():
            return
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"Admin token not configured. Set {ADMIN_TOKEN_ENV}.",
        )

    provided = _extract_request_token(request)
    if not provided or not secrets.compare_digest(provided, admin_token):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Unauthorized")
