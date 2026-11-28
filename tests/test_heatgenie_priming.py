"""HeatGenie APK-backed timed fuel-priming control and guard regressions."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from custom_components.diesel_heater.button import VevorFuelPrimingButton, async_setup_entry
from diesel_heater_ble import ProtocolHeatGenie

from .test_coordinator import create_mock_coordinator


def heater():
    coordinator = create_mock_coordinator()
    coordinator._protocol_mode = 8
    coordinator._protocol = ProtocolHeatGenie()
    coordinator._is_heatgenie_device = True
    coordinator._client = SimpleNamespace(is_connected=True)
    return coordinator


def report(coordinator, state=5, *, flags=0, seconds=0, fault=0):
    frame = bytearray(50)
    frame[0], frame[1], frame[7], frame[8], frame[9] = 0xAA, 9, 0xF2, state, flags
    frame[20:22] = seconds.to_bytes(2, "little")
    frame[28:30] = fault.to_bytes(2, "little")
    frame[-2:] = ProtocolHeatGenie.crc16(frame[:-2]).to_bytes(2, "big")
    coordinator._notification_callback(0, frame)


def feedback(coordinator, initial, subsequent):
    writes = []

    async def next_report(_timeout):
        # First report is the fresh precondition. Subsequent reports come
        # from the mocked GATT writer, exactly as notifications do.
        if not writes:
            report(coordinator, **initial)
            return True
        return False

    async def write(frame):
        writes.append(bytes(frame))
        if len(writes) <= len(subsequent):
            report(coordinator, **subsequent[len(writes) - 1])

    coordinator._wait_for_heatgenie_status = AsyncMock(side_effect=next_report)
    coordinator._write_gatt = AsyncMock(side_effect=write)
    return writes


def test_wire_packets_match_heatgenie_app_fields_and_crc():
    protocol = ProtocolHeatGenie()
    for frame, command, argument in (
        (protocol.build_fuel_priming_setup(), 0x62, 20),
        (protocol.build_fuel_priming_button(start=True), 0x61, 11),
        (protocol.build_fuel_priming_button(start=False), 0x61, 12),
    ):
        assert frame[:4] == bytes((0xAA, 0, command, argument))
        assert frame[5] == 0
        assert protocol.crc16(frame) == 0


@pytest.mark.asyncio
async def test_start_requires_duration_readback_and_pump_active():
    coordinator = heater()
    writes = feedback(coordinator, {}, [{"state": 7, "seconds": 20}, {"state": 7, "flags": 1, "seconds": 19}])
    assert await coordinator.async_set_fuel_priming(start=True)
    assert [packet[2:4] for packet in writes] == [b"b\x14", b"a\x0b"]
    assert coordinator.data["heatgenie_priming_remaining"] == 19
    assert not coordinator.fuel_priming_ready
    assert coordinator.fuel_priming_mode


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "reported",
    [
        {"state": 1},
        {"state": 4},
        {"state": 7},
        {"state": 8},
        {"fault": 1},
        {"flags": 1},
        {"flags": 4},
        {"flags": 8},
        {"flags": 0x40},
    ],
)
async def test_start_rejects_non_standby_faults_and_active_components(reported):
    coordinator = heater()
    report(coordinator)  # Cached standby must not authorize a write.
    writes = feedback(coordinator, reported, [])
    assert not await coordinator.async_set_fuel_priming(start=True)
    assert not writes


@pytest.mark.asyncio
@pytest.mark.parametrize("prep", [{"state": 7, "seconds": 120}, {"state": 7, "seconds": 0}, {}])
async def test_start_never_sends_pump_command_without_bounded_cutoff(prep):
    coordinator = heater()
    writes = feedback(coordinator, {}, [prep])
    assert not await coordinator.async_set_fuel_priming(start=True)
    assert len(writes) == 1
    assert writes[0][2:4] == b"b\x14"


@pytest.mark.asyncio
async def test_unconfirmed_start_does_not_retry():
    coordinator = heater()
    writes = feedback(coordinator, {}, [{"state": 7, "seconds": 20}])
    assert not await coordinator.async_set_fuel_priming(start=True)
    assert len(writes) == 2


@pytest.mark.asyncio
@pytest.mark.parametrize("power_off", [False, True])
async def test_stop_confirms_pump_inactive_then_exits_manual_mode(power_off):
    coordinator = heater()
    writes = feedback(coordinator, {"state": 7, "flags": 1, "seconds": 15}, [{"state": 7}, {}])
    if power_off:
        report(coordinator, state=7, flags=1, seconds=16)
        assert await coordinator._power_off()
    else:
        assert await coordinator.async_set_fuel_priming(start=False)
    assert [packet[2:4] for packet in writes] == [b"a\x0c", b"a\x02"]
    assert coordinator.data["heatgenie_priming_remaining"] is None


@pytest.mark.asyncio
async def test_stale_or_disconnected_report_cannot_start_priming():
    coordinator = heater()
    report(coordinator)
    coordinator._wait_for_heatgenie_status = AsyncMock(return_value=False)
    coordinator._write_gatt = AsyncMock()
    assert not await coordinator.async_set_fuel_priming(start=True)
    coordinator._client.is_connected = False
    assert not await coordinator.async_set_fuel_priming(start=True)
    coordinator._write_gatt.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize(("command", "argument"), [(3, 1), (3, 2), (3, -1), (2, 1)])
async def test_priming_blocks_regular_heat_and_mode_commands(command, argument):
    coordinator = heater()
    report(coordinator, state=7, flags=1, seconds=19)
    coordinator._write_gatt = AsyncMock()
    assert not await coordinator._send_heatgenie_command(command, argument, 5)
    coordinator._write_gatt.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", range(10))
async def test_only_heatgenie_has_priming_buttons(mode):
    coordinator = heater()
    coordinator._protocol_mode = mode
    report(coordinator)
    coordinator._protocol_mode = mode
    added = MagicMock()
    await async_setup_entry(MagicMock(), SimpleNamespace(runtime_data=coordinator), added)
    buttons = [
        entity for call in added.call_args_list for entity in call.args[0] if isinstance(entity, VevorFuelPrimingButton)
    ]
    assert len(buttons) == (2 if mode == 8 else 0)
    if mode == 8:
        assert buttons[0].available
        assert not buttons[1].available
