#!/usr/bin/env python3
"""NAD Receiver Integration Driver for Unfolded Circle Remote 3."""
import asyncio
import logging
import os
import sys
import json

import ucapi
from remote import NADRemote
from config import Config, NADdevice
from discovery import NADDeviceDiscovery

_LOG = logging.getLogger(__name__)

# Configuration - initialized in main()
api: ucapi.IntegrationAPI = None
config: Config = None
discovery: NADDeviceDiscovery = None

# Global device instances - managed by device_id
nad_devices: dict[str, NADRemote] = {}

# Discovery cache - stores discovered devices
discovered_devices: dict[str, dict] = {}

async def add_device(device_config: NADdevice) -> bool:
    """
    Add a NAD device.

    Args:
        device_config: Device configuration

    Returns:
        True if successful
    """
    global nad_devices

    _LOG.info(f"Adding NAD device: {device_config.device_id} ({device_config.name})")
    _LOG.debug(f"  Address: {device_config.address}:{device_config.port}")
    _LOG.debug(f"  Monitor power: {device_config.monitor_power}")

    device = NADRemote(
        host=device_config.address,
        port=device_config.port,
        name=device_config.name,
        api=api,
        monitor_power=device_config.monitor_power
    )
    _LOG.debug(f"  NADRemote instance created with entity_id: {device.entity_id}")

    # Connect to NAD device
    _LOG.debug(f"  Attempting to connect to NAD receiver...")
    connected = await device.connect()

    if not connected:
        _LOG.error(f"Could not connect to NAD device {device_config.device_id}")
        return False

    _LOG.debug(f"  Connection successful!")

    # Store device
    nad_devices[device_config.device_id] = device
    _LOG.debug(f"  Stored in nad_devices dict")

    # Add entity to available_entities (user subscribes via UC Remote UI)
    _LOG.debug(f"  Adding to api.available_entities...")
    api.available_entities.add(device)

    _LOG.info(f"NAD device added successfully: {device_config.device_id}")
    _LOG.debug(f"  Entity ID: {device.entity_id}")
    _LOG.debug(f"  Device name: {device_config.name}")
    return True


async def remove_device(device_id: str) -> bool:
    """
    Remove a NAD device.

    Args:
        device_id: Device identifier

    Returns:
        True if successful
    """
    global nad_devices

    if device_id not in nad_devices:
        _LOG.warning(f"Device not found: {device_id}")
        return False

    device = nad_devices[device_id]

    # Disconnect device
    await device.disconnect()

    # Remove entity
    entity_id = device.entity_id
    api.configured_entities.remove(entity_id)
    api.available_entities.remove(entity_id)

    # Remove from dictionary
    del nad_devices[device_id]

    _LOG.info(f"NAD device removed: {device_id}")
    return True

