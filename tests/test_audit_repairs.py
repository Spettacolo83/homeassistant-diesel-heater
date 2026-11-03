"""APK-backed regression cases for the end-to-end audit findings.

Evidence locators and hashes: audit/evidence-excerpts.txt and apk-source-index.json.
These exercise production parsers/coordinator logic; they do not operate heaters.
"""

import asyncio
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from custom_components.diesel_heater.climate import VevorHeaterClimate
from custom_components.diesel_heater.number import VevorHeaterTemperatureNumber
from custom_components.diesel_heater.sensor import VevorCabTemperatureSensor
from diesel_heater_ble import (
    ProtocolAA66,
    ProtocolABBA,
    ProtocolCBFF,
    ProtocolCronus,
    ProtocolHcalory,
    ProtocolHeatGenie,
)
from tests.test_coordinator import create_mock_coordinator


def abba_status(unit=1, target=68):
    frame = bytearray(21)
    frame[:4] = bytes.fromhex("abba11cc")
    frame[4:7] = bytes((1, 1, target))
    frame[10:12] = bytes((unit, 90 if unit else 50))
    return frame


def heatgenie_status(unit=1, probe=215):
    frame = bytearray(50)
    frame[0], frame[1], frame[7] = 0xAA, 9, 0xF2
    frame[8], frame[9] = 3, unit << 4
    frame[14:16] = (200).to_bytes(2, "little", signed=True)
    frame[16:18] = (1000).to_bytes(2, "little", signed=True)
    frame[24:26] = probe.to_bytes(2, "little", signed=True)
    frame[26:28] = probe.to_bytes(2, "little", signed=True)
    frame[41] = 68 if unit else 20
    frame[-2:] = ProtocolHeatGenie.crc16(frame[:-2]).to_bytes(2, "big")
    return frame


@pytest.mark.parametrize("target", [46, 68, 97])
def test_abba_fahrenheit_target_and_unit_byte(target):
    # AirHeaterCC setTemperature(target,isItCelsius), DB target 00 unit.
    protocol = ProtocolABBA()
    assert protocol.parse(abba_status(target=target))["set_temp"] == target
    packet = protocol.build_command(4, target, 0)
    assert packet[3:7] == bytes((0xDB, target, 0, 1))
    assert packet[-1] == sum(packet[:-1]) & 255
    assert protocol.build_command(18, 1, 0)[4] == 0xA6


@pytest.mark.parametrize("version,expected", [(1, 1000), (0, 100), (2, 100)])
def test_cbff_altitude_version_and_fahrenheit_target(version, expected):
    frame = bytearray(47)
    frame[2], frame[11], frame[12], frame[17] = version, 2, 68, 1
    frame[21:23] = (1000).to_bytes(2, "little")
    parsed = ProtocolCBFF._parse_cbff_fields(frame)
    assert parsed["altitude"] == expected
    assert parsed["set_temp"] == 68


@pytest.mark.parametrize(
    "command,index,value",
    [(14, 5, 2), (15, 1, 1), (16, 6, 4), (17, 7, 1), (19, 0, 1), (20, 4, -3), (21, 8, 50), (18, 12, 1)],
)
def test_feaa_setting_preserves_every_unmodified_snapshot_byte(command, index, value):
    # Sunster encrypt.js writeBufferData 03/01, 13-byte cached settings.
    protocol = ProtocolCBFF()
    snapshot = bytes((0, 0, 0, 0, 0, 1, 2, 3, 4, 5, 6, 7, 0))
    protocol._v21_settings = snapshot
    packet = protocol.build_command(command, value, 1234)
    expected = bytearray(snapshot)
    expected[index] = value & 255
    assert packet[6:8] == b"\x03\x01"
    assert packet[8:-1] == expected
    assert packet[-1] == sum(packet[:-1]) & 255
    assert protocol._v21_settings == snapshot  # not an optimistic acknowledgement


@pytest.mark.parametrize("command", [14, 15, 16, 17, 19, 20, 21])
def test_feaa_setting_does_not_invent_a_missing_capability(command):
    protocol = ProtocolCBFF()
    with pytest.raises(ValueError):
        protocol.build_command(command, 0, 0)
    protocol._v21_settings = bytes([255] * 13)
    if command != 20:  # FF is also the legitimate signed offset -1.
        with pytest.raises(ValueError):
            protocol.build_command(command, 0, 0)


