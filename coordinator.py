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
    DEFAULT_CONTAINER_DESCRIPTORS,
    DEFAULT_CONTAINER_NAME,
    DEFAULT_CONTAINER_PURPOSE,
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
        self._container_id: str = ""

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

        # Ensure we have a container ID
        if not self._container_id:
            await self._ensure_container()

        if not self._container_id:
            _LOGGER.warning("No container ID available — cannot fetch telemetry")
            return self.data

        for vin in self._vehicles:
            if not vin:
                continue
            _LOGGER.debug("Fetching telemetry for VIN: %s", vin)

            try:
                await self._fetch_telemetry(vin, self._container_id)
            except RateLimitExceeded:
                _LOGGER.warning("Rate limit hit — stopping REST polls")
                break

        return self.data

    async def _ensure_container(self) -> None:
        """Find an existing container or create one."""
        try:
            containers = await self._api.get_containers()
            _LOGGER.debug("Available containers: %s", containers)

            # Reuse any existing container
            for c in containers:
                if isinstance(c, dict):
                    cid = (
                        c.get("containerId")
                        or c.get("id")
                        or c.get("container_id", "")
                    )
                    if cid:
                        self._container_id = str(cid)
                        _LOGGER.info("Reusing existing container: %s", cid)
                        return

            # No containers found — create one
            _LOGGER.info("No containers found, creating one")
            self._container_id = await self._api.create_container(
                name=DEFAULT_CONTAINER_NAME,
                purpose=DEFAULT_CONTAINER_PURPOSE,
                descriptors=DEFAULT_CONTAINER_DESCRIPTORS,
            )
        except APIError as err:
            _LOGGER.error("Container setup failed: %s", err)
        except Exception as err:
            _LOGGER.error("Unexpected error in container setup: %s", err)

    async def _fetch_telemetry(
        self, vin: str, container_id: str
    ) -> None:
        """Fetch telemetric data for a single VIN and container."""
        try:
            entries = await self._api.get_telematic_data(vin, container_id)
            self._merge_rest_data(vin, entries)
            _LOGGER.debug(
                "Got %d entries for %s (container=%s)",
                len(entries), vin, container_id,
            )
        except RateLimitExceeded:
            _LOGGER.warning(
                "REST API rate limit reached — skipping remaining polls"
            )
            raise
        except APIError as err:
            if err.status == 401:
                raise ConfigEntryAuthFailed(
                    "BMW API returned 401 — re-authenticate"
                ) from err
            _LOGGER.warning(
                "Telemetry error for %s (container=%s): %s",
                vin, container_id, err,
            )
        except Exception as err:
            _LOGGER.warning(
                "Unexpected error fetching telemetry for %s: %s", vin, err
            )

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

        BMW MQTT payload format: {"vin": "...", "data": {"descriptor": {"value": ..., "unit": ..., "timestamp": ...}}}
        The VIN from the topic is used (already extracted by mqtt_stream),
        and the telemetry data is in the "data" dict using the same format
        as the REST API's telematicData response.
        """
        # Use VIN from payload if available, fall back to topic-extracted VIN
        msg_vin = payload.get("vin", vin)
        if msg_vin not in self.data:
            _LOGGER.debug("MQTT data for unknown VIN %s — ignoring", msg_vin)
            return

        vehicle = self.data[msg_vin]

        # BMW wraps telemetry in a "data" dict: {descriptor: {value, unit, timestamp}}
        data = payload.get("data") or {}
        if not isinstance(data, dict):
            _LOGGER.warning("MQTT payload 'data' is not a dict: %s", type(data))
            return

        count = 0
        for descriptor, descriptor_payload in data.items():
            if not isinstance(descriptor_payload, dict):
                continue
            value = descriptor_payload.get("value")
            if value is None:
                continue
            vehicle.telemetry[descriptor] = TelematicEntry(
                name=descriptor,
                value=str(value),
                unit=descriptor_payload.get("unit"),
                timestamp=descriptor_payload.get("timestamp", ""),
            )
            count += 1

        _LOGGER.debug("MQTT update for %s: %d descriptors", msg_vin, count)
        vehicle.mqtt_updated = time.time()

        # Trigger immediate entity refresh
        self.async_set_updated_data(self.data)
