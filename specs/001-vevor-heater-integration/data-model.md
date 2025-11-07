# Data Model: Vevor Diesel Heater Integration

**Date**: 2025-10-29
**Feature**: Vevor Diesel Heater Integration

## Overview

This integration models the Vevor diesel heater as a Home Assistant device with multiple entities representing sensors, controls, and status indicators. All data flows from the heater via BLE protocol responses - there is no persistent storage.

---

## Entities

### Device: Vevor Diesel Heater

**Represents**: The physical diesel heater hardware

**Identifiers**:
- MAC address (e.g., A4:C1:37:24:B8:64)
- Manufacturer: "Vevor"
- Model: "Diesel Heater" (detected from BLE advertisement if available)

**Device Info**:
```python
{
    "identifiers": {(DOMAIN, entry.data[CONF_ADDRESS])},
    "name": f"Vevor Heater {address[-5:].replace(':', '')}",
    "manufacturer": "Vevor",
    "model": "Diesel Heater",
    "sw_version": None,  # Not available from heater
}
```

**Relationships**:
- Has 8 sensors (temperature, voltage, status)
- Has 3 binary sensors (active, problem, connected)
- Has 1 switch (power)
- Has 2 number controls (level, target temperature)

---

## Sensors

### 1. Interior Temperature Sensor

**Entity ID**: `sensor.vevor_heater_XXXXX_interior_temperature`
**Device Class**: `temperature`
**Unit**: `°C`
**State Class**: `measurement`

**Data Source**: Parsed from BLE protocol response
- AA55: `bytes[15-16]` (signed 16-bit)
- AA66: `bytes[15-16]` (signed 16-bit)
- Encrypted: `bytes[32-33]/10` (signed 16-bit, decimal)

**Validation**: Range -40°C to 100°C (signed integer support for sub-zero temps)

---

### 2. Case Temperature Sensor

**Entity ID**: `sensor.vevor_heater_XXXXX_case_temperature`
**Device Class**: `temperature`
**Unit**: `°C`
**State Class**: `measurement`

**Data Source**: Parsed from BLE protocol response
- AA55: `bytes[13-14]` (signed 16-bit)
- AA66: `bytes[13-14]` (signed 16-bit)
- Encrypted: `bytes[13-14]` (signed 16-bit)

**Validation**: Range -40°C to 150°C (heater case can get hot)

---

### 3. Supply Voltage Sensor

**Entity ID**: `sensor.vevor_heater_XXXXX_supply_voltage`
**Device Class**: `voltage`
**Unit**: `V`
**State Class**: `measurement`

**Data Source**: Parsed from BLE protocol response
- AA55: `(bytes[12]*256 + bytes[11])/10`
- AA66: `(bytes[12]*256 + bytes[11])/10`
- Encrypted: `(bytes[11]*256 + bytes[12])/10`

**Validation**: Range 9V to 16V (typical 12V automotive range)

---

### 4. Running Step Sensor

**Entity ID**: `sensor.vevor_heater_XXXXX_running_step`
**Device Class**: `enum`
**Options**: ["Standby", "Self-test", "Ignition", "Running", "Cooldown"]

**Data Source**: Parsed from BLE protocol `bytes[5]`

**Value Mapping**:
```python
0: "Standby"
1: "Self-test"
2: "Ignition"
3: "Running"
4: "Cooldown"
```

---

### 5. Running Mode Sensor

**Entity ID**: `sensor.vevor_heater_XXXXX_running_mode`
**Device Class**: `enum`
**Options**: ["Manual", "Level Mode", "Temperature Mode"]

**Data Source**: Parsed from BLE protocol `bytes[8]`

**Value Mapping**:
```python
0: "Manual"
1: "Level Mode"
2: "Temperature Mode"
```

---

### 6. Set Level Sensor

**Entity ID**: `sensor.vevor_heater_XXXXX_set_level`
**Unit**: None (dimensionless 1-10)
**Icon**: `mdi:gauge`

**Data Source**: Parsed from BLE protocol based on running mode
- Level mode: `bytes[9]`
- Temperature mode: `bytes[10] + 1`
- Manual mode: `bytes[10] + 1`

**Validation**: Range 1-10

---

### 7. Altitude Sensor

**Entity ID**: `sensor.vevor_heater_XXXXX_altitude`
**Unit**: `m`
**State Class**: `measurement`
**Icon**: `mdi:altimeter`

**Data Source**: Parsed from BLE protocol
- AA55/AA66: `bytes[7]*256 + bytes[6]` (meters)
- Encrypted: `(bytes[7]*256 + bytes[6])/10` (meters)

**Purpose**: Altitude compensation for combustion efficiency

---

### 8. Error Sensor

**Entity ID**: `sensor.vevor_heater_XXXXX_error`
**Device Class**: None
**Icon**: `mdi:alert-circle`

**Data Source**: Parsed from BLE protocol
- AA55: `bytes[4]`
- AA66: `bytes[17]`
- Encrypted AA55: `bytes[4]`
- Encrypted AA66: `bytes[35]`

