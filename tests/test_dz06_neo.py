"""Focused tests for the experimentally supported Sunster Neo transport."""

from types import SimpleNamespace
from unittest.mock import ANY, AsyncMock, MagicMock

import pytest

from custom_components.diesel_heater import coordinator as coordinator_module
from custom_components.diesel_heater.burnoff import BurnoffController
from custom_components.diesel_heater.const import (
    CONF_BURNOFF_ENABLED,
    CONF_NEO_CONTROLLER_TYPE,
    RUNNING_MODE_TEMPERATURE,
    RUNNING_MODE_VENTILATION,
    RUNNING_STATE_ON,
    RUNNING_STEP_COOLDOWN,
    RUNNING_STEP_RUNNING,
    RUNNING_STEP_STANDBY,
    RUNNING_STEP_VENTILATION,
)
from custom_components.diesel_heater.coordinator import VevorHeaterCoordinator

from . import conftest  # noqa: F401

FFF1 = "0000fff1-0000-1000-8000-00805f9b34fb"
FFF2 = "0000fff2-0000-1000-8000-00805f9b34fb"


def neo_config_response(
    minimum: int = 8, maximum: int = 36, device_type: int = 1,
) -> bytearray:
    """Build the full 0x5C/0x16 configuration frame parsed by the Neo app."""
    frame = bytearray(24)
    frame[:2] = bytearray((0x5C, 0x16))
    frame[2] = device_type
    frame[4], frame[5] = minimum, maximum
    return frame


def neo_run_settings_response(
    raw_state: int = 0, run_type: int = 2, target: int = 30, altitude: int = 1500
) -> bytearray:
    """Build the 0xA5 startup response parsed by the Neo app."""
    return bytearray((0xA5, 0x06, 0x00, raw_state, run_type, target)) + altitude.to_bytes(2, "big")


def coordinator_for_layout(
    neo: bool, name: str = "Air Heater"
) -> VevorHeaterCoordinator:
    coordinator = VevorHeaterCoordinator.__new__(VevorHeaterCoordinator)
    coordinator._protocol_mode = 0
    coordinator._ble_device = SimpleNamespace(name=name)
    coordinator._heater_uses_fahrenheit = False
    coordinator._is_abba_device = True
    coordinator._characteristic = SimpleNamespace(uuid=FFF2 if neo else FFF1, properties=["notify"])
    coordinator._abba_write_char = SimpleNamespace(
        uuid=FFF1 if neo else FFF2,
        properties=["write-without-response"] if neo else ["write"],
    )
    coordinator.data = {"connected": False, "running_state": 1}
    coordinator.config_entry = SimpleNamespace(data={})
    coordinator._burnoff = BurnoffController(coordinator)
    coordinator._notification_data = None
    coordinator._neo_run_settings_received = False
    coordinator._neo_password = 100000000
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


def test_warm_drive_uses_controller_type_saved_at_discovery() -> None:
    coordinator = coordinator_for_layout(True, name=None)
    coordinator.config_entry = SimpleNamespace(
        data={CONF_NEO_CONTROLLER_TYPE: "air"}
    )

    assert coordinator.is_warm_drive_controller is True


def test_warm_drive_uses_cached_advertisement_when_live_name_is_missing() -> None:
    coordinator = coordinator_for_layout(True, name=None)
    coordinator.address = "C8:17:F5:28:E7:9D"
    coordinator.hass = MagicMock()
    cached = SimpleNamespace(name="Air Heater")

    with pytest.MonkeyPatch.context() as monkeypatch:
        monkeypatch.setattr(
            coordinator_module.bluetooth,
            "async_last_service_info",
            lambda *_args, **_kwargs: cached,
        )
        assert coordinator.is_warm_drive_controller is True


def test_warm_drive_ignores_a_mac_address_name() -> None:
    coordinator = coordinator_for_layout(True, name="C8:17:F5:28:E7:9D")
    coordinator.address = "C8:17:F5:28:E7:9D"

    assert coordinator.is_warm_drive_controller is False


