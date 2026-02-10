"""REST API client for BMW CarData with rate limiting."""

from __future__ import annotations

import logging
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Any

import aiohttp

from .const import (
    API_BASE_URL,
    API_VERSION_HEADER,
    RATE_LIMIT_MAX_CALLS,
    RATE_LIMIT_WINDOW,
)

_LOGGER = logging.getLogger(__name__)


class RateLimitExceeded(Exception):
    """Raised when the 24h API call budget is exhausted."""


class APIError(Exception):
    """Raised on non-2xx responses from the BMW API."""

    def __init__(self, status: int, message: str) -> None:
        super().__init__(f"API error {status}: {message}")
        self.status = status


@dataclass
class VehicleBasicData:
    """Basic vehicle information from the API."""

    vin: str
    brand: str
    model: str
    propulsion: str
    construction_year: int | None = None

    @classmethod
    def from_api(cls, data: dict[str, Any]) -> VehicleBasicData:
        """Parse from API response."""
        return cls(
            vin=data.get("vin", ""),
            brand=data.get("brand", "BMW"),
            model=data.get("model", "Unknown"),
            propulsion=data.get("propulsion", ""),
            construction_year=data.get("constructionYear"),
        )


@dataclass
class TelematicEntry:
    """Single telemetric data point."""

    name: str
    value: str
    unit: str | None
    timestamp: str  # ISO 8601


@dataclass
class VehicleData:
    """Aggregated vehicle data from REST and MQTT sources."""

    basic: VehicleBasicData
    telemetry: dict[str, TelematicEntry] = field(default_factory=dict)
    rest_updated: float | None = None
    mqtt_updated: float | None = None


class BMWCarDataAPI:
    """REST API client for BMW CarData."""

    def __init__(self, session: aiohttp.ClientSession) -> None:
        """Initialize with an aiohttp session."""
        self._session = session
        self._access_token: str = ""
        self._call_log: deque[float] = deque()

    def set_token(self, access_token: str) -> None:
        """Update the access token used for API calls."""
        self._access_token = access_token

    @property
    def remaining_calls(self) -> int:
        """Return the number of API calls remaining in the current 24h window."""
        self._prune_call_log()
        return max(0, RATE_LIMIT_MAX_CALLS - len(self._call_log))

    def _prune_call_log(self) -> None:
        """Remove call timestamps older than the rate limit window."""
        cutoff = time.time() - RATE_LIMIT_WINDOW
        while self._call_log and self._call_log[0] < cutoff:
            self._call_log.popleft()

    def _check_rate_limit(self) -> None:
        """Raise RateLimitExceeded if budget is exhausted."""
        self._prune_call_log()
        if len(self._call_log) >= RATE_LIMIT_MAX_CALLS:
            oldest = self._call_log[0]
            reset_in = int(oldest + RATE_LIMIT_WINDOW - time.time())
            raise RateLimitExceeded(
                f"Rate limit reached ({RATE_LIMIT_MAX_CALLS} calls). "
                f"Resets in {reset_in}s."
            )

    def _record_call(self) -> None:
        """Record a successful API call timestamp."""
        self._call_log.append(time.time())

    def _headers(self) -> dict[str, str]:
        """Build request headers."""
        return {
            "Authorization": f"Bearer {self._access_token}",
            "x-version": API_VERSION_HEADER,
            "Accept": "application/json",
        }

    async def _request(self, method: str, path: str, **kwargs: Any) -> Any:
        """Make an authenticated API request with rate limiting."""
        self._check_rate_limit()

        url = f"{API_BASE_URL}{path}"
        _LOGGER.debug("API %s %s", method, url)

        async with self._session.request(
            method, url, headers=self._headers(), **kwargs
        ) as resp:
            self._record_call()
            _LOGGER.debug(
                "API response %s (remaining calls: %d)",
                resp.status,
                self.remaining_calls,
            )

            if resp.status == 401:
                raise APIError(401, "Unauthorized — token may be expired")
            if resp.status == 429:
                raise APIError(429, "Rate limited by BMW API server")
            if not 200 <= resp.status < 300:
                body = await resp.text()
                raise APIError(resp.status, body[:500])

            if resp.content_length == 0:
                return None
            return await resp.json()

    # ── Vehicle Discovery ────────────────────────────────────────────────

    async def get_vehicle_mappings(self) -> list[str]:
        """Get list of VINs associated with the user's account.

        Endpoint: GET /customers/vehicles/mappings
        Returns a list of VIN strings, extracted from mapping objects.
        """
        result = await self._request("GET", "/customers/vehicles/mappings")
        items = result if isinstance(result, list) else result.get("mappings", [])
        vins: list[str] = []
        for item in items:
            if isinstance(item, str):
                vins.append(item)
            elif isinstance(item, dict) and "vin" in item:
                vins.append(item["vin"])
        return vins

    async def get_vehicle_basic_data(self, vin: str) -> VehicleBasicData:
        """Get basic vehicle information.

        Endpoint: GET /customers/vehicles/{vin}/basicData
        """
        result = await self._request("GET", f"/customers/vehicles/{vin}/basicData")
        return VehicleBasicData.from_api(result)

    # ── Telemetric Data ──────────────────────────────────────────────────

    async def get_telematic_data(
        self, vin: str, container_id: str | None = None
    ) -> list[TelematicEntry]:
        """Get telemetric data for a vehicle.

        Endpoint: GET /customers/vehicles/{vin}/telematicData
        Optional query param: containerId
        """
        params: dict[str, str] = {}
        if container_id:
            params["containerId"] = container_id

        result = await self._request(
            "GET", f"/customers/vehicles/{vin}/telematicData", params=params or None
        )

        entries: list[TelematicEntry] = []
        items = result if isinstance(result, list) else result.get("data", [])
        for item in items:
            entries.append(
                TelematicEntry(
                    name=item.get("name", ""),
                    value=str(item.get("value", "")),
                    unit=item.get("unit"),
                    timestamp=item.get("timestamp", ""),
                )
            )
        return entries

    # ── Container Management ─────────────────────────────────────────────

    async def get_containers(self) -> list[dict[str, Any]]:
        """Get telemetry data containers.

        Endpoint: GET /customers/containers/
        """
        result = await self._request("GET", "/customers/containers/")
        if isinstance(result, list):
            return result
        return result.get("containers", [])

    # ── Convenience ──────────────────────────────────────────────────────

    async def discover_vehicles(self) -> list[VehicleBasicData]:
        """Discover all vehicles: get VIN list then fetch basic data for each."""
        vins = await self.get_vehicle_mappings()
        vehicles: list[VehicleBasicData] = []
        for vin in vins:
            try:
                basic = await self.get_vehicle_basic_data(vin)
                vehicles.append(basic)
            except APIError as err:
                _LOGGER.warning("Failed to get basic data for %s: %s", vin, err)
                vehicles.append(
                    VehicleBasicData(vin=vin, brand="BMW", model="Unknown", propulsion="")
                )
        return vehicles