**Value Mapping**:
```python
0: "No fault"
1: "Startup failure"
2: "Lack of fuel"
3: "Supply voltage overrun"
4: "Outlet sensor fault"
5: "Inlet sensor fault"
6: "Pulse pump fault"
7: "Fan fault"
8: "Ignition unit fault"
9: "Overheating"
10: "Overheat sensor fault"
```

---

## Binary Sensors

### 1. Active Binary Sensor

**Entity ID**: `binary_sensor.vevor_heater_XXXXX_active`
**Device Class**: `running`

**State Logic**:
```python
ON: running_step in [1, 2, 3, 4]  # Self-test, Ignition, Running, Cooldown
OFF: running_step == 0  # Standby
```

**Purpose**: Indicates if heater is in any active operational state

---

### 2. Problem Binary Sensor

**Entity ID**: `binary_sensor.vevor_heater_XXXXX_problem`
**Device Class**: `problem`

**State Logic**:
```python
ON: error_code != 0
OFF: error_code == 0
```

**Purpose**: Quick problem indicator for automations

---

### 3. Connected Binary Sensor

**Entity ID**: `binary_sensor.vevor_heater_XXXXX_connected`
**Device Class**: `connectivity`
**Entity Category**: `diagnostic` (hidden by default)

**State Logic**:
```python
ON: coordinator.last_update_success and (now - coordinator.last_update_time) < 90s
OFF: not coordinator.last_update_success or stale data
```

**Purpose**: BLE connection status monitoring

---

## Controls

### 1. Power Switch

**Entity ID**: `switch.vevor_heater_XXXXX_power`
**Device Class**: `switch`
**Icon**: `mdi:power`

**Commands**:
- Turn ON: `_send_command(6, 0, 85)` → Heater starts ignition sequence
- Turn OFF: `_send_command(2, 0, 85)` → Heater enters cooldown then stops

**State Sync**: Reads `running_state` from BLE protocol `bytes[3]`

---

### 2. Level Number Control

**Entity ID**: `number.vevor_heater_XXXXX_level`
**Min**: 1
**Max**: 10
**Step**: 1
**Mode**: `slider`
**Icon**: `mdi:gauge`

**Command**: `_send_command(3, level, 85)` where `level` is 1-10

**Purpose**: Set heater power output level (1=minimum, 10=maximum)

---

### 3. Target Temperature Number Control

**Entity ID**: `number.vevor_heater_XXXXX_target_temperature`
**Device Class**: `temperature`
**Min**: 8
**Max**: 36
**Step**: 1
**Unit**: `°C`

**Command**: `_send_command(4, temperature, 85)` where `temperature` is 8-36°C

**Purpose**: Set target temperature for automatic control mode

---

## State Transitions

### Power On Sequence
```
Standby (0) → Self-test (1) → Ignition (2) → Running (3)
```

**Timing**: ~2-5 minutes from power on to running (depends on ambient temp)

---

### Power Off Sequence
```
Running (3) → Cooldown (4) → Standby (0)
```

**Timing**: ~3-5 minutes cooldown (heater continues running fan to cool combustion chamber)

---

### Error Handling
```
Any state → Error detected → Standby (0) + error_code != 0
```

**Recovery**: User must clear error condition then restart heater

---

## Data Flow

```
Heater → BLE Notify → Coordinator._notification_callback()
    → _parse_response() → Detect protocol
    → _parse_protocol_XX() → Update coordinator.data{}
    → Coordinator triggers entity updates
    → Entities read from coordinator.data{}
    → UI updates

User → UI action → Entity command
    → Coordinator.async_turn_on/off/set_level/set_temperature()
    → _send_command() → BLE Write
    → Heater executes command
    → Status update via notify (above flow)
```

---

## Validation Rules

### Input Validation (before sending to heater)
- **Level**: Must be integer 1-10
- **Temperature**: Must be integer 8-36°C
- **Commands**: Max 1 command in flight at a time (prevent conflicts)

### Output Validation (after parsing from heater)
- **Temperatures**: Reject values outside -40 to 150°C (likely corrupt data)
- **Voltage**: Reject values outside 9-16V (likely corrupt data)
- **Error codes**: Map unknown codes to 0 ("No fault")
- **Running step**: Map unknown values to 0 ("Standby")

---

## Error Handling

### Connection Loss
- All entities become `unavailable`
- Binary sensor "connected" shows OFF
- Coordinator attempts reconnection (exponential backoff)
- When reconnected, request fresh status update

### Corrupt Data
- Log warning with raw bytes (DEBUG level)
- Don't update entity states (keep previous valid state)
- Mark entity as `unavailable` if no valid data for 90 seconds

### Command Timeout
- If heater doesn't respond within 2 seconds, retry once
- If still no response, return error to user
- Don't mark entity unavailable (might be temporary)

---

## Summary

**Total Entities**: 14
- 8 sensors (temperatures, voltage, status, error)
- 3 binary sensors (active, problem, connected)
- 1 switch (power)
- 2 number controls (level, temperature)

**Data Storage**: None (stateless, real-time from heater)
**Update Frequency**: 30 seconds (configurable)
**Protocol Support**: All 4 variants auto-detected
