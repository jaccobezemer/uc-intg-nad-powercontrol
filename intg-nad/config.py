"""Configuration for NAD devices, backed by ucapi_framework's BaseConfigManager."""
from dataclasses import dataclass


@dataclass
class NADDeviceConfig:
    """NAD device configuration."""

    identifier: str = ""
    name: str = ""
    host: str = ""
    port: int = 23
    monitor_power: bool = True
