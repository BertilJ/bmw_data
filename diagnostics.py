"""Diagnostics support for BMW CarData integration."""

from __future__ import annotations

from typing import Any

from homeassistant.core import HomeAssistant

from . import BMWCarDataConfigEntry
from .coordinator import BMWCarDataCoordinator

REDACT_KEYS = {"access_token", "refresh_token", "id_token", "gcid", "code_verifier"}


def _redact(data: dict[str, Any]) -> dict[str, Any]:
    """Redact sensitive values from a dict."""
    return {
        k: "**REDACTED**" if k in REDACT_KEYS else v
        for k, v in data.items()
    }


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: BMWCarDataConfigEntry
) -> dict[str, Any]:
    """Return diagnostics for a config entry."""
    coordinator: BMWCarDataCoordinator = entry.runtime_data

    # Redact sensitive data from config entry
    config_data = _redact(dict(entry.data))
    if "tokens" in config_data and isinstance(config_data["tokens"], dict):
        config_data["tokens"] = _redact(config_data["tokens"])

    # Build vehicle diagnostics
    vehicles: dict[str, Any] = {}
    for vin, vehicle_data in coordinator.data.items():
        vehicles[vin] = {
            "basic": {
                "brand": vehicle_data.basic.brand,
                "model": vehicle_data.basic.model,
                "propulsion": vehicle_data.basic.propulsion,
                "construction_year": vehicle_data.basic.construction_year,
            },
            "telemetry_count": len(vehicle_data.telemetry),
            "telemetry_keys": sorted(vehicle_data.telemetry.keys()),
            "rest_updated": vehicle_data.rest_updated,
            "mqtt_updated": vehicle_data.mqtt_updated,
        }

    return {
        "config_entry": config_data,
        "remaining_api_calls": coordinator.remaining_api_calls,
        "vehicles": vehicles,
    }
