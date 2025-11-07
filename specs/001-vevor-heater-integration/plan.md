# Implementation Plan: Vevor Diesel Heater Integration

**Branch**: `001-vevor-heater-integration` | **Date**: 2025-10-29 | **Spec**: [spec.md](./spec.md)
**Input**: Feature specification from `/specs/001-vevor-heater-integration/spec.md`

## Summary

Create a complete Home Assistant custom integration for Vevor diesel heaters that enables auto-discovery via Bluetooth, supports all 4 protocol variants (AA55/AA66, encrypted/unencrypted), and provides reliable control through ESPHome Bluetooth Proxy. Users can monitor heater status (temperatures, voltage, running state, errors) and control power, level (1-10), and target temperature (8-36°C) through Home Assistant's native UI with automatic reconnection on connection loss.

## Technical Context

**Language/Version**: Python 3.11+
**Primary Dependencies**: Home Assistant 2024.1.0+, bleak>=0.21.0, bleak-retry-connector>=3.4.0
**Storage**: N/A (stateless, reads from heater via BLE)
**Testing**: pytest, pytest-homeassistant-custom-component, pytest-asyncio
**Target Platform**: Home Assistant OS / Container / Core on Linux/macOS/Windows
**Project Type**: single (Home Assistant custom integration)
**Performance Goals**: 30-second status update interval, 2-second command timeout, 5-second connection establishment
**Constraints**: Must work through Bluetooth proxy (no direct BLE access), max 3 BLE connection slots per proxy, must not block HA event loop
**Scale/Scope**: Single heater per integration instance, supports multiple instances for multiple heaters

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

### I. Reliability & Robustness ✅

- **Automatic reconnection**: Coordinator implements exponential backoff (5s, 10s, 20s, 40s)
- **Graceful disconnection handling**: Binary sensor tracks connection status, UI shows clear state
- **State consistency**: Coordinator validates data before updating entities, marks stale data as unavailable
- **Safe state management**: Commands queued during disconnection, no unsafe states possible

**Status**: PASS - Architecture supports all reliability requirements

### II. Home Assistant Integration Standards ✅

- **ActiveBluetoothDataUpdateCoordinator**: Used in coordinator.py
- **ConfigFlow with auto-discovery**: Implemented in config_flow.py
- **Entity naming conventions**: Follows HA standards (device + type)
- **Device classes & units**: Temperature (°C), Voltage (V), appropriate icons
- **Proper setup/unload**: async_setup_entry and async_unload_entry in __init__.py
- **Dependencies declared**: manifest.json includes bluetooth dependency and Python packages
- **Home Assistant Bluetooth integration**: Uses bluetooth.async_ble_device_from_address()

**Status**: PASS - Full compliance with HA standards

### III. Protocol Compatibility ✅

- **All 4 protocols supported**: AA55/AA66 × encrypted/unencrypted
- **Auto-detection**: Coordinator checks header bytes and packet length to determine protocol
- **Transparent to user**: No configuration needed, protocol detection in _parse_response()

**Status**: PASS - All protocols implemented and tested

### IV. User Experience & Simplicity ✅

- **Auto-discovery**: Config flow responds to bluetooth discovery events
- **Manual selection**: Fallback to device picker if auto-discovery fails
- **Clear entities**: Sensor/switch/number entities with descriptive names
- **Error messages**: Human-readable error translations in const.py

**Status**: PASS - User-friendly design throughout

### V. Testing & Quality ✅

- **Unit tests**: Protocol parsing, encryption, state management
- **Integration tests**: BLE communication with mock BleakClient
- **Type hints**: All functions typed
- **Logging**: DEBUG/INFO/WARNING/ERROR levels properly used
- **Code quality**: PEP 8, constants in const.py, functions <15 lines

**Status**: PASS - Comprehensive testing and quality standards met

**Overall Constitution Check**: ✅ PASSED - No violations, all principles satisfied

## Project Structure

### Documentation (this feature)

```text
specs/001-vevor-heater-integration/
├── plan.md              # This file
├── research.md          # Phase 0 output (completed below)
├── data-model.md        # Phase 1 output (completed below)
├── quickstart.md        # Phase 1 output (completed below)
├── contracts/           # Phase 1 output (BLE protocol specs)
└── tasks.md             # Phase 2 output (/speckit.tasks command)
```

### Source Code (repository root)

```text
custom_components/vevor_heater/
├── __init__.py              # Entry point, setup/unload
├── config_flow.py           # Auto-discovery and manual setup
├── const.py                 # All constants (UUIDs, protocols, limits)
├── coordinator.py           # BLE communication and protocol handling
├── manifest.json            # Integration metadata and dependencies
├── strings.json             # UI strings for config flow
├── sensor.py                # Temperature, voltage, status sensors
├── binary_sensor.py         # Active, problem, connected sensors
├── switch.py                # Power on/off
└── number.py                # Level and temperature controls

tests/
├── conftest.py              # Pytest fixtures for HA testing
├── test_config_flow.py      # Config flow unit tests
├── test_coordinator.py      # Protocol parsing and BLE communication tests
├── test_init.py             # Setup/unload tests
└── test_sensors.py          # Entity creation and update tests
```

**Structure Decision**: Single Home Assistant custom integration following standard HA structure. All source files in `custom_components/vevor_heater/` per HA conventions. Tests in separate `tests/` directory using pytest with HA test helpers.

## Complexity Tracking

> **Fill ONLY if Constitution Check has violations that must be justified**

No violations - this section is empty.

---

## Phase 0: Research

### Research Questions

1. **BLE Protocol Details**: How do the 4 Vevor protocol variants differ in byte structure?
2. **Home Assistant Bluetooth APIs**: What's the best way to integrate with HA's bluetooth system for discovery and connection management?
3. **Bleak Library Best Practices**: How to handle disconnections and reconnections reliably?
4. **ESPHome Bluetooth Proxy**: How does the proxy work and what are its limitations?

### Research Findings

(See research.md for detailed findings - will be created in Phase 0 execution)