@pytest.mark.parametrize("raw_state, expected", [(1, 1), (2, 1), (4, 1), (5, 1), (0, 0), (7, 0), (8, 0)])
def test_5a25_maps_only_observed_states(raw_state: int, expected: int) -> None:
    coordinator = coordinator_for_layout(True)
    frame = bytearray(39)
    frame[:2] = b"Z%"
    frame[3], frame[6], frame[15], frame[35] = raw_state, 125, 30, 21
    frame[32:34] = (1500).to_bytes(2, "big")
    frame[34] = 2
    coordinator._notification_callback(FFF2, frame)
    assert coordinator.data["connected"] is True
    assert coordinator.data["supply_voltage"] == 12.5
    assert coordinator.data["set_temp"] == 30.0
    assert coordinator.data["cab_temperature"] == 21.0
    assert coordinator.data["altitude"] == 1500
    assert coordinator.data["neo_run_type"] == 2
    assert coordinator.data["neo_raw_state"] == raw_state
    assert coordinator.data["running_state"] == expected


@pytest.mark.parametrize(
    ("raw_state", "expected_step"),
    [
        (1, None),
        (2, RUNNING_STEP_RUNNING),
        (3, RUNNING_STEP_RUNNING),
        (4, RUNNING_STEP_RUNNING),
        (5, RUNNING_STEP_RUNNING),
        (0, RUNNING_STEP_STANDBY),
        (6, RUNNING_STEP_COOLDOWN),
        (7, RUNNING_STEP_COOLDOWN),
        (8, RUNNING_STEP_COOLDOWN),
    ],
)
def test_5a25_only_maps_evidenced_cooldown_steps(raw_state: int, expected_step: int | None) -> None:
    coordinator = coordinator_for_layout(True)
    frame = bytearray(39)
    frame[:2], frame[3] = b"Z%", raw_state
    coordinator._notification_callback(FFF2, frame)
    assert coordinator.data["running_step"] == expected_step


@pytest.mark.asyncio
async def test_legacy_dz06_uses_configuration_before_status_polling() -> None:
    """The generic split-FFF0 path retains the app-required 5C16 exchange."""
    coordinator = coordinator_for_layout(True, name="Sunster Neo")
    coordinator._write_gatt = AsyncMock(
        side_effect=lambda packet: coordinator._notification_callback(
            FFF2, neo_config_response()
        )
    )

    assert await coordinator._send_dz06_neo_configuration() is True
    assert coordinator.data["neo_min_target"] == 8
    assert coordinator.data["neo_max_target"] == 36
    assert "neo_controller_type" not in coordinator.data


def test_legacy_dz06_keeps_its_own_5a25_layout() -> None:
    """Warm Drive offsets must not be applied to another split-FFF0 controller."""
    coordinator = coordinator_for_layout(True, name="Sunster Neo")
    frame = bytearray(39)
    frame[:2] = b"Z%"
    frame[3], frame[6], frame[15], frame[35] = 160, 125, 30, 21
    frame[32:34] = (1500).to_bytes(2, "big")
    frame[34] = 2

    coordinator._notification_callback(FFF2, frame)

    assert coordinator.data["supply_voltage"] == 12.5
    assert coordinator.data["running_state"] == RUNNING_STATE_ON
    assert coordinator.data["running_step"] == RUNNING_STEP_STANDBY
    assert coordinator.data.get("motor_speed") is None


def test_5a25_parses_warm_drive_status_layout() -> None:
    """Use the exact field layout decoded by Warm Drive."""
    coordinator = coordinator_for_layout(True)
    frame = bytearray(39)
    frame[:2] = b"Z%"
    frame[3] = 2
    frame[4] = 7  # Warm Drive normalizes this wire value to fault code 6.
    frame[5:7] = (300).to_bytes(2, "big")
    frame[7:9] = (2600).to_bytes(2, "big")
    frame[18:20] = (100).to_bytes(2, "big", signed=True)
    frame[20:22] = (65).to_bytes(2, "big", signed=True)
    frame[22:24] = (-5).to_bytes(2, "big", signed=True)
    frame[15] = 24
    frame[16] = 4
    frame[32:34] = (1500).to_bytes(2, "big")
    frame[34] = 2
    frame[35] = 21

    coordinator._notification_callback(FFF2, frame)

    assert coordinator.data["supply_voltage"] == 30.0
    assert coordinator.data["error_code"] == 6
    assert coordinator.data["fire_temperature"] == 100
    assert coordinator.data["motor_speed"] == 2600
    assert coordinator.data["hot_water_temperature"] == 65
    assert coordinator.data["water_temperature"] == -5
    assert coordinator.data["set_level"] == 4
    assert coordinator.data["set_temp"] == 24.0
    assert coordinator.data["cab_temperature"] == 21.0
    assert coordinator.data["altitude"] == 1500


