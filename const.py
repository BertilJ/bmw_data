"""Constants for the BMW CarData integration."""

from __future__ import annotations

from typing import Final

# ── Integration ──────────────────────────────────────────────────────────────

DOMAIN: Final = "bmw_cardata"

PLATFORMS: Final = ["sensor", "binary_sensor", "device_tracker"]

# ── OAuth 2.0 Endpoints ─────────────────────────────────────────────────────

AUTH_BASE: Final = "https://customer.bmwgroup.com/gcdm/oauth"
DEVICE_CODE_URL: Final = f"{AUTH_BASE}/device/code"
TOKEN_URL: Final = f"{AUTH_BASE}/token"
OAUTH_SCOPES: Final = "authenticate_user openid cardata:api:read cardata:streaming:read"

# ── API ──────────────────────────────────────────────────────────────────────

API_BASE_URL: Final = "https://api-cardata.bmwgroup.com"
API_VERSION_HEADER: Final = "v1"

# ── MQTT Streaming ───────────────────────────────────────────────────────────

MQTT_BROKER: Final = "customer.streaming-cardata.bmwgroup.com"
MQTT_PORT: Final = 9000
MQTT_KEEPALIVE: Final = 30

# ── Rate Limiting ────────────────────────────────────────────────────────────

RATE_LIMIT_MAX_CALLS: Final = 50
RATE_LIMIT_WINDOW: Final = 86400  # 24 hours in seconds

# ── Polling / Timing ────────────────────────────────────────────────────────

DEFAULT_POLL_INTERVAL: Final = 2400  # 40 minutes
TOKEN_REFRESH_MARGIN: Final = 300  # Refresh 5 minutes before expiry

# ── MQTT Reconnection ───────────────────────────────────────────────────────

MQTT_RECONNECT_MIN: Final = 5
MQTT_RECONNECT_MAX: Final = 60

# ── Config Entry Keys ───────────────────────────────────────────────────────

CONF_CLIENT_ID: Final = "client_id"
CONF_CONTAINER_ID: Final = "container_id"

# ── Default Container Descriptors ────────────────────────────────────────────
#
# These are the telemetry data points requested when creating a container.
# Based on the BMW CarData API HV battery + general vehicle descriptors.

DEFAULT_CONTAINER_DESCRIPTORS: Final = [
    "vehicle.drivetrain.batteryManagement.header",
    "vehicle.drivetrain.electricEngine.charging.acAmpere",
    "vehicle.drivetrain.electricEngine.charging.acVoltage",
    "vehicle.drivetrain.electricEngine.charging.level",
    "vehicle.drivetrain.electricEngine.charging.status",
    "vehicle.drivetrain.electricEngine.remainingElectricRange",
    "vehicle.powertrain.electric.battery.charging.power",
    "vehicle.powertrain.electric.battery.stateOfCharge.target",
    "vehicle.drivetrain.electricEngine.charging.phaseNumber",
    "vehicle.drivetrain.batteryManagement.maxEnergy",
    "vehicle.vehicle.avgAuxPower",
    "vehicle.vehicleIdentification.basicVehicleData",
]

DEFAULT_CONTAINER_NAME: Final = "HA BMW CarData"
DEFAULT_CONTAINER_PURPOSE: Final = "Home Assistant telemetry"

# ── Telemetry Key → Sensor Mapping ──────────────────────────────────────────
#
# Each entry maps a BMW descriptor to a tuple of:
#   (translation_key, unit, device_class, state_class, precision)

SENSOR_KEY_MAP: Final[dict[str, tuple[str, str | None, str | None, str | None, int | None]]] = {
    # ── Battery / Charging ───────────────────────────────────────────────
    "vehicle.drivetrain.electricEngine.charging.level": (
        "battery_level", "%", "battery", "measurement", 0,
    ),
    "vehicle.drivetrain.electricEngine.remainingElectricRange": (
        "range_electric", "km", "distance", "measurement", 0,
    ),
    "vehicle.powertrain.electric.battery.charging.power": (
        "charging_power", "W", "power", "measurement", 0,
    ),
    "vehicle.drivetrain.electricEngine.charging.status": (
        "charging_status", None, None, None, None,
    ),
    "vehicle.powertrain.electric.battery.stateOfCharge.target": (
        "target_soc", "%", "battery", None, 0,
    ),
    "vehicle.drivetrain.batteryManagement.maxEnergy": (
        "max_battery_energy", "kWh", "energy_storage", None, 1,
    ),
    "vehicle.vehicle.avgAuxPower": (
        "avg_aux_power", "W", "power", "measurement", 0,
    ),
    # ── AC Charging Details ──────────────────────────────────────────────
    "vehicle.drivetrain.electricEngine.charging.acVoltage": (
        "charging_ac_voltage", "V", "voltage", "measurement", 0,
    ),
    "vehicle.drivetrain.electricEngine.charging.acAmpere": (
        "charging_ac_current", "A", "current", "measurement", 1,
    ),
    "vehicle.drivetrain.electricEngine.charging.phaseNumber": (
        "charging_phases", None, None, None, 0,
    ),
}

# ── Telemetry Key → Binary Sensor Mapping ────────────────────────────────────
#
# Each entry maps a BMW descriptor to a tuple of:
#   (translation_key, device_class, on_values)

BINARY_SENSOR_KEY_MAP: Final[dict[str, tuple[str, str | None, set[str]]]] = {
    "vehicle.drivetrain.electricEngine.charging.status": (
        "charging_active", "battery_charging", {"CHARGINGACTIVE"},
    ),
}
