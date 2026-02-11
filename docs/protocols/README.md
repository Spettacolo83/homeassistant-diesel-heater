# Diesel Heater BLE Protocol Documentation

This directory contains detailed documentation for each BLE protocol variant supported by the Diesel Heater integration. These documents serve as a reference for protocol implementation and future maintenance.

## Supported Protocols

| Protocol | Mode | App | Description |
|----------|------|-----|-------------|
| [AA55](AA55.md) | 1 | AirHeaterBLE | Original Vevor unencrypted protocol |
| [AA55 Encrypted](AA55_ENCRYPTED.md) | 2 | AirHeaterBLE | XOR encrypted variant |
| [AA66](AA66.md) | 3 | AirHeaterBLE | BYD/Vevor 20-byte variant |
| [AA66 Encrypted](AA66_ENCRYPTED.md) | 4 | AirHeaterBLE | Encrypted, internal Fahrenheit |
| [ABBA](ABBA.md) | 5 | AirHeaterCC | HeaterCC protocol |
| [CBFF](CBFF.md) | 6 | Sunster | V2.1 with double XOR encryption |
| [Hcalory](HCALORY.md) | 7 | Hcalory | MVP1/MVP2 protocol |

## Protocol Detection

Protocol detection is performed in `coordinator.py` based on:
1. BLE service UUIDs
2. Notification data header bytes
3. Response packet length

### Service UUID Detection

| UUID | Protocol |
|------|----------|
| `0000FFE0-0000-1000-8000-00805F9B34FB` | AA55/AA66/ABBA/CBFF |
| `0000FFF0-0000-1000-8000-00805F9B34FB` | Hcalory MVP1 |
| `0000BD39-0000-1000-8000-00805F9B34FB` | Hcalory MVP2 |

### Header Detection

| Header | Protocol |
|--------|----------|
| `AA55` | AA55 (unencrypted, 18-20 bytes) |
| `AA55` (48 bytes) | AA55 Encrypted (needs XOR decryption) |
| `AA66` | AA66 (unencrypted, 20 bytes) |
| `AA66` (48 bytes) | AA66 Encrypted |
| `BAAB` | ABBA (HeaterCC) |
| `CBFF` | CBFF/Sunster |
| `AA77` | Sunster V2.1 ACK / locked state beacon |
| `FEAA` | Sunster V2.1 command header |
| `0002` | Hcalory MVP1/MVP2 |

## Command Format

All AA55-based protocols use an 8-byte command format:
```
Byte 0-1: Header (AA 55)
Byte 2:   Passkey high (passkey // 100)
Byte 3:   Passkey low (passkey % 100)
Byte 4:   Command code
Byte 5:   Argument low byte
Byte 6:   Argument high byte
Byte 7:   Checksum (sum of bytes 2-6 mod 256)
```

ABBA, CBFF, and Hcalory use their own command formats (see individual docs).

## Common Command Codes (AA55)

| Code | Command | Argument |
|------|---------|----------|
| 1 | Status request | 0 |
| 2 | Set mode | 1=level, 2=temp, 3=vent |
| 3 | Power on/off | 0=off, 1=on |
| 4 | Set temperature | 8-36 (Celsius) |
| 5 | Set gear level | 1-10 |
| 14 | Set altitude | meters |
| 15 | Set temp unit | 0=C, 1=F |
| 16 | Set tank volume | index |
| 17 | Set pump type | index |
| 19 | Set altitude unit | 0=m, 1=ft |
| 20 | Set backlight | 0-100 |
| 21 | Set language | index |

## Contributing

When adding a new protocol:
1. Create a new `.md` file in this directory
2. Document BLE UUIDs, packet structure, and parsing logic
3. Add the protocol to the table above
4. Implement `ProtocolXxx` class in `diesel_heater_ble/protocol.py`
5. Add tests in `tests/test_protocol_xxx.py`
6. Update coordinator for detection
