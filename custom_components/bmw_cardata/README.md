# BMW CarData – Home Assistant Integration

Custom Home Assistant integration for the **official BMW Car Data API**.

## Prerequisites

1. **BMW Car Data Portal account** — Register at [BMW Car Data Portal](https://cardata.bmwgroup.com/)
2. **Client ID** — Create an application in the portal to get your `client_id`
3. **Vehicle requirements** — Your BMW must have an active SIM card, Connected Drive contract, and be sold in a supported (EU) market
4. **PRIMARY user** — Only the primary user registered for the vehicle can access telemetry data

## Installation

1. Copy `custom_components/bmw_cardata/` to your Home Assistant `custom_components/` directory
2. Restart Home Assistant
3. Go to **Settings → Devices & Services → Add Integration → BMW CarData**
4. Enter your BMW Client ID
5. A verification URL and code will be shown — open the URL on any device and enter the code
6. Once authorized, your vehicles will be discovered automatically

## Features

### Data Sources

- **REST API** — Polls vehicle data every 30 minutes (50 calls/day limit)
- **MQTT Streaming** — Real-time push updates when vehicle state changes

### Entities

| Platform | Entities |
|----------|----------|
| **Sensor** | Battery level, electric/fuel range, odometer, charging power, tire pressure, outside temperature |
| **Binary Sensor** | Door/window/trunk/hood open, locked state, charging active, plugged in |
| **Device Tracker** | GPS location |

All entities are grouped under a single device per vehicle (identified by VIN).

### Dynamic Discovery

Telemetry keys not in the predefined map are automatically discovered and created as entities if they have numeric values.

## Rate Limiting

The BMW API allows **50 REST requests per 24 hours**. The integration:
- Polls every 30 minutes (48 calls/day for a single vehicle)
- Uses a rolling 24-hour window to track calls
- Gracefully skips REST polls when budget is exhausted
- MQTT streaming is unaffected by REST rate limits

## Re-authentication

Access tokens expire after 1 hour (auto-refreshed). Refresh tokens expire after 14 days. If the refresh token expires, Home Assistant will show a notification to re-authenticate.

## Diagnostics

Go to **Settings → Devices & Services → BMW CarData → 3 dots → Download diagnostics** for a redacted diagnostic dump useful for troubleshooting.


This is the URL how to set things up: https://www.bmw.co.uk/en-gb/mybmw/vehicle-overview (in English) and to get the 