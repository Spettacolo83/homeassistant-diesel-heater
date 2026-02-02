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

Control your Vevor/BYD/HeaterCC/Sunster Diesel Heater from Home Assistant via Bluetooth. Supports AirHeaterBLE (AA55/AA66), AirHeaterCC (ABBA), and Sunster (CBFF) protocol heaters.

## Features

- 🌡️ **Climate Entity** - Full thermostat control with target temperature and presets (Away, Comfort)
- 🔥 **Heater Level Control** - Adjust heating power (1-10) via number entity
- ⚙️ **Running Mode Selection** - Switch between Level and Temperature modes
- 📊 **Comprehensive Sensors** - Monitor temperature, voltage, altitude, and heater status
- ⛽ **Fuel Consumption Tracking** - Monitor fuel usage with 3 dedicated sensors
  - Hourly consumption rate (L/h) - real-time instantaneous rate
  - Daily consumption (L) - automatically resets at midnight
  - Total consumption (L) - lifetime tracking
- 🔌 **Bluetooth LE** - Direct local connection, no cloud required
- ⚡ **Real-time Updates** - 30-second polling interval
- 💾 **Data Persistence** - Fuel consumption data saved across restarts
- 🌐 **Multi-Protocol Support** - Works with AA55, AA66, ABBA, and CBFF protocol heaters
- 🛠️ **Configuration Settings** - AirHeaterBLE-like settings:
  - Language, Temperature Unit, Altitude Unit
  - Tank Volume, Pump Type, Temperature Offset
- 🌡️ **Auto Temperature Offset** - Automatic offset adjustment using external temperature sensor
- ⏰ **Time Sync** - Synchronize heater clock with Home Assistant

## Table of Contents

