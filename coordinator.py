"""DataUpdateCoordinator for BMW CarData integration."""

from __future__ import annotations

import logging
import time
from datetime import timedelta
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.update_coordinator import (
    DataUpdateCoordinator,
    UpdateFailed,
)

from .api import (
    APIError,
    BMWCarDataAPI,
    RateLimitExceeded,
    TelematicEntry,
    VehicleBasicData,
    VehicleData,
)
from .auth import BMWAuth, TokenRefreshFailed, TokenResponse
from .const import (
    CONF_CLIENT_ID,
    DEFAULT_POLL_INTERVAL,
    DOMAIN,
    TOKEN_REFRESH_MARGIN,
)
from .mqtt_stream import BMWMQTTStream

_LOGGER = logging.getLogger(__name__)


class BMWCarDataCoordinator(DataUpdateCoordinator[dict[str, VehicleData]]):
    """Coordinate REST polling and MQTT streaming for BMW vehicles.

    Data is a dict mapping VIN → VehicleData. REST polls update all VINs,
    MQTT updates individual VINs in real-time. Both sources merge into the
    same VehicleData objects so entities always see the latest state.
    """

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        vehicles: list[VehicleBasicData],
        tokens: TokenResponse,
    ) -> None:
        """Initialize the coordinator."""
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=timedelta(seconds=DEFAULT_POLL_INTERVAL),
        )
        self.entry = entry
        self._vehicles = {v.vin: v for v in vehicles}
        self._tokens = tokens

        session = async_get_clientsession(hass)
        self._auth = BMWAuth(session, entry.data[CONF_CLIENT_ID])
        self._api = BMWCarDataAPI(session)
        self._api.set_token(tokens.access_token)

        self._mqtt: BMWMQTTStream | None = None

        # Initialize vehicle data store
        self.data: dict[str, VehicleData] = {
            v.vin: VehicleData(basic=v) for v in vehicles
        }

    @property
    def vehicles(self) -> dict[str, VehicleBasicData]:
        """Return the vehicle map (VIN → basic data)."""
        return self._vehicles

    @property
    def remaining_api_calls(self) -> int:
        """Return remaining REST API calls in the current 24h window."""
        return self._api.remaining_calls

    # ── Token Management ─────────────────────────────────────────────────

    async def _ensure_valid_token(self) -> None:
        """Refresh the access token if it's about to expire.

        Persists new tokens to the config entry so they survive restarts.
        Raises ConfigEntryAuthFailed if the refresh token is invalid.
        """
        if time.time() < self._tokens.expiry_timestamp - TOKEN_REFRESH_MARGIN:
            return

        _LOGGER.debug("Access token expiring soon, refreshing")
        try:
            self._tokens = await self._auth.refresh_tokens(
                self._tokens.refresh_token
            )
        except TokenRefreshFailed as err:
            _LOGGER.error("Token refresh failed: %s", err)
            raise ConfigEntryAuthFailed(
                "BMW authentication expired. Please re-authenticate."
            ) from err

        # Update API client and MQTT stream with new tokens
        self._api.set_token(self._tokens.access_token)
        if self._mqtt:
            self._mqtt.update_token(self._tokens.id_token)

        # Persist tokens to config entry
        new_data = {**self.entry.data, "tokens": self._tokens.as_dict()}
        self.hass.config_entries.async_update_entry(self.entry, data=new_data)
        _LOGGER.debug("Tokens refreshed and persisted")

    # ── REST Polling ─────────────────────────────────────────────────────

    async def _async_update_data(self) -> dict[str, VehicleData]:
        """Fetch telemetric data from REST API for all vehicles.

        Called by DataUpdateCoordinator on each poll interval.
        """
        try:
            await self._ensure_valid_token()
        except ConfigEntryAuthFailed:
            raise
        except Exception as err:
            raise UpdateFailed(f"Token refresh error: {err}") from err

        for vin in self._vehicles:
            if not vin:
                _LOGGER.error(
                    "Empty VIN in vehicle list — delete and re-add the "
                    "integration to fix"
                )
                continue
            _LOGGER.debug("Fetching telemetry for VIN: %s", vin)
            try:
                entries = await self._api.get_telematic_data(vin)
                self._merge_rest_data(vin, entries)
            except RateLimitExceeded:
                _LOGGER.warning(
                    "REST API rate limit reached — skipping poll. "
                    "MQTT streaming continues."
                )
                break
            except APIError as err:
                if err.status == 401:
                    raise ConfigEntryAuthFailed(
                        "BMW API returned 401 — re-authenticate"
                    ) from err
                if err.status == 403:
                    _LOGGER.warning(
                        "Telemetry 403 for %s — have you configured "
                        "containers in the BMW CarData portal? "
                        "You need to set up data containers at "
                        "cardata.bmwgroup.com before telemetry is available",
                        vin,
                    )
                else:
                    _LOGGER.warning("Failed to fetch telemetry for %s: %s", vin, err)
            except Exception as err:
                _LOGGER.warning(
                    "Unexpected error fetching telemetry for %s: %s", vin, err
                )

        return self.data

    def _merge_rest_data(
        self, vin: str, entries: list[TelematicEntry]
    ) -> None:
        """Merge REST API telemetric entries into the vehicle data store."""
        if vin not in self.data:
            return

        vehicle = self.data[vin]
        for entry in entries:
            vehicle.telemetry[entry.name] = entry

        vehicle.rest_updated = time.time()
        _LOGGER.debug(
            "REST update for %s: %d entries (total: %d)",
            vin,
            len(entries),
            len(vehicle.telemetry),
        )

    # ── MQTT Streaming ───────────────────────────────────────────────────

    async def start_mqtt(self) -> None:
        """Start the MQTT streaming connection."""
        if not self._tokens.id_token:
            _LOGGER.warning("No id_token available — MQTT streaming disabled")
            return

        vins = list(self._vehicles.keys())
        self._mqtt = BMWMQTTStream(
            id_token=self._tokens.id_token,
            gcid=self._tokens.gcid,
            vins=vins,
            callback=self._on_mqtt_message,
        )
        await self._mqtt.start()

    async def stop_mqtt(self) -> None:
        """Stop the MQTT streaming connection."""
        if self._mqtt:
            await self._mqtt.stop()
            self._mqtt = None

    def _on_mqtt_message(self, vin: str, payload: dict[str, Any]) -> None:
        """Handle an incoming MQTT telemetry message.

        Merges the data and triggers an immediate entity update via
        async_set_updated_data(), bypassing the poll interval.
        """
        if vin not in self.data:
            _LOGGER.debug("MQTT data for unknown VIN %s — ignoring", vin)
            return

        vehicle = self.data[vin]

        # MQTT payload can be a list of entries or a single dict
        items = payload if isinstance(payload, list) else [payload]
        for item in items:
            name = item.get("name", "")
            if name:
                vehicle.telemetry[name] = TelematicEntry(
                    name=name,
                    value=str(item.get("value", "")),
                    unit=item.get("unit"),
                    timestamp=item.get("timestamp", ""),
                )

        vehicle.mqtt_updated = time.time()

        # Trigger immediate entity refresh
        self.async_set_updated_data(self.data)
