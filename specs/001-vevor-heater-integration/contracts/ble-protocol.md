# BLE Protocol Contract: Vevor Diesel Heater

**Version**: 1.0
**Date**: 2025-10-29

## Overview

This document defines the Bluetooth Low Energy (BLE) communication protocol for Vevor diesel heaters. The heater supports 4 protocol variants that must be auto-detected based on response characteristics.

---

## BLE Service & Characteristics

### Service UUID
```
0000fff0-0000-1000-8000-00805f9b34fb
```

### Write Characteristic UUID
```
0000fff1-0000-1000-8000-00805f9b34fb
```
**Purpose**: Send commands to heater

### Notify Characteristic UUID
```
0000fff2-0000-1000-8000-00805f9b34fb
```
**Purpose**: Receive status updates from heater

---

## Protocol Variants

### Protocol 1: AA55 Unencrypted (20 bytes)

**Characteristics**:
- Header: `0xAA 0x55`
- Length: 20 bytes
- Encryption: None

**Response Structure**:
```
Byte  0-1:  Header (0xAA55)
Byte  2:    Passkey high byte
Byte  3:    Running state (0=off, 1=on)
Byte  4:    Error code (0-10)
Byte  5:    Running step (0-4)
Byte  6-7:  Altitude (unsigned 16-bit, little-endian)
Byte  8:    Running mode (0=manual, 1=level, 2=temperature)
Byte  9:    Set level (mode 1) or set temperature (mode 2)
Byte  10:   Level index (mode 0/2)
Byte  11-12: Supply voltage × 10 (unsigned 16-bit, little-endian)
Byte  13-14: Case temperature (signed 16-bit, big-endian)
Byte  15-16: Interior temperature (signed 16-bit, big-endian)
Byte  17:   Unknown
Byte  18:   Unknown
Byte  19:   Checksum
```

---

### Protocol 2: AA66 Unencrypted (20 bytes)

**Characteristics**:
- Header: `0xAA 0x66`
- Length: 20 bytes
- Encryption: None

**Response Structure**:
```
Byte  0-1:  Header (0xAA66)
Byte  2:    Passkey high byte
Byte  3:    Running state (0=off, 1=on)
Byte  4:    Unknown
Byte  5:    Running step (0-4)
Byte  6-7:  Altitude (unsigned 16-bit, little-endian)
Byte  8:    Running mode (0=manual, 1=level, 2=temperature)
Byte  9:    Set level (mode 1) or set temperature (mode 2)
Byte  10:   Level index (mode 0/2)
Byte  11-12: Supply voltage × 10 (unsigned 16-bit, little-endian)
Byte  13-14: Case temperature (signed 16-bit, big-endian)
Byte  15-16: Interior temperature (signed 16-bit, big-endian)
Byte  17:   Error code (0-10) ← Different position!
Byte  18:   Unknown
Byte  19:   Checksum
```

---

### Protocol 3: AA55 Encrypted (48 bytes)

**Characteristics**:
- Header: `0xAA 0x55` (after decryption)
- Length: 48 bytes
- Encryption: XOR with key "password" = `[112, 97, 115, 115, 119, 111, 114, 100]`

**Decryption Algorithm**:
```python
def decrypt(data: bytearray) -> bytearray:
    key = [112, 97, 115, 115, 119, 111, 114, 100]  # "password"
    decrypted = bytearray(data)
    for block in range(6):  # 6 blocks of 8 bytes
        for i in range(8):
            index = block * 8 + i
            if index < len(decrypted):
                decrypted[index] = key[i] ^ decrypted[index]
    return decrypted
```

