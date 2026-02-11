# CBFF Protocol (Sunster V2.1)

**Protocol Mode**: 6
**App**: Sunster
**Packet Length**: 47 bytes

## Overview

The CBFF protocol is used by Sunster TB10Pro WiFi and similar heaters. It supports optional double-XOR encryption and uses a completely different packet structure with extensive configuration options.

## V2.1 Encrypted Mode

Some Sunster heaters require V2.1 encrypted mode. This is detected when:
1. The heater sends `AA77` beacon (locked state)
2. Data requires decryption to parse correctly

When V2.1 mode is active:
- All outgoing commands must be encrypted with double-XOR
- A handshake may be required (CMD1=0x86) with PIN code

### V2.1 Handshake

```python
def build_handshake(passkey: int) -> bytearray:
    # PIN encoding: e.g., 1234 -> [34, 12]
    payload = bytes([passkey % 100, passkey // 100])
    packet = build_feaa(cmd_1=0x86, cmd_2=0x00, payload=payload)
    return encrypt_cbff(packet, device_sn)
```

### V2.1 Power Commands

```python
# Power ON: mode + param + time (0xFFFF = infinite)
payload = bytes([1, 5, 0xFF, 0xFF])  # Level mode, level 5
packet = build_feaa(cmd_1=0x81, cmd_2=0x01, payload=payload)

# Power OFF
packet = build_feaa(cmd_1=0x81, cmd_2=0x00)
```

## BLE Configuration

| Type | UUID |
|------|------|
| Service | `0000FFE0-0000-1000-8000-00805F9B34FB` |
| Write Char | `0000FFE1-0000-1000-8000-00805F9B34FB` |
| Notify Char | `0000FFE1-0000-1000-8000-00805F9B34FB` |

## Encryption (Optional)

Some CBFF heaters use double-XOR encryption:
```python
KEY1 = b"passwordA2409PW"  # 15 bytes, hardcoded
KEY2 = device_sn.upper()  # BLE MAC without colons, 12 chars

def decrypt(data: bytearray, device_sn: str) -> bytearray:
    key1 = bytearray(KEY1)
    key2 = bytearray(device_sn.upper().encode("ascii"))
    out = bytearray(data)

    # First XOR pass with key1
    for i in range(len(out)):
        out[i] ^= key1[i % len(key1)]

    # Second XOR pass with key2
    for i in range(len(out)):
        out[i] ^= key2[i % len(key2)]

    return out
```

## Response Packet Structure

```
Offset  Bytes  Field                Description
------  -----  -----                -----------
0-1     2      Header               CB FF
2       1      Protocol Version
3-9     7      Reserved
10      1      Run State            2/5/6=Off, else=On
11      1      Run Mode             1/3/4=Level, 2=Temp
12      1      Run Param            Temp or level value
13      1      Now Gear             Current gear (even in temp mode)
14      1      Run Step
15      1      Fault Display        Error code (lower 6 bits)
16      1      Reserved
17      1      Temp Unit            Lower nibble: 0=C, 1=F
18-19   2      Cab Temperature      Little-endian int16
20      1      Altitude Unit        Lower nibble: 0=m, 1=ft
21-22   2      Altitude             Little-endian uint16
23-24   2      Voltage              Little-endian uint16, /10
25-26   2      Case Temperature     Little-endian int16, /10
27-28   2      CO PPM               Little-endian uint16, /10
29      1      Power On/Off
30-31   2      Hardware Version     Little-endian uint16
32-33   2      Software Version     Little-endian uint16
34      1      Temp Compensation    Signed int8 (offset)
35      1      Language             255=not available
36      1      Tank Volume          255=not available
37      1      Pump Model/RF433     20=RF off, 21=RF on
38      1      Backlight            255=not available
39      1      Startup Temp Diff    255=not available
40      1      Shutdown Temp Diff   255=not available
41      1      WiFi Enabled         255=not available
42      1      Auto Start/Stop
43      1      Heater Mode
44-45   2      Remain Run Time      Little-endian, 65535=not available
46      1      Checksum/Padding
```

## Run State Values

| Value | State |
|-------|-------|
| 2, 5, 6 | Off / Standby |
| Other | Running / On |

## Run Mode Values

| Value | Mode |
|-------|------|
| 1, 3, 4 | Level mode |
| 2 | Temperature mode |
| Other | Manual mode |

## Command Format (FEAA)

CBFF uses FEAA-prefixed commands:
```
Byte 0-1: FE AA (header)
Byte 2:   Version (0=heater)
Byte 3:   Package number (0)
Byte 4-5: Total length (uint16 LE)
Byte 6:   cmd_1 (command code, +0x80 for request)
Byte 7:   cmd_2 (0=read, 1=response, 2=cmd no payload, 3=cmd with payload)
Byte 8+:  Payload
Last:     Checksum (sum & 0xFF)
```

## Command Mapping

| Command | FEAA Format | Description |
|---------|-------------|-------------|
| Status | `cmd_1=0x80, cmd_2=0x00` | Status request |
| Power | `cmd_1=0x81, cmd_2=0x03, payload=[arg]` | On(1)/Off(0) |
| Set Temp | `cmd_1=0x81, cmd_2=0x03, payload=[2, temp]` | Temperature mode |
| Set Level | `cmd_1=0x81, cmd_2=0x03, payload=[1, level]` | Level mode |
| Config | Fall back to AA55 | For commands 14-21 |

## Building FEAA Commands

```python
def build_feaa(cmd_1: int, cmd_2: int, payload: bytes = b"") -> bytearray:
    total_length = 8 + len(payload) + 1  # header + payload + checksum

    packet = bytearray([
        0xFE, 0xAA,              # Header
        0x00,                    # version_num
        0x00,                    # package_num
        total_length & 0xFF,     # length LSB
        (total_length >> 8),     # length MSB
        cmd_1,                   # command code
        cmd_2,                   # command type
    ])
    packet.extend(payload)

    checksum = sum(packet) & 0xFF
    packet.append(checksum)

    return packet
```

## Data Validation

CBFF data is validated before use:
```python
def is_data_suspect(parsed: dict) -> bool:
    voltage = parsed.get("supply_voltage", 0)
    cab_temp = parsed.get("cab_temperature", 0)
    # Suspect if voltage > 100V or < 0V, or temp > 500°C
    return voltage > 100 or voltage < 0 or abs(cab_temp) > 500
```

If raw data is suspect, decryption is attempted. If still suspect, sensor values are cleared.

## Detection

Detected when:
1. Header is CBFF
2. Packet length is approximately 47 bytes