async def main(loop: asyncio.AbstractEventLoop):
    """Start the integration driver."""
    global api, config
    logging.basicConfig(
        level=logging.DEBUG,
        format="%(asctime)s | %(levelname)-8s | %(name)-25s | %(message)s"
    )

    # Set specific loggers to appropriate levels
    logging.getLogger("ucapi").setLevel(logging.DEBUG)
    logging.getLogger("ucapi.api").setLevel(logging.DEBUG)
    logging.getLogger("ucapi.entities").setLevel(logging.DEBUG)
    logging.getLogger("websockets").setLevel(logging.WARNING)
    logging.getLogger("client").setLevel(logging.DEBUG)
    logging.getLogger("remote").setLevel(logging.DEBUG)
    logging.getLogger("config").setLevel(logging.DEBUG)
    logging.getLogger("__main__").setLevel(logging.DEBUG)

    # Load version from driver.json
    driver_json_path = os.path.join(os.path.dirname(__file__), "..", "driver.json")
    try:
        with open(driver_json_path, 'r', encoding='utf-8') as f:
            driver_info = json.load(f)
            version = driver_info.get("version", "unknown")
    except Exception as e:
        _LOG.warning(f"Could not load version from driver.json: {e}")
        version = "unknown"

    _LOG.info(f"NAD Telnet Integration starting (v{version})")

    # Use the provided event loop
    api = ucapi.IntegrationAPI(loop)

    # Initialize configuration manager
    config_dir = os.environ.get("UC_CONFIG_HOME", os.path.expanduser("~/.config/uc-nad"))
    config = Config(config_dir)
    _LOG.info(f"Configuration loaded: {len(config.all_devices())} devices")

    # Initialize discovery
    discovery = NADDeviceDiscovery()

    # Load previously configured devices BEFORE api.init()
    # This ensures entities are available immediately after driver starts
    for device_config in config.enabled_devices():
        _LOG.info(f"Loading device from config: {device_config.device_id}")
        await add_device(device_config)

    # Event handlers
    @api.listens_to(ucapi.Events.CONNECT)
    async def on_connect() -> None:
        """Handle connect event."""
        _LOG.info("UC Remote 3 connected")
        await api.set_device_state(ucapi.DeviceStates.CONNECTED)

    @api.listens_to(ucapi.Events.DISCONNECT)
    async def on_disconnect() -> None:
        """Handle disconnect event."""
        _LOG.info("UC Remote 3 disconnected")

        # Stop discovery
        if discovery:
            await discovery.stop()

        # Disconnect all devices
        for device in nad_devices.values():
            await device.disconnect()

    @api.listens_to(ucapi.Events.ENTER_STANDBY)
    async def on_standby() -> None:
        """Handle standby event."""
        _LOG.info("UC Remote 3 entering standby")

    @api.listens_to(ucapi.Events.EXIT_STANDBY)
    async def on_exit_standby() -> None:
        """Handle exit standby event - reconnect devices with monitoring enabled."""
        _LOG.info("UC Remote 3 exiting standby")

        # Wait for network to become available after standby
        _LOG.info("Waiting 3 seconds for network to stabilize...")
        await asyncio.sleep(3)

        # Reconnect devices that have power monitoring enabled
        for device_id, device in nad_devices.items():
            if device._monitor_power:
                _LOG.info(f"Reconnecting device {device_id} after standby")

                # Stop monitoring to prevent race conditions, will restart after reconnect
                if device.client._monitoring:
                    _LOG.debug(f"Stopping power monitoring for clean reconnect")
                    await device.client.stop_power_monitoring()

                # Always disconnect and reconnect to ensure clean state
                await device.disconnect()

                # Try up to 3 times with increasing delays
                max_attempts = 3
                for attempt in range(1, max_attempts + 1):
                    try:
                        _LOG.info(f"Attempt {attempt}/{max_attempts}: Connecting to {device_id}")
                        connected = await device.connect()
                        if connected:
                            _LOG.info(f"Device {device_id} reconnected and power state refreshed")
                            break
                        else:
                            _LOG.warning(f"Connection attempt {attempt} failed for {device_id}")
                    except Exception as e:
                        _LOG.warning(f"Reconnection attempt {attempt} failed for {device_id}: {e}")

                    # Wait before retry (except on last attempt)
                    if attempt < max_attempts:
                        wait_time = attempt * 2  # 2, 4 seconds
                        _LOG.info(f"Waiting {wait_time} seconds before retry...")
                        await asyncio.sleep(wait_time)
                else:
                    _LOG.error(f"Failed to reconnect device {device_id} after {max_attempts} attempts")

    @api.listens_to(ucapi.Events.SUBSCRIBE_ENTITIES)
    async def on_subscribe_entities(entity_ids: list[str]) -> None:
        """Handle entity subscription - fetch status on-demand."""
        _LOG.info(f"Subscribe entities: {entity_ids}")
        for entity_id in entity_ids:
            if entity_id in nad_devices:
                device = nad_devices[entity_id]
                try:
                    await device.update_status()
                    _LOG.debug(f"Updated status for {entity_id} on subscribe")
                except Exception as e:
                    _LOG.warning(f"Failed to update status for {entity_id}: {e}")

    @api.listens_to(ucapi.Events.UNSUBSCRIBE_ENTITIES)
    async def on_unsubscribe_entities(entity_ids: list[str]) -> None:
        """Handle entity unsubscribe."""
        _LOG.info(f"Unsubscribe entities: {entity_ids}")
        
    # Setup handler dispatcher
    async def driver_setup_handler(msg: ucapi.SetupDriver) -> ucapi.SetupAction:
        """
        Dispatch driver setup requests to corresponding handlers.

        :param msg: the setup driver request object, either DriverSetupRequest or UserDataResponse
        :return: the setup action on how to continue
        """
        if isinstance(msg, ucapi.DriverSetupRequest):
            return await handle_driver_setup(msg)
        if isinstance(msg, ucapi.UserDataResponse):
            return await handle_user_data_response(msg)

        _LOG.error(f"Unknown setup message type: {type(msg)}")
        return ucapi.SetupError()

    async def configure_device(name: str, host: str, port: int, monitor_power: bool = False) -> ucapi.SetupAction:
        """
        Configure a NAD device with the given parameters.

        Args:
            name: Device name
            host: IP address
            port: Telnet port
            monitor_power: Enable power state monitoring

        Returns:
            SetupComplete on success, SetupError on failure
        """
        _LOG.info(f"Configuring NAD receiver '{name}' at {host}:{port} (monitor_power={monitor_power})")

        # Create device_id from IP address
        device_id = f"nad_{host.replace('.', '_')}"

        # Check if already configured
        if device_id in nad_devices:
            _LOG.info(f"Device {device_id} already configured")
            return ucapi.SetupComplete()

        # Create device config
        device_config = NADdevice(
            device_id=device_id,
            name=name,
            address=host,
            port=port,
            monitor_power=monitor_power
        )

        # Save to config
        config.add_device(device_config)

        # Add device
        success = await add_device(device_config)

        if success:
            _LOG.info(f"Successfully configured NAD receiver at {host}:{port}")
            return ucapi.SetupComplete()
        else:
            _LOG.error(f"Failed to configure NAD receiver at {host}:{port}")
            return ucapi.SetupError(error_type=ucapi.IntegrationSetupError.CONNECTION_REFUSED)

    async def handle_user_data_response(msg: ucapi.UserDataResponse) -> ucapi.SetupAction:
        """
        Handle user input during setup flow.

        Step 1: User entered IP or left blank for discovery
        Step 2: User selected device from dropdown
        """
        _LOG.info("Processing user data response")
        _LOG.debug(f"Input values: {msg.input_values}")

        # Get monitor_power setting from input
        monitor_power = True  # msg.input_values.get("monitor_power", True)

        # Step 2: User selected discovered device (check this FIRST!)
        if "device_choice" in msg.input_values:
            choice = msg.input_values["device_choice"]
            _LOG.info(f"User selected discovered device: {choice}")

            if choice not in discovered_devices:
                _LOG.error(f"Selected device {choice} not found")
                return ucapi.SetupError(error_type=ucapi.IntegrationSetupError.NOT_FOUND)

            device_info = discovered_devices[choice]
            name = device_info.get("name", "NAD Receiver")
            host = device_info["host"]
            port = device_info.get("port", 23)

            return await configure_device(name, host, port, monitor_power)

        # Step 1: Discovery/manual input (only if no device_choice)
        elif "address" in msg.input_values:
            name = msg.input_values.get("name", "").strip()
            address = msg.input_values.get("address", "").strip()
            port = msg.input_values.get("port", 23)

            # Manual configuration - name and address both provided
            if name and address:
                _LOG.info(f"Manual configuration: {name} at {address}:{port}")
                return await configure_device(name, address, port, monitor_power)
            # Only address provided, use default name
            elif address:
                _LOG.info(f"Manual address entered: {address}:{port}")
                return await configure_device("NAD Receiver", address, port, monitor_power)
            else:
                # Auto-discovery
                _LOG.info("Starting auto-discovery")
                discovered_devices.clear()

                try:
                    await discovery.start(on_device_discovered)
                    _LOG.info("Waiting for device discovery (5 seconds)...")
                    await asyncio.sleep(5)
                    await discovery.stop()
                    _LOG.info(f"Discovery complete: found {len(discovered_devices)} device(s)")
                except Exception as e:
                    _LOG.warning(f"Discovery failed: {e}")

                # Build dropdown with discovered devices
                dropdown_items = []
                for device_id, device_info in discovered_devices.items():
                    dropdown_items.append({
                        "id": device_id,
                        "label": {"en": f"{device_info.get('name', 'NAD')} ({device_info['host']})"}
                    })

                if not dropdown_items:
                    _LOG.warning("No devices discovered")
                    return ucapi.SetupError(error_type=ucapi.IntegrationSetupError.NOT_FOUND)

                # Present discovered devices
                return ucapi.RequestUserInput(
                    title="Select NAD Device",
                    settings=[
                        {
                            "id": "device_choice",
                            "label": {"en": "Device", "nl": "Apparaat"},
                            "field": {
                                "dropdown": {
                                    "value": dropdown_items[0]["id"],
                                    "items": dropdown_items
                                }
                            }
                        },
                        # {
                        #     "id": "monitor_power",
                        #     "label": {
                        #         "en": "Monitor Power State",
                        #         "nl": "Monitor Aan/Uit Status"
                        #     },
                        #     "field": {
                        #         "checkbox": {"value": False}
                        #     }
                        # }
                    ]
                )

        _LOG.error(f"Unexpected user data response format: {msg.input_values}")
        return ucapi.SetupError()

    async def on_device_discovered(device_info: dict):
        """Callback when a device is discovered via mDNS."""
        device_id = device_info["id"]
        _LOG.info(f"Discovered NAD device: {device_id} at {device_info['host']}")
        discovered_devices[device_id] = device_info

    async def handle_driver_setup(msg: ucapi.DriverSetupRequest) -> ucapi.SetupAction:
        """
        Handle initial driver setup request.

        Ask user for IP address or leave blank for auto-discovery.

        Args:
            msg: Setup request from Remote

        Returns:
            RequestUserInput asking for address
        """
        _LOG.info("========== DRIVER SETUP STARTED ==========")

        # Workaround for web-configurator not picking up first response
        await asyncio.sleep(1)

        # Ask user for IP or use auto-discovery
        return ucapi.RequestUserInput(
            title="NAD Receiver Setup",
            settings=[
                {
                    "id": "info",
                    "label": {
                        "en": "Discover or connect to NAD receiver",
                        "nl": "Ontdek of verbind met NAD receiver"
                    },
                    "field": {
                        "label": {
                            "value": {
                                "en": "Leave blank for auto-discovery or enter details manually.",
                                "nl": "Laat leeg voor automatische ontdekking of vul handmatig in."
                            }
                        }
                    }
                },
                {
                    "id": "name",
                    "label": {
                        "en": "Device Name",
                        "nl": "Apparaat Naam"
                    },
                    "field": {
                        "text": {"value": ""}
                    }
                },
                {
                    "id": "address",
                    "label": {
                        "en": "IP Address or mDNS name",
                        "nl": "IP Adres of mDNS naam"
                    },
                    "field": {
                        "text": {"value": ""}
                    }
                },
                {
                    "id": "port",
                    "label": {
                        "en": "Port",
                        "nl": "Poort"
                    },
                    "field": {
                        "number": {"value": 23, "min": 1, "max": 65535}
                    }
                },
                # {
                #     "id": "monitor_power",
                #     "label": {
                #         "en": "Monitor Power State",
                #         "nl": "Monitor Aan/Uit Status"
                #     },
                #     "field": {
                #         "checkbox": {"value": False}
                #     }
                # }
            ]
        )

    # Start the integration API with setup handler
    # Pass "driver.json" directly - ucapi library handles path resolution
    # This matches the approach used by LG TV and other integrations
    _LOG.info("Calling api.init() with setup handler...")
    _LOG.info(f"sys.frozen={getattr(sys, 'frozen', False)}, sys.executable={sys.executable if getattr(sys, 'frozen', False) else 'N/A'}")
    _LOG.info(f"cwd={os.getcwd()}, __file__={__file__}")

    await api.init("driver.json", driver_setup_handler)
    _LOG.info("API.INIT completed - driver ready")

if __name__ == "__main__":
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    loop.run_until_complete(main(loop))
    loop.run_forever()
