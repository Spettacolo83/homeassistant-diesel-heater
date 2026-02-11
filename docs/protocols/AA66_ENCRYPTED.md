# AA66 Encrypted Protocol

**Protocol Mode**: 4
**App**: AirHeaterBLE
**Packet Length**: 48 bytes (encrypted)

## Overview

The AA66 Encrypted protocol is a variant that uses XOR encryption (same as AA55 Encrypted) but has additional configuration bytes including temperature unit, language, tank volume, and pump type settings.

## BLE Configuration

| Type | UUID |
|------|------|
| Service | `0000FFE0-0000-1000-8000-00805F9B34FB` |
| Write Char | `0000FFE1-0000-1000-8000-00805F9B34FB` |
| Notify Char | `0000FFE1-0000-1000-8000-00805F9B34FB` |

## Encryption

Same XOR encryption as AA55 Encrypted:
```python
ENCRYPTION_KEY = bytearray([0x31, 0x32, 0x33, 0x34, 0x35, 0x36, 0x37, 0x38])
```

## Decrypted Packet Structure

```
Offset  Bytes  Field                Description
------  -----  -----                -----------
0-1     2      Header               AA 66
2       1      Reserved
3       1      Running State        0=off, 1=on
4       1      Reserved
5       1      Running Step
6-7     2      Altitude             Big-endian, /10 for meters
8       1      Running Mode         1=level, 2=temp
9       1      Set Temp             May be Fahrenheit internally
10      1      Set Level            Gear level
11-12   2      Voltage              Big-endian, /10 for volts
13-14   2      Case Temp            Big-endian, signed
15-25   11     Reserved
26      1      Language             Language index
27      1      Temp Unit            0=Celsius, 1=Fahrenheit
28      1      Tank Volume          Tank volume index
29      1      Pump Type/RF433      20=RF off, 21=RF on, else pump type
30      1      Altitude Unit        0=meters, 1=feet
31      1      Auto Start/Stop      0=off, 1=on
32-33   2      Cab Temp             Big-endian, /10 for °C
34      1      Heater Offset        Signed (-20 to +20)
35      1      Error Code           Different position than AA55
36      1      Backlight            0-100 brightness
37      1      CO Sensor Present    0=no, 1=yes
38-39   2      CO PPM               Big-endian
40-43   4      Part Number          Little-endian, hex string
44      1      Motherboard Version
45-47   3      Padding
```

## Internal Fahrenheit Handling

Some heaters store temperature in Fahrenheit internally (byte 27 = 1). The parser converts to Celsius:

```python
if heater_uses_fahrenheit:
    parsed["set_temp"] = max(8, min(36, round((raw_set_temp - 32) * 5 / 9)))
else:
    parsed["set_temp"] = max(8, min(36, raw_set_temp))
```

## Pump Type / RF433 Logic

Byte 29 has dual meaning:
- `20` = RF433 disabled, pump_type = None
- `21` = RF433 enabled, pump_type = None
- Other values = pump_type index, rf433_enabled = None

## Parsing Logic

```python
def parse(data: bytearray) -> dict:
    parsed = {}

    parsed["running_state"] = data[3]
    parsed["error_code"] = data[35]  # Note: different position
    parsed["running_step"] = data[5]
    parsed["altitude"] = (data[7] + 256 * data[6]) / 10
    parsed["running_mode"] = data[8]
    parsed["set_level"] = max(1, min(10, data[10]))

    # Temperature unit detection
    temp_unit = data[27]
    parsed["temp_unit"] = temp_unit
    uses_fahrenheit = (temp_unit == 1)

    # Set temperature with unit conversion
    raw_temp = data[9]
    if uses_fahrenheit:
        parsed["set_temp"] = max(8, min(36, round((raw_temp - 32) * 5 / 9)))
    else:
        parsed["set_temp"] = max(8, min(36, raw_temp))

    # Configuration settings
    parsed["language"] = data[26]
    parsed["tank_volume"] = data[28]
    parsed["altitude_unit"] = data[30]
    parsed["auto_start_stop"] = (data[31] == 1)

    # Pump type / RF433
    pump_byte = data[29]
    if pump_byte == 20:
        parsed["rf433_enabled"] = False
    elif pump_byte == 21:
        parsed["rf433_enabled"] = True
    else:
        parsed["pump_type"] = pump_byte

    parsed["supply_voltage"] = (256 * data[11] + data[12]) / 10
    parsed["case_temperature"] = signed_int16(256 * data[13] + data[14])
    parsed["cab_temperature"] = signed_int16(256 * data[32] + data[33]) / 10

    # Extended fields (same as AA55 Encrypted)
    if len(data) > 34:
        raw = data[34]
        parsed["heater_offset"] = (raw - 256) if raw > 127 else raw
    if len(data) > 36:
        parsed["backlight"] = data[36]
    # ... CO sensor, part number, motherboard version

    return parsed
```

## Detection

Detected when:
1. Header is AA66
2. Packet length is 48 bytes
3. Decryption produces valid values