def test_5a25_uses_warm_drive_fahrenheit_display_conversion() -> None:
    coordinator = coordinator_for_layout(True)
    board_info = bytearray(21)
    board_info[0], board_info[17] = 0x5D, 2
    coordinator._notification_callback(FFF2, board_info)
    frame = bytearray(39)
    frame[:2] = b"Z%"
    frame[15] = 20
    frame[18:20] = (100).to_bytes(2, "big", signed=True)
    frame[20:22] = (30).to_bytes(2, "big", signed=True)
    frame[22:24] = (10).to_bytes(2, "big", signed=True)
    frame[35] = 21

    coordinator._notification_callback(FFF2, frame)

    assert coordinator.data["set_temp"] == 68
    assert coordinator.data["fire_temperature"] == 212
    assert coordinator.data["hot_water_temperature"] == 86
    assert coordinator.data["water_temperature"] == 50
    assert coordinator.data["cab_temperature"] == 69


def test_warm_drive_telemetry_clears_after_disconnect() -> None:
    coordinator = coordinator_for_layout(True)
    coordinator.data.update(
        {
            "fire_temperature": 100,
            "hot_water_temperature": 65,
            "water_temperature": 40,
        }
    )

    coordinator._clear_sensor_values()

    assert coordinator.data["fire_temperature"] is None
    assert coordinator.data["hot_water_temperature"] is None
    assert coordinator.data["water_temperature"] is None



@pytest.mark.parametrize(
    ("raw_state", "expected_state", "expected_step"),
    [
        (160, 0, RUNNING_STEP_STANDBY),
        (170, 1, RUNNING_STEP_RUNNING),
        (171, 1, RUNNING_STEP_VENTILATION),
    ],
)
def test_5a25_maps_warm_drive_extended_states(
    raw_state: int, expected_state: int, expected_step: int,
) -> None:
    coordinator = coordinator_for_layout(True)
    frame = bytearray(39)
    frame[:2], frame[3] = b"Z%", raw_state

    coordinator._notification_callback(FFF2, frame)

    assert coordinator.data["running_state"] == expected_state
    assert coordinator.data["running_step"] == expected_step
    if raw_state == 171:
        assert coordinator.data["running_mode"] == RUNNING_MODE_VENTILATION


def test_5a25_unknown_state_preserves_previous_running_state() -> None:
    coordinator = coordinator_for_layout(True)
    frame = bytearray(39)
    frame[:2], frame[3] = b"Z%", 99
    coordinator._notification_callback(FFF2, frame)
    assert coordinator.data["running_state"] == 1


def test_neo_command_packets_match_app_vectors() -> None:
    assert VevorHeaterCoordinator._neo_packet(0x00, 1, 8, 1) == bytearray.fromhex("a50901000108000101fde2")
    assert VevorHeaterCoordinator._neo_packet(0x51, 1, 30, 1) == bytearray.fromhex("a5090151011e00010134eb")
    assert VevorHeaterCoordinator._neo_packet(0x5A, 2, 30, 1500) == bytearray.fromhex("a509015a021e05dc011ee7")
    assert VevorHeaterCoordinator._neo_packet(0x5C, 2, 30, 1500) == bytearray.fromhex("a509015c021e05dc0178e7")


@pytest.mark.asyncio
async def test_status_poll_uses_app_startup_settings() -> None:
    coordinator = coordinator_for_layout(True)
    coordinator._client = SimpleNamespace(is_connected=True)
    response = bytearray(39)
    response[:2] = b"Z%"
    coordinator._write_gatt = AsyncMock(
        side_effect=lambda packet: coordinator._notification_callback(FFF2, response)
    )
    assert await coordinator._send_command(1, 0) is True
    assert coordinator._write_gatt.await_args.args[0] == bytearray.fromhex("a50901000108000101fde2")


@pytest.mark.asyncio
async def test_unsupported_neo_command_fails_closed() -> None:
    coordinator = coordinator_for_layout(True)
    coordinator._client = SimpleNamespace(is_connected=True)
    coordinator._write_gatt = AsyncMock()
    assert await coordinator._send_command(18, 1) is False
    coordinator._write_gatt.assert_not_awaited()


