"""Sunster APK-backed CBFF ventilation and clock-write regressions."""
import asyncio
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from custom_components.diesel_heater.select import VevorHeaterModeSelect
from diesel_heater_ble import ProtocolCBFF
from tests.test_coordinator import create_mock_coordinator
from tests.test_protocol import _make_cbff_data


def status(board=11, mode=1, power=2, level=4):
    frame = _make_cbff_data(run_mode=mode, run_state=power, run_param=level)
    frame[8] = board
    frame[-1] = sum(frame[:-1]) & 255
    return frame


@pytest.mark.parametrize("board", [0, 1, 10, 11, 20, 21, 255])
@pytest.mark.parametrize("encrypted", [False, True])
def test_ventilation_capability_tracks_validated_board(board, encrypted):
    p = ProtocolCBFF()
    frame = status(board)
    if encrypted:
        p.set_device_sn("E466E5BC086D")
        frame = p._encrypt_cbff(frame, "E466E5BC086D")
    parsed = p.parse(frame)
    assert parsed["cbff_mainboard_type"] == board
    h = create_mock_coordinator()
    h._protocol_mode = 6
    h.data.update(parsed)
    assert h.supports_cbff_ventilation == (board in (1, 11, 21))
    options = VevorHeaterModeSelect(h).options
    assert ("Ventilation" in options) == (board in (1, 11, 21))
    if board not in (1, 11, 21):
        with pytest.raises(ValueError):
            p.build_command(2, 3, 1234)


@pytest.mark.parametrize("power", [2, 5, 6])
def test_ventilation_mode_uses_powered_on_command(power):
    p = ProtocolCBFF()
    p.parse(status(power=power))
    packet = p.build_command(2, 3, 1234)
    assert packet[6:12] == bytes((1, 1, 3, 4, 255, 255))


@pytest.mark.parametrize("power,expected", [(1, 0), (2, 1)])
def test_fan_level_does_not_switch_ventilation_to_heating(power, expected):
    p = ProtocolCBFF()
    p.parse(status(mode=3, power=power))
    packet = p.build_command(5, 7, 1234)
    assert packet[6:12] == bytes((1, expected, 3, 7, 255, 255))
    assert p.build_command(3, 1, 1234)[8] == 3
    assert p.build_command(3, 0, 1234)[8] == 3


def test_ventilation_requires_confirmed_capability():
    with pytest.raises(ValueError):
        ProtocolCBFF().build_command(2, 3, 1234)


@pytest.mark.parametrize("encrypted", [False, True])
def test_clock_payload_matches_apk_date_slots_without_mutating_settings(encrypted):
    p = ProtocolCBFF()
    frame = status()
    frame[34:43] = bytes((254, 2, 5, 3, 1, 3, 4, 0, 1))
    frame[-1] = sum(frame[:-1]) & 255
    p.parse(frame)
    snapshot = p._v21_settings
    if encrypted:
        p.set_device_sn("E466E5BC086D")
    packet = p.build_v21_time_sync(datetime(2026, 11, 15, 13, 14))
    if encrypted:
        packet = p._decrypt_cbff(packet, "E466E5BC086D")
    assert packet[8:21] == bytes((0, 0, 26, 131, 234, 11, 15, 0, 1, 3, 4, 0, 1))
    assert p._v21_settings == snapshot
    ordinary = p.build_command(14, 4, 1234)
    if encrypted:
        ordinary = p._decrypt_cbff(ordinary, "E466E5BC086D")
    assert ordinary[10:12] == bytes((0, 0))
    assert ordinary[12:16] == bytes((254, 4, 5, 3))


