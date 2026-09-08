"""NAD setup flow for Unfolded Circle integration."""
import logging
from typing import Any

from ucapi import RequestUserInput
from ucapi_framework import BaseSetupFlow, DiscoveredDevice

from client import NADClient
from config import NADDeviceConfig

_LOG = logging.getLogger(__name__)

DEFAULT_PORT = 23


class NADSetupFlow(BaseSetupFlow[NADDeviceConfig]):
    """Setup flow for NAD integration: auto-discovery with manual fallback."""

    def get_manual_entry_form(self) -> RequestUserInput:
        return RequestUserInput(
            {"en": "NAD Receiver Setup", "nl": "NAD Receiver Instellen"},
            [
                {
                    "id": "name",
                    "label": {"en": "Device Name", "nl": "Apparaat Naam"},
                    "field": {"text": {"value": "NAD Receiver"}},
                },
                {
                    "id": "host",
                    "label": {"en": "IP Address", "nl": "IP Adres"},
                    "field": {"text": {"value": ""}},
                },
                {
                    "id": "port",
                    "label": {"en": "Port", "nl": "Poort"},
                    "field": {"number": {"value": DEFAULT_PORT, "min": 1, "max": 65535}},
                },
            ],
        )

    async def prepare_input_from_discovery(
        self, discovered: DiscoveredDevice, additional_input: dict[str, Any]
    ) -> dict[str, Any]:
        port = (discovered.extra_data or {}).get("port", DEFAULT_PORT)
        return {
            "name": discovered.name,
            "host": discovered.address,
            "port": port,
        }

    async def query_device(
        self, input_values: dict[str, Any]
    ) -> NADDeviceConfig | RequestUserInput:
        host = input_values.get("host", "").strip()
        if not host:
            raise ValueError("IP address is required")

        name = input_values.get("name", "").strip() or f"NAD Receiver ({host})"

        port = input_values.get("port", DEFAULT_PORT)
        if isinstance(port, str):
            try:
                port = int(port)
            except ValueError:
                port = DEFAULT_PORT

        _LOG.info("Verifying NAD receiver at %s:%d", host, port)

        client = NADClient(host=host, port=port)
        try:
            connected = await client.connect()
            if not connected:
                raise ValueError(
                    f"Could not reach a NAD receiver at {host}:{port}. "
                    "Please verify the device is powered on, reachable, and has Telnet enabled."
                )
        finally:
            await client.close()

        return NADDeviceConfig(
            identifier=host.replace(".", "_"),
            name=name,
            host=host,
            port=port,
            monitor_power=True,
        )
