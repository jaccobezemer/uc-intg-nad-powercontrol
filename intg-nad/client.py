"""NAD Receiver Telnet Client."""
import asyncio
import logging
import telnetlib
from typing import Optional, Callable

_LOG = logging.getLogger(__name__)


class NADClient:
    """
    Async wrapper for NAD receiver telnet control.

    Based on joopert/nad_receiver library.
    """

    def __init__(self, host: str, port: int = 23, timeout: int = 5):
        """
        Initialize NAD client.

        Args:
            host: NAD receiver IP address
            port: Telnet port (default 23)
            timeout: Command timeout in seconds
        """
        self.host = host
        self.port = port
        self.timeout = timeout
        self._tn: Optional[telnetlib.Telnet] = None
        self._lock = asyncio.Lock()
        self._monitoring = False
        self._monitor_task: Optional[asyncio.Task] = None
        self._power_callback: Optional[Callable[[bool], None]] = None

    async def connect(self) -> bool:
        """
        Connect to NAD receiver via telnet.

        Returns:
            True if connected successfully
        """
        try:
            loop = asyncio.get_event_loop()
            self._tn = await loop.run_in_executor(
                None,
                lambda: telnetlib.Telnet(self.host, self.port, self.timeout)
            )
            _LOG.info(f"Connected to NAD receiver at {self.host}:{self.port}")
            return True
        except Exception as e:
            _LOG.error(f"Failed to connect to NAD receiver: {e}")
            return False

    async def close(self):
        """Close telnet connection."""
        if self._tn:
            try:
                loop = asyncio.get_event_loop()
                await loop.run_in_executor(None, self._tn.close)
                _LOG.info("NAD telnet connection closed")
            except Exception as e:
                _LOG.error(f"Error closing connection: {e}")
            finally:
                self._tn = None

    async def _send_command(self, command: str) -> Optional[str]:
        """
        Send command to NAD receiver.

        Args:
            command: NAD command (e.g., "Main.Volume?", "Main.Power=On")

        Returns:
            Response string or None on error
        """
        if not self._tn:
            _LOG.error("Not connected to NAD receiver")
            return None

        async with self._lock:
            try:
                loop = asyncio.get_event_loop()

                # Send command with newline
                cmd_bytes = f"{command}\r\n".encode('ascii')
                _LOG.debug(f"Sending command: '{command}' (bytes={cmd_bytes!r})")
                await loop.run_in_executor(None, self._tn.write, cmd_bytes)

                # Determine expected response prefix based on command
                # For query commands (Main.Power?), expect response starting with Main.Power=
                # For set commands (Main.Power=On), expect response with Main.Power=
                if "?" in command:
                    expected_prefix = command.replace("?", "=")
                elif "=" in command:
                    expected_prefix = command.split("=")[0] + "="
                else:
                    expected_prefix = None

                # Read responses until we get the expected one or timeout
                # NAD may send multiple status updates, we need the right one
                # Use shorter timeout per read (0.5s) but keep trying for total timeout
                start_time = asyncio.get_event_loop().time()
                read_timeout = 0.5
                skipped_count = 0

                while (asyncio.get_event_loop().time() - start_time) < self.timeout:
                    try:
                        response = await loop.run_in_executor(
                            None,
                            lambda: self._tn.read_until(b"\n", timeout=read_timeout)
                        )
                        result = response.decode('ascii').strip()
                        _LOG.debug(f"Received telnet data: '{result}' (length={len(result)}, bytes={response!r})")

                        # Skip empty lines
                        if not result:
                            _LOG.debug("Skipping empty line")
                            continue

                        # Check if this is the response we're looking for
                        if expected_prefix is None or result.startswith(expected_prefix):
                            if skipped_count > 0:
                                _LOG.debug(f"Skipped {skipped_count} status updates before receiving response")
                            _LOG.debug(f"Command: {command} -> Response: {result}")
                            return result
                        else:
                            skipped_count += 1
                            _LOG.debug(f"Skipping unrelated status update: '{result}' (expected prefix: '{expected_prefix}')")
                    except Exception as e:
                        # Timeout or other error waiting for next line
                        _LOG.debug(f"Read timeout or error (expected, continuing): {type(e).__name__}")
                        continue

                _LOG.warning(f"Did not receive expected response for command '{command}' after {skipped_count} status updates (expected prefix: '{expected_prefix}')")
                return None

            except Exception as e:
                _LOG.error(f"Error sending command '{command}': {e}")
                return None

    async def get_power(self) -> Optional[bool]:
        """
        Get power state.

        Returns:
            True if on, False if off, None on error
        """
        response = await self._send_command("Main.Power?")
        if response and "=" in response:
            value = response.split("=")[1].strip()
            return value.lower() == "on"
        return None

    async def set_power(self, on: bool) -> bool:
        """
        Set power state.

        Args:
            on: True to turn on, False to turn off

        Returns:
            True if successful
        """
        command = "Main.Power=On" if on else "Main.Power=Off"
        response = await self._send_command(command)
        return response is not None

    async def get_volume(self) -> Optional[int]:
        """
        Get volume level (0-100).

        Returns:
            Volume level or None on error
        """
        response = await self._send_command("Main.Volume?")
        if response and "=" in response:
            try:
                # NAD returns volume in -dB format, convert to 0-100
                # Typical range: -92dB (min) to 0dB (max)
                value = response.split("=")[1].strip()
                if value.startswith("-"):
                    db = int(value.replace("dB", ""))
                    # Convert -92dB...0dB to 0...100
                    volume = max(0, min(100, int((db + 92) * 100 / 92)))
                    return volume
                return 0
            except ValueError:
                _LOG.error(f"Invalid volume response: {response}")
        return None

    async def set_volume(self, volume: int) -> bool:
        """
        Set volume level (0-100).

        Args:
            volume: Volume level (0-100)

        Returns:
            True if successful
        """
        # Convert 0-100 to -92dB...0dB
        volume = max(0, min(100, volume))
        db = int((volume * 92 / 100) - 92)
        command = f"Main.Volume={db}"
        response = await self._send_command(command)
        return response is not None

    async def volume_up(self) -> bool:
        """
        Increase volume.

        Returns:
            True if successful
        """
        response = await self._send_command("Main.Volume+")
        return response is not None

    async def volume_down(self) -> bool:
        """
        Decrease volume.

        Returns:
            True if successful
        """
        response = await self._send_command("Main.Volume-")
        return response is not None

    async def get_mute(self) -> Optional[bool]:
        """
        Get mute state.

        Returns:
            True if muted, False if not muted, None on error
        """
        response = await self._send_command("Main.Mute?")
        if response and "=" in response:
            value = response.split("=")[1].strip()
            return value.lower() == "on"
        return None

    async def set_mute(self, muted: bool) -> bool:
        """
        Set mute state.

        Args:
            muted: True to mute, False to unmute

        Returns:
            True if successful
        """
        command = "Main.Mute=On" if muted else "Main.Mute=Off"
        response = await self._send_command(command)
        return response is not None

    async def toggle_mute(self) -> bool:
        """
        Toggle mute state.

        Returns:
            True if successful
        """
        current = await self.get_mute()
        if current is not None:
            return await self.set_mute(not current)
        return False

    async def get_source(self) -> Optional[int]:
        """
        Get current source (1-based index).

        Returns:
            Source number or None on error
        """
        response = await self._send_command("Main.Source?")
        if response and "=" in response:
            try:
                value = response.split("=")[1].strip()
                return int(value)
            except ValueError:
                _LOG.error(f"Invalid source response: {response}")
        return None

    async def set_source(self, source: int) -> bool:
        """
        Set source (1-based index).

        Args:
            source: Source number (typically 1-12)

        Returns:
            True if successful
        """
        command = f"Main.Source={source}"
        response = await self._send_command(command)
        return response is not None

    async def get_model(self) -> Optional[str]:
        """
        Get receiver model.

        Returns:
            Model string or None on error
        """
        response = await self._send_command("Main.Model?")
        if response and "=" in response:
            return response.split("=")[1].strip()
        return None

    async def get_version(self) -> Optional[str]:
        """
        Get firmware version.

        Returns:
            Version string or None on error
        """
        response = await self._send_command("Main.Version?")
        if response and "=" in response:
            return response.split("=")[1].strip()
        return None

    def start_power_monitoring(self, callback: Callable[[bool], None]) -> None:
        """
        Start monitoring power state changes.

        Args:
            callback: Async function to call when power state changes (receives True/False)
        """
        if self._monitoring:
            _LOG.warning("Power monitoring already started")
            return

        self._power_callback = callback
        self._monitoring = True
        self._monitor_task = asyncio.create_task(self._monitor_power_loop())
        _LOG.info("Started power state monitoring")

    async def stop_power_monitoring(self) -> None:
        """Stop monitoring power state changes."""
        self._monitoring = False

        if self._monitor_task and not self._monitor_task.done():
            self._monitor_task.cancel()
            try:
                await self._monitor_task
            except asyncio.CancelledError:
                pass

        self._monitor_task = None
        self._power_callback = None
        _LOG.info("Stopped power state monitoring")

    async def _monitor_power_loop(self) -> None:
        """
        Background task to monitor unsolicited power state updates from NAD.

        The NAD sends Main.Power=On/Off messages automatically when power state
        changes (e.g., via physical button or remote).

        If connection is lost, attempts to reconnect every 10 seconds.
        """
        _LOG.info("Starting power monitoring loop")
        consecutive_errors = 0
        max_consecutive_errors = 5
        reconnect_delay = 10  # seconds between reconnect attempts

        try:
            while self._monitoring:
                # Check if connection is lost
                if self._tn is None:
                    _LOG.warning("Telnet connection lost, attempting to reconnect...")
                    try:
                        connected = await self.connect()
                        if connected:
                            _LOG.info("Reconnected to NAD receiver successfully")
                            consecutive_errors = 0
                        else:
                            _LOG.warning(f"Reconnection failed, retrying in {reconnect_delay} seconds")
                            await asyncio.sleep(reconnect_delay)
                            continue
                    except Exception as e:
                        _LOG.error(f"Reconnection error: {e}")
                        await asyncio.sleep(reconnect_delay)
                        continue

                try:
                    loop = asyncio.get_event_loop()

                    # Read any incoming line with short timeout (non-blocking check)
                    response = await loop.run_in_executor(
                        None,
                        lambda: self._tn.read_until(b"\n", timeout=1.0)
                    )

                    result = response.decode('ascii').strip()

                    # Log all received data
                    if result:
                        _LOG.debug(f"Monitor received: '{result}' (length={len(result)}, bytes={response!r})")

                        # Check if it's a power state update
                        if result.startswith("Main.Power="):
                            value = result.split("=")[1].strip()
                            power_on = value.lower() == "on"
                            _LOG.info(f"Power state changed: {'ON' if power_on else 'OFF'}")

                            # Call the callback
                            if self._power_callback:
                                if asyncio.iscoroutinefunction(self._power_callback):
                                    await self._power_callback(power_on)
                                else:
                                    self._power_callback(power_on)

                            consecutive_errors = 0
                        else:
                            # Skip temperature messages from debug log to reduce noise
                            if not result.startswith("Main.Temp."):
                                _LOG.debug(f"Unsolicited message (not power change): '{result}'")

                except asyncio.TimeoutError:
                    # Normal - no data available, continue monitoring
                    consecutive_errors = 0
                    continue
                except asyncio.CancelledError:
                    _LOG.info("Power monitoring task cancelled")
                    raise
                except Exception as e:
                    consecutive_errors += 1
                    _LOG.warning(f"Error in power monitoring loop: {e}")

                    # Connection likely lost - close and mark for reconnect
                    if consecutive_errors >= max_consecutive_errors:
                        _LOG.error(f"Too many consecutive errors ({consecutive_errors}), closing connection for reconnect")
                        try:
                            if self._tn:
                                self._tn.close()
                        except:
                            pass
                        self._tn = None
                        consecutive_errors = 0

                    await asyncio.sleep(1)

        finally:
            self._monitoring = False
            _LOG.info("Power monitoring loop stopped")
