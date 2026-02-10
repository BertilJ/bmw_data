"""OAuth 2.0 Device Code Flow with PKCE for BMW CarData."""

from __future__ import annotations

import base64
import hashlib
import logging
import secrets
import time
from dataclasses import dataclass
from typing import Any

import aiohttp

from .const import (
    DEVICE_CODE_URL,
    OAUTH_SCOPES,
    TOKEN_URL,
)

_LOGGER = logging.getLogger(__name__)


# ── PKCE Helpers ─────────────────────────────────────────────────────────────


def generate_code_verifier() -> str:
    """Generate a 128-character URL-safe random code verifier."""
    return secrets.token_urlsafe(96)[:128]


def generate_code_challenge(verifier: str) -> str:
    """Generate S256 code challenge from verifier."""
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")


# ── Data Classes ─────────────────────────────────────────────────────────────


@dataclass
class DeviceCodeResponse:
    """Response from the device code endpoint."""

    device_code: str
    user_code: str
    verification_uri: str
    verification_uri_complete: str
    expires_in: int
    interval: int


@dataclass
class TokenResponse:
    """Token set from the token endpoint."""

    access_token: str
    refresh_token: str
    id_token: str
    expires_in: int
    gcid: str
    token_time: float  # time.time() when tokens were obtained

    @property
    def expiry_timestamp(self) -> float:
        """Absolute expiry time."""
        return self.token_time + self.expires_in

    def as_dict(self) -> dict[str, Any]:
        """Serialize for storage in config entry data."""
        return {
            "access_token": self.access_token,
            "refresh_token": self.refresh_token,
            "id_token": self.id_token,
            "expires_in": self.expires_in,
            "gcid": self.gcid,
            "token_time": self.token_time,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> TokenResponse:
        """Deserialize from config entry data."""
        return cls(
            access_token=data["access_token"],
            refresh_token=data["refresh_token"],
            id_token=data["id_token"],
            expires_in=data["expires_in"],
            gcid=data["gcid"],
            token_time=data["token_time"],
        )


class AuthError(Exception):
    """Base authentication error."""


class AuthorizationPending(AuthError):
    """User has not yet completed authorization."""


class SlowDown(AuthError):
    """Polling too fast."""


class DeviceCodeExpired(AuthError):
    """Device code has expired."""


class TokenRefreshFailed(AuthError):
    """Refresh token is invalid or expired."""


# ── OAuth Client ─────────────────────────────────────────────────────────────


class BMWAuth:
    """Handle BMW CarData OAuth 2.0 Device Code Flow with PKCE."""

    def __init__(self, session: aiohttp.ClientSession, client_id: str) -> None:
        """Initialize with an aiohttp session and client_id."""
        self._session = session
        self._client_id = client_id
        self._code_verifier: str | None = None

    @property
    def code_verifier(self) -> str | None:
        """Return the current code verifier (needed for persistence)."""
        return self._code_verifier

    @code_verifier.setter
    def code_verifier(self, value: str) -> None:
        """Set the code verifier (for restoring from persistence)."""
        self._code_verifier = value

    async def request_device_code(self) -> DeviceCodeResponse:
        """Request a device code for user authorization.

        Returns the device code response containing the user_code and
        verification URL that the user must visit.
        """
        self._code_verifier = generate_code_verifier()
        challenge = generate_code_challenge(self._code_verifier)

        data = {
            "client_id": self._client_id,
            "response_type": "device_code",
            "scope": OAUTH_SCOPES,
            "code_challenge": challenge,
            "code_challenge_method": "S256",
        }

        async with self._session.post(DEVICE_CODE_URL, data=data) as resp:
            if resp.status != 200:
                body = await resp.text()
                raise AuthError(f"Device code request failed ({resp.status}): {body}")
            result = await resp.json()

        return DeviceCodeResponse(
            device_code=result["device_code"],
            user_code=result["user_code"],
            verification_uri=result["verification_uri"],
            verification_uri_complete=result.get(
                "verification_uri_complete", result["verification_uri"]
            ),
            expires_in=result.get("expires_in", 300),
            interval=result.get("interval", 5),
        )

    async def poll_for_token(self, device_code: str) -> TokenResponse:
        """Poll the token endpoint once.

        Raises AuthorizationPending if the user hasn't authorized yet,
        SlowDown if polling too fast, or DeviceCodeExpired if expired.
        Returns TokenResponse on success.
        """
        if not self._code_verifier:
            raise AuthError("No code verifier — call request_device_code first")

        data = {
            "client_id": self._client_id,
            "grant_type": "urn:ietf:params:oauth:grant-type:device_code",
            "device_code": device_code,
            "code_verifier": self._code_verifier,
        }

        async with self._session.post(TOKEN_URL, data=data) as resp:
            body = await resp.json(content_type=None)

            if resp.status == 200:
                return TokenResponse(
                    access_token=body["access_token"],
                    refresh_token=body["refresh_token"],
                    id_token=body.get("id_token", ""),
                    expires_in=body.get("expires_in", 3599),
                    gcid=body.get("gcid", ""),
                    token_time=time.time(),
                )

            error = body.get("error", "")
            description = body.get("error_description", "")

            if error == "authorization_pending" or resp.status == 403:
                raise AuthorizationPending(description or "Waiting for user")
            if error == "slow_down":
                raise SlowDown(description or "Slow down")
            if resp.status == 401:
                raise DeviceCodeExpired(description or "Device code expired")

            raise AuthError(f"Token poll failed ({resp.status}): {error} {description}")

    async def refresh_tokens(self, refresh_token: str) -> TokenResponse:
        """Refresh the access token using a refresh token."""
        data = {
            "client_id": self._client_id,
            "grant_type": "refresh_token",
            "refresh_token": refresh_token,
        }

        async with self._session.post(TOKEN_URL, data=data) as resp:
            body = await resp.json(content_type=None)

            if resp.status == 200:
                return TokenResponse(
                    access_token=body["access_token"],
                    refresh_token=body.get("refresh_token", refresh_token),
                    id_token=body.get("id_token", ""),
                    expires_in=body.get("expires_in", 3599),
                    gcid=body.get("gcid", ""),
                    token_time=time.time(),
                )

            _LOGGER.error(
                "Token refresh failed (%s): %s", resp.status, body
            )
            raise TokenRefreshFailed(
                f"Refresh failed ({resp.status}): {body.get('error', 'unknown')}"
            )