@pytest.mark.parametrize("sign,expected", [(0, 12.5), (1, -12.5)])
def test_hcalory_sign_and_fraction(sign, expected):
    frame = bytearray(38)
    frame[20], frame[21] = 0x85, 1
    frame[26] = frame[29] = sign
    frame[27:29] = frame[30:32] = (125).to_bytes(2, "big")
    frame[8] = 3
    frame.append(sum(frame[8:]) & 255)
    parsed = ProtocolHcalory().parse(frame)
    assert parsed["cab_temperature"] == parsed["case_temperature"] == expected


@pytest.mark.parametrize("bd39", [False, True])
def test_hcalory_gatt_specific_timestamp(bd39):
    # Hcalory q2/h.q branches on p2/e0.p (active BD39 service).
    protocol = ProtocolHcalory()
    protocol.set_transport(bd39=bd39)
    now = datetime(2026, 11, 2, 17, 34, 21, tzinfo=timezone(timedelta(hours=-3, minutes=-30)))
    protocol.set_query_timestamp(now)
    packet = protocol.build_command(1, 0, 0)
    expected = bytes((17, 34, 21, 1)) if bd39 else (int(now.timestamp()) - 12600).to_bytes(4, "big")
    assert packet[12:16] == expected


def test_heatgenie_fahrenheit_is_a_display_preference_not_telemetry_unit():
    coordinator = create_mock_coordinator()
    coordinator._is_heatgenie_device = True
    coordinator.async_set_updated_data = MagicMock()
    coordinator._parse_response(heatgenie_status())
    assert coordinator.data["cab_temperature"] == 20
    assert coordinator.data["case_temperature"] == 100
    assert coordinator.data["set_temp"] == 20
    assert coordinator.data["temp_unit"] == 1
    assert not coordinator._heater_uses_fahrenheit
    assert coordinator._protocol._uses_fahrenheit


def test_absent_heatgenie_probe_clears_last_valid_reading():
    coordinator = create_mock_coordinator()
    coordinator._is_heatgenie_device = True
    coordinator.async_set_updated_data = MagicMock()
    coordinator._parse_response(heatgenie_status(probe=215))
    assert coordinator.data["intake_temperature"] == 21.5
    coordinator._parse_response(heatgenie_status(probe=32760))
    assert coordinator.data["intake_temperature"] is None
    assert coordinator.data["outlet_temperature"] is None


@pytest.mark.parametrize("raises", [False, True])
def test_invalid_status_preserves_real_state_and_cannot_complete_poll(raises):
    coordinator = create_mock_coordinator()
    coordinator.data.update(connected=True, running_state=1, error_code=9)
    before = coordinator.data.copy()
    protocol = MagicMock(protocol_mode=5)
    protocol.parse = MagicMock(side_effect=ValueError("invalid")) if raises else MagicMock(return_value=None)
    coordinator._detect_protocol = MagicMock(return_value=(protocol, bytearray(8)))
    coordinator._parse_response(bytearray.fromhex("abba000000000000"))
    assert coordinator.data == before
    assert coordinator._notification_data is None


def test_temperature_entities_follow_later_native_unit_change():
    coordinator = create_mock_coordinator()
    coordinator._protocol_mode = 5
    coordinator.data.update(cab_temperature=20, set_temp=20)
    sensor = VevorCabTemperatureSensor(coordinator)
    number = VevorHeaterTemperatureNumber(coordinator)
    climate = VevorHeaterClimate(coordinator, coordinator.config_entry)
    assert sensor.native_unit_of_measurement == "°C"
    assert (number.native_min_value, number.native_max_value) == (8, 36)
    coordinator._parse_response(abba_status())
    assert sensor.native_unit_of_measurement == climate.temperature_unit == number.native_unit_of_measurement == "°F"
    assert (number.native_min_value, number.native_max_value) == (46, 97)


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", [5, 7])
@pytest.mark.parametrize("enabled", [False, True])
async def test_toggle_switch_is_idempotent(mode, enabled):
    coordinator = create_mock_coordinator()
    coordinator._protocol_mode = mode
    coordinator.data["auto_start_stop"] = enabled
    coordinator._send_command = AsyncMock()
    await coordinator.async_set_auto_start_stop(enabled)
    coordinator._send_command.assert_not_awaited()
    coordinator.data["auto_start_stop"] = not enabled
    coordinator._send_command.return_value = True
    await coordinator.async_set_auto_start_stop(enabled)
    coordinator._send_command.assert_awaited_once_with(18, int(enabled))


