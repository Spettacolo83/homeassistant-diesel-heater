# AA55 Encrypted Protocol

**Protocol Mode**: 2
**App**: AirHeaterBLE
**Packet Length**: 48 bytes (encrypted)

## Overview

The AA55 Encrypted protocol is a variant of AA55 that uses XOR encryption with a hardcoded key. The encrypted data is 48 bytes and contains extended information including backlight, CO sensor, and part number.

## BLE Configuration

Same as AA55:
| Type | UUID |
|------|------|
| Service | `0000FFE0-0000-1000-8000-00805F9B34FB` |
| Write Char | `0000FFE1-0000-1000-8000-00805F9B34FB` |
| Notify Char | `0000FFE1-0000-1000-8000-00805F9B34FB` |

## Encryption

XOR encryption with 8-byte key repeated 6 times:
```python
ENCRYPTION_KEY = bytearray([0x31, 0x32, 0x33, 0x34, 0x35, 0x36, 0x37, 0x38])
# ASCII: "12345678"

def decrypt(data: bytearray) -> bytearray:
    decrypted = bytearray(data)
    for j in range(6):  # 6 blocks of 8 bytes
        for i in range(8):
            idx = 8 * j + i
            if idx < len(decrypted):
                decrypted[idx] ^= ENCRYPTION_KEY[i]
    return decrypted
```

## Decrypted Packet Structure

```
Offset  Bytes  Field                Description
------  -----  -----                -----------
0-1     2      Header               AA 55
2       1      Reserved
3       1      Running State        0=off, 1=on
4       1      Error Code
5       1      Running Step
6-7     2      Altitude             Big-endian, /10 for meters
8       1      Running Mode         1=level, 2=temp
9       1      Set Temp             Temperature setpoint
10      1      Set Level            Gear level
11-12   2      Voltage              Big-endian, /10 for volts
13-14   2      Case Temp            Big-endian, signed
15-31   17     Reserved
32-33   2      Cab Temp             Big-endian, /10 for °C
34      1      Heater Offset        Signed (-20 to +20)
35      1      Reserved
36      1      Backlight            0-100 brightness
37      1      CO Sensor Present    0=no, 1=yes
38-39   2      CO PPM               Big-endian, if sensor present
40-43   4      Part Number          Little-endian, hex string
44      1      Motherboard Version
45-47   3      Padding
```

## Parsing Logic

```python
def parse(data: bytearray) -> dict:
    # Data is already decrypted by coordinator
    parsed = {}

    parsed["running_state"] = data[3]
    parsed["error_code"] = data[4]
    parsed["running_step"] = data[5]
    parsed["altitude"] = (data[7] + 256 * data[6]) / 10
    parsed["running_mode"] = data[8]
    parsed["set_temp"] = max(8, min(36, data[9]))
    parsed["set_level"] = max(1, min(10, data[10]))

    parsed["supply_voltage"] = (256 * data[11] + data[12]) / 10
    parsed["case_temperature"] = signed_int16(256 * data[13] + data[14])
    parsed["cab_temperature"] = signed_int16(256 * data[32] + data[33]) / 10

    # Heater offset (signed)
    if len(data) > 34:
        raw = data[34]
        parsed["heater_offset"] = (raw - 256) if raw > 127 else raw

    # Backlight brightness
    if len(data) > 36:
        parsed["backlight"] = data[36]

    # CO sensor
    if len(data) > 39 and data[37] == 1:
        parsed["co_ppm"] = float((data[38] << 8) | data[39])

    # Part number (hex string)
    if len(data) > 43:
        part = data[40] | (data[41] << 8) | (data[42] << 16) | (data[43] << 24)
        if part != 0:
            parsed["part_number"] = format(part, 'x')

    # Motherboard version
    if len(data) > 44 and data[44] != 0:
        parsed["motherboard_version"] = data[44]

    return parsed
```

## Command Format

Commands are sent unencrypted (same 8-byte AA55 format):
```
AA 55 [passkey_hi] [passkey_lo] [cmd] [arg_lo] [arg_hi] [checksum]
```

## Detection

Detected when:
1. Header is AA55
2. Packet length is 48 bytes
3. Decryption produces valid data (running_state <= 1, error_code < 20)
