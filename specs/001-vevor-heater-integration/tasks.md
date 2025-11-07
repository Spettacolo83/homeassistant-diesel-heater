# Tasks: Vevor Diesel Heater Integration

**Input**: Design documents from `/specs/001-vevor-heater-integration/`
**Prerequisites**: plan.md ✅, spec.md ✅, research.md ✅, data-model.md ✅, contracts/ ✅

**Tests**: Tests are OPTIONAL and not explicitly requested in the specification. They are included here for completeness but can be skipped if not needed.

**Organization**: Tasks are grouped by user story to enable independent implementation and testing of each story.

**Current Status**: Most implementation is complete. Primary missing component is `config_flow.py` for auto-discovery and manual setup.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependencies)
- **[Story]**: Which user story this task belongs to (e.g., US1, US2, US3)
- Include exact file paths in descriptions

## Path Conventions

Home Assistant custom integration structure:
- Integration code: `custom_components/vevor_heater/` (currently at repository root)
- Tests: `tests/` (to be created)
- Documentation: `specs/001-vevor-heater-integration/`

---

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: Project initialization and verification

**Status**: ✅ COMPLETE - All infrastructure files exist

- [x] T001 Create project structure per implementation plan
- [x] T002 Initialize Home Assistant integration with manifest.json and dependencies
- [x] T003 [P] Define constants in const.py (UUIDs, protocols, limits, error codes)

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: Core infrastructure that MUST be complete before ANY user story can be implemented

**⚠️ CRITICAL**: No user story work can begin until this phase is complete

**Status**: ✅ MOSTLY COMPLETE - Only config_flow.py missing

- [x] T004 Implement BLE protocol parsing in coordinator.py with all 4 protocol variants
- [x] T005 [P] Implement XOR decryption function for encrypted protocols in coordinator.py
- [x] T006 [P] Setup ActiveBluetoothDataUpdateCoordinator with connection management in coordinator.py
- [x] T007 Implement command sending infrastructure (_send_command) with timeout handling in coordinator.py
- [x] T008 [P] Create entity base classes and device info structure
- [x] T009 Implement entry point in __init__.py with async_setup_entry and async_unload_entry
- [x] T010 **Implement config_flow.py with Bluetooth discovery and manual setup** (REQUIRED)

**Checkpoint**: Foundation ready once T010 complete - all user stories are then functional

---

## Phase 3: User Story 1 - Auto-Discovery and Setup (Priority: P1) 🎯 MVP

**Goal**: Enable users to automatically discover their Vevor heater via Bluetooth and complete setup within 2 minutes

**Independent Test**: Turn on heater within Bluetooth range. A discovery notification should appear in Home Assistant within 30 seconds. Complete setup flow and verify all entities are created.

**Status**: ⚠️ BLOCKED BY T010 - config_flow.py missing

**Dependencies**: Requires Phase 2 complete (especially T010)

### Implementation for User Story 1

- [x] T011 [US1] Implement ConfigFlow class in config_flow.py inheriting from ConfigFlow
- [x] T012 [US1] Add discovery filter for service UUID 0000fff0-0000-1000-8000-00805f9b34fb in config_flow.py
- [x] T013 [US1] Implement async_step_bluetooth() for auto-discovery handling in config_flow.py
- [x] T014 [US1] Implement async_step_user() for manual device selection in config_flow.py
- [x] T015 [US1] Add async_step_confirm() for user confirmation dialog in config_flow.py
- [x] T016 [US1] Implement device validation to check if already configured in config_flow.py
- [x] T017 [US1] Add error handling for "no devices found" and "already configured" in config_flow.py
- [x] T018 [US1] Verify strings.json has all config flow UI text (already exists, verify completeness)

**Checkpoint**: User can discover and set up heater. All 14 entities should be visible and updating.

---

## Phase 4: User Story 2 - Monitor Heater Status (Priority: P1)

**Goal**: Users can monitor heater status (temperatures, voltage, running state, errors) with 30-second update frequency

**Independent Test**: With heater connected and running, verify all sensor values update within 30 seconds. Simulate error condition and verify error sensor shows correct fault.

**Status**: ✅ COMPLETE - All sensors implemented

**Dependencies**: Requires US1 complete (config flow to connect device)

### Implementation for User Story 2

- [x] T019 [P] [US2] Implement interior temperature sensor in sensor.py
- [x] T020 [P] [US2] Implement case temperature sensor in sensor.py
- [x] T021 [P] [US2] Implement supply voltage sensor in sensor.py
- [x] T022 [P] [US2] Implement running step sensor in sensor.py
- [x] T023 [P] [US2] Implement running mode sensor in sensor.py
- [x] T024 [P] [US2] Implement set level sensor in sensor.py
- [x] T025 [P] [US2] Implement altitude sensor in sensor.py
- [x] T026 [P] [US2] Implement error sensor with human-readable error code mapping in sensor.py
- [x] T027 [P] [US2] Implement "active" binary sensor in binary_sensor.py
- [x] T028 [P] [US2] Implement "problem" binary sensor in binary_sensor.py
- [x] T029 [P] [US2] Implement "connected" binary sensor in binary_sensor.py
- [x] T030 [US2] Verify coordinator updates every 30 seconds (UPDATE_INTERVAL in const.py)