@pytest.mark.asyncio
async def test_startup_run_settings_matches_app_sequence() -> None:
    coordinator = coordinator_for_layout(True)
    coordinator._write_gatt = AsyncMock(
        side_effect=lambda packet: coordinator._notification_callback(
            FFF2, neo_run_settings_response()
        )
    )
    assert await coordinator._send_dz06_neo_run_settings() is True
    packet = coordinator._write_gatt.await_args.args[0]
    assert packet[:4] == bytearray.fromhex("290dff00")
    assert packet[8:13] == bytearray.fromhex("0000000001")
    assert coordinator.data["neo_run_type"] == 2
    assert coordinator.data["set_temp"] == 30.0
    assert coordinator.data["altitude"] == 1500


@pytest.mark.asyncio
async def test_startup_run_settings_does_not_include_a_password() -> None:
    coordinator = coordinator_for_layout(True)
    coordinator._neo_password = 12345678
    coordinator._write_gatt = AsyncMock(
        side_effect=lambda packet: coordinator._notification_callback(
            FFF2, neo_run_settings_response()
        )
    )
    assert await coordinator._send_dz06_neo_run_settings() is True
    assert coordinator._write_gatt.await_args.args[0][8:12] == bytearray.fromhex("00000000")


@pytest.mark.asyncio
async def test_startup_run_settings_requires_an_a5_response(monkeypatch: pytest.MonkeyPatch) -> None:
    coordinator = coordinator_for_layout(True)
    coordinator._write_gatt = AsyncMock(
        side_effect=lambda packet: coordinator._notification_callback(
            FFF2, bytearray.fromhex("5c16")
        )
    )
    clock = iter((0, 11))
    fake_time = SimpleNamespace(monotonic=lambda: next(clock, 11.0))
    monkeypatch.setattr(coordinator_module, "time", fake_time)
    assert await coordinator._send_dz06_neo_run_settings() is False


@pytest.mark.asyncio
async def test_power_requires_confirmed_5a25() -> None:
    coordinator = coordinator_for_layout(True)
    coordinator.data.update({"set_temp": 30, "neo_run_type": 1, "altitude": 1, "neo_raw_state": 1})
    response = bytearray(39)
    response[:2] = b"Z%"
    response[3] = 1
    coordinator._write_gatt = AsyncMock(side_effect=lambda packet: coordinator._notification_callback(FFF2, response))
    assert await coordinator._send_dz06_neo_power(True) is True
    assert coordinator._write_gatt.await_args.args[0] == bytearray.fromhex("a509015a011e0001014fea")


@pytest.mark.asyncio
async def test_power_rejects_5a25_that_reports_the_wrong_state() -> None:
    coordinator = coordinator_for_layout(True)
    coordinator.data.update({"set_temp": 30, "neo_run_type": 1, "altitude": 1, "neo_raw_state": 1})
    response = bytearray(39)
    response[:2] = b"Z%"
    coordinator._write_gatt = AsyncMock(
        side_effect=lambda packet: coordinator._notification_callback(FFF2, response)
    )
    assert await coordinator._send_dz06_neo_power(True) is False


@pytest.mark.asyncio
async def test_neo_power_preserves_reported_mode_and_altitude() -> None:
    coordinator = coordinator_for_layout(True)
    coordinator.data.update({"set_temp": 30, "neo_run_type": 2, "altitude": 1500, "neo_raw_state": 1})
    response = bytearray(39)
    response[:2], response[3] = b"Z%", 1
    coordinator._write_gatt = AsyncMock(
        side_effect=lambda packet: coordinator._notification_callback(FFF2, response)
    )
    assert await coordinator._send_dz06_neo_power(True) is True
    assert coordinator._write_gatt.await_args.args[0] == bytearray.fromhex("a509015a021e05dc011ee7")


@pytest.mark.asyncio
async def test_power_missing_target_fails_without_writing() -> None:
    coordinator = coordinator_for_layout(True)
    coordinator._write_gatt = AsyncMock()
    assert await coordinator._send_dz06_neo_power(False) is False
    coordinator._write_gatt.assert_not_awaited()