**Response Structure** (after decryption):
```
Byte  0-1:  Header (0xAA55)
Byte  2:    Passkey high byte
Byte  3:    Running state (0=off, 1=on)
Byte  4:    Error code (0-10)
Byte  5:    Running step (0-4)
Byte  6-7:  Altitude × 10 (unsigned 16-bit, big-endian)
Byte  8:    Running mode (0=manual, 1=level, 2=temperature)
Byte  9:    Set temperature (8-36)
Byte  10:   Set level (1-10)
Byte  11-12: Supply voltage × 10 (unsigned 16-bit, big-endian)
Byte  13-14: Case temperature (signed 16-bit, big-endian)
Byte  15-47: Extended data (not fully documented)
Byte  32-33: Interior temperature × 10 (signed 16-bit, big-endian)
```

---

### Protocol 4: AA66 Encrypted (48 bytes)

**Characteristics**:
- Header: `0xAA 0x66` (after decryption)
- Length: 48 bytes
- Encryption: XOR with key "password"

**Response Structure** (after decryption):
```
Byte  0-1:  Header (0xAA66)
Byte  2:    Passkey high byte
Byte  3:    Running state (0=off, 1=on)
Byte  4:    Unknown
Byte  5:    Running step (0-4)
Byte  6-7:  Altitude × 10 (unsigned 16-bit, big-endian)
Byte  8:    Running mode (0=manual, 1=level, 2=temperature)
Byte  9:    Set temperature (8-36)
Byte  10:   Set level (1-10)
Byte  11-12: Supply voltage × 10 (unsigned 16-bit, big-endian)
Byte  13-14: Case temperature (signed 16-bit, big-endian)
Byte  15-34: Extended data
Byte  32-33: Interior temperature × 10 (signed 16-bit, big-endian)
Byte  35:   Error code (0-10) ← Different position!
Byte  36-47: Extended data
```

---

## Command Structure

All commands follow this 8-byte format:

```
Byte  0:    Header (0xAA)
Byte  1:    Command type (85 or 136)
Byte  2:    Passkey high byte or random
Byte  3:    Passkey low byte or random
Byte  4:    Command ID
Byte  5:    Argument low byte
Byte  6:    Argument high byte
Byte  7:    Checksum = (byte2 + byte3 + byte4 + byte5 + byte6) % 256
```

### Command Types

#### Type 85 (0x55) - Normal Commands
```python
packet[2] = passkey // 100
packet[3] = passkey % 100
```

#### Type 136 (0x88) - Pairing Commands
```python
packet[2] = random.randint(0, 255)
packet[3] = random.randint(0, 255)
```

---

## Available Commands

### 1. Request Status
**Command ID**: 1
**Argument**: 0
**Type**: 85

**Purpose**: Request current heater status
**Response**: Status packet (20 or 48 bytes depending on protocol)

**Example**:
```python
send_command(1, 0, 85)
→ [0xAA, 0x55, 0x00, 0x00, 0x01, 0x00, 0x00, 0x01]
```

---

### 2. Turn Off
**Command ID**: 2
**Argument**: 0
**Type**: 85

**Purpose**: Turn heater off (enters cooldown sequence)

**Example**:
```python
send_command(2, 0, 85)
→ [0xAA, 0x55, 0x00, 0x00, 0x02, 0x00, 0x00, 0x02]
```

---

### 3. Set Level
**Command ID**: 3
**Argument**: 1-10 (level)
**Type**: 85

**Purpose**: Set heater output level (1=min, 10=max)
**Validation**: Argument must be 1-10

**Example** (set level 5):
```python
send_command(3, 5, 85)
→ [0xAA, 0x55, 0x00, 0x00, 0x03, 0x05, 0x00, 0x08]
```

---

### 4. Set Temperature
**Command ID**: 4
**Argument**: 8-36 (°C)
**Type**: 85

**Purpose**: Set target temperature for automatic control
**Validation**: Argument must be 8-36

**Example** (set 20°C):
```python
send_command(4, 20, 85)
→ [0xAA, 0x55, 0x00, 0x00, 0x04, 0x14, 0x00, 0x18]
```

---

### 5. Start/Turn On
**Command ID**: 6
**Argument**: 0
**Type**: 85

**Purpose**: Start heater (begins ignition sequence)