@pytest.mark.asyncio
async def test_manual_cbff_clock_returns_actual_result():
    coordinator = create_mock_coordinator()
    coordinator._protocol_mode = 6
    coordinator._send_v21_time_sync = AsyncMock(return_value=True)
    assert coordinator.supports_time_sync
    assert await coordinator.async_sync_time() is True


@pytest.mark.asyncio
async def test_missing_post_command_temperature_does_not_raise():
    coordinator = create_mock_coordinator()
    coordinator._protocol_mode = 5
    coordinator.data["set_temp"] = None
    coordinator._send_command = AsyncMock(return_value=True)
    coordinator._refresh_after_control_command = AsyncMock()
    assert await coordinator.async_set_temperature(20) is True


@pytest.mark.asyncio
async def test_unload_cancels_owned_writer_and_blocks_late_work():
    coordinator = create_mock_coordinator()
    waiting = asyncio.Event()
    cancelled = asyncio.Event()

    async def writer():
        try:
            await waiting.wait()
        finally:
            cancelled.set()

    task = coordinator.create_background_task(writer())
    await asyncio.sleep(0)
    coordinator._cleanup_connection = AsyncMock()
    await coordinator.async_shutdown()
    assert task.cancelled() and cancelled.is_set()
    assert not coordinator._background_tasks
    assert coordinator.create_background_task(writer()) is None
    with pytest.raises(Exception, match="unloading"):
        await coordinator._write_gatt(bytearray(8))


def test_cronus_fragments_are_individual_ble_writes():
    payload = bytes(range(25))
    frames = ProtocolCronus.build_write_frames(73, payload)
    assert len(frames) == 4
    assert [frame[4] for frame in frames] == [0x50, 0x51, 0x51, 0x51]
    assert all(len(frame) == 7 + frame[6] for frame in frames)
    assert frames[0][9:] + b"".join(frame[8:] for frame in frames[1:]) == payload


@pytest.mark.parametrize("raw", [350, 351, 1500, 65526])
def test_plain_aa66_case_temperature_uses_signed_whole_degrees(raw):
    # AirHeaterBLE ble.js AA66 branch: UnsignToSign(256*i[14]+i[13]).
    frame = bytearray(20)
    frame[13:15] = raw.to_bytes(2, "little")
    assert ProtocolAA66().parse(frame)["case_temperature"] == (raw - 65536 if raw >= 32768 else raw)


@pytest.mark.parametrize("auth_byte", [1, 2])
def test_hcalory_auth_reply_is_separate_from_status(auth_byte):
    coordinator = create_mock_coordinator()
    coordinator._protocol = ProtocolHcalory()
    coordinator._protocol_mode = 7
    frame = bytearray.fromhex("000300010001000B0C0000060101020304011E")
    frame[17] = auth_byte
    frame[-1] = sum(frame[8:-1]) & 255
    coordinator._notification_callback(0, frame)
    assert coordinator._hcalory_auth_response == frame
    assert coordinator._notification_data is None
    assert coordinator.data["connected"] is False
    assert ProtocolHcalory.parse_password_response(frame) is (auth_byte == 1)
    frame[-1] ^= 1
    assert ProtocolHcalory.parse_password_response(frame) is None


@pytest.mark.asyncio
async def test_save_keeps_the_dates_that_own_the_unreset_daily_totals():
    coordinator = create_mock_coordinator()
    coordinator._last_reset_date = "2026-11-01"
    coordinator._last_runtime_reset_date = "2026-10-31"
    await coordinator.async_save_data()
    from custom_components.diesel_heater.const import STORAGE_KEY_DAILY_DATE, STORAGE_KEY_DAILY_RUNTIME_DATE

    stored = coordinator._store.async_save.await_args.args[0]
    assert stored[STORAGE_KEY_DAILY_DATE] == "2026-11-01"
    assert stored[STORAGE_KEY_DAILY_RUNTIME_DATE] == "2026-10-31"


def test_disconnect_clears_measured_probes_and_component_states():
    coordinator = create_mock_coordinator()
    fields = ("intake_temperature", "outlet_temperature", "pump_active", "fan_active", "glow_plug_active")
    coordinator.data.update(dict.fromkeys(fields, 1))
    coordinator._clear_sensor_values()
    assert all(coordinator.data[field] is None for field in fields)