**Checkpoint**: All monitoring entities functional. Status updates visible in HA UI within 30 seconds.

---

## Phase 5: User Story 3 - Control Heater Power and Level (Priority: P1)

**Goal**: Users can control heater on/off, level (1-10), and target temperature (8-36°C) from Home Assistant

**Independent Test**: Turn heater on via switch, verify ignition starts. Adjust level slider, verify heater responds. Turn off and verify cooldown sequence.

**Status**: ✅ COMPLETE - All controls implemented

**Dependencies**: Requires US1 complete (config flow) and US2 complete (status monitoring to verify commands)

### Implementation for User Story 3

- [x] T031 [US3] Implement power switch in switch.py with turn_on and turn_off
- [x] T032 [US3] Map switch commands to coordinator.async_turn_on() and async_turn_off() in switch.py
- [x] T033 [P] [US3] Implement level number control in number.py (1-10 range)
- [x] T034 [P] [US3] Implement target temperature number control in number.py (8-36°C range)
- [x] T035 [US3] Add input validation for level and temperature before sending commands in coordinator.py
- [x] T036 [US3] Implement async_set_level() in coordinator.py
- [x] T037 [US3] Implement async_set_temperature() in coordinator.py
- [x] T038 [US3] Verify command timeout handling (2 seconds max in _send_command) in coordinator.py

**Checkpoint**: All control entities functional. Commands execute within 5 seconds and heater responds.

---

## Phase 6: User Story 4 - Reliable Connection Management (Priority: P2)

**Goal**: Integration automatically reconnects on connection loss with exponential backoff, no user intervention required

**Independent Test**: Restart ESP32 Bluetooth proxy while heater connected. Integration should detect disconnection and reconnect within 60 seconds automatically.

**Status**: ✅ MOSTLY COMPLETE - Core logic exists, may need reconnection strategy refinement

**Dependencies**: Requires US1 complete (config flow) and US2 complete (connection monitoring)

### Implementation for User Story 4

- [x] T039 [US4] Implement connection detection in _ensure_connected() in coordinator.py
- [x] T040 [US4] Use bleak-retry-connector establish_connection() for automatic retries in coordinator.py
- [x] T041 [US4] Implement connection status tracking in coordinator.data["connected"] in coordinator.py
- [x] T042 [US4] Add exponential backoff logic for reconnection attempts (5s, 10s, 20s, 40s) in coordinator.py
- [ ] T043 [US4] Implement command queuing for commands sent during disconnection (optional enhancement) in coordinator.py
- [x] T044 [US4] Add clear error messages when commands fail due to disconnection in coordinator.py
- [x] T045 [US4] Implement async_shutdown() to gracefully stop notifications and disconnect in coordinator.py

**Checkpoint**: Connection loss and recovery working automatically. No user intervention needed.

---

## Phase 7: User Story 5 - Create Automations (Priority: P3)

**Goal**: Users can create Home Assistant automations using heater entities (temperature triggers, voltage protection, scheduled heating)

**Independent Test**: Create automation: "IF interior temperature < 10°C THEN turn on heater at level 5". Lower temperature and verify automation triggers.

**Status**: ✅ COMPLETE - All entities support automations via HA standard entity APIs

**Dependencies**: Requires US2 complete (sensors for triggers) and US3 complete (controls for actions)

### Implementation for User Story 5

- [x] T046 [US5] Verify all sensors are properly registered and available for automation triggers
- [x] T047 [US5] Verify all controls (switch, numbers) are available for automation actions
- [x] T048 [US5] Confirm entity states update correctly to trigger automations
- [x] T049 [US5] Test example automation from spec (low temperature trigger)

**Checkpoint**: Users can create automations using any heater entity without issues.

---

## Phase 8: Polish & Cross-Cutting Concerns

**Purpose**: Testing, documentation, and final validation

