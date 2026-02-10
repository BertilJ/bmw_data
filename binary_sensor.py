"""Binary sensor platform for BMW CarData integration."""

from __future__ import annotations

import logging
from dataclasses import dataclass

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
    BinarySensorEntityDescription,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from . import BMWCarDataConfigEntry
from .const import BINARY_SENSOR_KEY_MAP, DOMAIN
from .coordinator import BMWCarDataCoordinator

_LOGGER = logging.getLogger(__name__)

# Map string device class names to BinarySensorDeviceClass enum
_DEVICE_CLASS_MAP: dict[str, BinarySensorDeviceClass] = {
    "door": BinarySensorDeviceClass.DOOR,
    "window": BinarySensorDeviceClass.WINDOW,
    "lock": BinarySensorDeviceClass.LOCK,
    "battery_charging": BinarySensorDeviceClass.BATTERY_CHARGING,
    "plug": BinarySensorDeviceClass.PLUG,
}


@dataclass(frozen=True, kw_only=True)
class BMWBinarySensorEntityDescription(BinarySensorEntityDescription):
    """Describe a BMW CarData binary sensor entity."""

    telemetry_key: str
    on_values: frozenset[str]


def _build_descriptions() -> list[BMWBinarySensorEntityDescription]:
    """Build binary sensor descriptions from BINARY_SENSOR_KEY_MAP."""
    descriptions: list[BMWBinarySensorEntityDescription] = []

    for telemetry_key, (
        translation_key,
        device_class_str,
        on_values,
    ) in BINARY_SENSOR_KEY_MAP.items():
        descriptions.append(
            BMWBinarySensorEntityDescription(
                key=translation_key,
                translation_key=translation_key,
                telemetry_key=telemetry_key,
                device_class=_DEVICE_CLASS_MAP.get(device_class_str) if device_class_str else None,
                on_values=frozenset(on_values),
            )
        )

    return descriptions


async def async_setup_entry(
    hass: HomeAssistant,
    entry: BMWCarDataConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up BMW CarData binary sensor entities."""
    coordinator: BMWCarDataCoordinator = entry.runtime_data
    descriptions = _build_descriptions()

    entities: list[BMWBinarySensor] = []
    for vin in coordinator.data:
        for desc in descriptions:
            entities.append(BMWBinarySensor(coordinator, desc, vin, entry))

    async_add_entities(entities)


class BMWBinarySensor(
    CoordinatorEntity[BMWCarDataCoordinator], BinarySensorEntity
):
    """Representation of a BMW CarData binary sensor."""

    entity_description: BMWBinarySensorEntityDescription
    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: BMWCarDataCoordinator,
        description: BMWBinarySensorEntityDescription,
        vin: str,
        entry: BMWCarDataConfigEntry,
    ) -> None:
        """Initialize the binary sensor."""
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
    def is_on(self) -> bool | None:
        """Return True if the binary sensor is on."""
        if not self.coordinator.data:
            return None

        vehicle = self.coordinator.data.get(self._vin)
        if not vehicle:
            return None

        entry = vehicle.telemetry.get(self.entity_description.telemetry_key)
        if not entry:
            return None

        return entry.value in self.entity_description.on_values