@pytest.mark.asyncio
@pytest.mark.parametrize("board", [0, 1, 10, 11, 20, 21])
@pytest.mark.parametrize("powered_on", [False, True])
async def test_coordinator_enforces_cbff_capability(board, powered_on):
    h = create_mock_coordinator()
    h._protocol_mode = 6
    h.data["cbff_mainboard_type"] = board
    h.data["running_state"] = int(powered_on)
    h._send_command = AsyncMock(return_value=True)
    h._refresh_after_control_command = AsyncMock()
    result = await h.async_set_mode(3)
    assert result == (powered_on and board in (1, 11, 21))
    if result:
        h._send_command.assert_awaited_once_with(2, 3)
    else:
        h._send_command.assert_not_awaited()


@pytest.mark.parametrize("mode", [1, 2, 3, 4, 5, 7, 8, 9])
def test_cbff_capability_does_not_leak_to_other_protocols(mode):
    h = create_mock_coordinator()
    h._protocol_mode = mode
    h.data["cbff_mainboard_type"] = 11
    assert not h.supports_cbff_ventilation


def settings_controller(language=3, mask=15, apply=True):
    h = create_mock_coordinator()
    p = ProtocolCBFF()
    h._protocol_mode = 6
    h._protocol = p
    h._protocols[6] = p
    h._client = SimpleNamespace(is_connected=True)
    h._characteristic = SimpleNamespace(uuid="0000fff1-0000-1000-8000-00805f9b34fb")
    remote = status()
    remote[35] = language
    remote[38] = 1
    p.parse(status())  # Cached values intentionally differ from the controller.
    h._detect_protocol = lambda data, header: (p, data)
    writes = []

    def deliver(cmd1, cmd2, payload=b""):
        h._notification_callback(0, p._build_feaa(cmd1, cmd2, payload))

    async def write(packet):
        kind = tuple(packet[6:8])
        writes.append(bytes(packet))
        if kind == (0, 3):
            payload = bytearray(16)
            payload[8:10] = mask.to_bytes(2, "little")
            deliver(0x80, 3, payload)
        elif kind == (3, 0):
            deliver(0x83, 0, remote[8:-1])
        elif kind == (3, 1):
            if apply:
                remote[34:43] = packet[12:21]
            deliver(0x83, 1)  # ACK alone does not prove the fields changed.

    h._write_gatt = AsyncMock(side_effect=write)
    return h, p, remote, writes


@pytest.mark.asyncio
async def test_serialized_settings_do_not_restore_old_language():
    h, _, remote, writes = settings_controller()
    with patch("custom_components.diesel_heater.coordinator.asyncio.sleep", AsyncMock()):
        results = await asyncio.gather(h._send_command(14, 4), h._send_command(21, 7))
    assert results == [True, True], ([packet.hex() for packet in writes], h._logger.mock_calls)
    controls = [packet for packet in writes if packet[6:8] == bytes((3, 1))]
    assert len(controls) == 2
    assert [packet[13] for packet in controls] == [4, 4]
    assert remote[35] == 4
    assert remote[38] == 7
    assert h.data["language"] == 4


@pytest.mark.asyncio
async def test_fresh_read_preserves_language_changed_on_controller():
    h, _, _, writes = settings_controller(language=4)
    with patch("custom_components.diesel_heater.coordinator.asyncio.sleep", AsyncMock()):
        assert await h._send_command(21, 7)
    control = next(packet for packet in writes if packet[6:8] == bytes((3, 1)))
    assert control[13] == 4


@pytest.mark.asyncio
async def test_ack_without_applied_language_is_not_success():
    h, _, _, _ = settings_controller(apply=False)
    with patch("custom_components.diesel_heater.coordinator.asyncio.sleep", AsyncMock()):
        assert not await h._send_command(14, 4)
    assert h.data["language"] == 3


@pytest.mark.asyncio
async def test_unsupported_language_never_sends_setting_write():
    h, _, _, writes = settings_controller(mask=1)
    with patch("custom_components.diesel_heater.coordinator.asyncio.sleep", AsyncMock()):
        assert not await h._send_command(14, 4)
    assert all(packet[6:8] != bytes((3, 1)) for packet in writes)


