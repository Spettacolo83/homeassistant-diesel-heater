# Feature Specification: Vevor Diesel Heater Integration

**Feature Branch**: `001-vevor-heater-integration`
**Created**: 2025-10-29
**Status**: Draft
**Input**: Complete Vevor Diesel Heater Home Assistant Integration with Bluetooth Proxy support

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Auto-Discovery and Setup (Priority: P1)

A van owner with Home Assistant and an ESP32 Bluetooth Proxy wants to control their Vevor diesel heater without manual configuration. They turn on the heater and expect Home Assistant to automatically discover it and guide them through setup.

**Why this priority**: Core functionality that determines whether users can use the integration at all. Without discovery and setup, no other features are accessible.

**Independent Test**: Turn on the heater within Bluetooth range of the proxy. A notification should appear in Home Assistant offering to configure the device. Completing the setup flow should create all entities.

**Acceptance Scenarios**:

1. **Given** Home Assistant with Bluetooth integration and ESP32 proxy running, **When** Vevor heater is powered on within range, **Then** Home Assistant shows a discovery notification within 30 seconds
2. **Given** discovery notification appears, **When** user clicks "Configure", **Then** config flow presents the discovered heater with its MAC address
3. **Given** user completes config flow, **When** setup finishes, **Then** all sensor, switch, and control entities are created and available
4. **Given** heater uses any of the 4 protocol variants (AA55/AA66, encrypted/unencrypted), **When** integration connects, **Then** protocol is auto-detected and communication works correctly

---

### User Story 2 - Monitor Heater Status (Priority: P1)

A van owner wants to monitor their heater's current state including temperatures, battery voltage, running step, and any errors - all from their Home Assistant dashboard or mobile app.

**Why this priority**: Essential safety and awareness feature. Users need to know heater status, especially battery voltage to prevent drain and error codes for troubleshooting.

**Independent Test**: With heater connected, check that all sensor values update within 30 seconds and reflect actual heater state. Simulate an error condition (e.g., disconnect fuel) and verify error sensor shows correct fault.

**Acceptance Scenarios**:

1. **Given** heater is connected and running, **When** viewing entities in Home Assistant, **Then** interior temperature, case temperature, and supply voltage sensors show current values
2. **Given** heater changes state (e.g., from ignition to running), **When** 30 seconds elapse, **Then** running step sensor reflects the new state
3. **Given** heater encounters an error, **When** error occurs, **Then** error sensor displays error code with human-readable description
4. **Given** heater is running normally, **When** viewed in dashboard, **Then** "active" binary sensor shows ON and "problem" binary sensor shows OFF
5. **Given** Bluetooth connection is lost, **When** 60 seconds elapse, **Then** "connected" binary sensor shows OFF

---

### User Story 3 - Control Heater Power and Level (Priority: P1)

A user in their van wants to turn the heater on/off and adjust the power level (1-10) or target temperature (8-36°C) directly from Home Assistant without using the physical remote.

**Why this priority**: Primary control functionality. Users need basic on/off and level adjustment for daily use. This is the minimum viable control interface.

**Independent Test**: Use the power switch to turn heater on, verify it starts ignition sequence. Adjust level slider while running, verify heater responds. Turn off and verify cooldown sequence starts.

**Acceptance Scenarios**:

1. **Given** heater is off, **When** user toggles power switch ON in Home Assistant, **Then** heater starts ignition sequence and running step changes to "Ignition"
2. **Given** heater is running, **When** user adjusts level slider (1-10), **Then** heater changes output level within 5 seconds
3. **Given** heater is running in temperature mode, **When** user sets target temperature, **Then** heater adjusts automatically to maintain that temperature
4. **Given** heater is running, **When** user toggles power switch OFF, **Then** heater enters cooldown mode and shuts down safely
5. **Given** multiple commands sent rapidly (e.g., level changes), **When** commands are queued, **Then** all commands execute without conflicts or crashes

---

### User Story 4 - Reliable Connection Management (Priority: P2)

A user's Bluetooth proxy may restart, move out of range temporarily, or lose connection due to interference. The integration should automatically reconnect and maintain state consistency without user intervention.

**Why this priority**: Critical for usability in mobile/van environments where connections are unstable. Users should not need to manually reconnect or restart the integration.

**Independent Test**: While heater is connected, restart the ESP32 Bluetooth proxy. Integration should detect disconnection, attempt reconnection, and re-establish communication within 60 seconds without user action.

**Acceptance Scenarios**:

1. **Given** heater is connected, **When** Bluetooth proxy restarts, **Then** integration detects disconnection and attempts reconnection automatically
2. **Given** connection is lost, **When** reconnection attempts begin, **Then** integration uses exponential backoff (5s, 10s, 20s intervals)
3. **Given** heater moves out of range, **When** it returns to range, **Then** connection re-establishes automatically within 60 seconds
4. **Given** connection is lost, **When** user tries to send a command, **Then** user receives clear error message and command is queued for retry
5. **Given** connection drops during heater operation, **When** connection is restored, **Then** heater state is correctly synchronized without leaving heater in unsafe state

---

### User Story 5 - Create Automations (Priority: P3)

A user wants to create automations such as "start heater when temperature drops below 10°C" or "turn off heater when battery voltage is below 11.5V" using Home Assistant's automation engine.

**Why this priority**: Enhances user experience by enabling hands-free operation and safety protections. Not critical for basic operation but adds significant value.

**Independent Test**: Create automation: IF interior temperature < 10°C THEN turn on heater at level 5. Lower temperature sensor reading (via integration test) and verify automation triggers and heater starts.

**Acceptance Scenarios**:

