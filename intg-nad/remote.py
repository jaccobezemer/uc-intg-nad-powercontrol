"""NAD remote entity."""
import asyncio
import logging
from typing import Any

from ucapi import remote, StatusCodes
from ucapi_framework import RemoteEntity

from config import NADDeviceConfig
from device import NADDevice

_LOG = logging.getLogger(__name__)

FEATURES = [
    remote.Features.ON_OFF,
    remote.Features.TOGGLE,
]

_STATE_MAP = {
    "ON": remote.States.ON,
    "OFF": remote.States.OFF,
    "UNAVAILABLE": remote.States.UNAVAILABLE,
}


class NADRemoteEntity(RemoteEntity):
    """Remote entity for NAD receivers (power control only)."""

    def __init__(self, device_config: NADDeviceConfig, device: NADDevice) -> None:
        self._device = device
        # Keep the original entity ID scheme ("nad_<host>", no dot) so
        # upgrading never breaks existing activity references - see
        # NADDriver.device_from_entity_id() for the matching parse side.
        entity_id = f"nad_{device_config.identifier}"
        super().__init__(
            entity_id,
            device_config.name,
            features=FEATURES,
            attributes={
                remote.Attributes.STATE: remote.States.UNKNOWN,
            },
            simple_commands=["POWER_ON", "POWER_OFF", "POWER_TOGGLE"],
            cmd_handler=self._handle_command,
        )
        self.subscribe_to_device(device)

    async def sync_state(self) -> None:
        d = self._device
        self.set_state(_STATE_MAP.get(d.state, remote.States.UNKNOWN), update=True)

    async def _handle_command(
        self, entity: remote.Remote, cmd_id: str, params: dict[str, Any] | None
    ) -> StatusCodes:
        try:
            return await self._dispatch_command(cmd_id, params)
        except Exception as err:  # pylint: disable=broad-except
            _LOG.error("[%s] Command error: %s", self.id, err)
            return StatusCodes.SERVER_ERROR

    async def _dispatch_command(self, cmd_id: str, params: dict[str, Any] | None) -> StatusCodes:
        d = self._device

        if cmd_id == remote.Commands.ON:
            ok = await d.set_power(True)
        elif cmd_id == remote.Commands.OFF:
            ok = await d.set_power(False)
        elif cmd_id == remote.Commands.TOGGLE:
            ok = await d.toggle_power()
        elif cmd_id == remote.Commands.SEND_CMD:
            simple_cmd = (params or {}).get("command")
            if simple_cmd == "POWER_ON":
                ok = await d.set_power(True)
            elif simple_cmd == "POWER_OFF":
                ok = await d.set_power(False)
            elif simple_cmd == "POWER_TOGGLE":
                ok = await d.toggle_power()
            else:
                return StatusCodes.BAD_REQUEST
        else:
            return StatusCodes.NOT_IMPLEMENTED

        # Push the new state immediately rather than waiting for the next poll.
        await asyncio.sleep(0.1)
        await self.sync_state()

        return StatusCodes.OK if ok else StatusCodes.SERVER_ERROR
