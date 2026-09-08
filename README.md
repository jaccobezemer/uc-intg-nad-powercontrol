# NAD Power Control Integration for Unfolded Circle Remote 3

Integration driver for controlling NAD receivers via Telnet protocol on the Unfolded Circle Remote 3.

## Features

- Power control (On/Off/Toggle)
- Power status monitoring

## Supported Devices

This integration uses the Telnet protocol and is known to work with:
- NAD M33 and T787
- Other NAD receivers with Telnet support (port 23)

## Installation

1. Download the latest release `.tar.gz` file from [Releases](https://github.com/jaccobezemer/uc-intg-nad-powercontrol/releases)
2. Open the Unfolded Circle Remote 3 web configurator
3. Go to Integrations → Add Integration
4. Upload the downloaded `.tar.gz` file
5. Wait for installation to complete

## Setup

1. After installation, click "Setup" to configure the integration.
2. The integration scans your network for NAD/BluOS devices (this may take a few seconds).
3. Select your receiver from the list, or choose "Setup Manually" to enter its IP address directly.
4. Click "Done" to finish. Repeat the process to add additional receivers.

## NAD Telnet Protocol

This integration communicates with NAD receivers using the Telnet protocol on port 23. Commands follow the format:

```
Main.Command?          # Query
Main.Command=Value     # Set value
Main.Command+          # Increment
Main.Command-          # Decrement
```

### Example Commands

- Power: `Main.Power?` (query), `Main.Power=On` (turn on), `Main.Power=Off` (turn off)

## Troubleshooting

### Connection Issues

1. Verify your NAD receiver has Telnet enabled
2. Check that the IP address is correct
3. Ensure the receiver is on the same network as the Remote 3
4. Try pinging the receiver from another device
5. Check firewall settings

### Logs

Check the integration logs in the Remote 3 web configurator for detailed error messages.

## Development

This integration is based on:
- [joopert/nad_receiver](https://github.com/joopert/nad_receiver) - Python library for NAD control
- [Unfolded Circle Integration API](https://github.com/unfoldedcircle/integration-python-library)

### Building

The integration is automatically built using GitHub Actions when a version tag is pushed:

```bash
git tag -a v0.1.0 -m "Release v0.1.0"
git push origin v0.1.0
```

## License

MPL-2.0 license

## Credits

Created by Jacco Bezemer
Based on the nad_receiver library by joopert