1. **Given** automation configured for low temperature, **When** interior temperature drops below threshold, **Then** automation triggers and heater turns on
2. **Given** automation configured for low battery protection, **When** supply voltage drops below 11.5V, **Then** heater is turned off automatically
3. **Given** automation configured for scheduled heating, **When** time condition is met, **Then** heater starts at specified level
4. **Given** multiple automations active, **When** conditions overlap, **Then** most recent command takes priority without conflicts

---

### Edge Cases

- What happens when heater is manually controlled via physical remote while integration is connected?
- How does system handle rapid on/off commands (user accidentally double-tapping)?
- What happens if heater firmware is updated and protocol changes slightly?
- How does integration behave when ESP32 proxy reaches maximum connection slots (3 devices)?
- What happens if user has multiple Vevor heaters in range?
- How does system handle invalid sensor readings (e.g., temperature sensor disconnected)?

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: System MUST auto-discover Vevor heaters via Bluetooth when they are powered on and within range of configured Bluetooth proxy
- **FR-002**: System MUST support manual device selection from list of discovered Bluetooth devices if auto-discovery fails
- **FR-003**: System MUST automatically detect which of the 4 protocol variants (AA55/AA66, encrypted/unencrypted) the heater uses
- **FR-004**: System MUST read and update heater status every 30 seconds including: interior temperature, case temperature, supply voltage, running state, running step, running mode, set level, error code
- **FR-005**: System MUST provide power on/off control via Home Assistant switch entity
- **FR-006**: System MUST provide level control (1-10) via Home Assistant number entity
- **FR-007**: System MUST provide target temperature control (8-36°C) via Home Assistant number entity
- **FR-008**: System MUST automatically reconnect when Bluetooth connection is lost with exponential backoff (5s, 10s, 20s, 40s intervals)
- **FR-009**: System MUST queue commands when connection is unavailable and execute them when connection is restored
- **FR-010**: System MUST validate all user inputs before sending to heater (level 1-10, temperature 8-36°C)
- **FR-011**: System MUST provide clear binary sensor indicating connection status (connected/disconnected)
- **FR-012**: System MUST provide binary sensor indicating if heater is actively heating (on/off)
- **FR-013**: System MUST provide binary sensor indicating if heater has an error condition (problem/no problem)
- **FR-014**: System MUST translate error codes into human-readable descriptions (e.g., code 2 = "Lack of fuel")
- **FR-015**: System MUST work through Home Assistant's Bluetooth integration and ESPHome Bluetooth Proxy
- **FR-016**: System MUST log all BLE communication events at DEBUG level for troubleshooting
- **FR-017**: System MUST not send conflicting commands simultaneously (implement command queue if needed)
- **FR-018**: System MUST respect command response timeout of 2 seconds maximum
- **FR-019**: System MUST establish connection within 5 seconds maximum
- **FR-020**: System MUST maintain state consistency even during disconnections (not show stale data)

### Key Entities

- **Heater Device**: Represents the Vevor diesel heater with MAC address, model info, firmware version
  - Attributes: BLE address, connection status, protocol type (detected)
  - Relationships: Has multiple sensors, controls, and binary sensors

- **Temperature Sensors**: Interior temperature (cabin), Case temperature (heater housing)
  - Attributes: Current value in °C, timestamp of last update
  - Constraints: Must handle signed integers (can be negative in cold climates)

- **Voltage Sensor**: Battery supply voltage
  - Attributes: Current value in volts (V), timestamp
  - Constraints: Typical range 10V-15V for 12V systems

- **Status Sensors**: Running step (Standby/Self-test/Ignition/Running/Cooldown), Running mode (Manual/Level/Temperature), Set level (1-10)
  - Attributes: Current state, human-readable name
  - Relationships: Running step determines if heater is actively heating

- **Error Sensor**: Current error code and description
  - Attributes: Numeric code (0-10), human-readable message
  - Relationships: Triggers "problem" binary sensor when code != 0

- **Control Entities**: Power switch, Level number input, Target temperature number input
  - Attributes: Current value, min/max constraints
  - Relationships: Commands sent to heater device, validated before transmission

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: Users can complete heater setup from auto-discovery notification to fully functional entities in under 2 minutes
- **SC-002**: Heater status updates (temperature, voltage, state) are visible in Home Assistant within 30 seconds of change
- **SC-003**: Power on/off commands execute and heater responds within 5 seconds
- **SC-004**: Level and temperature adjustments are applied by heater within 5 seconds of user input
- **SC-005**: Integration automatically reconnects after connection loss within 60 seconds without user intervention
- **SC-006**: System handles 10 rapid sequential commands (level changes) without crashes, conflicts, or missed commands
- **SC-007**: All 4 protocol variants (AA55/AA66, encrypted/unencrypted) are correctly detected and work identically from user perspective
- **SC-008**: Error conditions (low fuel, overheat, sensor faults) are detected and displayed with correct descriptions within 30 seconds
- **SC-009**: Integration works reliably through ESP32 Bluetooth Proxy without requiring direct BLE access from Home Assistant server
- **SC-010**: 95% of users successfully set up and control their heater without needing to consult documentation or troubleshooting guides

### Assumptions

- User has Home Assistant 2024.1.0 or later installed and running
- User has configured at least one Bluetooth integration (ESPHome Bluetooth Proxy or built-in Bluetooth)
- ESP32 Bluetooth Proxy is within 10 meters of the Vevor heater
- Heater is one of the compatible Vevor models using standard BLE service UUID `0000fff0-0000-1000-8000-00805f9b34fb`
- User's van electrical system is 12V (standard for automotive applications)
- Heater firmware responds to standard Vevor protocol commands (may vary by model year, but base protocol is consistent)
- User has basic Home Assistant knowledge (can navigate UI, add integrations)
