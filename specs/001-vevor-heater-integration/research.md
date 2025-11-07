# Research: Vevor Diesel Heater Integration

**Date**: 2025-10-29
**Feature**: Vevor Diesel Heater Integration
**Purpose**: Resolve technical unknowns before implementation

## 1. BLE Protocol Details

### Decision
Support all 4 Vevor protocol variants with automatic detection:
1. **AA55 (20 bytes, unencrypted)**: Header 0xAA55, error at byte 4
2. **AA66 (20 bytes, unencrypted)**: Header 0xAA66, error at byte 17
3. **AA55 Encrypted (48 bytes)**: XOR-encrypted with "password" key
4. **AA66 Encrypted (48 bytes)**: XOR-encrypted with "password" key

### Rationale
- Different heater models/firmware use different protocols
- Auto-detection via header bytes (0xAA55 vs 0xAA66) and packet length (20 vs 48 bytes)
- XOR encryption uses static key `[112, 97, 115, 115, 119, 111, 114, 100]` ("password")
- User should never need to configure protocol manually

### Alternatives Considered
- **Single protocol support**: Rejected - would limit compatibility
- **User-configured protocol**: Rejected - poor UX, users don't know their protocol
- **Protocol negotiation**: Not supported by heater firmware

### Implementation Notes
```python
# Protocol detection in coordinator.py _parse_response()
header = (data[0] << 8) | data[1]
if header == 0xAA55 and len(data) == 20:
    # Protocol 1: AA55 unencrypted
elif header == 0xAA66 and len(data) == 20:
    # Protocol 2: AA66 unencrypted
elif len(data) == 48:
    decrypted = _decrypt_data(data)
    header = (decrypted[0] << 8) | decrypted[1]
    if header == 0xAA55:
        # Protocol 3: AA55 encrypted
    elif header == 0xAA66:
        # Protocol 4: AA66 encrypted
```

---

## 2. Home Assistant Bluetooth APIs

### Decision
Use Home Assistant's native Bluetooth integration with `ActiveBluetoothDataUpdateCoordinator`:
- `bluetooth.async_ble_device_from_address()` for device lookup
- `establish_connection()` from bleak-retry-connector for reliable connections
- `BluetoothServiceInfoBleak` for discovery in config flow
- Native `bluetooth` platform dependency in manifest.json

### Rationale
- **ActiveBluetoothDataUpdateCoordinator**: Designed for BLE devices, handles connection lifecycle
- **Automatic discovery**: HA's bluetooth integration emits discovery events we can subscribe to
- **Proxy support**: HA routes BLE through proxies transparently, no special handling needed
- **Connection pooling**: HA manages connection slots across all integrations

### Alternatives Considered
- **Direct bleak usage**: Rejected - doesn't integrate with HA's bluetooth system, no proxy support
- **BluetoothDataUpdateCoordinator**: Rejected - deprecated, use Active variant
- **BLEDevice directly**: Rejected - requires manual connection management

### Implementation Notes
```python
# In __init__.py
ble_device = bluetooth.async_ble_device_from_address(
    hass, address.upper(), connectable=True
)
coordinator = VevorHeaterCoordinator(hass, ble_device)

# In coordinator.py
class VevorHeaterCoordinator(ActiveBluetoothDataUpdateCoordinator):
    def __init__(self, hass, ble_device):
        super().__init__(
            hass, _LOGGER,
            address=ble_device.address,
            mode=BluetoothScanningMode.ACTIVE,
            connectable=True,
            needs_poll_method=self._async_update,
            poll_interval=timedelta(seconds=30),
        )
```

---

## 3. Bleak Library Best Practices

### Decision
Use `bleak-retry-connector` with custom reconnection logic:
- `establish_connection()` for initial connection
- Exponential backoff: 5s → 10s → 20s → 40s for reconnection attempts
- `start_notify()` for receiving heater data updates
- Command timeout: 2 seconds maximum
- Connection timeout: 5 seconds maximum

### Rationale
- **bleak-retry-connector**: Built-in retry logic for flaky BLE connections
- **Exponential backoff**: Prevents hammering heater/proxy during temporary outages
- **Notifications**: Heater pushes status updates, more efficient than polling
- **Timeouts**: Prevent indefinite hangs if heater doesn't respond

### Alternatives Considered
- **Plain bleak**: Rejected - no retry logic, manual reconnection needed
- **Infinite retries**: Rejected - could spam logs and waste resources
- **Linear backoff**: Rejected - less efficient for transient issues

### Implementation Notes
```python
# In coordinator.py
async def _ensure_connected(self):
    if self._client and self._client.is_connected:
        return

    self._client = await establish_connection(
        BleakClient, self._ble_device, self._ble_device.address
    )

    await self._client.start_notify(NOTIFY_UUID, self._notification_callback)

# Reconnection handled by ActiveBluetoothDataUpdateCoordinator
# Exponential backoff in _async_update() error handling
```

---

## 4. ESPHome Bluetooth Proxy

### Decision
Integration works seamlessly through HA's Bluetooth integration - no special proxy handling needed.

### Key Facts
- **Connection slots**: ESP32 proxies typically support 3 simultaneous BLE connections
- **Transparent routing**: HA automatically routes BLE through available proxies
- **Range**: ~10 meters typical for ESP32 Bluetooth
- **Discovery**: Proxies forward BLE advertisements to HA

### Constraints
- Max 3 devices per proxy (connection slot limit)
- Proxy must be within BLE range of heater
- Proxy must be connected to HA and have `bluetooth_proxy` enabled in ESPHome config

### Implementation Notes
- No proxy-specific code needed in integration
- HA handles proxy selection, connection routing, failover
- Integration just uses standard `bluetooth.async_ble_device_from_address()`
- HA docs: https://www.home-assistant.io/integrations/bluetooth/

---

## 5. Testing Strategy

### Decision
Three-level testing approach:

#### Unit Tests (pytest)
- Protocol parsing for all 4 variants
- Encryption/decryption functions
- State management and validation
- Entity creation and attribute mapping

#### Integration Tests (pytest with mocks)
- BLE communication flow with mocked BleakClient
- Connection lifecycle (connect, disconnect, reconnect)
- Command sending and response handling
- Config flow (discovery and manual setup)

#### Manual Hardware Testing
- Real heater with ESP32 proxy
- All protocol variants (if available)
- Connection loss scenarios
- Multiple heaters
- Rapid command sequences

### Tools
- `pytest`: Test runner
- `pytest-homeassistant-custom-component`: HA-specific fixtures
- `pytest-asyncio`: Async test support
- `pytest-mock`: Mocking BLE devices

### Coverage Goals
- 90%+ code coverage for coordinator and config flow
- 100% coverage for protocol parsing functions
- All error paths tested

---

## Summary

**Technical Stack Confirmed**:
- Python 3.11+ with type hints
- Home Assistant 2024.1.0+
- bleak>=0.21.0, bleak-retry-connector>=3.4.0
- pytest with HA test helpers

**Key Architectural Decisions**:
1. ActiveBluetoothDataUpdateCoordinator for BLE lifecycle
2. Auto-detect protocol from response headers/length
3. XOR decryption for encrypted protocols
4. Exponential backoff reconnection
5. Works through ESPHome proxies transparently

**No Unresolved Questions** - Ready for Phase 1 (Design)
