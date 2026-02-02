# diesel-heater-ble

Pure Python library for parsing and controlling BLE diesel heaters.

Supports Vevor, Hcalory, Sunster, and HeaterCC diesel heater protocols
over Bluetooth Low Energy (BLE). No dependency on Home Assistant.

## Supported Protocols

| Protocol | Mode | Description |
|----------|------|-------------|
| AA55 | 1 | Unencrypted, 18-20 bytes (Vevor/Hcalory) |
| AA55enc | 2 | Encrypted, 48 bytes XOR (Vevor/Hcalory) |
| AA66 | 3 | Unencrypted, 20 bytes (BYD variant) |
| AA66enc | 4 | Encrypted, 48 bytes XOR (Vevor/Hcalory) |
| ABBA | 5 | HeaterCC protocol, 21+ bytes, own command format |
| CBFF | 6 | Sunster v2.1, 47 bytes, optional double-XOR encryption |

## Installation

```bash
pip install diesel-heater-ble
```

## Usage

```python
from diesel_heater_ble import ProtocolAA55, ProtocolCBFF

# Parse a BLE notification
protocol = ProtocolAA55()
data = bytearray(...)  # raw BLE notification bytes
result = protocol.parse(data)

print(result["running_state"])   # 0=off, 1=on
print(result["cab_temperature"]) # interior temperature
print(result["supply_voltage"])  # battery voltage

# Build a command
cmd = protocol.build_command(command=3, argument=0, passkey=1234)
# Send cmd to BLE characteristic...
```

## API

### Protocol Classes

All protocol classes implement the `HeaterProtocol` interface:

- `HeaterProtocol` - Abstract base class
- `ProtocolAA55` - AA55 unencrypted
- `ProtocolAA55Encrypted` - AA55 with XOR encryption
- `ProtocolAA66` - AA66 unencrypted (BYD variant)
- `ProtocolAA66Encrypted` - AA66 with XOR encryption
- `ProtocolABBA` - ABBA/HeaterCC protocol
- `ProtocolCBFF` - CBFF/Sunster v2.1 protocol

### Methods

- `parse(data: bytearray) -> dict | None` - Parse BLE notification data
- `build_command(command: int, argument: int, passkey: int) -> bytearray` - Build command packet

### Helper Functions

- `_decrypt_data(data)` / `_encrypt_data(data)` - XOR encryption/decryption
- `_u8_to_number(value)` - Convert unsigned 8-bit value
- `_unsign_to_sign(value)` - Convert unsigned to signed value

## License

MIT
