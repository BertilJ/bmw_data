"""Device tracker platform for BMW CarData integration."""

from __future__ import annotations

import logging

from homeassistant.components.device_tracker import SourceType
from homeassistant.components.device_tracker.config_entry import TrackerEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from . import BMWCarDataConfigEntry
from .const import DOMAIN
from .coordinator import BMWCarDataCoordinator

_LOGGER = logging.getLogger(__name__)

# Telemetry keys that may contain GPS coordinates
_LAT_KEYS = ("navigation.latitude", "gps.latitude", "position.latitude")
_LON_KEYS = ("navigation.longitude", "gps.longitude", "position.longitude")


async def async_setup_entry(
    hass: HomeAssistant,
    entry: BMWCarDataConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up BMW CarData device tracker entities."""
    coordinator: BMWCarDataCoordinator = entry.runtime_data

    entities: list[BMWDeviceTracker] = []
    for vin in coordinator.data:
        entities.append(BMWDeviceTracker(coordinator, vin, entry))

    async_add_entities(entities)


class BMWDeviceTracker(
    CoordinatorEntity[BMWCarDataCoordinator], TrackerEntity
):
    """Representation of a BMW vehicle location tracker."""

    _attr_has_entity_name = True
    _attr_translation_key = "location"
    _attr_icon = "mdi:car"

    def __init__(
        self,
        coordinator: BMWCarDataCoordinator,
        vin: str,
        entry: BMWCarDataConfigEntry,
    ) -> None:
        """Initialize the device tracker."""
        super().__init__(coordinator)
        self._vin = vin
        self._attr_unique_id = f"{vin}_location"

        vehicle = coordinator.vehicles.get(vin)
        model = vehicle.model if vehicle else "Unknown"
        brand = vehicle.brand if vehicle else "BMW"

        self._attr_device_info = {
            "identifiers": {(DOMAIN, vin)},
            "name": f"{brand} {model}",
            "manufacturer": brand,
            "model": model,
            "serial_number": vin,
        }

    @property
    def source_type(self) -> SourceType:
        """Return the source type."""
        return SourceType.GPS

    @property
    def latitude(self) -> float | None:
        """Return the latitude of the vehicle."""
        return self._get_coordinate(_LAT_KEYS)

    @property
    def longitude(self) -> float | None:
        """Return the longitude of the vehicle."""
        return self._get_coordinate(_LON_KEYS)

    def _get_coordinate(self, keys: tuple[str, ...]) -> float | None:
        """Try multiple telemetry keys to find a coordinate value."""
        if not self.coordinator.data:
            return None

        vehicle = self.coordinator.data.get(self._vin)
        if not vehicle:
            return None

        for key in keys:
            entry = vehicle.telemetry.get(key)
            if entry:
                try:
                    return float(entry.value)
                except (ValueError, TypeError):
                    continue

        return None
