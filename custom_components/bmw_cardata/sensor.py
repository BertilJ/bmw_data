"""Sensor platform for BMW CarData integration."""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from . import BMWCarDataConfigEntry
from .api import VehicleData
from .const import DOMAIN, SENSOR_KEY_MAP
from .coordinator import BMWCarDataCoordinator

_LOGGER = logging.getLogger(__name__)

# Map string device class names to SensorDeviceClass enum
_DEVICE_CLASS_MAP: dict[str, SensorDeviceClass] = {
    "battery": SensorDeviceClass.BATTERY,
    "distance": SensorDeviceClass.DISTANCE,
    "power": SensorDeviceClass.POWER,
    "duration": SensorDeviceClass.DURATION,
    "temperature": SensorDeviceClass.TEMPERATURE,
    "pressure": SensorDeviceClass.PRESSURE,
}

# Map string state class names to SensorStateClass enum
_STATE_CLASS_MAP: dict[str, SensorStateClass] = {
    "measurement": SensorStateClass.MEASUREMENT,
    "total": SensorStateClass.TOTAL,
    "total_increasing": SensorStateClass.TOTAL_INCREASING,
}


@dataclass(frozen=True, kw_only=True)
class BMWSensorEntityDescription(SensorEntityDescription):
    """Describe a BMW CarData sensor entity."""

    telemetry_key: str


def _friendly_name(telemetry_key: str) -> str:
    """Convert a BMW telemetry key to a friendly name.

    e.g. 'electricVehicle.chargingLevelHv' → 'Charging Level Hv'
    """
    # Take the last segment after the last dot
    name = telemetry_key.rsplit(".", 1)[-1]
    # Insert spaces before uppercase letters (camelCase → Camel Case)
    name = re.sub(r"(?<=[a-z])(?=[A-Z])", " ", name)
    return name.replace("_", " ").title()


def _build_descriptions(
    vehicle_data: VehicleData,
) -> list[BMWSensorEntityDescription]:
    """Build sensor descriptions from predefined map + dynamic discovery."""
    descriptions: list[BMWSensorEntityDescription] = []
    seen_keys: set[str] = set()

    # Predefined sensors from SENSOR_KEY_MAP
    for telemetry_key, (
        translation_key,
        unit,
        device_class_str,
        state_class_str,
        precision,
    ) in SENSOR_KEY_MAP.items():
        seen_keys.add(telemetry_key)
        descriptions.append(
            BMWSensorEntityDescription(
                key=translation_key,
                translation_key=translation_key,
                telemetry_key=telemetry_key,
                native_unit_of_measurement=unit,
                device_class=_DEVICE_CLASS_MAP.get(device_class_str) if device_class_str else None,
                state_class=_STATE_CLASS_MAP.get(state_class_str) if state_class_str else None,
                suggested_display_precision=precision,
            )
        )

    # Dynamic sensors for any telemetry keys not in the predefined map
    for telemetry_key, entry in vehicle_data.telemetry.items():
        if telemetry_key in seen_keys:
            continue
        # Skip keys that look like binary sensors (common values)
        if entry.value.upper() in (
            "OPEN", "CLOSED", "LOCKED", "UNLOCKED", "SECURED",
            "TRUE", "FALSE", "CONNECTED", "DISCONNECTED",
            "CHARGING", "NOT_CHARGING",
        ):
            continue

        # Try to parse as a number — only create sensor if it's numeric
        try:
            float(entry.value)
        except (ValueError, TypeError):
            continue

        safe_key = telemetry_key.replace(".", "_").lower()
        descriptions.append(
            BMWSensorEntityDescription(
                key=safe_key,
                translation_key=safe_key,
                telemetry_key=telemetry_key,
                native_unit_of_measurement=entry.unit,
                name=_friendly_name(telemetry_key),
                state_class=SensorStateClass.MEASUREMENT,
            )
        )

    return descriptions


async def async_setup_entry(
    hass: HomeAssistant,
    entry: BMWCarDataConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up BMW CarData sensor entities."""
    coordinator: BMWCarDataCoordinator = entry.runtime_data

    entities: list[BMWSensor] = []
    for vin, vehicle_data in coordinator.data.items():
        descriptions = _build_descriptions(vehicle_data)
        for desc in descriptions:
            entities.append(BMWSensor(coordinator, desc, vin, entry))

    async_add_entities(entities)


class BMWSensor(
    CoordinatorEntity[BMWCarDataCoordinator], SensorEntity
):
    """Representation of a BMW CarData sensor."""

    entity_description: BMWSensorEntityDescription
    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: BMWCarDataCoordinator,
        description: BMWSensorEntityDescription,
        vin: str,
        entry: BMWCarDataConfigEntry,
    ) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator)
        self.entity_description = description
        self._vin = vin
        self._attr_unique_id = f"{vin}_{description.key}"

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
    def native_value(self) -> float | str | None:
        """Return the sensor value."""
        if not self.coordinator.data:
            return None

        vehicle = self.coordinator.data.get(self._vin)
        if not vehicle:
            return None

        entry = vehicle.telemetry.get(self.entity_description.telemetry_key)
        if not entry:
            return None

        # Try to return as numeric value
        try:
            return float(entry.value)
        except (ValueError, TypeError):
            return entry.value
