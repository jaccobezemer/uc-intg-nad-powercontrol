"""NAD Remote entity implementation."""
import asyncio
import logging
from typing import Any, Optional

from ucapi import Remote, StatusCodes
from ucapi.remote import (
    Attributes,
    Commands,
    Features,
    States,
)

from client import NADClient

_LOG = logging.getLogger(__name__)


class NADRemote(Remote):
    """NAD Receiver Remote entity."""

    def __init__(self, host: str, port: int = 23, name: str = "NAD Receiver", api=None, monitor_power: bool = True):
        """
        Initialize NAD remote.

        Args:
            host: NAD receiver IP address
            port: Telnet port (default 23)
            name: Device name (from setup)
            api: Integration API instance
            monitor_power: Enable continuous power state monitoring
        """
        self.host = host
        self.port = port
        self._api = api
        self.entity_id = f"nad_{host.replace('.', '_')}"
        self._monitor_power = monitor_power

        self.client = NADClient(host=host, port=port)

        # Current status
        self._state = States.OFF

        # Create the remote entity with command handler
        # Note: Entity class auto-converts string name to {"en": name}
        super().__init__(
            identifier=self.entity_id,
            name=name,  # Pass as string - Entity class handles dict conversion
            features=[
                Features.ON_OFF,
                Features.TOGGLE,
            ],
            attributes={
                Attributes.STATE: self._state,
            },
            simple_commands=["POWER_ON", "POWER_OFF", "POWER_TOGGLE"],
            cmd_handler=self._handle_command,
        )
        # Note: self.name is now {"en": name} dict as set by Entity.__init__

    async def connect(self) -> bool:
        """Connect to NAD receiver."""
        _LOG.info(f"Connecting to NAD receiver at {self.host}:{self.port}")

        try:
            connected = await self.client.connect()

            if not connected:
                _LOG.error(f"Could not connect to NAD receiver at {self.host}")
                return False

            # Fetch initial status
            await self.update_status()

            # Get receiver info for logging (don't use for naming anymore)
            model = await self.client.get_model()
            version = await self.client.get_version()
            _LOG.debug(f"Model response: {model}, Version response: {version}")
            _LOG.info(f"Connected to NAD receiver at {self.host} (model: {model}, firmware: {version})")

            # Start power monitoring if enabled
            if self._monitor_power:
                _LOG.info("Starting power state monitoring")
                self.client.start_power_monitoring(self._on_power_change)

            return True

        except Exception as e:
            _LOG.error(f"Error connecting: {e}", exc_info=True)
            return False

    async def disconnect(self):
        """Disconnect from device."""
        _LOG.info(f"Disconnecting from NAD receiver at {self.host}")

        # Stop power monitoring if running
        if self._monitor_power:
            await self.client.stop_power_monitoring()

        await self.client.close()

    async def _on_power_change(self, power_on: bool):
        """
        Callback when power state changes.

        Args:
            power_on: True if power is on, False if off
        """
        _LOG.info(f"Power state changed externally: {'ON' if power_on else 'OFF'}")
        self._state = States.ON if power_on else States.OFF
        await self.update_attributes()

    async def update_status(self):
        """Update device status from receiver."""
        try:
            # Get power state
            power = await self.client.get_power()
            if power is not None:
                self._state = States.ON if power else States.OFF

            await self.update_attributes()

        except Exception as e:
            _LOG.error(f"Error updating status: {e}", exc_info=True)

    async def update_attributes(self):
        """Update entity attributes."""
        if self._api:
            attributes = {
                Attributes.STATE: self._state,
            }

            self._api.configured_entities.update_attributes(
                self.entity_id,
                attributes
            )

    async def _handle_command(self, entity_id: str, command: str, params: dict[str, Any] | None = None) -> StatusCodes:
        """
        Handle remote commands.

        Args:
            entity_id: The ID of the entity receiving the command
            command: The command to execute
            params: Optional parameters

        Returns:
            StatusCode of the operation
        """
        _LOG.info(f"Command received: {command} with params: {params}")

        try:
            if command == Commands.ON:
                await self.client.set_power(True)

            elif command == Commands.OFF:
                await self.client.set_power(False)

            elif command == Commands.TOGGLE:
                power = await self.client.get_power()
                if power is not None:
                    await self.client.set_power(not power)

            elif command == Commands.SEND_CMD:
                # Handle simple commands
                if params and "command" in params:
                    cmd = params["command"]
                    if cmd == "POWER_ON":
                        await self.client.set_power(True)
                    elif cmd == "POWER_OFF":
                        await self.client.set_power(False)
                    elif cmd == "POWER_TOGGLE":
                        power = await self.client.get_power()
                        if power is not None:
                            await self.client.set_power(not power)

            # Update status after command
            await asyncio.sleep(0.1)
            await self.update_status()

            return StatusCodes.OK

        except Exception as e:
            _LOG.error(f"Error executing command {command}: {e}")
            return StatusCodes.SERVER_ERROR
