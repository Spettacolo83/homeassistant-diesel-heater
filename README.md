<p align="center">
  <img src="custom_components/vevor_heater/icon.png" alt="VEVOR Logo" width="100"/>
</p>

<h1 align="center">Vevor Diesel Heater - Home Assistant Integration</h1>

<p align="center">
  <a href="https://github.com/hacs/integration"><img src="https://img.shields.io/badge/HACS-Custom-41BDF5.svg" alt="HACS"></a>
  <a href="https://github.com/Spettacolo83/homeassistant-vevor-heater/releases"><img src="https://img.shields.io/github/release/Spettacolo83/homeassistant-vevor-heater.svg" alt="GitHub release"></a>
  <a href="https://github.com/Spettacolo83/homeassistant-vevor-heater/blob/main/LICENSE"><img src="https://img.shields.io/github/license/Spettacolo83/homeassistant-vevor-heater.svg" alt="License"></a>
</p>

> This is a maintained fork of the original [homeassistant-vevor-heater](https://github.com/MSDATDE/homeassistant-vevor-heater) by [@MSDATDE](https://github.com/MSDATDE), enhanced with HACS 2.0+ compatibility and additional improvements.

Control your Vevor/BYD Diesel Heater from Home Assistant via Bluetooth.

## Features

- 🌡️ **Climate Entity** - Full thermostat control with target temperature
- 🔥 **Heater Level Control** - Adjust heating power (1-10) via fan entity
- ⚙️ **Running Mode Selection** - Switch between Manual, Level, and Temperature modes
- 📊 **Sensors** - Monitor temperature, voltage, altitude, and heater status
- 🔌 **Bluetooth LE** - Direct local connection, no cloud required
- ⚡ **Real-time Updates** - 30-second polling interval
- ⛽ **Fuel Consumption Tracking** - Monitor fuel usage based on power level estimation (0.16-0.52 L/h)

## Supported Devices

This integration has been tested with:
- Vevor Diesel Heater (BYD variant)
- Protocol: AA66 (20-byte unencrypted)
- Bluetooth Service UUID: `0000ffe0-0000-1000-8000-00805f9b34fb`

Other Vevor diesel heaters using similar protocols (AA55 encrypted/unencrypted) may also work.

## Installation

### HACS (Recommended)

1. Open HACS in Home Assistant
2. Go to "Integrations"
3. Click the three dots menu → "Custom repositories"
4. Add this repository: `https://github.com/Spettacolo83/homeassistant-vevor-heater`
5. Category: "Integration"
6. Click "Add"
7. Search for "Vevor Diesel Heater" and install
8. Restart Home Assistant

### Manual Installation

1. Download the latest release from [GitHub](https://github.com/Spettacolo83/homeassistant-vevor-heater/releases)
2. Copy the `custom_components/vevor_heater` folder to your Home Assistant's `custom_components` directory
3. Restart Home Assistant

## Finding Your Heater's MAC Address

Before adding the integration, you need to find your heater's Bluetooth MAC address:

1. Install Python dependencies:
   ```bash
   pip install bleak
   ```

2. Run the finder script (included in this repo):
   ```bash
   python3 find_heater.py before
   ```

3. **Close the Vevor app** if it's running

4. Open the Vevor app and **connect** to your heater

5. Run the finder script again:
   ```bash
   python3 find_heater.py after
   ```

6. The device that **disappeared** is your heater! Note its MAC address (e.g., `69:96:19:04:59:9B`)

## Configuration

### Add Integration

1. Go to **Settings** → **Devices & Services**
2. Click **"+ Add Integration"**
3. Search for **"Vevor Diesel Heater"**
4. Enter your heater's MAC address (found using the script above)
5. Click **"Submit"**

### Entities Created

After setup, you'll have these entities:

#### Climate
- `climate.vevor_heater` - Main thermostat control
  - Set target temperature (8-36°C)
  - Turn heater ON/OFF
  - Works in Temperature Mode

#### Fan
- `fan.vevor_heater_heater_level` - Heater power level (1-10)
  - Only available in Manual or Level mode
  - Percentage control (10%-100%)

#### Select
- `select.vevor_heater_running_mode` - Mode selector
  - Manual - Full manual control
  - Level Mode - Set heating level (1-10)
  - Temperature Mode - Automatic temperature control

#### Sensors
- `sensor.vevor_heater_case_temperature` - Heater case temperature (°C)
- `sensor.vevor_heater_interior_temperature` - Room/cabin temperature (°C)
- `sensor.vevor_heater_supply_voltage` - Power supply voltage (V)
- `sensor.vevor_heater_altitude` - Altitude compensation setting (m)
- `sensor.vevor_heater_running_step` - Current operation step
- `sensor.vevor_heater_error` - Error status
- `sensor.vevor_heater_running_mode` - Current running mode
- `sensor.vevor_heater_set_level` - Current set level
- `sensor.vevor_heater_hourly_fuel_consumption` - Instantaneous fuel consumption rate (L/h)
- `sensor.vevor_heater_daily_fuel_consumed` - Daily fuel consumption (L, resets at midnight)
- `sensor.vevor_heater_total_fuel_consumed` - Total fuel consumed since installation (L)

#### Binary Sensors
- `binary_sensor.vevor_heater_active` - Heater active status

#### Switches
- `switch.vevor_heater_power` - Simple ON/OFF control

#### Number
- `number.vevor_heater_target_temperature` - Set target temperature

## Dashboard Cards

### Recommended Setup

Create a nice dashboard with these cards:

1. **Climate Card** - For temperature control
   ```yaml
   type: thermostat
   entity: climate.vevor_heater
   ```

2. **Mode Selector** - To switch modes
   ```yaml
   type: entities
   entities:
     - entity: select.vevor_heater_running_mode
   ```

3. **Heater Level Control** - For manual power control
   ```yaml
   type: entities
   entities:
     - entity: fan.vevor_heater_heater_level
   ```

4. **Sensor Overview**
   ```yaml
   type: entities
   title: Heater Status
   entities:
     - entity: sensor.vevor_heater_interior_temperature
     - entity: sensor.vevor_heater_case_temperature
     - entity: sensor.vevor_heater_supply_voltage
     - entity: binary_sensor.vevor_heater_active
   ```

## Troubleshooting

### Heater Not Found

- Make sure Bluetooth is enabled on your Home Assistant host
- Ensure the heater is powered on
- Vevor app must be **disconnected** (only one BLE connection allowed)
- Try running `find_heater.py` again to verify MAC address

### No Data / Connection Issues

- Check Home Assistant logs: **Settings** → **System** → **Logs**
- Look for entries with `vevor_heater`
- The integration uses exponential backoff (5s, 10s, 20s, 40s) for reconnection

### Commands Not Working

- Verify you're using the correct passkey (default: `1234`)
- Some commands only work in specific modes:
  - Temperature setting: Temperature Mode
  - Level setting: Manual or Level Mode

### Debug Logging

Enable debug logging in `configuration.yaml`:

```yaml
logger:
  default: info
  logs:
    custom_components.vevor_heater: debug
```

## Protocol Details

This integration communicates via Bluetooth LE using the Vevor/BYD diesel heater protocol:

- **Service UUID**: `0000ffe0-0000-1000-8000-00805f9b34fb`
- **Characteristic UUID**: `0000ffe1-0000-1000-8000-00805f9b34fb` (read/write/notify)
- **Protocol**: AA66 (20-byte unencrypted) or AA55 (encrypted variants)
- **Default Passkey**: `1234`

### Commands
- Command 1: Status query
- Command 2: Set running mode
- Command 3: Turn ON (arg=1) / OFF (arg=0)
- Command 4: Set level or temperature

## Changelog

### Version 1.0.3 (Fork)
- **Fuel Consumption Tracking** - Monitor fuel usage based on power level estimation
  - Hourly consumption rate sensor (L/h) - real-time instantaneous rate
  - Daily fuel consumed sensor (L) - automatically resets at midnight
  - Total fuel consumed sensor (L) - lifetime consumption tracking
  - Data persisted across Home Assistant restarts
- Consumption calculated using VEVOR specifications (0.16-0.52 L/h range)
- Only tracks consumption when heater is actively running
- Minimal, stable implementation without UI changes

### Version 1.0.2 (Fork)
- Fixed HACS icon display by adding logo URL to hacs.json

### Version 1.0.1 (Fork)
- Fixed HACS 2.0+ compatibility by restructuring repository
- Moved integration files to `custom_components/vevor_heater/`
- Added `hacs.json` configuration file
- Added VEVOR brand icon for better visual identification
- Updated repository URLs and metadata
- Maintained full compatibility with original integration

### Version 1.0.0 (Original)
- Initial release by [@MSDATDE](https://github.com/MSDATDE)
- Full climate entity support with thermostat control
- Heater level control via fan entity
- Multiple running modes (Manual, Level, Temperature)
- Comprehensive sensor suite
- Bluetooth LE connectivity
- Temperature calibration feature

## Contributing

Contributions are welcome! Please feel free to submit a Pull Request.

## License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

## Acknowledgments

- **Original Author**: [@MSDATDE](https://github.com/MSDATDE) - Thank you for creating this excellent integration!
- **Original Repository**: [MSDATDE/homeassistant-vevor-heater](https://github.com/MSDATDE/homeassistant-vevor-heater)
- Based on the [vevor-ble-bridge](https://github.com/andyrak/vevor-ble-bridge) protocol documentation
- Thanks to the Home Assistant community for support

## Support

If you encounter issues, please:
1. Check the [Issues](https://github.com/Spettacolo83/homeassistant-vevor-heater/issues) page
2. Enable debug logging and include logs in your report
3. Provide your heater model and protocol type (AA55/AA66)

---

**Disclaimer**: This is an unofficial integration and is not affiliated with Vevor or BYD.
