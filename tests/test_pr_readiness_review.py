"""Pre-PR checks for protocol selection and native-unit transitions."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from custom_components.diesel_heater.climate import VevorHeaterClimate
from custom_components.diesel_heater.const import RUNNING_MODE_TEMPERATURE
from custom_components.diesel_heater.temperature import temperature_bounds
from diesel_heater_ble import ProtocolABBA, ProtocolCBFF, ProtocolHcalory, ProtocolHeatGenie
from tests.test_audit_repairs import abba_status
from tests.test_coordinator import create_mock_coordinator
from tests.test_dz06_neo import coordinator_for_layout


def test_rejected_frame_cannot_replace_working_protocol():
    coordinator = create_mock_coordinator()
    coordinator._protocol_mode = 1
    coordinator._protocol = coordinator._protocols[1]
    selected = coordinator._protocol
    coordinator.data.update(connected=True, running_state=1)
    before = coordinator.data.copy()
    coordinator._parse_response(bytearray.fromhex("abba000000000000"))
    assert coordinator.protocol_mode == 1
    assert coordinator._protocol is selected
    assert coordinator.data == before
    assert coordinator._notification_data is None


@pytest.mark.parametrize("minimum,maximum,expected", [(12, 13, (53, 55)), (8, 36, (46, 96)), (15, 35, (59, 95))])
def test_warm_drive_bounds_use_apk_integer_conversion(minimum, maximum, expected):
    # DataConvertUtil.celsiusToFahrenheit truncates rather than rounding.
    coordinator = coordinator_for_layout(True)
    coordinator._heater_uses_fahrenheit = True
    coordinator.data.update(neo_min_target=minimum, neo_max_target=maximum)
    assert temperature_bounds(coordinator) == expected


@pytest.mark.parametrize("protocol_type", [ProtocolABBA, ProtocolHeatGenie])
def test_building_unit_command_cannot_change_last_validated_preference(protocol_type):
    protocol = protocol_type()
    assert not protocol._uses_fahrenheit
    protocol.build_command(15, 1, 0)
    assert not protocol._uses_fahrenheit


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", [5, 6, 7])
async def test_unit_command_ack_does_not_relabel_old_measurements(mode):
    coordinator = create_mock_coordinator()
    coordinator._protocol_mode = mode
    coordinator.data.update(temp_unit=0, cab_temperature=20, set_temp=20)
    coordinator._send_command = AsyncMock(return_value=True)
    coordinator._refresh_after_control_command = AsyncMock()
    await coordinator.async_set_temp_unit(True)
    assert coordinator.data["temp_unit"] == 0
    assert not coordinator._heater_uses_fahrenheit
    assert coordinator.data["cab_temperature"] == 20


def test_abba_level_report_converts_cached_target_when_unit_changes():
    coordinator = create_mock_coordinator()
    coordinator._parse_response(abba_status(unit=0, target=20))
    climate = VevorHeaterClimate(coordinator, coordinator.config_entry)
    assert climate.target_temperature == 20
    frame = abba_status(unit=1)
    frame[5], frame[6] = 0, 5  # Level mode omits the temperature target.
    coordinator._parse_response(frame)
    assert coordinator.data["set_temp"] == 68
    assert climate.target_temperature is None  # Level mode hides the cached target.
    coordinator.data["running_mode"] = RUNNING_MODE_TEMPERATURE
    assert climate.target_temperature == 68
    frame[10], frame[11] = 0, 50
    coordinator._parse_response(frame)
    assert coordinator.data["set_temp"] == 20
    assert climate.target_temperature is None
    coordinator.data["running_mode"] = RUNNING_MODE_TEMPERATURE
    assert climate.target_temperature == 20


def test_abba_restored_target_tracks_unit_when_no_wire_target_is_available():
    coordinator = create_mock_coordinator()
    coordinator._protocol_mode = 5
    coordinator.data["set_temp"] = None
    coordinator.data["running_mode"] = RUNNING_MODE_TEMPERATURE
    climate = VevorHeaterClimate(coordinator, coordinator.config_entry)
    climate._restored_abba_target = 20
    coordinator._heater_uses_fahrenheit = True
    assert climate.target_temperature == 68
    coordinator._heater_uses_fahrenheit = False
    assert climate.target_temperature == 20


def hcalory_status(state, unit):
    frame = bytearray(38)
    frame[8], frame[20], frame[21], frame[22], frame[37] = 3, state, 1, (68 if unit else 20), unit
    frame.append(sum(frame[8:]) & 255)
    return frame


def test_hcalory_off_report_converts_remembered_target_once():
    coordinator = create_mock_coordinator()
    coordinator._protocol = ProtocolHcalory()
    coordinator._protocols[7] = coordinator._protocol
    coordinator._is_hcalory_device = True
    coordinator._parse_response(hcalory_status(0x85, 0))
    assert coordinator.data["set_temp"] == 20
    coordinator._parse_response(hcalory_status(0, 1))
    assert coordinator.data["set_temp"] == 68
    coordinator._parse_response(hcalory_status(0, 1))
    assert coordinator.data["set_temp"] == 68
    coordinator._parse_response(hcalory_status(0, 0))
    assert coordinator.data["set_temp"] == 20


def test_legacy_hcalory_checksum_is_not_mistaken_for_unit():
    frame = hcalory_status(0x85, 0)
    del frame[37]  # Old payload omits the optional unit byte.
    frame[-1] = sum(frame[8:-1]) & 255
    assert len(frame) == 38
    assert frame[-1] not in (0, 1)
    assert ProtocolHcalory().parse(frame)["temp_unit"] == 0


@pytest.mark.parametrize("encrypted", [False, True])
@pytest.mark.asyncio
async def test_cbff_legacy_status_can_complete_a_real_poll(encrypted, monkeypatch):
    coordinator = create_mock_coordinator()
    protocol = coordinator._protocols[6]
    coordinator._protocol = protocol
    coordinator._protocol_mode = 6
    coordinator._client = AsyncMock()
    coordinator._client.is_connected = True
    coordinator._characteristic = object()
    frame = bytearray(47)
    frame[:2] = bytes((0xCB, 0xFF))
    frame[2], frame[10], frame[11], frame[12] = 1, 5, 1, 5
    frame[23:25] = (120).to_bytes(2, "little")
    if encrypted:
        protocol.set_device_sn("AABBCCDDEEFF")
        frame = protocol._encrypt_cbff(frame, "AABBCCDDEEFF")
        coordinator._queue_v21_handshake = lambda _: None
    coordinator._write_gatt = AsyncMock(side_effect=lambda packet: coordinator._notification_callback(0, frame))

    async def no_delay(_):
        return None

    monkeypatch.setattr("custom_components.diesel_heater.coordinator.asyncio.sleep", no_delay)
    assert await coordinator._send_command(1, 0, timeout=0.1) is True
    assert coordinator.data["supply_voltage"] == 12


@pytest.mark.parametrize(
    "command,ack_id,expected",
    [(1, 0x83, False), (14, 0x81, False), (14, 0x83, True), (3, 0x83, False), (3, 0x81, True)],
)
def test_feaa_acknowledgement_matches_the_outstanding_family(command, ack_id, expected):
    protocol = ProtocolCBFF()
    packet = protocol._build_feaa(ack_id, 1)
    assert protocol.matches_response(packet, command) is expected


@pytest.mark.asyncio
async def test_abba_restores_ha_display_target_in_native_unit():
    coordinator = create_mock_coordinator()
    coordinator._protocol_mode = 5
    coordinator._heater_uses_fahrenheit = True
    climate = VevorHeaterClimate(coordinator, coordinator.config_entry)
    climate.hass = MagicMock()
    climate.hass.config.units.temperature_unit = "°C"
    climate.async_get_last_state = AsyncMock(return_value=SimpleNamespace(attributes={"temperature": 20.0}))
    await climate.async_added_to_hass()
    assert climate._restored_abba_target == 68


def test_standalone_hcalory_fff0_clock_includes_host_utc_offset(monkeypatch):
    import os
    import time
    from datetime import UTC, datetime

    if not hasattr(time, "tzset"):
        pytest.skip("tzset is required for the isolated host-timezone check")
    old_tz = os.environ.get("TZ")

    class FixedDatetime(datetime):
        @classmethod
        def now(cls, tz=None):
            return cls(2026, 11, 2, 17, 34, 21)

    try:
        monkeypatch.setenv("TZ", "Etc/GMT-5")
        time.tzset()
        monkeypatch.setattr("diesel_heater_ble.protocol.datetime", FixedDatetime)
        protocol = ProtocolHcalory()
        protocol.set_transport(bd39=False)
        packet = protocol.build_command(1, 0, 0)
        expected = int(datetime(2026, 11, 2, 17, 34, 21, tzinfo=UTC).timestamp())
        assert int.from_bytes(packet[12:16], "big") == expected
    finally:
        if old_tz is None:
            monkeypatch.delenv("TZ", raising=False)
        else:
            monkeypatch.setenv("TZ", old_tz)
        time.tzset()


@pytest.mark.parametrize("kind", ["wrong_header", "bad_checksum", "settings_reply"])
def test_cbff_rejects_non_status_even_when_measurements_look_plausible(kind):
    protocol = ProtocolCBFF()
    if kind == "wrong_header":
        frame = bytearray(47)
    else:
        frame = protocol._build_feaa(0x83 if kind == "settings_reply" else 0x80, 0, bytes(38))
        if kind == "bad_checksum":
            frame[-1] ^= 1
    assert protocol.parse(frame) is None


def test_warm_drive_settings_read_keeps_target_in_the_native_display_unit():
    from tests.test_dz06_neo import FFF2, neo_run_settings_response

    coordinator = coordinator_for_layout(True)
    coordinator._heater_uses_fahrenheit = True
    coordinator._notification_callback(FFF2, neo_run_settings_response(target=20))
    assert coordinator.data["set_temp"] == 68
    coordinator.data["neo_raw_state"] = 2
    assert coordinator._neo_control_settings()[1] == 20


def test_warm_drive_board_unit_change_converts_cached_whole_celsius_values():
    from tests.test_dz06_neo import FFF2

    coordinator = coordinator_for_layout(True)
    coordinator.data.update(set_temp=20, cab_temperature=21, fire_temperature=-10, hot_water_temperature=30)
    frame = bytearray(21)
    frame[0], frame[1], frame[17] = 0x5D, 19, 2
    coordinator._notification_callback(FFF2, frame)
    assert coordinator.data["set_temp"] == 68
    assert coordinator.data["cab_temperature"] == 69
    assert coordinator.data["fire_temperature"] == 14
    frame[17] = 1
    coordinator._notification_callback(FFF2, frame)
    assert coordinator.data["set_temp"] == 20
    assert coordinator.data["cab_temperature"] == 21
    assert coordinator.data["fire_temperature"] == -10
    assert coordinator.data["hot_water_temperature"] == 30


@pytest.mark.asyncio
@pytest.mark.parametrize("state", [0, 1, 2])
@pytest.mark.parametrize("accepted", [False, True])
@pytest.mark.parametrize("desired", [1, 2])
async def test_abba_mode_change_requires_reported_mode(monkeypatch, state, accepted, desired):
    coordinator = create_mock_coordinator()
    coordinator._protocol_mode = 5
    coordinator._protocol = ProtocolABBA()
    coordinator._client = MagicMock(is_connected=True)
    coordinator._characteristic = "write"
    coordinator._write_gatt = AsyncMock()
    coordinator.async_request_refresh = AsyncMock()
    frame = abba_status(unit=0, target=20)
    frame[4] = state
    previous = 2 if desired == 1 else 1
    frame[5] = previous - 1
    coordinator._parse_response(frame)

    async def report(_delay):
        reply = bytearray(frame)
        reply[5] = (desired if accepted else previous) - 1
        coordinator._parse_response(reply)

    monkeypatch.setattr("custom_components.diesel_heater.coordinator.asyncio.sleep", report)
    assert await coordinator.async_set_mode(desired) is accepted
    assert coordinator.data["running_mode"] == (desired if accepted else previous)
    # Only the mode button and status query may be written, never heat toggle A1.
    assert [call.args[0][3] for call in coordinator._write_gatt.await_args_list] == [0xBB, 0xCC]
    assert coordinator._write_gatt.await_args_list[0].args[0][4] == (0xAD if desired == 2 else 0xAC)
    assert coordinator.async_request_refresh.await_count == int(accepted)


@pytest.mark.asyncio
async def test_abba_mode_change_waits_past_unchanged_status(monkeypatch):
    coordinator = create_mock_coordinator()
    coordinator._protocol_mode = 5
    coordinator._protocol = ProtocolABBA()
    coordinator._client = MagicMock(is_connected=True)
    coordinator._characteristic = "write"
    coordinator._write_gatt = AsyncMock()
    reports = 0

    async def report(_delay):
        nonlocal reports
        reports += 1
        frame = abba_status(unit=0, target=20)
        frame[5] = int(reports >= 3)
        coordinator._parse_response(frame)

    monkeypatch.setattr("custom_components.diesel_heater.coordinator.asyncio.sleep", report)
    assert await coordinator._send_command(2, 2) is True
    assert reports == 3


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", ["max", "restore_level", "restore_temperature"])
async def test_abba_burnoff_does_not_write_target_after_failed_mode(operation):
    coordinator = create_mock_coordinator()
    coordinator._protocol_mode = 5
    coordinator.data["running_mode"] = 2
    coordinator.async_set_mode = AsyncMock(return_value=False)
    coordinator.async_set_level = AsyncMock(return_value=True)
    coordinator.async_set_temperature = AsyncMock(return_value=True)
    cycle = coordinator._burnoff.cycle
    if operation == "max":
        result = await coordinator.async_apply_burnoff_max_power(cycle)
    else:
        cycle.saved_mode = 1 if operation == "restore_level" else 2
        cycle.saved_level = 3
        cycle.saved_temp = 20
        result = await coordinator.async_restore_burnoff_snapshot(cycle)
    assert result is False
    coordinator.async_set_level.assert_not_awaited()
    coordinator.async_set_temperature.assert_not_awaited()