@pytest.mark.asyncio
async def test_temperature_requires_matching_5a25_target() -> None:
    coordinator = coordinator_for_layout(True)
    coordinator.data.update({"set_temp": 30, "neo_run_type": 1, "altitude": 1, "neo_raw_state": 1})
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


@pytest.mark.asyncio
async def test_power_before_first_status_fails_closed_with_warning() -> None:
    coordinator = coordinator_for_layout(True)
    coordinator.data.update({"set_temp": 30, "neo_run_type": 1, "altitude": 1})
    coordinator._write_gatt = AsyncMock()

    assert await coordinator._send_dz06_neo_power(True) is False
    coordinator._write_gatt.assert_not_awaited()
    coordinator._logger.warning.assert_called_once_with(
        "DZ06 Neo control blocked until first 5A25 status frame"
    )


@pytest.mark.asyncio
async def test_power_write_failure_is_logged() -> None:
    coordinator = coordinator_for_layout(True)
    coordinator.data.update(
        {"set_temp": 30, "neo_run_type": 1, "altitude": 1, "neo_raw_state": 1}
    )
    coordinator._write_gatt = AsyncMock(side_effect=RuntimeError("write failed"))

    assert await coordinator._send_dz06_neo_power(True) is False
    coordinator._logger.warning.assert_called_once_with(
        "DZ06 Neo power write failed: %s", ANY
    )


@pytest.mark.asyncio
async def test_temperature_write_failure_is_logged() -> None:
    coordinator = coordinator_for_layout(True)
    coordinator.data.update(
        {"set_temp": 30, "neo_run_type": 1, "altitude": 1, "neo_raw_state": 1}
    )
    coordinator._write_gatt = AsyncMock(side_effect=RuntimeError("write failed"))

    await coordinator.async_set_temperature(30)

    coordinator._logger.warning.assert_called_once_with(
        "DZ06 Neo control write failed: %s", ANY
    )
    coordinator.async_request_refresh.assert_not_awaited()


def test_bluetooth_config_response_sets_neo_target_range() -> None:
    coordinator = coordinator_for_layout(True)
    coordinator._notification_callback(FFF2, neo_config_response())
    assert coordinator.data["neo_min_target"] == 8
    assert coordinator.data["neo_max_target"] == 36


@pytest.mark.parametrize(("device_type", "expected"), [(1, "air"), (2, "water")])
def test_bluetooth_config_response_sets_warm_drive_controller_type(
    device_type: int, expected: str,
) -> None:
    coordinator = coordinator_for_layout(True)
    coordinator._notification_callback(
        FFF2, neo_config_response(device_type=device_type)
    )
    assert coordinator.data["neo_controller_type"] == expected


def test_board_info_response_sets_warm_drive_temperature_unit() -> None:
    coordinator = coordinator_for_layout(True)
    frame = bytearray(21)
    frame[0] = 0x5D
    frame[17] = 2
    coordinator._notification_callback(FFF2, frame)
    assert coordinator._heater_uses_fahrenheit is True


@pytest.mark.asyncio
async def test_board_info_request_uses_warm_drive_command() -> None:
    coordinator = coordinator_for_layout(True)
    response = bytearray(21)
    response[0] = 0x5D
    response[17] = 1
    coordinator._write_gatt = AsyncMock(
        side_effect=lambda packet: coordinator._notification_callback(FFF2, response)
    )

    await coordinator._send_dz06_neo_board_info()

    packet = coordinator._write_gatt.await_args.args[0]
    assert packet[:4] == bytearray((0x29, 0x0D, 0x5D, 0))
    assert coordinator._heater_uses_fahrenheit is False


@pytest.mark.asyncio
async def test_max_power_control_uses_the_app_packet_and_configured_limit() -> None:
    coordinator = coordinator_for_layout(True)
    coordinator.data.update(
        {
            "neo_min_target": 8,
            "neo_max_target": 36,
            "neo_raw_state": 1,
            "set_temp": 22,
            "altitude": 1500,
        }
    )
    response = bytearray(39)
    response[:2], response[3], response[15], response[34] = b"Z%", 1, 36, 1
    coordinator._write_gatt = AsyncMock(
        side_effect=lambda packet: coordinator._notification_callback(FFF2, response)
    )

    assert await coordinator._async_set_dz06_neo_control(1, 36, 1500) is True
    assert coordinator._write_gatt.await_args.args[0] == bytearray.fromhex(
        "a5090151012405dc01bdae"
    )


