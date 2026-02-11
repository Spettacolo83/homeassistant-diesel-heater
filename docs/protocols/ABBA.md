# ABBA Protocol (HeaterCC)

**Protocol Mode**: 5
**App**: AirHeaterCC
**Packet Length**: 21+ bytes

## Overview

The ABBA protocol is used by HeaterCC-compatible heaters. It has a completely different command structure using BAAB headers instead of AA55. This protocol supports ventilation mode and uses different status codes.

## BLE Configuration

| Type | UUID |
|------|------|
| Service | `0000FFE0-0000-1000-8000-00805F9B34FB` |
| Write Char | `0000FFE1-0000-1000-8000-00805F9B34FB` |
| Notify Char | `0000FFE1-0000-1000-8000-00805F9B34FB` |

## Response Packet Structure

```
Offset  Bytes  Field                Description
------  -----  -----                -----------
0-1     2      Header               AB BA (response) or BA AB (command)
2-3     2      Length/Type
4       1      Status               0=Off, 1=Heating, 2=Cooldown, 4=Vent, 6=Standby
5       1      Mode                 0=Level, 1=Temp, 0xFF=Error
6       1      Gear/Temp/Error      Depends on mode
7       1      Reserved
8       1      Auto Start/Stop      0=off, 1=on
9       1      Voltage              Single byte volts
10      1      Temp Unit            0=Celsius, 1=Fahrenheit
11      1      Environment Temp     Raw value (see parsing)
12-13   2      Case Temperature     Big-endian uint16
14      1      Altitude Unit        0=meters, 1=feet
15      1      High Altitude Mode   0=off, 1=on
16-17   2      Altitude             Little-endian uint16
18-20   3      Checksum/Padding
```

## Status Codes

| Value | Status | Description |
|-------|--------|-------------|
| 0x00 | Off | Heater is off |
| 0x01 | Heating | Actively heating |
| 0x02 | Cooldown | Cooling down after heating |
| 0x04 | Ventilation | Fan-only mode (no heating) |
| 0x06 | Standby | Ready, waiting for command |

## Mode Interpretation

| Byte 5 | Byte 6 | Interpretation |
|--------|--------|----------------|
| 0x00 | gear | Level mode, gear 1-10 |
| 0x01 | temp | Temperature mode, 8-36°C |
| 0xFF | error | Error mode, byte 6 is error code |

## Temperature Parsing

Environment temperature (byte 11) requires offset subtraction:
```python
# Fahrenheit mode: subtract 22
# Celsius mode: subtract 30
offset = 22 if uses_fahrenheit else 30
cab_temperature = raw_value - offset
```

## Parsing Logic

```python
def parse(data: bytearray) -> dict:
    if len(data) < 21:
        return None

    parsed = {"connected": True}

    # Status
    status_byte = data[4]
    parsed["running_state"] = 1 if status_byte == 0x01 else 0
    parsed["running_step"] = STATUS_MAP.get(status_byte, status_byte)

    # Mode
    mode_byte = data[5]
    if mode_byte == 0xFF:
        parsed["error_code"] = data[6]
    else:
        parsed["error_code"] = 0
        if mode_byte == 0x00:
            parsed["running_mode"] = 1  # Level
        elif mode_byte == 0x01:
            parsed["running_mode"] = 2  # Temperature

    # Gear/Temp (only if not in error state)
    if "running_mode" in parsed:
        gear_byte = data[6]
        if parsed["running_mode"] == 1:
            parsed["set_level"] = max(1, min(10, gear_byte))
        else:
            parsed["set_temp"] = max(8, min(36, gear_byte))

    parsed["auto_start_stop"] = (data[8] == 1)
    parsed["supply_voltage"] = float(data[9])
    parsed["temp_unit"] = data[10]

    # Cab temperature with offset
    uses_f = (data[10] == 1)
    parsed["cab_temperature"] = float(data[11] - (22 if uses_f else 30))
    parsed["cab_temperature_raw"] = parsed["cab_temperature"]

    # Case temperature (big-endian)
    parsed["case_temperature"] = float((data[12] << 8) | data[13])

    parsed["altitude_unit"] = data[14]
    parsed["high_altitude"] = data[15]
    parsed["altitude"] = data[16] | (data[17] << 8)

    return parsed
```

## Command Format

ABBA uses its own command format:
```
Byte 0-1: BA AB (command header)
Byte 2-3: 04 XX (length/type)
Byte 4-5: Command bytes
Byte 6:   Argument (if applicable)
Byte 7:   00 (padding)
Last:     Checksum (sum of all bytes & 0xFF)
```

## Command Mapping

| AA55 Cmd | ABBA Command | Description |
|----------|--------------|-------------|
| 1 | `baab04cc000000` | Status request |
| 3 (on/off) | `baab04bba10000` | Toggle heat (same cmd for on/off) |
| 4 (temp) | `baab04db[TT]0000` | Set temperature |
| 2 (mode=2) | `baab04bbac0000` | Constant temp mode |
| 2 (mode=3) | `baab04bba40000` | Ventilation mode |
| 15 (F) | `baab04bba80000` | Set Fahrenheit |
| 15 (C) | `baab04bba70000` | Set Celsius |
| 19 (ft) | `baab04bbaa0000` | Set feet |
| 19 (m) | `baab04bba90000` | Set meters |
| 99 | `baab04bba50000` | Toggle high altitude |
| 101 | `baab04bba40000` | Ventilation (direct) |

## Special Behavior

1. **Toggle Power**: ABBA uses a single toggle command (0xA1) for both on and off
2. **Ventilation Mode**: Only works when heater is in standby/off state
3. **No Calibration**: ABBA protocol sets `cab_temperature_raw` directly
4. **Post-Status**: Requires sending status request after commands

## Detection

Detected when:
1. Header starts with `BAAB` or `ABBA`
2. Packet length is at least 21 bytes
