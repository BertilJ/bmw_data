"""The BMW CarData integration."""

from __future__ import annotations

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .api import VehicleBasicData
from .auth import TokenResponse
from .const import PLATFORMS
from .coordinator import BMWCarDataCoordinator

_LOGGER = logging.getLogger(__name__)

type BMWCarDataConfigEntry = ConfigEntry[BMWCarDataCoordinator]


async def async_setup_entry(
    hass: HomeAssistant, entry: BMWCarDataConfigEntry
) -> bool:
    """Set up BMW CarData from a config entry."""
    # Restore tokens from config entry
    token_data = entry.data.get("tokens", {})
    if not token_data:
        _LOGGER.error("No token data in config entry — cannot set up")
        return False

    tokens = TokenResponse.from_dict(token_data)

    # Restore vehicle list from config entry
    vehicle_list = entry.data.get("vehicles", [])
    vehicles = [
        VehicleBasicData(
            vin=v["vin"],
            brand=v.get("brand", "BMW"),
            model=v.get("model", "Unknown"),
            propulsion=v.get("propulsion", ""),
            construction_year=v.get("construction_year"),
        )
        for v in vehicle_list
    ]

    if not vehicles:
        _LOGGER.error("No vehicles in config entry — cannot set up")
        return False

    _LOGGER.debug(
        "Setting up BMW CarData with %d vehicle(s): %s",
        len(vehicles),
        [(v.vin, v.model) for v in vehicles],
    )

    # Create the coordinator
    coordinator = BMWCarDataCoordinator(hass, entry, vehicles, tokens)

    # Perform first REST data refresh
    await coordinator.async_config_entry_first_refresh()

    # Store coordinator on the entry for entity platforms to access
    entry.runtime_data = coordinator

    # Start MQTT streaming for real-time updates
    await coordinator.start_mqtt()

    # Forward setup to entity platforms
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    return True


async def async_unload_entry(
    hass: HomeAssistant, entry: BMWCarDataConfigEntry
) -> bool:
    """Unload a BMW CarData config entry."""
    coordinator: BMWCarDataCoordinator = entry.runtime_data

    # Stop MQTT streaming
    await coordinator.stop_mqtt()

    # Unload entity platforms
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
