---
title: Diesel Heater
description: Instructions on how to integrate supported diesel-heater Bluetooth Low Energy protocols.
ha_category:
  - Climate
  - Sensor
  - Binary sensor
  - Switch
  - Select
  - Number
  - Button
  - Fan
ha_release: "2025.2"
ha_iot_class: Local Polling
ha_codeowners:
  - '@Spettacolo83'
ha_domain: diesel_heater
ha_bluetooth: true
ha_platforms:
  - binary_sensor
  - button
  - climate
  - fan
  - number
  - select
  - sensor
  - switch
ha_config_flow: true
ha_integration_type: device
ha_quality_scale: bronze
---

The **Diesel Heater** {% term integration %} allows you to control and monitor supported diesel air and water heater controllers via Bluetooth Low Energy (BLE). This integration provides local control without requiring cloud connectivity.

## Supported devices

This integration supports heaters whose BLE transport and status protocol match a supported controller family:

- **AirHeaterBLE** AA55 and AA66 controllers, encrypted or unencrypted
- **HeaterCC/AirHeaterCC** ABBA controllers
- **Sunster** CBFF/FEAA V2.1 controllers
- **Hcalory** MVP1 and MVP2 controllers
- **HeatGenie/Boygu** register-protocol controllers
- **Webasto ThermoConnect Cronus** air and water controllers

Brand names and an app installation alone do not establish compatibility. The
integration verifies the protocol after connecting.

### Supported protocols

| Protocol | App | Notes |
|----------|-----|-------|
| AA55 | AirHeaterBLE | Original Vevor protocol |
| AA55 Encrypted | AirHeaterBLE | XOR encrypted variant |
| AA66 | AirHeaterBLE | 20-byte variant |
| AA66 Encrypted | AirHeaterBLE | Encrypted, Fahrenheit internal |
| ABBA | AirHeaterCC | HeaterCC heaters |
| CBFF/FEAA | Sunster | V2.1 protocol; encrypted variants use double XOR |
| Hcalory MVP1/MVP2 | Hcalory | Separate Hcalory transport variants |
| HeatGenie / Boygu | Heat Genie | Register protocol with optional probes and component state bits |
| Webasto Cronus | ThermoConnect | Record protocol for air and water controllers |

See the [protocol reference](protocols/README.md) for the validated transport,
status, and command behavior for each family.

## Prerequisites

Before setting up this integration:

1. Your diesel heater must be powered on and within Bluetooth range (typically 10-30 meters)
2. Close or disconnect the mobile controller app if it is actively connected to the heater. Connection behavior varies by controller
3. The [Bluetooth](/integrations/bluetooth) integration must be set up and functional

{% include integrations/config_flow.md %}

## Configuration options

After setup, you can configure these options:

| Option | Description |
|--------|-------------|
| PIN Code | 4-digit PIN for heater authentication (default: 1234) |
| Temperature Offset | Manual calibration offset for the temperature sensor (-20 to +20°C) |
| Away Preset Temperature | Temperature for Away preset (default: 8°C) |
| Comfort Preset Temperature | Temperature for Comfort preset (default: 21°C) |
| External Temperature Sensor | Select an external HA temperature sensor for automatic offset calibration |
| Max Auto Offset | Maximum automatic offset when using external sensor (1-9°C) |

## Entities

Entities are created based on the detected BLE protocol. Only entities supported by your heater's protocol are created.

### Availability by controller family

| Controller family | Additional controls and telemetry | Important limits |
|---|---|---|
| AA55 / AA66 | Established air-heater entities and local auto-offset | No encrypted-controller settings, timer, component bits, or intake/outlet probes |
| AA55 Encrypted | Temperature Offset, Backlight, and Timer | No Language, Pump Type, Tank Volume, or unit switches |
| AA66 Encrypted | Temperature Offset, Backlight, Timer, Language, Pump Type, Tank Volume, Auto Start/Stop, Temperature Unit, and Altitude Unit | Extended telemetry only where reported |
| ABBA / HeaterCC | Auto Start/Stop, Temperature Unit, Altitude Unit, High Altitude, and supported ventilation | No timer, component bits, or intake/outlet probes |
| CBFF / Sunster | Extended telemetry, controller configuration, unit settings, Auto Start/Stop, and CBFF diagnostics | No component bits or intake/outlet probes |
| Hcalory MVP1/MVP2 | Auto Start/Stop, Temperature Unit, and three-position High Altitude Mode | No altitude sensor, auto-offset, timer, component bits, or intake/outlet probes |
| HeatGenie / Boygu | Temperature Unit, optional Intake/Outlet Temperature, and Fuel Pump/Fan/Glow Plug state bits | No auto-offset, timer, or controller configuration selects |
| Webasto Cronus | ThermoConnect Mode, controller-specific temperatures and durations, Continuous Run, and Interlock | Air and water capabilities differ; see the sections below |

### Climate

The climate entity provides thermostat control:

- Temperature range: controller-specific
- Presets: Away, Comfort (not created for Cronus)
- HVAC modes: Off, Heat

### Fan

Fan entity for heater level control (1-10) when in Level mode. It is not created for Cronus.

### Sensors

