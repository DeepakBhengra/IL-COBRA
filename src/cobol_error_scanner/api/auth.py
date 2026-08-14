"""Authentication helpers for external API routes."""

from __future__ import annotations

import os
import secrets

from fastapi import Header, HTTPException

API_KEY_ENV = "COBOL_EXTERNAL_API_KEY"
APPLICATION_KEY_ENV = "COBOL_EXTERNAL_APPLICATION_KEY"


def verify_external_api_keys(
    x_api_key: str | None = Header(default=None, alias="X-API-Key"),
    x_application_key: str | None = Header(default=None, alias="X-Application-Key"),
) -> None:
    """Validate external API credentials from request headers."""
    expected_api_key = os.environ.get(API_KEY_ENV, "").strip()
    expected_application_key = os.environ.get(APPLICATION_KEY_ENV, "").strip()
    if not expected_api_key or not expected_application_key:
        raise HTTPException(
            status_code=503,
            detail=(
                "External lookup API is not configured. Set "
                f"{API_KEY_ENV} and {APPLICATION_KEY_ENV} on the server."
            ),
        )

    if not x_api_key or not x_application_key:
        raise HTTPException(status_code=401, detail="Missing API credentials")

    if not secrets.compare_digest(x_api_key, expected_api_key) or not secrets.compare_digest(
        x_application_key, expected_application_key
    ):
        raise HTTPException(status_code=401, detail="Invalid API credentials")
