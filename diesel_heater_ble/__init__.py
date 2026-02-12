"""diesel-heater-ble: Protocol library for BLE diesel heaters.

Supports Vevor, Hcalory, Sunster, and HeaterCC diesel heater protocols
over Bluetooth Low Energy (BLE). No dependency on Home Assistant.

Protocols supported:
  - AA55 (unencrypted, 18-20 bytes)
  - AA55 encrypted (48 bytes, XOR)
  - AA66 (unencrypted, 20 bytes, BYD variant)
  - AA66 encrypted (48 bytes, XOR)
  - ABBA/HeaterCC (21+ bytes, own command format)
  - CBFF/Sunster v2.1 (47 bytes, optional double-XOR encryption)
"""
from .protocol import (
    HeaterProtocol,
    ProtocolAA55,
    ProtocolAA55Encrypted,
    ProtocolAA66,
    ProtocolAA66Encrypted,
    ProtocolABBA,
    ProtocolCBFF,
    ProtocolHcalory,
    VevorCommandMixin,
    _decrypt_data,
    _encrypt_data,
    _u8_to_number,
    _unsign_to_sign,
)

__all__ = [
    "HeaterProtocol",
    "ProtocolAA55",
    "ProtocolAA55Encrypted",
    "ProtocolAA66",
    "ProtocolAA66Encrypted",
    "ProtocolABBA",
    "ProtocolCBFF",
    "ProtocolHcalory",
    "VevorCommandMixin",
    "_decrypt_data",
    "_encrypt_data",
    "_u8_to_number",
    "_unsign_to_sign",
]