| Sensor | Description |
|--------|-------------|
| Interior Temperature | Cabin/room temperature |
| Case Temperature | Heater body temperature (not Cronus) |
| Supply Voltage | Power supply voltage |
| Running Step | Current operation step (established air-heater protocols) |
| Running Mode | Current mode (established air-heater protocols) |
| Set Level | Current power level setting |
| Altitude | Current altitude reading (not Hcalory or Cronus) |
| Error | Error code if any fault detected (not Cronus) |
| Estimated Hourly Fuel Consumption | Locally estimated rate for established air-heater protocols and selected Cronus model profiles |
| Estimated Daily Fuel Consumed | Locally estimated daily consumption for established air-heater protocols and selected Cronus model profiles |
| Estimated Total Fuel Consumed | Locally estimated lifetime consumption for established air-heater protocols and selected Cronus model profiles |
| Daily Runtime | Locally tracked daily runtime for established air-heater protocols and selected Cronus model profiles |
| Total Runtime | Locally tracked cumulative runtime for established air-heater protocols and selected Cronus model profiles |

Additional sensors for specific protocols:
- **Carbon Monoxide** (CBFF): CO level in ppm
- **Hardware/Software Version** (CBFF): Firmware information
- **Remaining Run Time** (CBFF): Time until auto-shutoff
- **Intake/Outlet Temperature** (HeatGenie): created only when that controller reports the probe
- **External/Coolant Temperature and Run Duration** (Cronus): ThermoConnect record telemetry
- **Air Pressure** (Cronus air controllers): controller-reported pressure
- **Mode** (Cronus water controllers): read-only controller telemetry

### Binary sensors

| Sensor | Description |
|--------|-------------|
| Active | Whether the heater is currently heating |
| Problem | Whether an error condition exists |
| Connected | BLE connection status |
| Auto Start/Stop | Auto temperature control status |
| Fuel Pump, Fan, Glow Plug | HeatGenie component bits |
| Continuous Run, Interlock | Cronus controller status |

### Switches

| Switch | Description |
|--------|-------------|
| Power | Turn heater on/off |
| Auto Temperature Offset | Enable automatic offset using external sensor (not Hcalory, HeatGenie, or Cronus) |
| Auto Start/Stop | Enable automatic temperature control with full stop |
| Fahrenheit Mode | Use Fahrenheit for temperature display |
| Feet Mode | Use feet for altitude display |
| High Altitude Mode | ABBA binary setting or Hcalory MVP2 three-position setting |

### Selects

| Select | Description |
|--------|-------------|
| Running Mode | Switch between Level and Temperature modes; ABBA can additionally offer Ventilation |
| Cronus Mode | Air controllers only: Heating, Ventilation, Boost, and Eco |
| Language | Display language (EN, CN, DE, Silent, RU) |
| Pump Type | Fuel pump type (16/22/28/32 µl) |
| Tank Volume | Tank size for fuel estimation |
| Backlight | Display backlight brightness |
| High Altitude Mode | Hcalory MVP2: Disabled, Mode 1, Mode 2 |

### Numbers

| Number | Description |
|--------|-------------|
| Level | Set heater power level (1-10); Cronus air controllers expose it in Ventilation mode |
| Target Temperature | Set target temperature within the controller-supported range; Cronus air controllers expose it outside Ventilation mode |
| Temperature Offset | Manual temperature offset (-9 to +9) |
| Tank Capacity | Tank capacity for fuel tracking |

### Buttons

| Button | Description |
|--------|-------------|
| Sync Time | Synchronize heater clock with Home Assistant (not Cronus) |
| Reset Estimated Fuel Remaining | Reset local fuel tracking after refueling (not Cronus) |

## Actions

### Action `diesel_heater.send_command`

Send a raw command to the heater for debugging purposes.

| Data attribute | Optional | Description |
| ---------------------- | -------- | ----------- |
| `device_id` | no | Device ID of the heater |
| `command` | no | Command number (1-20) |
| `argument` | yes | Command argument (-128 to 127) |

## Fuel consumption tracking

The integration estimates fuel consumption based on the heater's power level (0.16-0.52 L/h range). Consumption data is:

- Calculated in real-time while the heater is running
- Persisted across Home Assistant restarts
- Available for graphing via Home Assistant's native statistics

For **Webasto Cronus Smart** controllers, the mobile protocol reports whether the controller is connected to an air or water heater, but does not report the attached heater model. Fuel-tracking entities are therefore disabled until the installed model is selected in the integration options. The available diesel profiles are Air Top Evo 40/55 and Thermo Top Evo 4/5 kW. Ventilation is tracked as zero fuel use; heating is an estimate from the model's documented modulation range, with the air-heater Boost and Eco modes using their documented mode behavior.

### Graphing fuel consumption

Use the built-in statistics graph card:

```yaml
type: statistics-graph
entities:
  - sensor.diesel_heater_daily_fuel_consumed
stat_types:
  - sum
period: day
days_to_show: 7
chart_type: bar
title: Daily Fuel Consumption
```

## Troubleshooting

### Device not discovered

1. Ensure the heater is powered on
2. Close or disconnect the mobile controller app if it is actively connected to the heater
3. Close the heater app completely
4. Check that the Bluetooth integration is active

### Connection drops frequently

- ESPHome Bluetooth proxies have limited simultaneous connections (3-7 depending on ESP32 model)
- Raspberry Pi 4's built-in Bluetooth can be unreliable - consider using an external USB Bluetooth 5.0 dongle
- Reduce distance and obstacles between the Bluetooth adapter and heater

### Temperature control not working

For established air-heater protocols, temperature control requires **Temperature Mode**. Cronus air controllers provide a setpoint in Heating, Boost, and Eco modes; their Ventilation mode has no temperature setpoint. Cronus water controllers do not expose an air setpoint.

### Commands not responding

1. Verify the correct PIN is configured (default: 1234)
2. Check that no other device (phone app) is connected to the heater
3. Enable debug logging:

```yaml
logger:
  logs:
    custom_components.diesel_heater: debug
    diesel_heater_ble: debug
```

## Removing the integration

{% include integrations/remove_device_service.md %}
