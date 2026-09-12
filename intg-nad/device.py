"""NAD device implementation using ucapi_framework's PollingDevice."""
import asyncio
import logging
from typing import Any

from ucapi_framework import PollingDevice

from client import NADClient
from config import NADDeviceConfig

_LOG = logging.getLogger(__name__)

# Periodic backup poll interval (matches the original 5-minute poll). Unsolicited
# power changes are pushed immediately via the client's own monitoring callback,
# this is just a safety net in case an update is missed.
POLL_INTERVAL = 300


class NADDevice(PollingDevice):
    """NAD receiver wrapped as a framework PollingDevice."""

    def __init__(self, device_config: NADDeviceConfig, **kwargs: Any) -> None:
        super().__init__(device_config, poll_interval=POLL_INTERVAL, **kwargs)
        self._device_config = device_config
        self.client = NADClient(host=device_config.host, port=device_config.port)
        self._monitor_power = device_config.monitor_power
        self._state: str = "OFF"
        self._connect_lock = asyncio.Lock()

    # -- Identity ---------------------------------------------------------

    @property
    def identifier(self) -> str:
        return self._device_config.identifier

    @property
    def name(self) -> str:
        return self._device_config.name

    @property
    def address(self) -> str:
        return self._device_config.host

    @property
    def log_id(self) -> str:
        return f"{self.name} ({self.address})"

    # -- State ------------------------------------------------------------

    @property
    def state(self) -> str:
        return self._state

    # -- Connection ---------------------------------------------------------

    async def establish_connection(self) -> None:
        _LOG.info("[%s] Connecting to NAD receiver", self.log_id)

        connected = await self.client.connect()
        if not connected:
            raise ConnectionError(f"Cannot reach NAD receiver at {self.address}:{self._device_config.port}")

        # Force a push here: the framework marks the entity UNAVAILABLE on any
        # prior disconnect/error independently of our own state tracking, so a
        # reconnect must unconditionally re-announce the current state rather
        # than rely on the "did state change" gate poll_device() uses - by the
        # time the next poll runs, self._state already matches, so it would
        # never push and the entity would stay stuck UNAVAILABLE.
        await self._refresh_status(push=True, force=True)

        model = await self.client.get_model()
        version = await self.client.get_version()
        _LOG.info("[%s] Connected (model: %s, firmware: %s)", self.log_id, model, version)

        if self._monitor_power:
            self.client.start_power_monitoring(self._on_power_change)

    async def disconnect(self) -> None:
        await super().disconnect()
        if self._monitor_power:
            await self.client.stop_power_monitoring()
        await self.client.close()
        self._state = "UNAVAILABLE"

    # -- Updates ------------------------------------------------------------

    async def poll_device(self) -> None:
        await self._refresh_status(push=True)

    async def _refresh_status(self, push: bool, force: bool = False) -> None:
        power = await self.client.get_power()
        if power is None:
            return
        new_state = "ON" if power else "OFF"
        changed = new_state != self._state
        self._state = new_state
        if push and (changed or force):
            self.push_update()

    async def _on_power_change(self, power_on: bool) -> None:
        """Callback from the client's own monitoring loop on unsolicited power updates."""
        self._state = "ON" if power_on else "OFF"
        self.push_update()

    # -- Commands -------------------------------------------------------------

    async def _ensure_connected(self) -> bool:
        """Reconnect on demand before a command, rather than failing instantly.

        Commands arrive independently of the driver's background reconnect
        (e.g. right after the Remote wakes from standby, before WiFi has
        re-associated). Without this, a command sent while the telnet
        connection is down fails immediately with no chance to succeed,
        instead of waiting the moment it takes for the network to come back.
        """
        if self.is_connected:
            return True
        async with self._connect_lock:
            if self.is_connected:
                return True
            return await self.connect()

    async def set_power(self, on: bool) -> bool:
        if not await self._ensure_connected():
            return False
        ok = await self.client.set_power(on)
        if ok:
            self._state = "ON" if on else "OFF"
        return ok

    async def toggle_power(self) -> bool:
        if not await self._ensure_connected():
            return False
        power = await self.client.get_power()
        if power is None:
            return False
        return await self.set_power(not power)