- [Features](#features)
- [Supported Devices](#supported-devices)
- [Screenshots](#screenshots)
- [Installation](#installation)
- [Troubleshooting](#troubleshooting) ⚠️
- [Finding Your Heater's MAC Address](#finding-your-heaters-mac-address)
- [Configuration](#configuration)
- [Dashboard Cards](#dashboard-cards)
- [Protocol Details](#protocol-details)
- [Changelog](#changelog)
- [Contributing](#contributing)
- [Support](#support)

## Supported Devices

This integration supports **multiple protocols** and has been tested with various diesel heaters:

### Supported Protocols

| Protocol | Completion | Apps | Notes |
|----------|-----------|------|-------|
| AA55 Unencrypted | 95% | AirHeaterBLE | Original Vevor protocol |
| AA55 Encrypted | 99% | AirHeaterBLE | XOR encrypted variant |
| AA66 Unencrypted | 95% | AirHeaterBLE | 20-byte variant |
| AA66 Encrypted | 95% | AirHeaterBLE | XOR encrypted, Fahrenheit internal |
| ABBA | 80% | AirHeaterCC | Different command structure |
| CBFF | 50% | Sunster | Double XOR encryption variant |

ABBA and CBFF protocols are recent findings in newer Vevor and Chinabasto heaters. CBFF appeared in Sunster Bluetooth+WiFi heaters, but more heaters may use this protocol.
We are actively developing them based on community feedback. If you own one, please check the [Issues](https://github.com/Spettacolo83/homeassistant-vevor-heater/issues), beta test, and report any problems.

### Bluetooth Service UUIDs

- **FFE0** Service: `0000ffe0-0000-1000-8000-00805f9b34fb` (AA55/AA66 heaters)
- **FFF0** Service: `0000fff0-0000-1000-8000-00805f9b34fb` (ABBA/HeaterCC and CBFF/Sunster heaters)

### Tested Heaters

- Vevor Diesel Heater (various models)
- BYD Diesel Heaters
- HeaterCC compatible heaters
- Sunster TB10Pro WiFi
- Generic Chinese diesel heaters using AirHeaterBLE, AirHeaterCC, or Sunster apps

## Screenshots

### Fuel Consumption Sensors
Monitor your heater's fuel consumption with real-time tracking:

![Fuel Consumption Sensors](docs/images/fuel-consumption-sensors.png)

### Heater Controls
Full control over your heater including temperature, level, and mode selection:

![Heater Controls](docs/images/heater-controls.png)

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

## Troubleshooting

### Heater Not Found / Connection Issues

**1. Unpair from your phone first!**
> The most common issue! If the heater is paired with the Vevor app on your phone, Home Assistant cannot connect.
- Open your phone's Bluetooth settings
- Find the heater device and **forget/unpair** it
- Close the Vevor app completely
- Try adding the integration again

**2. Bluetooth Proxy Connection Limits**
> ESPHome Bluetooth proxies have a maximum of **3-7 simultaneous connections** (varies by ESP32 model).
- Check how many BLE devices are using your proxy
- Consider adding a dedicated ESP32 proxy for the heater
- Or use a USB Bluetooth dongle directly on your HA server

**3. Raspberry Pi 4 Internal Bluetooth Issues**
> The built-in Bluetooth on RPi4 can be unreliable for BLE devices.
- **Recommended**: Use an external USB Bluetooth 5.0 dongle
- **Alternative**: Use an ESPHome Bluetooth proxy (ESP32)
- Disable the internal Bluetooth if using external adapter:
  ```
  # Add to /boot/config.txt
  dtoverlay=disable-bt
  ```

**4. Other Integrations Interfering**
> Some integrations scan for Bluetooth devices aggressively.
- Check if you have other BLE integrations running
- The Bluetooth Integration's passive scanning can cause conflicts
- Try disabling other BLE integrations temporarily to test

**5. Distance and Obstacles**
> Bluetooth LE has limited range, especially through walls.
- Move your Bluetooth adapter/proxy closer to the heater
- ESP32 proxies can be placed near the heater with power over USB
- Metal surfaces and water (including bodies) block BLE signals

### Connection Drops / "Unavailable" Status

**1. Stale Data Tolerance**
> The integration keeps sensor values for 3 polling cycles before showing unavailable.
- Brief disconnections won't affect your automations
- If unavailable persists, check the issues above

**2. Enable Debug Logging**
> Add this to your `configuration.yaml` to see detailed connection logs:
```yaml
logger:
  default: info
  logs:
    custom_components.vevor_heater: debug
```

### Temperature Not Changing

**1. Check Running Mode**
> Temperature control only works in **Temperature Mode**.
- Use `select.vevor_heater_running_mode` to switch to "Temperature Mode"
- In "Level Mode", the heater uses fixed power levels instead

**2. Protocol Compatibility**
> Some heaters use Fahrenheit internally (AA66 encrypted).
- The integration auto-detects and converts temperatures
- If issues persist, check the logs for "protocol" messages

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
4. The integration will auto-discover nearby heaters, or you can enter the MAC address manually
5. Enter your heater's **PIN** (default: `1234`, change if you set a custom PIN via the Vevor app)
6. Click **"Submit"**

### Integration Options

After setup, go to the integration's **Configure** button to access these options:

- **PIN**: Change the heater connection PIN
- **Preset Away Temperature**: Target temperature for Away preset (default: 16°C)
- **Preset Comfort Temperature**: Target temperature for Comfort preset (default: 22°C)
- **External Temperature Sensor**: Select an external HA temperature sensor for auto offset adjustment
- **Auto Offset Max**: Maximum offset value when using external sensor (1-9, only shown when external sensor is configured)

### Entities Created

Entities are created **conditionally based on the detected BLE protocol**. Only entities that the protocol supports are created, preventing unsupported entities from showing as "Unavailable".

#### Core Entities (all protocols)

| Platform | Entity | Description |
|----------|--------|-------------|
| Climate | `climate.vevor_heater` | Thermostat control (8-36°C), presets (Away, Comfort) |
| Fan | `fan.vevor_heater_heater_level` | Level control as fan entity (1-10) |
| Switch | `switch.vevor_heater_power` | Simple ON/OFF control |
| Switch | `switch.vevor_heater_auto_offset` | Auto Temperature Offset toggle *(Config)* |
| Select | `select.vevor_heater_running_mode` | Mode selector (Off, Level, Temperature) |
| Number | `number.vevor_heater_level` | Set heater power level (1-10) |
| Number | `number.vevor_heater_target_temperature` | Set target temperature (8-36°C) |
| Number | `number.vevor_heater_tank_capacity` | Set tank capacity for fuel estimation *(Config)* |
| Button | `button.vevor_heater_sync_time` | Sync heater clock with HA time *(Config)* |
| Button | `button.vevor_heater_reset_est_fuel_remaining` | Reset estimated fuel after refuel *(Config)* |
| Sensor | Case Temperature, Interior Temperature, Voltage, Running Step/Mode, Set Level, Altitude, Error Code | Basic heater sensors |
| Sensor | Estimated Hourly/Daily/Total Fuel, Fuel Remaining, Fuel Since Refuel | Fuel tracking (computed locally) |
| Sensor | Daily/Total Runtime, History sensors | Runtime tracking (computed locally) |
| Binary Sensor | Active, Problem, Connected | Heater status sensors *(Diagnostic)* |

#### Extended Entities (AA55 Encrypted, AA66 Encrypted, CBFF)

| Platform | Entity | Description |
|----------|--------|-------------|
| Number | Temperature Offset | Temperature offset (-9 to +9) *(Config)* |
| Select | Backlight | Display backlight brightness (Off, 1-10, 20-100) *(Config)* |
| Sensor | Raw Interior Temperature, Heater Offset, CO (ppm) | Extended protocol sensors |

#### Config Entities (AA66 Encrypted, CBFF)

| Platform | Entity | Description |
|----------|--------|-------------|
| Select | Language, Pump Type, Tank Volume | Heater configuration selects *(Config)* |

#### Unit/Auto Entities (AA66 Encrypted, ABBA, CBFF)

| Platform | Entity | Description |
|----------|--------|-------------|
| Switch | Auto Start/Stop | Auto Start/Stop toggle |
| Switch | Temperature Unit, Altitude Unit | Unit switches *(Config)* |
| Binary Sensor | Auto Start/Stop | Auto Start/Stop status |

#### CBFF-only Entities (Sunster)

| Platform | Entity | Description |
|----------|--------|-------------|
| Sensor | HW/SW Version, Remaining Run Time, Startup/Shutdown Temp Diff | CBFF-specific sensors |

#### ABBA-only Entities (HeaterCC)

| Platform | Entity | Description |
|----------|--------|-------------|
| Switch | High Altitude | High altitude mode toggle |

> Entities marked *(Diagnostic)* appear in the Diagnostic section of the device page.
> Entities marked *(Config)* appear in the Configuration section.

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
     - entity: sensor.vevor_diesel_heater_interior_temperature
     - entity: sensor.vevor_diesel_heater_case_temperature
     - entity: sensor.vevor_diesel_heater_supply_voltage
     - entity: binary_sensor.vevor_diesel_heater_active
   ```

### Fuel Consumption History Graph

The integration automatically imports daily fuel consumption data into Home Assistant's **long-term statistics**, enabling native graphing without any additional cards or plugins!

#### Using Built-in Statistics Graph (Recommended)

**No installation required!** The integration automatically makes historical data available to Home Assistant's native `statistics-graph` card.

![Native Statistics Graph](docs/images/fuel-statistics-graph.png)

**Bar Chart - Last 7 Days:**
```yaml
type: statistics-graph
entities:
  - sensor.vevor_diesel_heater_daily_fuel_consumed
stat_types:
  - sum
period: day
days_to_show: 7
chart_type: bar
title: Daily Fuel Consumption (Last 7 Days)
```

**Line Chart - Last 30 Days:**
```yaml
type: statistics-graph
entities:
  - sensor.vevor_diesel_heater_daily_fuel_consumed
stat_types:
  - sum
period: day
days_to_show: 30
chart_type: line
title: Daily Fuel Consumption (Last 30 Days)
```

**Note**: The statistics are automatically populated from your fuel history. If you have existing history data, it will be imported on the next restart!

#### Using ApexCharts Card (Alternative)

Install [ApexCharts Card](https://github.com/RomRider/apexcharts-card) via HACS for beautiful historical graphs:

**Bar Chart - Last 7 Days:**
```yaml
type: custom:apexcharts-card
header:
  title: Daily Fuel Consumption (Last 7 Days)
  show: true
  show_states: true
graph_span: 7d
span:
  start: day
all_series_config:
  type: column
  opacity: 0.8
series:
  - entity: sensor.vevor_diesel_heater_daily_fuel_history
    data_generator: |
      return Object.entries(entity.attributes.history || {})
        .slice(0, 7)
        .reverse()
        .map(([date, liters]) => [new Date(date).getTime(), liters]);
    name: Liters
    color: '#ff6b6b'
yaxis:
  - decimals: 2
    min: 0
    apex_config:
      title:
        text: Liters (L)
```

**Line Chart - Last 30 Days:**
```yaml
type: custom:apexcharts-card
header:
  title: Daily Fuel Consumption (Last 30 Days)
  show: true
graph_span: 30d
span:
  start: day
all_series_config:
  type: line
  stroke_width: 2
  curve: smooth
series:
  - entity: sensor.vevor_diesel_heater_daily_fuel_history
    data_generator: |
      return Object.entries(entity.attributes.history || {})
        .reverse()
        .map(([date, liters]) => [new Date(date).getTime(), liters]);
    name: Daily Consumption
    color: '#4ecdc4'
yaxis:
  - decimals: 2
    min: 0
    apex_config:
      title:
        text: Liters (L)
```

**Multi-Period Comparison:**
```yaml
type: custom:apexcharts-card
header:
  title: Fuel Consumption Trends
  show: true
series:
  - entity: sensor.vevor_diesel_heater_daily_fuel_history
    attribute: last_7_days
    name: Last 7 Days
    type: column
  - entity: sensor.vevor_diesel_heater_daily_fuel_history
    attribute: last_30_days
    name: Last 30 Days
    type: column
yaxis:
  - decimals: 2
    min: 0
    apex_config:
      title:
        text: Total Liters (L)
```

#### Using Built-in Cards

**Attributes Card - View History Data:**
```yaml
type: entities
title: Fuel History
entities:
  - entity: sensor.vevor_diesel_heater_daily_fuel_history
    type: attribute
    attribute: last_7_days
    name: Last 7 Days Total
  - entity: sensor.vevor_diesel_heater_daily_fuel_history
    type: attribute
    attribute: last_30_days
    name: Last 30 Days Total
  - entity: sensor.vevor_diesel_heater_daily_fuel_history
    type: attribute
    attribute: days_tracked
    name: Days Tracked
```

**Markdown Card - Formatted History:**
```yaml
type: markdown
title: Daily Fuel History
content: |
  {% set history = state_attr('sensor.vevor_diesel_heater_daily_fuel_history', 'history') %}
  {% if history %}
  | Date | Liters |
  |------|--------|
  {% for date, liters in history.items() | list | sort(reverse=true) %}
  | {{ date }} | {{ liters }} L |
  {% endfor %}
  {% else %}
  No history data available yet.
  {% endif %}
```

## Protocol Details

This integration communicates via Bluetooth LE and supports 6 protocol variants across 3 families:

### AA55/AA66 Protocol (AirHeaterBLE heaters)

- **Service UUID**: `0000ffe0-0000-1000-8000-00805f9b34fb`
- **Characteristic UUID**: `0000ffe1` (read/write/notify)
- **Variants**: AA55 (18/20-byte), AA66 (20-byte), encrypted (48-byte) and unencrypted
- **Encryption**: XOR with 8-byte key "password"
- **Default Passkey**: `1234` (configurable)

#### AA55/AA66 Commands

| Command | Function | Argument |
|---------|----------|----------|
| 1 | Status query | 0 |
| 2 | Set running mode | 0=Off, 1=Level, 2=Temperature |
| 3 | Turn ON/OFF | 0=OFF, 1=ON |
| 4 | Set level or temperature | 1-10 (level) or 8-36 (temp) |
| 10 | Time sync | 60 * hours + minutes |
| 14 | Set language | 0=EN, 1=CN, 2=DE, 3=Silent, 4=RU |
| 15 | Set temp unit | 0=Celsius, 1=Fahrenheit |
| 16 | Set tank volume | 0-10 (index-based) |
| 17 | Set pump type | 0-3 (16µl, 22µl, 28µl, 32µl) |
| 18 | Auto Start/Stop | 0=Off, 1=On |
| 19 | Set altitude unit | 0=Meters, 1=Feet |
| 20 | Set temp offset | -9 to +9 |

### ABBA Protocol (HeaterCC/AirHeaterCC heaters)

- **Service UUID**: `0000fff0-0000-1000-8000-00805f9b34fb`
- **Write UUID**: `0000fff2` / **Notify UUID**: `0000fff1`
- **Header**: `0xABBA` (notifications) / `0xBAAB` (commands)

#### ABBA Status Response (21 bytes)

| Byte | Field | Values |
|------|-------|--------|
| 0-3 | Header | `ABBA11CC` |
| 4 | Status | 0=Off, 1=Heating, 2=Cooldown, 4=Ventilation, 6=Standby |
| 5 | Mode | 0=Level, 1=Temperature, 0xFF=Error |
| 6 | Gear/Temp | Level (1-6) or target temp (°C) |
| 8 | Auto Start/Stop | 0=Off, 1=On |
| 9 | Voltage | Decimal value (V) |
| 10 | Temp Unit | 0=Celsius, 1=Fahrenheit |
| 11 | Env Temp | Raw - 30 (°C) or Raw - 22 (°F) |
| 12-13 | Case Temp | uint16 (°C) |
| 14 | Altitude Unit | 0=Meters, 1=Feet |
| 15 | High Altitude | 0=Normal, 1=High |
| 16-17 | Altitude | uint16 |
| 20 | Checksum | Validation byte |

#### ABBA Error Codes (when byte 5 = 0xFF)

| Code | Error |
|------|-------|
| 2 | E2 - Voltage fault |
| 3 | E3 - Igniter fault |
| 4 | E4 - Fuel pump fault |
| 5 | E5 - Over-temperature |
| 6 | E6 - Fan fault |
| 7 | E7 - Communication fault |
| 8 | E8 - Flameout |
| 9 | E9 - Sensor fault |
| 10 | E10 - Startup failure |
| 192 | EC0 - Carbon monoxide alarm |

### CBFF Protocol (Sunster heaters)

- **Service UUID**: `0000fff0-0000-1000-8000-00805f9b34fb`
- **Write UUID**: `0000fff2` / **Notify UUID**: `0000fff1`
- **Header**: `0xCBFF` (notifications) / Commands use AA55 format, ACK with `0xAA77`
- **Encryption**: Some heaters use double-XOR encryption (key1 = "passwordA2409PW", key2 = BLE MAC)
- **Packet size**: 47 bytes

#### CBFF Response (47 bytes)

| Byte | Field | Values |
|------|-------|--------|
| 0-1 | Header | `CB FF` |
| 2 | Protocol Version | Version byte |
| 10 | Run State | 2/5/6 = OFF, others = ON |
| 11 | Run Mode | 1/3/4=Level, 2=Temperature |
| 12 | Run Param | Level (1-10) or temp target |
| 13 | Now Gear | Current gear in temp mode |
| 14 | Run Step | Operation step |
| 15 | Fault Display | Error code (lower 6 bits) |
| 17 | Temp Unit | Lower nibble: 0=C, 1=F |
| 18-19 | Cab Temperature | int16 LE (°C) |
| 20 | Altitude Unit | Lower nibble: 0=m, 1=ft |
| 21-22 | Altitude | uint16 LE |
| 23-24 | Voltage | uint16 LE (/10) |
| 25-26 | Case Temperature | int16 LE (/10) |
| 27-28 | CO PPM | uint16 LE (/10) |
| 30-31 | Hardware Version | uint16 LE |
| 32-33 | Software Version | uint16 LE |
| 34 | Temp Compensation | int8 offset |
| 35 | Language | 255=N/A |
| 36 | Tank Volume | 255=N/A |
| 37 | Pump Model | 20=RF off, 21=RF on, other=pump type |
| 38 | Backlight | 255=N/A |
| 39-40 | Startup/Shutdown Temp Diff | 255=N/A |
| 42 | Auto Start/Stop | 0=Off, 1=On |
| 44-45 | Remaining Run Time | uint16 LE, 65535=N/A |

## Changelog

### Version 1.0.27 (Latest)
- **Conditional Entity Creation**: Entities are now created only if the detected BLE protocol supports them (Issue #28)
  - AA55/AA66 basic protocols only create core entities
  - Extended entities (backlight, offset, CO) only for encrypted protocols and CBFF
  - Config entities (language, pump type, tank volume) only for AA66Encrypted and CBFF
  - Unit switches only for AA66Encrypted, ABBA, CBFF
  - Mode 0 (unknown) creates all entities as safe fallback
- **Backlight Select Entity**: Replaced 0-100 number slider with discrete value select matching the Vevor app (Issue #25)
  - Values: Off, 1-10, 20, 30, ..., 100
- **CBFF/Sunster Protocol**: Support for Sunster TB10Pro WiFi and similar heaters
  - 47-byte CBFF notifications with optional double-XOR encryption
  - Full sensor support: HW/SW version, remaining run time, temp diff, CO
- **Entity Unique ID Migration**: Seamless migration from older entity names — history is preserved
- **Standalone Protocol Library**: `diesel_heater_ble` package extracted for future PyPI/HA core submission
- **`entry.runtime_data` Pattern**: Migrated to modern HA config entry data pattern
- **Estimated Fuel Sensors**: Renamed fuel tracking sensors with "Estimated" prefix for clarity
  - Added "Estimated Fuel Since Refuel" sensor
- **ABBA Fixes**: Fixed power off (toggle via 0xA1), fixed device detection regression, fixed case_temperature byte order
- **BLE Resilience**: Status request retries (3x) and stale data tolerance (3 cycles) before going Unavailable
- **Manifest**: Added `integration_type: device` and `loggers` for HA core preparation
- **Test Suite**: 213 tests covering all 6 protocol parsers, config flow, and library parity
- Special thanks to @Xev for extensive protocol research, beta testing, and detailed feedback

### Version 1.0.26
- **ABBA Protocol Support**: Full support for HeaterCC/AirHeaterCC app heaters
  - Status parsing (Heating, Off, Cooldown, Ventilation, Standby)
  - Temperature readings (cabin and case)
  - Mode display (Level/Temperature)
  - Voltage reading and ABBA-specific error code detection (E2-E10, EC0)
- **Configuration Settings** (AirHeaterBLE-like):
  - Language selection (English, Chinese, German, Silent, Russian)
  - Temperature Unit (Celsius/Fahrenheit)
  - Altitude Unit (Meters/Feet)
  - Tank Volume selection (None, 5L-50L) via index-based dropdown
  - Pump Type selection (16µl, 22µl, 28µl, 32µl)
  - Temperature Offset (-9 to +9)
- **Auto Temperature Offset**: Automatic offset adjustment using external HA temperature sensor
  - Configure external sensor in integration options
  - Automatically calculates and sends offset to heater
  - Configurable maximum offset (1-9)
  - Persists state across restarts
- **Climate Presets**: Added Away and Comfort presets with configurable temperatures
- **Entity Organization**: Diagnostic sensors moved to diagnostic category, configuration entities to config category
- **Improved Error Handling**: Better error detection and reporting for all protocols
- **Debug Service**: `vevor_heater.send_command` for raw BLE command debugging
  - Target specific heaters by MAC address
  - Supports negative argument values (-128 to 127)
- Special thanks to @Xev and @postal for extensive testing and ABBA protocol research

### Version 1.0.25
- **Statistics Graphing Fix**: Fixed `async_add_external_statistics` for HA 2026.11+ compatibility
  - Fixed timestamp format (now uses midnight instead of end of day)
  - Added `mean_type` and `unit_class` to StatisticMetaData
  - Statistics now appear correctly in Developer Tools → Statistics
- **Preset Mode Fix**: Fixed PRESET_NONE not persisting after page refresh
  - Added `_user_cleared_preset` flag to prevent auto-detection from overriding "None" selection
  - Fixed preset_mode to return "none" string instead of Python None

### Version 1.0.22
- **Statistics Fix**: Fixed "Invalid statistic_id" error preventing statistics graphs from working
  - `statistic_id` now includes device MAC address for uniqueness
  - Supports multiple heaters without conflicts

### Version 1.0.21
- **Custom PIN Support**: Heaters with custom PINs can now be configured
  - Added PIN option in config flow during setup (default: 1234)
  - PIN can be changed later in integration options
  - Users who changed their PIN via the Vevor app can now use this integration

### Version 1.0.20
- **Auto Start/Stop Switch**: New switch entity to toggle automatic temperature control with full stop
  - When enabled in Temperature mode, the heater completely stops when room temp reaches 2°C above target
  - Without this, the heater only reduces power to level 1 but keeps running
- **Time Sync Button**: Sync heater's internal clock with Home Assistant time
- **Ventilation Mode Detection**: Now properly detects Ventilation mode (running_step=6)
- **Better Temperature Unit Detection**: Uses byte 27 to detect Celsius vs Fahrenheit instead of `>50` heuristic
- **Auto Start/Stop State Parsing**: Reads byte 31 to show current Auto Start/Stop state
- Based on protocol analysis by @Xev and the [warehog/esphome-diesel-heater-ble](https://github.com/warehog/esphome-diesel-heater-ble) project

### Version 1.0.19
- **Set Level Statistics**: Added `state_class: measurement` to enable graphing in HA statistics
- **Level Control Availability Fix**: Level control (fan entity) is now only available in Level Mode
  - In Manual mode (mode 0), level control shows as unavailable (only Start/Stop allowed)
  - In Temperature mode (mode 2), level control is unavailable (automatic)

### Version 1.0.18
- **Temperature Unit Auto-Detection Fix**: Fixed temperature setting on some mode 4 heaters
  - Auto-detect whether heater uses Celsius or Fahrenheit from its response
  - Send temperature commands in the same unit the heater expects
  - Fixes issues on Celsius-based mode 4 heaters (e.g., Vevor XMZ-F-D5)

### Version 1.0.17
- **Runtime Tracking**: Track how long your heater runs with new sensors
  - Daily Runtime - Hours of operation today (resets at midnight)
  - Total Runtime - Cumulative hours of operation
  - Daily Runtime History - Last 30 days of runtime data
  - Tracks only when heater is in "Running" step
  - Persistent storage and native HA Statistics integration for graphing

### Version 1.0.16
- **18-byte AA55 Protocol Support**: Some heaters send 18-byte AA55 packets instead of 20-byte
  - Integration now accepts both variants
  - Fixes "Unknown protocol, length: 18" warnings
  - Thanks to @zak4206 for identifying this issue

### Version 1.0.15
- **OptionsFlow Fix**: Fixed crash on Home Assistant 2024.1+
  - Fixed `AttributeError: property 'config_entry' has no setter`
  - `OptionsFlow.config_entry` is now automatically set by the framework

### Version 1.0.14
- **F-variant UUID Support**: Fixed connection for F-variant heaters (e.g., ZM8006)
  - Integration now automatically tries both UUID variants: `FFE0/FFE1` and `FFF0/FFF1`
  - Fixes "Could not find heater characteristic" error
- **Renamed to Auto Temperature Mode**: Better aligns with AirHeaterBLE app terminology

### Version 1.0.13
- **BLE Connection Resilience**: Improved stability for intermittent Bluetooth connections
  - Added "stale data tolerance" - keeps last valid sensor values for 3 failed cycles instead of immediately showing unavailable
  - Reduced log spam by using debug level for repeated connection failures
  - Only shows warning after 4+ consecutive failures
  - Better connection failure handling with cached last valid data

### Version 1.0.12
- **Case Temperature Auto-Detection**: Fixed case temperature parsing for heaters that send direct °C values
  - Some heaters (AA66 unencrypted) send case temperature as direct °C, not 0.1°C format
  - Added auto-detection: if raw value > 350, divide by 10 (0.1°C format); otherwise use raw value (direct °C)
  - Thanks to Umberto for reporting and testing

### Version 1.0.11
- **AA66 Encrypted Protocol Support**: Fixed temperature control for heaters using AA66 encrypted protocol (mode 4)
  - Added protocol-aware command building with extensive debug logging
  - Fixed: Always use AA55 commands (heater only accepts AA55, regardless of response protocol)
  - Fixed: Convert temperature to Fahrenheit for mode 4 heaters that use Fahrenheit internally
  - Fixed: Use `round()` instead of `int()` for temperature conversion to avoid off-by-one errors
- Tested and confirmed working with ESPHome BLE proxy setups
- Resolves Issue #1 for users with AA66 encrypted heaters

### Version 1.0.10
- **ESPHome BLE Proxy Fix**: Fixed temperature setting for ESPHome BLE proxy users (Issue #1)
  - Fixed temperature range from 1-36 to correct 8-36°C
  - Changed BLE write to use `response=False` to avoid 'Insufficient authorization' error with ESPHome BLE proxy and other BLE relay setups
  - Added logging for temperature setting commands
- Resolves issue where target temperature would always revert to 36°C

### Version 1.0.9
- **Critical BLE Connection Stability Fixes**: Resolved 7 major connection problems causing heater unavailability
  - Fixed notification UUID mismatch preventing proper disconnect/reconnect
  - Added proper connection cleanup on failures
  - Increased status request timeout from 2s to 5s
  - Added device wake-up mechanism for deep sleep recovery
  - Limited internal retry attempts to reduce log spam
  - Added service discovery validation
  - Improved connection state cleanup
- Eliminates 'No status received' errors, 'Failed to cancel connection' errors, and '[org.bluez.Error.InProgress]' errors

### Version 1.0.8
- **Native Statistics Graphing**: Daily fuel consumption now automatically imports into Home Assistant statistics
  - No ApexCharts or custom cards needed!
  - Use built-in `statistics-graph` card for beautiful bar/line charts
  - Historical data automatically imported at startup
  - Existing fuel history (up to 30 days) is retroactively imported
  - Works natively with Home Assistant's energy dashboard integration
- **Documentation Fix**: Corrected entity names in README
  - Updated all sensor entity IDs from `sensor.vevor_heater_*` to `sensor.vevor_diesel_heater_*`
  - Fixed dashboard card examples with correct entity names
- **Minor Fix**: Improved sensor availability when heater is offline to prevent graph spikes

### Version 1.0.7
- **New Feature**: Historical Daily Fuel Consumption Tracking
  - Added `sensor.vevor_diesel_heater_daily_fuel_history` to track daily fuel consumption over time
  - Stores last 30 days of consumption data with automatic cleanup
  - History persists across Home Assistant restarts
  - Daily values automatically saved to history at midnight before reset
  - New sensor attributes:
    - `history` - Complete daily consumption history (date -> liters)
    - `days_tracked` - Number of days in history
    - `total_in_history` - Total fuel consumed in tracked period
    - `last_7_days` - Total consumption for last 7 days
    - `last_30_days` - Total consumption for last 30 days
- **Dashboard Integration**: Added comprehensive graphing examples
  - ApexCharts configurations for bar and line charts
  - Built-in card examples (markdown, attributes)
  - Support for 7-day, 30-day, and custom time ranges
- **Data Persistence**: History automatically saved with daily resets

### Version 1.0.6
- **Critical Fixes**: Prevent crashes and fix daily fuel reset when heater is offline
  - Fixed commands (turn on/off, set level/temperature) causing HA crashes when heater disconnected
  - Commands now check connection status before requesting refresh
  - Only refresh state if command was successfully sent
  - Fixed daily fuel counter not resetting at midnight when heater offline
  - Daily reset check now runs on every coordinator update regardless of connection
  - Reset happens even if heater is off/unreachable at midnight

### Version 1.0.5
- **Critical Fix**: Prevent Home Assistant crashes during integration startup
  - Added 30-second timeout on initial connection attempt
  - Setup now completes even if heater is offline/unreachable
  - Integration retries connection in background every 30 seconds
  - Entities show as "unavailable" until connection succeeds
  - **Home Assistant now starts normally** even if heater is off/out of range
  - Improved logging with helpful troubleshooting messages

### Version 1.0.4
- **Bug Fix**: Fixed Daily Fuel Consumed sensor not resetting at midnight
  - Added runtime check for date change (previously only checked at startup)
  - Daily counter now properly resets to 0.0L when midnight passes
  - Separate tracking for daily vs total fuel consumption
  - Data automatically saved after midnight reset

### Version 1.0.3
- **Fuel Consumption Tracking** - Monitor fuel usage based on power level estimation
  - Hourly consumption rate sensor (L/h) - instantaneous rate with decimal precision
  - Daily fuel consumed sensor (L) - automatically resets at midnight
  - Total fuel consumed sensor (L) - lifetime consumption tracking
  - Data persisted across Home Assistant restarts
- **Bug Fixes**
  - Fixed climate entity showing as unavailable in newer HA versions
  - Fixed fuel sensors showing "Unknown" values
  - Fixed fuel tracking not updating due to protocol parser bug
  - Fixed hourly fuel consumption displaying integers instead of decimals
- **Improvements**
  - Removed non-functional "Manual" mode from running mode selector
  - Running mode can now be switched between "Level Mode" and "Temperature Mode"
  - Manual mode only accessible via physical heater buttons
- Consumption calculated using VEVOR specifications (0.16-0.52 L/h range)
- Compatible with all protocol variants (AA55/AA66, encrypted/unencrypted)

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
- **@Xev** - Extensive testing, protocol research, ABBA/CBFF protocol analysis, Sunster app reverse engineering, and invaluable feedback throughout development
- **@postal** - ABBA protocol byte mapping and verification
- **@triptyx-ux** - ABBA and CBFF/Sunster heater testing
- **@zak4206** - 18-byte AA55 protocol identification
- **@warehog** - [esphome-diesel-heater-ble](https://github.com/warehog/esphome-diesel-heater-ble) protocol documentation and AirHeaterBLE app analysis
- Based on the [vevor-ble-bridge](https://github.com/andyrak/vevor-ble-bridge) protocol documentation
- Thanks to the Home Assistant community for support and testing

## Support

If you encounter issues, please:
1. Check the [Issues](https://github.com/Spettacolo83/homeassistant-vevor-heater/issues) page
2. Enable debug logging and include logs in your report:
   ```yaml
   logger:
     logs:
       custom_components.vevor_heater: debug
   ```
3. Provide your heater model, protocol type (AA55/AA66/ABBA), and which app works with your heater (AirHeaterBLE or AirHeaterCC)

---

**Disclaimer**: This is an unofficial integration and is not affiliated with Vevor or BYD.