@pytest.mark.parametrize(
    "packet",
    [
        bytes.fromhex("aa550c2201140043"),
        bytes.fromhex("000300010001000B0C0000060101020304011E"),
        bytes.fromhex("290d5c000000000005f5e100010000"),
    ],
)
def test_diagnostic_packet_text_redacts_credentials(packet):
    coordinator = create_mock_coordinator()
    text = coordinator._packet_for_log(packet)
    assert text != packet.hex()


@pytest.mark.asyncio
async def test_unsupported_cbff_write_returns_failure_without_disconnect():
    coordinator = create_mock_coordinator()
    coordinator._protocol_mode = 6
    coordinator._protocol = ProtocolCBFF()
    coordinator._client = SimpleNamespace(is_connected=True)
    coordinator._characteristic = object()
    coordinator._write_gatt = AsyncMock()
    coordinator._cleanup_connection = AsyncMock()
    assert await coordinator._send_command(14, 2) is False
    coordinator._write_gatt.assert_not_awaited()
    coordinator._cleanup_connection.assert_not_awaited()


@pytest.mark.asyncio
async def test_cbff_settings_ack_is_admitted_without_becoming_status():
    coordinator = create_mock_coordinator()
    coordinator._protocol_mode = 6
    coordinator._protocol = coordinator._protocols[6]
    frame = ProtocolCBFF._build_feaa(0x83, 1)
    before = coordinator.data.copy()
    coordinator._parse_response(frame)
    assert coordinator._notification_data == frame
    assert coordinator.data == before


@pytest.mark.asyncio
async def test_unsupported_heatgenie_probe_has_no_entity():
    from custom_components.diesel_heater.sensor import async_setup_entry

    coordinator = create_mock_coordinator()
    coordinator._protocol_mode = 8
    coordinator.data.update(intake_temperature=None, outlet_temperature=0)
    entry = SimpleNamespace(runtime_data=coordinator, data={})
    collected = []
    await async_setup_entry(coordinator.hass, entry, collected.extend)
    keys = [entity._key for entity in collected]
    assert "intake_temperature" not in keys
    assert "outlet_temperature" in keys  # zero is a valid measurement


@pytest.mark.parametrize("position", [8, 20, 27, -1])
def test_hcalory_corrupt_status_is_not_accepted(position):
    frame = bytearray.fromhex("00010001000100230300001EFFFF01F40000000085014602007800102C00023000000000000100000000C9")
    assert ProtocolHcalory().parse(frame) is not None
    frame[position] ^= 1
    assert ProtocolHcalory().parse(frame) is None


@pytest.mark.parametrize("bd39", [True, False])
def test_hcalory_poll_timestamp_uses_ha_timezone(monkeypatch, bd39):
    coordinator = create_mock_coordinator()
    coordinator._protocol = ProtocolHcalory()
    coordinator._protocol.set_transport(bd39=bd39)
    now = datetime(2026, 11, 2, 17, 34, 21, tzinfo=timezone(timedelta(hours=-3, minutes=-30)))
    monkeypatch.setattr("custom_components.diesel_heater.coordinator.dt_util.now", lambda: now)
    packet = coordinator._build_command_packet(1)
    expected = bytes((17, 34, 21, 1)) if bd39 else (int(now.timestamp()) - 12600).to_bytes(4, "big")
    assert packet[12:16] == expected


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "warm,raw_state,powered",
    [
        (True, 3, True),
        (True, 6, False),
        (True, 160, False),
        (True, 170, True),
        (True, 171, True),
        (False, 3, True),
        (False, 6, False),
        (False, 160, True),
        (False, 171, True),
    ],
)
async def test_neo_power_confirmation_matches_each_controller_profile(warm, raw_state, powered, monkeypatch):
    from tests.test_dz06_neo import FFF2, coordinator_for_layout

    coordinator = coordinator_for_layout(True, name="Air Heater" if warm else "Sunster Neo")
    coordinator.data.update(neo_raw_state=2, neo_run_type=2, set_temp=20, altitude=1)
    response = bytearray(39)
    response[:2], response[3], response[34] = b"Z%", raw_state, 2
    coordinator._write_gatt = AsyncMock(side_effect=lambda packet: coordinator._notification_callback(FFF2, response))

    async def no_delay(_):
        return None

    monkeypatch.setattr("custom_components.diesel_heater.coordinator.asyncio.sleep", no_delay)
    assert await coordinator._send_dz06_neo_power(powered) is True