@pytest.mark.parametrize("encrypted", [False, True])
@pytest.mark.parametrize("opcode", [0, 1, 2])
def test_full_attribute_reply_updates_settings_without_becoming_status(encrypted, opcode):
    p = ProtocolCBFF()
    if encrypted:
        p.set_device_sn("E466E5BC086D")
    frame = status()
    frame[35] = 4
    reply = p._build_feaa(0x83, opcode, frame[8:-1])
    if encrypted:
        reply = p._encrypt_cbff(reply, "E466E5BC086D")
    parsed = p.parse_settings_response(reply)
    assert parsed["language"] == 4
    assert "connected" not in parsed
    assert p._v21_settings[5] == 4
    assert p.parse(reply) is None


def test_short_or_corrupt_attribute_reply_cannot_refresh_snapshot():
    p = ProtocolCBFF()
    p.parse(status())
    revision = p.settings_revision
    assert p.parse_settings_response(p._build_feaa(0x83, 1)) is None
    reply = p._build_feaa(0x83, 1, status()[8:-1])
    reply[-1] ^= 1
    assert p.parse_settings_response(reply) is None
    assert p.settings_revision == revision


@pytest.mark.parametrize("encrypted", [False, True])
def test_metadata_language_mask_is_not_a_status_report(encrypted):
    p = ProtocolCBFF()
    payload = bytearray(16)
    payload[8:10] = bytes((9, 0))  # English and German, plus implicit Off.
    packet = p._build_feaa(0x80, 3, payload)
    if encrypted:
        p.set_device_sn("E466E5BC086D")
        packet = p._encrypt_cbff(packet, "E466E5BC086D")
    assert p.parse_metadata_response(packet) == {"cbff_language_mask": 9}
    assert p.parse(packet) is None


@pytest.mark.asyncio
async def test_failed_attribute_read_does_not_write_cached_settings():
    h, _, _, _ = settings_controller()
    h._write_gatt = AsyncMock(side_effect=RuntimeError("Attribute read failed"))
    assert not await h._send_command(21, 7)
    assert h._write_gatt.await_count == 1
    assert h._write_gatt.await_args.args[0][6:8] == bytes((3, 0))


@pytest.mark.asyncio
async def test_unsolicited_status_cannot_complete_attribute_read():
    h, p, _, _ = settings_controller()

    async def write(packet):
        h._notification_callback(0, p._build_feaa(0x80, 0, status()[8:-1]))

    h._write_gatt = AsyncMock(side_effect=write)
    with patch("custom_components.diesel_heater.coordinator.asyncio.sleep", AsyncMock()):
        assert not await h._read_cbff_settings_unlocked()
    assert p.settings_revision > 1
    assert p.attribute_revision == 0



def test_cbff_fan_only_does_not_count_estimated_fuel():
    h = create_mock_coordinator()
    h._protocol_mode = 6
    h.data.update(running_mode=3, running_step=3, set_level=7)
    assert h._calculate_fuel_consumption(60) == 0
    h._update_fuel_tracking(60)
    assert h.data["hourly_fuel_consumption"] == 0



def test_ventilation_uses_confirmed_fan_level_or_apk_default_one():
    p = ProtocolCBFF()
    p.parse(status(mode=0, power=2))
    assert p.build_command(2, 3, 1234)[9] == 1
    p.parse(status(mode=1, level=4))
    p.parse(status(mode=2, level=24))
    assert p.build_command(2, 3, 1234)[9] == 4


@pytest.mark.asyncio
async def test_cbff_metadata_is_reset_before_a_cancelled_reconnect_cleanup():
    h = create_mock_coordinator()
    h._stopping = False
    h._client = None
    h._cbff_metadata_requested = True
    h._cleanup_connection = AsyncMock(side_effect=asyncio.CancelledError)
    with pytest.raises(asyncio.CancelledError):
        await h._ensure_connected()
    assert h._cbff_metadata_requested is False


