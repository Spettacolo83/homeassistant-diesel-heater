# Quickstart: Vevor Diesel Heater Integration

**Date**: 2025-10-29
**For**: Developers implementing the integration

## Prerequisites

- Home Assistant 2024.1.0+ installed
- Python 3.11+ development environment
- ESP32 Bluetooth Proxy configured and connected to HA
- Vevor diesel heater within BLE range of proxy
- Git, pytest, and development tools installed

---

## Quick Setup (5 minutes)

### 1. Clone and Install

```bash
# Navigate to your Home Assistant config directory
cd /config

# Create custom_components directory if it doesn't exist
mkdir -p custom_components

# Copy integration files
cp -r /path/to/vevor_heater custom_components/

# Install dependencies (if developing locally)
pip install bleak>=0.21.0 bleak-retry-connector>=3.4.0 pytest pytest-homeassistant-custom-component
```

### 2. Restart Home Assistant

```bash
# From HA UI: Settings → System → Restart
# Or from command line:
ha core restart
```

### 3. Add Integration

**Option A: Auto-Discovery** (Recommended)
1. Turn on your Vevor heater
2. Wait 30 seconds for HA to detect it
3. Click the notification: "New device discovered"
4. Click "Configure" → "Submit"
5. Done! Entities are now available

**Option B: Manual Setup**
1. Go to Settings → Devices & Services
2. Click "+ Add Integration"
3. Search for "Vevor"
4. Select "Vevor Diesel Heater"
5. Choose your heater from the list
6. Click "Submit"

---

## Verify Installation

### Check Entities Created

Go to Settings → Devices & Services → Vevor Diesel Heater → Device

You should see **14 entities**:

**Sensors (8)**:
- Interior Temperature
- Case Temperature
- Supply Voltage
- Running Step
- Running Mode
- Set Level
- Altitude
- Error

**Binary Sensors (3)**:
- Active
- Problem
- Connected (hidden, diagnostic)

**Controls (3)**:
- Power (switch)
- Level (number, 1-10)
- Target Temperature (number, 8-36°C)

---

## Quick Test

### Test Power Control

1. Find the "Power" switch entity
2. Toggle it ON
3. Watch "Running Step" sensor change: Standby → Self-test → Ignition → Running
4. This takes 2-5 minutes depending on ambient temperature
5. Toggle Power OFF
6. Watch Running Step: Running → Cooldown → Standby

### Test Level Control

1. Ensure heater is Running (Running Step = "Running")
2. Adjust "Level" number input (1-10)
3. Within 5 seconds, heater should change output
4. Listen for fan speed change (audible confirmation)

### Test Status Monitoring

1. Open the device page
2. Watch sensors update every 30 seconds
3. Interior Temperature should change as heater warms cabin
4. Supply Voltage should show your battery voltage (typically 12-14V)

---

## Development Workflow

### Project Structure

```
custom_components/vevor_heater/
├── __init__.py              # Entry point
├── config_flow.py           # Auto-discovery & setup UI
├── const.py                 # Constants (UUIDs, protocols, limits)
├── coordinator.py           # BLE communication & protocol parsing
├── manifest.json            # Metadata & dependencies
├── strings.json             # UI strings
├── sensor.py                # 8 sensor entities
├── binary_sensor.py         # 3 binary sensor entities
├── switch.py                # Power switch
└── number.py                # Level & temperature controls

tests/
├── conftest.py              # Pytest fixtures
├── test_config_flow.py      # Config flow tests
├── test_coordinator.py      # Protocol parsing tests
├── test_init.py             # Setup/unload tests
└── test_sensors.py          # Entity tests
```

### Running Tests

```bash
# From repository root
pytest tests/ -v

# Run specific test file
pytest tests/test_coordinator.py -v

# Run with coverage
pytest tests/ --cov=custom_components.vevor_heater --cov-report=html
```

### Enable Debug Logging

Add to `configuration.yaml`:

```yaml
logger:
  default: info
  logs:
    custom_components.vevor_heater: debug
```

Restart HA and check logs: Settings → System → Logs

You'll see:
- BLE connection events
- Protocol detection
- Raw byte arrays (responses from heater)
- Command sending
- Parsing details

---

## Common Development Tasks

### Add a New Sensor

1. **Define in `data-model.md`**: Document entity structure
2. **Add to `sensor.py`**:
```python
class VevorNewSensor(CoordinatorEntity, SensorEntity):
    def __init__(self, coordinator, entry):
        super().__init__(coordinator)
        self._attr_name = f"Vevor Heater {entry.data[CONF_ADDRESS][-5:]} New Sensor"
        self._attr_unique_id = f"{entry.data[CONF_ADDRESS]}_new_sensor"

    @property
    def native_value(self):
        return self.coordinator.data.get("new_field")
```

3. **Update coordinator parsing**: Extract value in `_parse_protocol_XX()`
4. **Add to `PLATFORMS` in `__init__.py`** (if new platform type)
5. **Write tests in `test_sensors.py`**

### Add a New Command

