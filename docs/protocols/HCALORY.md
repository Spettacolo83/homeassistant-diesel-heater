# Hcalory Protocol (MVP1/MVP2)

**Protocol Mode**: 7
**App**: Hcalory
**Packet Length**: Variable (command-dependent)

## Overview

The Hcalory protocol is used by Hcalory HBU1S and similar diesel heaters. It comes in two variants:
- **MVP1**: Older models with FFF0 service UUID
- **MVP2**: Newer models with BD39 service UUID (e.g., HBU1S)

This protocol uses a completely different packet structure from AA55/ABBA/CBFF protocols.

## Credits

Protocol reverse-engineered by [@Xev](https://github.com/Xev) from the Hcalory Android APK using jadx decompilation. Published in [Issue #33](https://github.com/Spettacolo83/homeassistant-diesel-heater/issues/33).

## BLE Configuration

### MVP1 (Older Models)

| Type | UUID |
|------|------|
| Service | `0000FFF0-0000-1000-8000-00805F9B34FB` |
| Write Char | `0000FFF2-0000-1000-8000-00805F9B34FB` |
| Notify Char | `0000FFF1-0000-1000-8000-00805F9B34FB` |

### MVP2 (Newer Models - HBU1S)

| Type | UUID |
|------|------|
| Service | `0000BD39-0000-1000-8000-00805F9B34FB` |
| Write Char | `0000BDF7-0000-1000-8000-00805F9B34FB` |
| Notify Char | `0000BDF8-0000-1000-8000-00805F9B34FB` |

## Command Format

All commands follow this structure:
```
Offset  Bytes  Field            Description
------  -----  -----            -----------
0-1     2      Protocol ID      Always 00 02
2-3     2      Reserved         Always 00 01
4-5     2      Flags            00 01=expects response, 00 00=no response
6-9     4      Command Type     e.g., 06 07 = set gear
10-11   2      Reserved         Always 00 00
12-15   4      Payload Length   Hex, e.g., 00 01 = 1 byte
16-N    N      Payload          Command-specific data
N+1-N+2 2      Checksum         Sum of all previous bytes & 0xFF
```

### Example: Set Gear to Level 3
```
00 02 00 01 00 01 00 06 07 00 00 01 03 [checksum]
└──┬──┘└──┬──┘└──┬──┘└────┬────┘└──┬──┘└────┬────┘
  Proto  Resv  Flags   CmdType  Resv  PayloadLen=1 → Payload=3
```

## Response Format

```
Offset  Hex Chars  Field            Description
------  ---------  -----            -----------
0-1     2          Protocol Ver     00
2-3     2          Message Type     02 (response)
4-7     4          Reserved         0001
8-9     2          Flags            00 or 01
10-13   4          Message ID       Echo of command type
14-15   2          Total Frames     Usually 01
16-17   2          Frame Sequence   Current frame
18-21   4          Payload Length
22-23   2          dpID             Data Point ID
24-25   2          dpType           Data type
26-29   4          dpLength         Data content length
30-N    N          dpContent        Actual data
N+1-N+2 2          Checksum
```

## Checksum Calculation

```python
def calculate_checksum(hex_string: str) -> str:
    """Calculate 8-bit checksum."""
    hex_string = hex_string.replace(" ", "").upper()
    total = 0
    for i in range(0, len(hex_string), 2):
        byte = int(hex_string[i:i+2], 16)
        total += byte
    return f"{total & 0xFF:02X}"
```

## Command Reference

### Set Gear Level (Command Type: 0607)

```
Payload Length: 0001
Payload: [gear] where gear = 01-06

Full: 00020001000100060700000103 + checksum  (gear 3)
```

### Set Temperature (Command Type: 0706)

```
Payload Length: 0002
Payload: [temp] [unit]
  - unit: 00=Celsius, 01=Fahrenheit

Full: 0002000100010007060000021900 + checksum  (25°C)
Full: 0002000100010007060000024D01 + checksum  (77°F)
```

### Power Control (MVP1 - Command Type: 0E04)

```
Payload Length: 0009
Payload: 00 00 00 00 00 00 00 00 [action]

Actions:
  00 = Query state
  01 = Power on
  02 = Power off
  03 = Enable auto start/stop
  04 = Disable auto start/stop
  0A = Set Celsius
  0B = Set Fahrenheit
  0D = Query altitude (MVP2)
```

### Query State (MVP2 - Command Type: 0A0A)

```
Payload Length: 0005
Payload: [4-byte timestamp] 00

Timestamp formats:
  - HH:MM:SS + day: e.g., 0A1E2D01
  - Unix timestamp: e.g., 6611E8CE
```

### Set Altitude (MVP2 - Command Type: 0909)

```
Payload Length: 0004
Payload: [sign] [altitude_hi] [altitude_lo] [unit]

Sign: 00=positive, 01=negative
Altitude: 16-bit value
Unit: 00=meters, 01=feet

Example: 000200010001000909000004000005DC00  (1500m)
```

## Device State Response (dpID 03)

Minimum 76 hex characters (38 bytes). Parse positions are in hex character offsets:

```
Offset  Chars  Field              Description
------  -----  -----              -----------
0-3     4      device_id
4-7     4      timestamp
8-11    4      reserved
12-13   2      highland_gear      MVP2 only
14-15   2      reserved
16-17   2      status_flags       Bit flags (reversed)
18-19   2      device_state       See Device State enum
20-21   2      temp_or_gear       Current setting
22-23   2      auto_start_stop    00=off, 01=on
24-27   4      voltage_raw        Voltage x10
28-29   2      shell_temp_sign    00=pos, 01=neg
30-33   4      shell_temp_raw     Temp x10
34-35   2      ambient_temp_sign  00=pos, 01=neg
36-39   4      ambient_temp_raw   Temp x10
40-45   6      reserved
46-47   2      scene_id
48-49   2      highland_mode      00=off, 01=on (MVP2)
50-51   2      temp_unit          00=°C, 01=°F

MVP2 Extended (60+ chars):
52-53   2      height_unit        00=meter, 01=foot
54-55   2      altitude_sign
56-59   4      altitude_raw
```

### Status Flags Parsing

The status flags byte is bit-reversed before parsing:
```python
def parse_status_flags(flags_hex: str) -> dict:
    flags_byte = int(flags_hex, 16)
    reversed_binary = format(flags_byte, '08b')[::-1]
    return {
        "heating_is_starting": reversed_binary[0] == '1',
        "heating_is_stopping": reversed_binary[1] == '1',
        "fan_is_running": reversed_binary[2] == '1',
        "ignition_plug_running": reversed_binary[3] == '1',
        "oil_pump_running": reversed_binary[4] == '1',
        "operative_state_bits": reversed_binary[6:8],
    }
```

### Temperature/Voltage Parsing

```python
def parse_temperature(sign_hex: str, value_hex: str) -> float:
    sign = -1 if sign_hex == "01" else 1
    return (sign * int(value_hex, 16)) / 10.0

def parse_voltage(voltage_hex: str) -> float:
    return int(voltage_hex, 16) / 10.0
```

## Device State Enum

| Value | Name | Description |
|-------|------|-------------|
| 00 | STANDBY | Device in standby |
| 01 | HEATING_TEMP_AUTO | Temperature control mode |
| 02 | HEATING_MANUAL_GEAR | Manual gear mode |
| 03 | NATURAL_WIND | Fan-only mode |
| FF | MACHINE_FAULT | Error state |

## Operative State Enum

| Value | Name |
|-------|------|
| 00 | HEATING_STOPPED |
| 01 | HEATING |
| 10 | COOLING_ENGINE_BODY |
| 11 | NATURAL_WIND |

## Error Codes

When device_state = FF, error code is in operative state field:

| Code | Name | Description |
|------|------|-------------|
| E01 | IGNITION_FAILURE | Ignition failed |
| E02 | FLAME_OUT | Flame went out |
| E03 | OVERHEAT | Temperature too high |
| E04 | FAN_FAILURE | Fan motor failure |
| E05 | PUMP_FAILURE | Fuel pump failure |
| E06 | SENSOR_FAILURE | Temperature sensor failure |
| E07 | VOLTAGE_LOW | Supply voltage too low |
| E08 | VOLTAGE_HIGH | Supply voltage too high |
| E09 | COMMUNICATION_ERROR | Internal comms error |
| E10 | CO_HIGH | CO concentration high |
| E11 | CO_CRITICAL | CO concentration critical |

## Temperature Unit Enum

| Value | Symbol |
|-------|--------|
| 00 | °C (Celsius) |
| 01 | °F (Fahrenheit) |

## Height Unit Enum

| Value | Unit |
|-------|------|
| 00 | Meter |
| 01 | Foot |

## Gear Levels

| Value | Description |
|-------|-------------|
| 01 | Gear 1 (Lowest) |
| 02 | Gear 2 |
| 03 | Gear 3 |
| 04 | Gear 4 |
| 05 | Gear 5 |
| 06 | Gear 6 (Highest) |

Note: Hcalory uses 6 gear levels, not 10 like other protocols.

## Detection Logic

```python
def detect_hcalory(service_uuids: list) -> str | None:
    MVP1_SERVICE = "0000FFF0-0000-1000-8000-00805F9B34FB"
    MVP2_SERVICE = "0000BD39-0000-1000-8000-00805F9B34FB"

    for uuid in service_uuids:
        if MVP1_SERVICE.upper() in uuid.upper():
            return "MVP1"
        if MVP2_SERVICE.upper() in uuid.upper():
            return "MVP2"
    return None
```

## Implementation Notes

1. **Gear Levels**: Hcalory uses 1-6 levels, not 1-10. Map accordingly.
2. **Temperature Range**: Typical valid range is 10-32°C (50-90°F).
3. **Checksum**: Always calculate and append checksum byte.
4. **MVP1 vs MVP2**: Use different UUIDs and some different commands.
5. **Status Polling**: Use query state command (0A0A for MVP2) to get current status.
6. **Notification Enable**: Write 0x0100 to CCCD descriptor (0x2902) to enable notifications.