@pytest.mark.asyncio
async def test_burnoff_shutdown_uses_neo_app_power_off_packet() -> None:
    coordinator = coordinator_for_layout(True)
    coordinator.data.update(
        {
            "neo_min_target": 8,
            "neo_max_target": 36,
            "neo_raw_state": 1,
            "neo_run_type": 1,
            "set_temp": 30,
            "altitude": 1,
        }
    )
    response = bytearray(39)
    response[:2], response[3] = b"Z%", 0
    coordinator._write_gatt = AsyncMock(
        side_effect=lambda packet: coordinator._notification_callback(FFF2, response)
    )

    await coordinator._power_off()
    assert coordinator._write_gatt.await_args.args[0] == bytearray.fromhex(
        "a509015c011e00010129ea"
    )


@pytest.mark.asyncio
async def test_ha_neo_power_off_does_not_create_pending_burnoff() -> None:
    coordinator = coordinator_for_layout(True)
    coordinator.config_entry = SimpleNamespace(data={CONF_BURNOFF_ENABLED: True})
    coordinator.data.update(
        {
            "running_state": RUNNING_STATE_ON,
            "running_step": RUNNING_STEP_RUNNING,
            "running_mode": RUNNING_MODE_TEMPERATURE,
        }
    )
    coordinator._burnoff.observe_status()
    coordinator._send_dz06_neo_power = AsyncMock(return_value=True)

    await coordinator._power_off()

    response = bytearray(39)
    response[:2], response[3], response[34] = b"Z%", 0, 2
    coordinator._notification_callback(FFF2, response)

    assert coordinator.burnoff_pending is False
    assert coordinator._burnoff.ha_power_off is False


@pytest.mark.asyncio
async def test_neo_temperature_write_accepts_stored_none_limits() -> None:
    coordinator = coordinator_for_layout(True)
    coordinator.data.update(
        {
            "neo_min_target": None,
            "neo_max_target": None,
            "neo_raw_state": 2,
            "neo_run_type": 2,
            "set_temp": 22,
            "altitude": 1500,
        }
    )
    response = bytearray(39)
    response[:2], response[15], response[34] = b"Z%", 30, 2
    coordinator._write_gatt = AsyncMock(
        side_effect=lambda packet: coordinator._notification_callback(FFF2, response)
    )

    assert await coordinator.async_set_temperature(30) is True
    assert coordinator._write_gatt.await_args.args[0] == bytearray.fromhex(
        "a5090151021e05dc0165e6"
    )


def test_neo_control_settings_converts_fahrenheit_display_target() -> None:
    coordinator = coordinator_for_layout(True)
    coordinator._heater_uses_fahrenheit = True
    coordinator.data.update(
        {
            "neo_min_target": 8,
            "neo_max_target": 36,
            "neo_raw_state": 2,
            "neo_run_type": 2,
            "set_temp": 68,
            "altitude": 1500,
        }
    )

    assert coordinator._neo_control_settings() == (2, 20, 1500)


@pytest.mark.asyncio
async def test_neo_power_off_failure_clears_ha_shutdown_intent() -> None:
    coordinator = coordinator_for_layout(True)
    coordinator._send_dz06_neo_power = AsyncMock(return_value=False)

    await coordinator._power_off()

    assert coordinator._burnoff.ha_power_off is False
    coordinator.async_request_refresh.assert_not_awaited()


@pytest.mark.asyncio
async def test_neo_burnoff_requires_a_complete_restorable_snapshot() -> None:
    coordinator = coordinator_for_layout(True)
    coordinator._burnoff.cycle.saved_protocol_state = {"neo_altitude": 1500}
    coordinator._write_gatt = AsyncMock()

    assert await coordinator.async_apply_burnoff_max_power(coordinator._burnoff.cycle) is False
    coordinator._write_gatt.assert_not_awaited()


def test_neo_burnoff_snapshot_captures_the_configured_upper_limit() -> None:
    coordinator = coordinator_for_layout(True)
    coordinator.data.update(
        {
            "neo_raw_state": 2,
            "neo_run_type": 2,
            "set_temp": 22,
            "altitude": 1500,
            "neo_min_target": 8,
            "neo_max_target": 35,
        }
    )

    assert coordinator.burnoff_protocol_snapshot()["neo_max_target"] == 35