1. **Document in `contracts/ble-protocol.md`**: Specify command ID, arguments
2. **Add method to `coordinator.py`**:
```python
async def async_new_action(self, argument: int) -> None:
    """New action description."""
    await self._send_command(command_id=X, argument=argument, n=85)
    await self.async_request_refresh()
```

3. **Call from entity** (switch/button/number)
4. **Add tests with mocked BLE communication**

### Debug Protocol Issues

```python
# In coordinator.py _notification_callback()
_LOGGER.debug("Raw notification: %s", data.hex())

# In _parse_response()
_LOGGER.debug("Detected protocol %d, length %d", protocol, len(data))

# In _parse_protocol_XX()
_LOGGER.debug("Parsed data: %s", self.data)
```

Check logs to see exactly what bytes are received and how they're parsed.

---

## Troubleshooting

### Integration Not Appearing

**Symptoms**: Can't find "Vevor" when adding integration

**Solutions**:
1. Check `manifest.json` is valid JSON
2. Check `__init__.py` has no syntax errors
3. Restart HA with `ha core restart`
4. Check logs for import errors

### Auto-Discovery Not Working

**Symptoms**: No notification when heater turns on

**Solutions**:
1. Verify heater is within 10 meters of Bluetooth proxy
2. Check proxy is connected: Settings → Devices & Services → Bluetooth
3. Check heater advertises service UUID `0000fff0-0000-1000-8000-00805f9b34fb`
4. Try manual setup instead

### Entities Show "Unavailable"

**Symptoms**: All entities unavailable after setup

**Solutions**:
1. Check "Connected" binary sensor (enable it first, it's hidden)
2. Enable debug logging and check for BLE errors
3. Verify proxy has available connection slots (max 3)
4. Try disconnecting other BLE devices temporarily
5. Check heater is powered on and responding

### Commands Don't Work

**Symptoms**: Toggling power or changing level has no effect

**Solutions**:
1. Check "Connected" binary sensor is ON
2. Enable debug logging, watch for command sending
3. Verify coordinator is connected to correct MAC address
4. Check heater isn't being controlled by physical remote simultaneously
5. Verify command timeout (2s) isn't being exceeded

### Wrong Temperature Readings

**Symptoms**: Temperatures show extreme values or wrong sign

**Solutions**:
1. Check protocol detection: Should auto-detect 1 of 4 protocols
2. Verify signed integer conversion for negative temps
3. Check byte order (big-endian vs little-endian)
4. Compare with physical remote display

---

## Performance Tuning

### Adjust Update Interval

In `const.py`:
```python
UPDATE_INTERVAL: Final = 30  # Change to 15, 60, etc. (seconds)
```

**Trade-offs**:
- Shorter interval: More responsive, more BLE traffic
- Longer interval: Less battery drain on proxy, less network traffic

### Adjust Command Timeout

In `coordinator.py` `_send_command()`:
```python
for _ in range(20):  # Change to 30 for 3s timeout, 10 for 1s timeout
    await asyncio.sleep(0.1)
```

### Reconnection Backoff

In `coordinator.py` (if implementing custom backoff):
```python
backoff_intervals = [5, 10, 20, 40, 60]  # Add more intervals or adjust
```

---

## Next Steps

1. **Read the specs**:
   - `spec.md` - User scenarios and requirements
   - `data-model.md` - Entity definitions
   - `contracts/ble-protocol.md` - Protocol details

2. **Run tests**: `pytest tests/ -v`

3. **Try manual control**: Use HA UI to control heater

4. **Create automations**: Test automation scenarios from `spec.md`

5. **Contribute**: Follow constitution.md principles for code quality

---

## Quick Reference

### Key Files

| File | Purpose |
|------|---------|
| `__init__.py` | Setup/unload, platform forwarding |
| `config_flow.py` | Auto-discovery, manual setup UI |
| `coordinator.py` | BLE communication, protocol parsing |
| `const.py` | All constants, no magic numbers |
| `sensor.py` | 8 sensor entities |
| `binary_sensor.py` | 3 binary sensor entities |
| `switch.py` | Power control |
| `number.py` | Level & temperature controls |

### Key Commands

```bash
# Restart HA
ha core restart

# Run tests
pytest tests/ -v

# Check logs
tail -f /config/home-assistant.log | grep vevor

# Reload integration (after code change)
# Settings → Devices & Services → Vevor → ⋮ → Reload
```

### BLE Details

| Item | Value |
|------|-------|
| Service UUID | `0000fff0-0000-1000-8000-00805f9b34fb` |
| Write Characteristic | `0000fff1-0000-1000-8000-00805f9b34fb` |
| Notify Characteristic | `0000fff2-0000-1000-8000-00805f9b34fb` |
| Protocols | AA55/AA66 × encrypted/unencrypted (4 total) |
| Update Interval | 30 seconds |
| Command Timeout | 2 seconds |
| Connection Timeout | 5 seconds |

---

## Support

- **Documentation**: See `specs/001-vevor-heater-integration/` directory
- **Constitution**: `.specify/memory/constitution.md` for coding standards
- **Issues**: Check logs first, then create detailed bug report
- **Testing**: All PRs must include tests and pass constitution checks