@pytest.mark.parametrize("rf433_value", [20, 21])
def test_feaa_rf433_capability_is_not_overwritten_as_pump_type(rf433_value):
    protocol = ProtocolCBFF()
    settings = bytearray(13)
    settings[7] = rf433_value
    protocol._v21_settings = bytes(settings)
    with pytest.raises(ValueError, match="RF433"):
        protocol.build_command(17, 1, 0)


def test_feaa_negative_one_offset_is_a_value_not_an_absent_capability():
    protocol = ProtocolCBFF()
    settings = bytearray(13)
    settings[4] = 255
    protocol._v21_settings = bytes(settings)
    packet = protocol.build_command(20, -3, 0)
    assert packet[12] == 253


@pytest.mark.asyncio
async def test_warm_drive_profile_has_only_its_supported_config_controls():
    from custom_components.diesel_heater import number, select, sensor, switch
    from tests.test_dz06_neo import coordinator_for_layout

    coordinator = coordinator_for_layout(True)
    coordinator.address = "AA:BB:CC:DD:EE:FF"
    coordinator.data.update(
        neo_controller_type="air",
        neo_raw_state=2,
        neo_run_type=2,
        set_temp=20,
        connected=True,
        running_mode=2,
        fire_temperature=100,
    )
    coordinator.hass = MagicMock()
    entry = SimpleNamespace(runtime_data=coordinator, data={})
    names = []
    for module in (sensor, number, select, switch):
        entities = []
        await module.async_setup_entry(coordinator.hass, entry, entities.extend)
        names.extend(type(entity).__name__ for entity in entities)
    for unsupported in (
        "VevorHeaterOffsetNumber",
        "VevorTempUnitSwitch",
        "VevorAltitudeUnitSwitch",
        "VevorHeaterLanguageSelect",
        "VevorBacklightSelect",
        "VevorHighAltitudeSwitch",
        "VevorHardwareVersionSensor",
        "VevorCaseTemperatureSensor",
    ):
        assert unsupported not in names
    assert "VevorHeaterTemperatureNumber" in names
    assert "VevorAutoStartStopSwitch" in names
    assert "VevorHeaterPumpTypeSelect" in names
    assert "VevorHeaterTankVolumeSelect" in names


@pytest.mark.asyncio
async def test_valid_neo_status_can_finish_setup_with_numeric_mode_zero(monkeypatch):
    import custom_components.diesel_heater as integration

    coordinator = MagicMock()
    coordinator.protocol_mode = 0
    coordinator.is_dz06_neo = True
    coordinator.is_cronus_device = False
    coordinator.data = {"connected": True, "neo_raw_state": 2}
    coordinator.async_load_data = AsyncMock()
    coordinator.async_config_entry_first_refresh = AsyncMock()
    coordinator.async_shutdown = AsyncMock()
    hass = MagicMock()
    hass.services.has_service.return_value = True
    hass.config_entries.async_forward_entry_setups = AsyncMock()
    entry = MagicMock(data={"address": "AA:BB:CC:DD:EE:FF"})
    monkeypatch.setattr(integration, "VevorHeaterCoordinator", MagicMock(return_value=coordinator))
    monkeypatch.setattr(integration, "_migrate_entity_unique_ids", MagicMock())
    monkeypatch.setattr(integration.bluetooth, "async_ble_device_from_address", MagicMock(return_value=object()))
    assert await integration.async_setup_entry(hass, entry) is True
    hass.config_entries.async_forward_entry_setups.assert_awaited_once()
    coordinator.async_shutdown.assert_not_awaited()


def test_legacy_neo_self_check_has_the_app_defined_step():
    from custom_components.diesel_heater.const import RUNNING_STEP_SELF_TEST
    from tests.test_dz06_neo import FFF2, coordinator_for_layout

    coordinator = coordinator_for_layout(True, name="Sunster Neo")
    frame = bytearray(39)
    frame[:2], frame[3] = b"Z%", 1
    coordinator._notification_callback(FFF2, frame)
    assert coordinator.data["running_step"] == RUNNING_STEP_SELF_TEST