- [ ] T050 [P] Create pytest configuration in tests/conftest.py with Home Assistant fixtures
- [ ] T051 [P] Write unit tests for protocol parsing in tests/test_coordinator.py
- [ ] T052 [P] Write unit tests for encryption/decryption in tests/test_coordinator.py
- [ ] T053 [P] Write config flow tests in tests/test_config_flow.py
- [ ] T054 [P] Write integration tests for BLE communication with mocks in tests/test_init.py
- [ ] T055 [P] Write entity creation tests in tests/test_sensors.py
- [ ] T056 Validate all 4 protocol variants parse correctly with test vectors from contracts/ble-protocol.md
- [ ] T057 Test connection loss and reconnection scenarios manually
- [ ] T058 Test rapid command sequences (10+ level changes) without crashes
- [ ] T059 Validate all edge cases from spec.md (manual remote control, multiple heaters, etc.)
- [ ] T060 Run quickstart.md validation checklist
- [x] T061 Update README.md with installation and usage instructions
- [ ] T062 [P] Add inline code documentation (docstrings) for public methods
- [ ] T063 Verify all entity names match strings.json translations
- [ ] T064 Test with real hardware (ESP32 proxy + actual heater)
- [ ] T065 Performance check: Ensure no blocking operations in async functions
- [ ] T066 Security review: Verify no sensitive data logged at INFO level
- [x] T067 Verify manifest.json has correct version and requirements
- [ ] T068 Final constitution check: Code quality, PEP 8, type hints, error handling

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: ✅ COMPLETE
- **Foundational (Phase 2)**: ⚠️ 90% complete - T010 (config_flow.py) BLOCKS all user stories
- **User Stories (Phase 3-7)**:
  - **US1 (Phase 3)**: ⚠️ BLOCKED by T010 - config flow required for discovery/setup
  - **US2 (Phase 4)**: ✅ COMPLETE - sensors functional, needs US1 for end-to-end test
  - **US3 (Phase 5)**: ✅ COMPLETE - controls functional, needs US1 for end-to-end test
  - **US4 (Phase 6)**: ⚠️ 80% complete - connection management exists, may need reconnection refinement
  - **US5 (Phase 7)**: ✅ COMPLETE - automations work through standard HA APIs
- **Polish (Phase 8)**: Depends on all user stories complete

### User Story Dependencies

- **User Story 1 (P1)**: ⚠️ BLOCKED by T010 (config_flow.py) - HIGH PRIORITY
- **User Story 2 (P1)**: ✅ Code complete, needs US1 for integration testing
- **User Story 3 (P1)**: ✅ Code complete, needs US1 for integration testing
- **User Story 4 (P2)**: ⚠️ Mostly complete, may need reconnection logic enhancement (T042-T044)
- **User Story 5 (P3)**: ✅ Complete, works through existing entity APIs

### Critical Path

1. **T010**: Implement config_flow.py (HIGHEST PRIORITY - unblocks everything)
2. **T011-T018**: Complete US1 config flow implementation
3. **T042-T044**: Enhance reconnection logic for US4 (optional but recommended)
4. **T050-T068**: Testing and validation (Phase 8)

### Parallel Opportunities

Once T010 is complete:
- All tests in Phase 8 marked [P] can run in parallel
- Documentation tasks (T061-T063) can run in parallel
- Hardware testing (T064) can run alongside other validation tasks

---

## Parallel Example: Phase 8 Testing

```bash
# After T010 complete, launch all test creation tasks in parallel:
Task: "Write unit tests for protocol parsing in tests/test_coordinator.py"
Task: "Write unit tests for encryption/decryption in tests/test_coordinator.py"
Task: "Write config flow tests in tests/test_config_flow.py"
Task: "Write integration tests for BLE communication with mocks in tests/test_init.py"
Task: "Write entity creation tests in tests/test_sensors.py"
Task: "Add inline code documentation for public methods"
Task: "Update README.md with installation instructions"
```

---

## Implementation Strategy

### MVP First (Minimal Viable Product)

**Goal**: Get basic functionality working end-to-end

1. ✅ Phase 1: Setup (COMPLETE)
2. ⚠️ Phase 2: Foundational - **Complete T010 (config_flow.py) FIRST**
3. Phase 3: User Story 1 - Complete T011-T018 (config flow)
4. **STOP and VALIDATE**: Test discovery, setup, and verify all entities appear
5. Manual test: Turn heater on/off, adjust level, monitor sensors
6. **MVP COMPLETE** - Integration is now usable!

### Full Feature Delivery

After MVP complete:

1. Phase 6: User Story 4 - Complete T042-T044 (reconnection improvements)
2. Phase 8: Testing - Complete T050-T056 (unit and integration tests)
3. Phase 8: Validation - Complete T057-T060 (edge cases and hardware testing)
4. Phase 8: Documentation - Complete T061-T063 (README, docs, comments)
5. Phase 8: Final checks - Complete T064-T068 (performance, security, constitution)

### Recommended Immediate Actions

1. **START HERE**: T010 - Implement config_flow.py
   - This is the ONLY missing critical component
   - Reference: Home Assistant config flow docs, existing HA integrations
   - Use BluetoothServiceInfoBleak for discovery
   - Implement async_step_bluetooth, async_step_user, async_step_confirm

2. **THEN**: T011-T018 - Complete config flow details
   - Discovery filter, validation, error handling

3. **TEST**: Manual end-to-end test with real heater
   - Verify discovery, setup, monitoring, control all work

4. **OPTIONAL**: T042-T044 - Enhance reconnection logic
   - Exponential backoff, command queuing

5. **POLISH**: Phase 8 tasks as needed
   - Tests, docs, validation

---

## Notes

- **Current Status**: ~85% complete - only config_flow.py missing for core functionality
- **Priority Focus**: T010 (config_flow.py) unblocks everything
- Tests are optional but recommended for production use
- Most implementation already follows Home Assistant best practices
- Protocol parsing and entity implementation are solid
- [P] tasks = different files, no dependencies
- [Story] label maps task to specific user story for traceability
- Each user story should be independently completable and testable
- Commit after each task or logical group
- Avoid: vague tasks, same file conflicts, cross-story dependencies
