"""Focused tests for the experimentally supported Sunster Neo transport."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from . import conftest  # noqa: F401
from custom_components.diesel_heater import coordinator as coordinator_module
from custom_components.diesel_heater.coordinator import VevorHeaterCoordinator

FFF1 = "0000fff1-0000-1000-8000-00805f9b34fb"
FFF2 = "0000fff2-0000-1000-8000-00805f9b34fb"


def coordinator_for_layout(neo: bool) -> VevorHeaterCoordinator:
    coordinator = VevorHeaterCoordinator.__new__(VevorHeaterCoordinator)
    coordinator._protocol_mode = 0
    coordinator._heater_uses_fahrenheit = False
    coordinator._is_abba_device = True
    coordinator._characteristic = SimpleNamespace(uuid=FFF2 if neo else FFF1, properties=["notify"])
    coordinator._abba_write_char = SimpleNamespace(
        uuid=FFF1 if neo else FFF2,
        properties=["write-without-response"] if neo else ["write"],
    )
    coordinator.data = {"connected": False, "running_state": 1}
    coordinator._notification_data = None
    coordinator._logger = MagicMock()
    coordinator.async_request_refresh = AsyncMock()
    return coordinator


def test_split_fff0_layout_is_detected_narrowly() -> None:
    assert coordinator_for_layout(True).is_dz06_neo is True
    assert coordinator_for_layout(False).is_dz06_neo is False


def test_direction_associates_writes_with_fff1_and_notifications_with_fff2() -> None:
    coordinator = coordinator_for_layout(True)
    assert coordinator._abba_write_char.uuid == FFF1
    assert coordinator._characteristic.uuid == FFF2


@pytest.mark.parametrize("raw_state, expected", [(1, 1), (2, 1), (4, 1), (5, 1), (0, 0), (7, 0), (8, 0)])
def test_5a25_maps_only_observed_states(raw_state: int, expected: int) -> None:
    coordinator = coordinator_for_layout(True)
    frame = bytearray(39)
    frame[:2] = b"Z%"
    frame[3], frame[6], frame[15], frame[35] = raw_state, 125, 30, 21
    coordinator._notification_callback(FFF2, frame)
    assert coordinator.data["connected"] is True
    assert coordinator.data["supply_voltage"] == 12.5
    assert coordinator.data["set_temp"] == 30.0
    assert coordinator.data["cab_temperature"] == 21.0
    assert coordinator.data["neo_raw_state"] == raw_state
    assert coordinator.data["running_state"] == expected


def test_5a25_unknown_state_preserves_previous_running_state() -> None:
    coordinator = coordinator_for_layout(True)
    frame = bytearray(39)
    frame[:2], frame[3] = b"Z%", 99
    coordinator._notification_callback(FFF2, frame)
    assert coordinator.data["running_state"] == 1


def test_neo_command_packets_match_captured_30c_vectors() -> None:
    assert VevorHeaterCoordinator._neo_packet(0x51, 30) == bytearray.fromhex("a5090151021e000001a4ae")
    assert VevorHeaterCoordinator._neo_packet(0x5A, 30) == bytearray.fromhex("a509015a021e000001dfaf")
    assert VevorHeaterCoordinator._neo_packet(0x5C, 30) == bytearray.fromhex("a509015c021e000001b9af")


@pytest.mark.asyncio
async def test_unsupported_neo_command_fails_closed() -> None:
    coordinator = coordinator_for_layout(True)
    coordinator._client = SimpleNamespace(is_connected=True)
    coordinator._write_gatt = AsyncMock()
    assert await coordinator._send_command(18, 1) is False
    coordinator._write_gatt.assert_not_awaited()


@pytest.mark.asyncio
async def test_auth_succeeds_only_after_5c16() -> None:
    coordinator = coordinator_for_layout(True)
    coordinator._write_gatt = AsyncMock(
        side_effect=lambda packet: coordinator._notification_callback(
            FFF2, bytearray.fromhex("5c16")
        )
    )
    assert await coordinator._send_dz06_neo_auth() is True


@pytest.mark.asyncio
async def test_auth_without_5c16_fails_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    coordinator = coordinator_for_layout(True)
    coordinator._write_gatt = AsyncMock()
    clock = iter((0, 11))
    fake_time = SimpleNamespace(monotonic=lambda: next(clock, 11.0))
    monkeypatch.setattr(coordinator_module, "time", fake_time)
    assert await coordinator._send_dz06_neo_auth() is False


@pytest.mark.asyncio
async def test_power_requires_confirmed_5a25() -> None:
    coordinator = coordinator_for_layout(True)
    coordinator.data["set_temp"] = 30
    response = bytearray(39)
    response[:2] = b"Z%"
    coordinator._write_gatt = AsyncMock(side_effect=lambda packet: coordinator._notification_callback(FFF2, response))
    assert await coordinator._send_dz06_neo_power(True) is True
    assert coordinator._write_gatt.await_args.args[0] == bytearray.fromhex("a509015a021e000001dfaf")


@pytest.mark.asyncio
async def test_power_missing_target_fails_without_writing() -> None:
    coordinator = coordinator_for_layout(True)
    coordinator._write_gatt = AsyncMock()
    assert await coordinator._send_dz06_neo_power(False) is False
    coordinator._write_gatt.assert_not_awaited()


@pytest.mark.asyncio
async def test_temperature_requires_matching_5a25_target() -> None:
    coordinator = coordinator_for_layout(True)
    response = bytearray(39)
    response[:2] = b"Z%"
    response[15] = 29
    coordinator._write_gatt = AsyncMock(side_effect=lambda packet: coordinator._notification_callback(FFF2, response))
    clock = iter((0, 4))
    monkeypatch = pytest.MonkeyPatch()
    fake_time = SimpleNamespace(monotonic=lambda: next(clock, 4.0))
    monkeypatch.setattr(coordinator_module, "time", fake_time)
    try:
        await coordinator.async_set_temperature(30)
    finally:
        monkeypatch.undo()
    assert coordinator.async_request_refresh.await_count == 0


def test_arbitrary_neo_notification_does_not_connect() -> None:
    coordinator = coordinator_for_layout(True)
    coordinator._notification_callback(FFF2, bytearray.fromhex("5c16"))
    assert coordinator.data["connected"] is False