@pytest.mark.asyncio
async def test_connected_poll_does_not_reset_cbff_metadata():
    h = create_mock_coordinator()
    h._stopping = False
    h._client = SimpleNamespace(is_connected=True)
    h._cbff_metadata_requested = True
    h._cleanup_connection = AsyncMock()
    await h._ensure_connected()
    assert h._cbff_metadata_requested is True
    h._cleanup_connection.assert_not_called()


def test_off_controller_does_not_build_ventilation_selection():
    protocol = ProtocolCBFF()
    protocol.parse(status(power=1))
    with pytest.raises(ValueError, match="powered-on"):
        protocol.build_command(2, 3, 1234)


@pytest.mark.parametrize("subcommand", [0, 1, 2])
@pytest.mark.parametrize("encrypted", [False, True])
def test_cbff_ventilation_reply_updates_running_mode(subcommand, encrypted):
    coordinator = create_mock_coordinator()
    coordinator._protocol_mode = 6
    protocol = coordinator._protocols[6]
    coordinator._protocol = protocol
    coordinator.data["running_mode"] = 1
    frame = status(mode=3)
    frame = protocol._build_feaa(0x81, subcommand, frame[8:-1])
    if encrypted:
        protocol.set_device_sn("E466E5BC086D")
        frame = protocol._encrypt_cbff(frame, "E466E5BC086D")

    coordinator._notification_callback(0, frame)

    assert VevorHeaterModeSelect(coordinator).current_option == "Ventilation"
    assert protocol.matches_response(frame, 2)
    assert not protocol.matches_response(frame, 1)


def test_short_cbff_reply_acknowledges_without_updating_telemetry():
    coordinator = create_mock_coordinator()
    coordinator._protocol_mode = 6
    protocol = coordinator._protocols[6]
    coordinator._protocol = protocol
    coordinator.data["running_mode"] = 1
    frame = protocol._build_feaa(0x81, 1)

    coordinator._notification_callback(0, frame)

    assert coordinator._notification_data == frame
    assert coordinator.data["running_mode"] == 1
    assert protocol.matches_response(frame, 2)
    assert not protocol.matches_response(frame, 1)


def test_invalid_cbff_ventilation_telemetry_does_not_confirm_command():
    protocol = ProtocolCBFF()
    frame = status(mode=3)
    frame[23:25] = bytes((255, 255))
    frame = protocol._build_feaa(0x81, 1, frame[8:-1])
    assert protocol.parse(frame) is None
    assert not protocol.matches_response(frame, 2)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("power", "mode", "step", "expected"),
    [
        (1, 0, 0, "Standby"),
        (1, 2, 0, "Standby"),
        (3, 0, 4, "Cooldown"),
        (2, 2, 4, "Cooldown"),
        (5, 2, 0, "Temperature"),
        (2, 3, 6, "Ventilation"),
    ],
)
async def test_cbff_mode_select_displays_reported_operating_state(power, mode, step, expected):
    frame = status(mode=mode, power=power)
    frame[14] = step
    frame[-1] = sum(frame[:-1]) & 255

    coordinator = create_mock_coordinator()
    coordinator._protocol_mode = 6
    coordinator.data.update(ProtocolCBFF().parse(frame))
    coordinator.async_set_mode = AsyncMock()
    entity = VevorHeaterModeSelect(coordinator)

    assert entity.available
    assert entity.current_option == expected
    assert expected in entity.options
    if expected in ("Standby", "Cooldown"):
        await entity.async_select_option(expected)
        coordinator.async_set_mode.assert_not_awaited()

    coordinator.data["connected"] = False
    assert not entity.available
    assert "Standby" not in entity.options
    assert "Cooldown" not in entity.options


def test_cbff_mode_select_does_not_assume_missing_status_means_standby():
    coordinator = create_mock_coordinator()
    coordinator._protocol_mode = 6
    coordinator.data.update(connected=True, running_state=None, running_mode=None, running_step=None)
    entity = VevorHeaterModeSelect(coordinator)

    assert entity.current_option is None
    assert "Standby" not in entity.options
