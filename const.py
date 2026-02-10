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

DEFAULT_POLL_INTERVAL: Final = 1800  # 30 minutes
TOKEN_REFRESH_MARGIN: Final = 300  # Refresh 5 minutes before expiry

# ── MQTT Reconnection ───────────────────────────────────────────────────────

MQTT_RECONNECT_MIN: Final = 5
MQTT_RECONNECT_MAX: Final = 300

# ── Config Entry Keys ───────────────────────────────────────────────────────

CONF_CLIENT_ID: Final = "client_id"
CONF_ACCESS_TOKEN: Final = "access_token"
CONF_REFRESH_TOKEN: Final = "refresh_token"
CONF_ID_TOKEN: Final = "id_token"
CONF_TOKEN_EXPIRY: Final = "token_expiry"
CONF_GCID: Final = "gcid"
CONF_VEHICLES: Final = "vehicles"
CONF_CODE_VERIFIER: Final = "code_verifier"

# ── Telemetry Key → Sensor Mapping ──────────────────────────────────────────
#
# Each entry maps a BMW telemetry key to a tuple of:
#   (translation_key, unit, device_class, state_class, precision)
#
# These drive dynamic sensor creation in sensor.py.

SENSOR_KEY_MAP: Final[dict[str, tuple[str, str | None, str | None, str | None, int | None]]] = {
    # ── Electric / HV Battery ────────────────────────────────────────────
    "electricVehicle.chargingLevelHv": (
        "battery_level", "%", "battery", "measurement", 0,
    ),
    "electricVehicle.remainingRangeElectric": (
        "range_electric", "km", "distance", "measurement", 0,
    ),
    "electricVehicle.chargingPower": (
        "charging_power", "kW", "power", "measurement", 2,
    ),
    "electricVehicle.chargingTimeRemaining": (
        "charging_time_remaining", "min", "duration", None, 0,
    ),
    "electricVehicle.chargingStatus": (
        "charging_status", None, None, None, None,
    ),
    # ── Fuel (ICE / PHEV) ────────────────────────────────────────────────
    "fuel.remainingFuel": (
        "fuel_level", "L", None, "measurement", 1,
    ),
    "fuel.remainingRangeFuel": (
        "range_fuel", "km", "distance", "measurement", 0,
    ),
    # ── Combined Range ───────────────────────────────────────────────────
    "remainingRangeCombined": (
        "range_combined", "km", "distance", "measurement", 0,
    ),
    # ── Odometer ─────────────────────────────────────────────────────────
    "odometer": (
        "odometer", "km", "distance", "total_increasing", 0,
    ),
    # ── Tire Pressure (bar) ──────────────────────────────────────────────
    "tirePressure.frontLeft": (
        "tire_pressure_front_left", "bar", "pressure", "measurement", 1,
    ),
    "tirePressure.frontRight": (
        "tire_pressure_front_right", "bar", "pressure", "measurement", 1,
    ),
    "tirePressure.rearLeft": (
        "tire_pressure_rear_left", "bar", "pressure", "measurement", 1,
    ),
    "tirePressure.rearRight": (
        "tire_pressure_rear_right", "bar", "pressure", "measurement", 1,
    ),
    # ── Temperature ──────────────────────────────────────────────────────
    "outsideTemperature": (
        "outside_temperature", "°C", "temperature", "measurement", 1,
    ),
}

# ── Telemetry Key → Binary Sensor Mapping ────────────────────────────────────
#
# Each entry maps a BMW telemetry key to a tuple of:
#   (translation_key, device_class, on_values)
#
# on_values is a set of raw string values considered "on" / True.

BINARY_SENSOR_KEY_MAP: Final[dict[str, tuple[str, str | None, set[str]]]] = {
    # ── Doors ────────────────────────────────────────────────────────────
    "doors.driverFront": (
        "door_driver_front", "door", {"OPEN"},
    ),
    "doors.driverRear": (
        "door_driver_rear", "door", {"OPEN"},
    ),
    "doors.passengerFront": (
        "door_passenger_front", "door", {"OPEN"},
    ),
    "doors.passengerRear": (
        "door_passenger_rear", "door", {"OPEN"},
    ),
    # ── Windows ──────────────────────────────────────────────────────────
    "windows.driverFront": (
        "window_driver_front", "window", {"OPEN", "INTERMEDIATE"},
    ),
    "windows.driverRear": (
        "window_driver_rear", "window", {"OPEN", "INTERMEDIATE"},
    ),
    "windows.passengerFront": (
        "window_passenger_front", "window", {"OPEN", "INTERMEDIATE"},
    ),
    "windows.passengerRear": (
        "window_passenger_rear", "window", {"OPEN", "INTERMEDIATE"},
    ),
    # ── Hood / Trunk ─────────────────────────────────────────────────────
    "hood": (
        "hood", "door", {"OPEN"},
    ),
    "trunk": (
        "trunk", "door", {"OPEN"},
    ),
    # ── Lock State ───────────────────────────────────────────────────────
    "doorLockState": (
        "locked", "lock", {"LOCKED", "SECURED"},
    ),
    # ── Charging ─────────────────────────────────────────────────────────
    "electricVehicle.chargingActive": (
        "charging_active", "battery_charging", {"true", "TRUE", "CHARGING"},
    ),
    "electricVehicle.pluggedIn": (
        "plugged_in", "plug", {"true", "TRUE", "CONNECTED"},
    ),
}
