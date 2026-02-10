"""Config flow for BMW CarData integration."""

from __future__ import annotations

import asyncio
import logging
from typing import Any

import voluptuous as vol

from homeassistant.config_entries import ConfigEntry, ConfigFlow, ConfigFlowResult
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import BMWCarDataAPI, VehicleBasicData
from .auth import (
    AuthError,
    AuthorizationPending,
    BMWAuth,
    DeviceCodeExpired,
    DeviceCodeResponse,
    SlowDown,
    TokenResponse,
)
from .const import CONF_CLIENT_ID, DOMAIN

_LOGGER = logging.getLogger(__name__)


class BMWCarDataConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow for BMW CarData."""

    VERSION = 1

    def __init__(self) -> None:
        """Initialize the config flow."""
        self._client_id: str = ""
        self._auth: BMWAuth | None = None
        self._device_code_resp: DeviceCodeResponse | None = None
        self._tokens: TokenResponse | None = None
        self._vehicles: list[VehicleBasicData] = []
        self._reauth_entry: ConfigEntry | None = None
        self._login_task: asyncio.Task[None] | None = None

    # ── Step 1: Enter Client ID ──────────────────────────────────────────

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle the initial step: enter BMW client_id."""
        errors: dict[str, str] = {}

        if user_input is not None:
            self._client_id = user_input[CONF_CLIENT_ID].strip()

            session = async_get_clientsession(self.hass)
            self._auth = BMWAuth(session, self._client_id)

            try:
                self._device_code_resp = await self._auth.request_device_code()
            except AuthError as err:
                _LOGGER.error("Failed to request device code: %s", err)
                errors["base"] = "device_code_failed"
            else:
                return await self.async_step_open_link()

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {vol.Required(CONF_CLIENT_ID): str}
            ),
            errors=errors,
        )

    # ── Step 2a: Show URL and Code ───────────────────────────────────────

    async def async_step_open_link(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Show the verification URL and user code.

        The user opens the link in a browser, enters the code, and clicks
        Submit here to start polling for the authorization result.
        """
        if not self._device_code_resp:
            return self.async_abort(reason="no_device_code")

        if user_input is not None:
            # User clicked Submit — start polling
            return await self.async_step_authorize()

        return self.async_show_form(
            step_id="open_link",
            data_schema=vol.Schema({}),
            description_placeholders={
                "url": self._device_code_resp.verification_uri_complete,
                "code": self._device_code_resp.user_code,
            },
        )

    # ── Step 2b: Poll for Authorization ──────────────────────────────────

    async def async_step_authorize(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Poll for authorization in background with progress spinner.

        This method is called twice by the framework:
        1. Initially — creates the background task, shows progress spinner.
        2. On re-entry (when task completes) — checks result and advances.
        """
        if not self._device_code_resp:
            return self.async_abort(reason="no_device_code")

        # Create the background polling task once
        if self._login_task is None:
            self._login_task = self.hass.async_create_task(
                self._poll_for_authorization()
            )

        # Re-entry: task has completed
        if self._login_task.done():
            if self._login_task.exception() or not self._tokens:
                return self.async_show_progress_done(
                    next_step_id="authorize_failed"
                )
            return self.async_show_progress_done(next_step_id="discover")

        # Task still running — show progress spinner
        return self.async_show_progress(
            step_id="authorize",
            progress_action="wait_for_authorization",
            progress_task=self._login_task,
        )

    async def _poll_for_authorization(self) -> None:
        """Poll BMW token endpoint until user authorizes or timeout.

        The framework automatically re-invokes async_step_authorize()
        when this task completes (success or exception).
        """
        if not self._auth or not self._device_code_resp:
            raise AuthError("Missing auth or device code")

        interval = self._device_code_resp.interval
        deadline = (
            asyncio.get_event_loop().time()
            + self._device_code_resp.expires_in
        )

        while asyncio.get_event_loop().time() < deadline:
            await asyncio.sleep(interval)
            try:
                self._tokens = await self._auth.poll_for_token(
                    self._device_code_resp.device_code
                )
                return  # Success — task completes, framework re-invokes step
            except AuthorizationPending:
                continue
            except SlowDown:
                interval = min(interval + 2, 10)
                continue
            except DeviceCodeExpired:
                _LOGGER.error("Device code expired before user authorized")
                raise
            except AuthError as err:
                _LOGGER.error("Unexpected auth error: %s", err)
                raise

        raise DeviceCodeExpired("Polling deadline exceeded")

    async def async_step_authorize_failed(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle authorization failure."""
        return self.async_abort(reason="authorization_failed")

    # ── Step 3: Vehicle Discovery ────────────────────────────────────────

    async def async_step_discover(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Discover vehicles and create config entry."""
        if not self._tokens:
            return self.async_abort(reason="no_tokens")

        if not self._vehicles:
            session = async_get_clientsession(self.hass)
            api = BMWCarDataAPI(session)
            api.set_token(self._tokens.access_token)

            try:
                self._vehicles = await api.discover_vehicles()
            except Exception as err:
                _LOGGER.error("Vehicle discovery failed: %s", err)
                return self.async_abort(reason="discovery_failed")

        if not self._vehicles:
            return self.async_abort(reason="no_vehicles")

        # If this is a reauth flow, update the existing entry
        if self._reauth_entry:
            return await self._finish_reauth()

        return await self._create_entry()

    async def _create_entry(self) -> ConfigFlowResult:
        """Create the config entry with tokens and vehicle data."""
        primary_vin = self._vehicles[0].vin
        await self.async_set_unique_id(primary_vin)
        self._abort_if_unique_id_configured()

        vehicle_data = [
            {
                "vin": v.vin,
                "brand": v.brand,
                "model": v.model,
                "propulsion": v.propulsion,
                "construction_year": v.construction_year,
            }
            for v in self._vehicles
        ]

        title = ", ".join(f"{v.brand} {v.model}" for v in self._vehicles)

        return self.async_create_entry(
            title=title,
            data={
                CONF_CLIENT_ID: self._client_id,
                "tokens": self._tokens.as_dict() if self._tokens else {},
                "vehicles": vehicle_data,
            },
        )

    # ── Reauth Flow ─────────────────────────────────────────────────────

    async def async_step_reauth(
        self, entry_data: dict[str, Any]
    ) -> ConfigFlowResult:
        """Handle re-authentication when tokens expire."""
        self._reauth_entry = self.hass.config_entries.async_get_entry(
            self.context["entry_id"]
        )
        self._client_id = entry_data.get(CONF_CLIENT_ID, "")
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Confirm re-authentication."""
        if user_input is not None:
            session = async_get_clientsession(self.hass)
            self._auth = BMWAuth(session, self._client_id)

            try:
                self._device_code_resp = await self._auth.request_device_code()
            except AuthError as err:
                _LOGGER.error("Reauth device code failed: %s", err)
                return self.async_abort(reason="device_code_failed")

            return await self.async_step_open_link()

        return self.async_show_form(
            step_id="reauth_confirm",
            description_placeholders={
                CONF_CLIENT_ID: self._client_id,
            },
        )

    async def _finish_reauth(self) -> ConfigFlowResult:
        """Complete the reauth flow by updating the config entry."""
        if not self._reauth_entry or not self._tokens:
            return self.async_abort(reason="reauth_failed")

        new_data = {
            **self._reauth_entry.data,
            "tokens": self._tokens.as_dict(),
        }
        self.hass.config_entries.async_update_entry(
            self._reauth_entry, data=new_data
        )
        await self.hass.config_entries.async_reload(self._reauth_entry.entry_id)
        return self.async_abort(reason="reauth_successful")