**Example**:
```python
send_command(6, 0, 85)
→ [0xAA, 0x55, 0x00, 0x00, 0x06, 0x00, 0x00, 0x06]
```

---

## Data Types

### Running State
```
0: OFF
1: ON
```

### Running Step
```
0: Standby
1: Self-test
2: Ignition
3: Running
4: Cooldown
```

### Running Mode
```
0: Manual (direct level control)
1: Level Mode (set level, heater maintains)
2: Temperature Mode (automatic, heater adjusts level)
```

### Error Codes
```
0:  No fault
1:  Startup failure
2:  Lack of fuel
3:  Supply voltage overrun
4:  Outlet sensor fault
5:  Inlet sensor fault
6:  Pulse pump fault
7:  Fan fault
8:  Ignition unit fault
9:  Overheating
10: Overheat sensor fault
```

---

## Protocol Detection Algorithm

```python
def detect_protocol(data: bytearray) -> int:
    """
    Returns protocol number (1-4)
    """
    if len(data) == 20:
        header = (data[0] << 8) | data[1]
        if header == 0xAA55:
            return 1  # AA55 unencrypted
        elif header == 0xAA66:
            return 2  # AA66 unencrypted

    elif len(data) == 48:
        decrypted = decrypt(data)
        header = (decrypted[0] << 8) | decrypted[1]
        if header == 0xAA55:
            return 3  # AA55 encrypted
        elif header == 0xAA66:
            return 4  # AA66 encrypted

    raise ValueError(f"Unknown protocol: length={len(data)}, header={data[0]:02X}{data[1]:02X}")
```

---

## Timing Requirements

| Operation | Timeout | Notes |
|-----------|---------|-------|
| Command response | 2 seconds | Max wait for heater to respond |
| Connection establishment | 5 seconds | Initial BLE connection |
| Status update interval | 30 seconds | How often to request status |
| Reconnection backoff | 5s, 10s, 20s, 40s | Exponential backoff on connection loss |

---

## Error Handling

### Invalid Response Length
- If `len(data) != 20 and len(data) != 48`: Log error, discard packet

### Invalid Header
- If header not in `[0xAA55, 0xAA66]` (after decryption if needed): Log error, discard packet

### Checksum Validation
- Last byte should equal `(sum of bytes 2-6) % 256`
- If mismatch: Log warning, still parse (some heaters have buggy checksums)

### Timeout Handling
- If no response within 2 seconds: Retry command once
- If still no response: Return error to user, don't mark device unavailable

---

## Testing Contracts

### Unit Test Requirements

1. **Parse all 4 protocols correctly** with known test vectors
2. **Encrypt/decrypt correctly** with "password" key
3. **Handle corrupt data** gracefully (log, don't crash)
4. **Validate temperature ranges** (signed integers, -40 to 150°C)
5. **Validate voltage ranges** (9-16V)
6. **Command construction** with correct checksums
7. **Protocol auto-detection** from response characteristics

### Test Vectors

#### Protocol 1 (AA55 Unencrypted)
```python
# Heater running at level 5, 22°C interior, 65°C case, 12.8V
data = bytes([
    0xAA, 0x55, 0x00, 0x01, 0x00, 0x03, 0x00, 0x00,
    0x01, 0x05, 0x04, 0x80, 0x00, 0x00, 0x41, 0x00,
    0x16, 0x00, 0x00, 0xAB
])
# Expected: interior_temp=22, case_temp=65, voltage=12.8, level=5, running_step=3, error=0
```

---

## Implementation Checklist

- [ ] BLE service/characteristic UUIDs configured
- [ ] All 4 protocol parsers implemented
- [ ] XOR decryption function correct
- [ ] Protocol auto-detection working
- [ ] All 5 commands implemented (status, on, off, set level, set temp)
- [ ] Checksum calculation correct
- [ ] Timeout handling (2s command, 5s connection)
- [ ] Signed integer support for temperatures
- [ ] Error code mapping (0-10)
- [ ] Running step/mode mapping
- [ ] Unit tests for all protocols with test vectors
