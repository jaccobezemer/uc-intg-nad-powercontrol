"""NAD receiver discovery via mDNS/Zeroconf, using ucapi_framework's MDNSDiscovery."""
import logging
import socket
from typing import Any

from ucapi_framework import DiscoveredDevice, MDNSDiscovery

_LOG = logging.getLogger(__name__)

# NAD receivers with BluOS advertise the same mDNS service type as other BluOS players.
NAD_SERVICE_TYPE = "_musc._tcp.local."
DEFAULT_PORT = 23


class NADDiscovery(MDNSDiscovery):
    """mDNS-based NAD (BluOS) receiver discovery."""

    def __init__(self, timeout: int = 5):
        """Initialize NAD discovery.

        Args:
            timeout: Discovery timeout in seconds
        """
        super().__init__(NAD_SERVICE_TYPE, timeout=timeout)

    def parse_mdns_service(self, service_info: Any) -> DiscoveredDevice | None:
        """Parse an mDNS service announcement into a DiscoveredDevice."""
        if not service_info.addresses:
            _LOG.warning("No address for service %s", service_info.name)
            return None

        host = socket.inet_ntoa(service_info.addresses[0])

        props: dict[str, str] = {}
        if service_info.properties:
            for key, value in service_info.properties.items():
                try:
                    key_str = key.decode("utf-8") if isinstance(key, bytes) else key
                    value_str = value.decode("utf-8") if isinstance(value, bytes) else value
                    props[key_str] = value_str
                except (UnicodeDecodeError, AttributeError):
                    pass

        # Derive a readable name from the mDNS instance name, e.g. "Living Room._musc._tcp.local."
        name = service_info.name.replace(f".{NAD_SERVICE_TYPE}", "").replace(".", " ").strip()
        if not name:
            name = "NAD"

        # Only prepend the model name if it isn't already part of the device name
        model = props.get("model")
        if model and model not in name:
            name = f"{model} - {name}"

        name = f"{name} Remote"

        _LOG.info("Discovered NAD device: %s at %s", name, host)

        return DiscoveredDevice(
            identifier=host.replace(".", "_"),
            name=name,
            address=host,
            extra_data={"port": DEFAULT_PORT},
        )
