"""MQTT streaming client for BMW CarData real-time telemetry."""

from __future__ import annotations

import asyncio
import json
import logging
import ssl
from collections.abc import Callable
from typing import Any

from .const import (
    MQTT_BROKER,
    MQTT_KEEPALIVE,
    MQTT_PORT,
    MQTT_RECONNECT_MAX,
    MQTT_RECONNECT_MIN,
)

_LOGGER = logging.getLogger(__name__)

# Type for the callback invoked when new telemetry arrives
TelemetryCallback = Callable[[str, dict[str, Any]], None]


class BMWMQTTStream:
    """MQTT streaming client for real-time BMW vehicle telemetry.

    Connects to the BMW MQTT broker using the id_token for authentication.
    Subscribes to vehicle telemetry topics and invokes a callback on each
    message, allowing the coordinator to merge updates immediately.
    """

    def __init__(
        self,
        id_token: str,
        gcid: str,
        vins: list[str],
        callback: TelemetryCallback,
    ) -> None:
        """Initialize the MQTT stream.

        Args:
            id_token: BMW id_token for broker authentication.
            gcid: User's gcid (used as MQTT client-id prefix).
            vins: List of VINs to subscribe to.
            callback: Called with (vin, payload_dict) on each message.
        """
        self._id_token = id_token
        self._gcid = gcid
        self._vins = vins
        self._callback = callback
        self._task: asyncio.Task[None] | None = None
        self._stop_event = asyncio.Event()
        self._backoff = MQTT_RECONNECT_MIN

    def update_token(self, id_token: str) -> None:
        """Update the id_token for the next reconnection."""
        self._id_token = id_token

    async def start(self) -> None:
        """Start the MQTT streaming loop in a background task."""
        if self._task and not self._task.done():
            _LOGGER.debug("MQTT stream already running")
            return
        self._stop_event.clear()
        self._task = asyncio.create_task(self._run_loop())

    async def stop(self) -> None:
        """Stop the MQTT streaming loop."""
        self._stop_event.set()
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None

    @property
    def is_running(self) -> bool:
        """Return True if the stream task is active."""
        return self._task is not None and not self._task.done()

    async def _run_loop(self) -> None:
        """Run the MQTT connection loop with reconnection logic."""
        try:
            import aiomqtt
        except ImportError:
            _LOGGER.error(
                "aiomqtt is not installed. MQTT streaming is unavailable. "
                "Install with: pip install aiomqtt"
            )
            return

        while not self._stop_event.is_set():
            try:
                await self._connect_and_listen(aiomqtt)
                # Clean disconnect — reset backoff
                self._backoff = MQTT_RECONNECT_MIN
            except asyncio.CancelledError:
                raise
            except Exception:
                _LOGGER.exception(
                    "MQTT connection failed, reconnecting in %ds", self._backoff
                )
                try:
                    await asyncio.wait_for(
                        self._stop_event.wait(), timeout=self._backoff
                    )
                    # If we get here, stop was requested
                    return
                except asyncio.TimeoutError:
                    pass
                # Exponential backoff with cap
                self._backoff = min(self._backoff * 2, MQTT_RECONNECT_MAX)

    async def _connect_and_listen(self, aiomqtt: Any) -> None:
        """Connect to the MQTT broker and process messages."""
        ssl_context = ssl.create_default_context()

        client_id = f"{self._gcid}_ha"

        _LOGGER.debug(
            "Connecting to MQTT broker %s:%d as %s "
            "(gcid=%s, id_token=%s...%s, token_len=%d)",
            MQTT_BROKER,
            MQTT_PORT,
            client_id,
            self._gcid or "(empty)",
            self._id_token[:20] if self._id_token else "(empty)",
            self._id_token[-10:] if self._id_token else "",
            len(self._id_token) if self._id_token else 0,
        )

        async with aiomqtt.Client(
            hostname=MQTT_BROKER,
            port=MQTT_PORT,
            username=self._gcid,
            password=self._id_token,
            identifier=client_id,
            tls_context=ssl_context,
            keepalive=MQTT_KEEPALIVE,
        ) as client:
            _LOGGER.info("MQTT connected to %s", MQTT_BROKER)
            self._backoff = MQTT_RECONNECT_MIN

            # Subscribe to telemetry topics for each VIN
            for vin in self._vins:
                topic = f"cardata/{vin}/telemetry"
                await client.subscribe(topic)
                _LOGGER.debug("Subscribed to %s", topic)

            async for message in client.messages:
                if self._stop_event.is_set():
                    break
                self._handle_message(message)

    def _handle_message(self, message: Any) -> None:
        """Parse an MQTT message and invoke the callback."""
        try:
            topic = str(message.topic)
            payload = json.loads(message.payload.decode("utf-8"))

            # Extract VIN from topic: cardata/{vin}/telemetry
            parts = topic.split("/")
            if len(parts) >= 2:
                vin = parts[1]
            else:
                _LOGGER.warning("Unexpected topic format: %s", topic)
                return

            _LOGGER.debug("MQTT message for %s: %d entries", vin, len(payload) if isinstance(payload, list) else 1)
            self._callback(vin, payload)

        except (json.JSONDecodeError, UnicodeDecodeError) as err:
            _LOGGER.warning("Failed to parse MQTT message: %s", err)
        except Exception:
            _LOGGER.exception("Error handling MQTT message")
