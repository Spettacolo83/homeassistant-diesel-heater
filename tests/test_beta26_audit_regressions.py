"""Regression coverage for failures reproduced on beta.26."""

import asyncio
import time
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, call

from custom_components.diesel_heater.burnoff import BurnoffPhase
from custom_components.diesel_heater.const import RUNNING_MODE_LEVEL
from diesel_heater_ble import ProtocolCBFF, ProtocolCronus, ProtocolHcalory

from .test_audit_repairs import heatgenie_status
from .test_cbff_ventilation_clock import status
from .test_coordinator import _set_heating, create_mock_coordinator
from .test_dz06_neo import FFF2, _warm_drive_status, coordinator_for_layout, neo_config_response
from .test_protocol import _make_aa55_data


async def test_burnoff_refuses_maximum_power_if_snapshot_cannot_be_saved():
    host = create_mock_coordinator()
    _set_heating(host)
    host.async_save_data = AsyncMock(return_value=False)
    host.async_apply_burnoff_max_power = AsyncMock(return_value=True)

    await host._burnoff.start()

    host.async_save_data.assert_awaited_once()
    host.async_apply_burnoff_max_power.assert_not_awaited()
    assert not host.burnoff_active


async def test_cancelled_burnoff_discards_queued_maximum_power():
    host = create_mock_coordinator()
    _set_heating(host)
    host.data["running_mode"] = RUNNING_MODE_LEVEL
    burnoff = host._burnoff
    burnoff.cycle.phase = BurnoffPhase.AWAITING_STATUS
    burnoff.cycle.ends_at = datetime.now(UTC) + timedelta(minutes=2)
    queued = []
    burnoff._create_task = queued.append
    host.async_apply_burnoff_max_power = AsyncMock(return_value=True)

    burnoff.schedule_abort_if_ecu_stopped()
    await burnoff.cancel(restore=True)
    await queued.pop()

    host.async_apply_burnoff_max_power.assert_not_awaited()
    assert not burnoff.active


async def test_failed_final_off_is_persisted_and_retried():
    host = create_mock_coordinator()
    _set_heating(host)
    burnoff = host._burnoff
    burnoff.cycle.phase = BurnoffPhase.RUNNING
    burnoff.cycle.shutdown_after = True
    burnoff.cycle.saved_mode = RUNNING_MODE_LEVEL
    burnoff.restore_saved_mode = AsyncMock(return_value=True)
    host._power_off = AsyncMock(side_effect=[False, True])

    await burnoff.complete()
    payload = burnoff.storage_payload()
    assert payload["shutdown_after"] is True
    assert payload["saved_mode"] is None
    assert burnoff.cycle.phase == BurnoffPhase.RESTORING

    await burnoff.try_snapshot_write()

    assert host._power_off.await_count == 2
    assert not burnoff.active


async def test_concurrent_abba_off_reads_state_and_toggles_only_once():
    host = create_mock_coordinator()
    host._protocol_mode = 5
    _set_heating(host)

    async def reply(command, argument):
        await asyncio.sleep(0)
        if (command, argument) == (3, 0):
            host.data.update(running_state=0, running_step=4)
        if command == 1:
            raw_state = 1 if host.data["running_state"] else 2
            host._notification_data = bytearray((0xAB, 0xBA, 0x11, 0xCC, raw_state))
        return True

    host._send_command_unlocked = AsyncMock(side_effect=reply)

    await asyncio.gather(host.async_turn_off(immediate=True), host.async_turn_off(immediate=True))

    assert host._send_command_unlocked.await_args_list == [call(1, 0), call(3, 0), call(1, 0)]


async def test_aa_concurrent_targets_do_not_both_succeed_on_one_echo():
    host = create_mock_coordinator()
    host._protocol_mode = 1
    host._protocol = host._protocols[1]
    host._client = MagicMock(is_connected=True)
    host._characteristic = MagicMock()

    async def reply_to_second(packet):
        if packet[5] == 25:
            reply = _make_aa55_data(running_mode=2, byte9=25)
            reply[2] = 4
            host._notification_callback(0, reply)

    host._write_gatt = AsyncMock(side_effect=reply_to_second)
    results = await asyncio.gather(
        host._send_command(4, 22, timeout=0.1),
        host._send_command(4, 25, timeout=0.1),
    )
    assert results == [False, True]


async def test_warm_drive_settings_write_keeps_other_concurrent_change():
    host = coordinator_for_layout(True)
    host._client = MagicMock(is_connected=True)
    config = neo_config_response()
    host._notification_callback(FFF2, config)

    async def write(packet):
        await asyncio.sleep(0)
        config[2:17] = packet[2:17]

    async def read():
        await asyncio.sleep(0)
        host._notification_callback(FFF2, config.copy())
        return True

    host._write_gatt = AsyncMock(side_effect=write)
    host._send_dz06_neo_configuration = AsyncMock(side_effect=read)
    results = await asyncio.gather(
        host._async_write_warm_drive_config({15: 1}, {}, "Tank"),
        host._async_write_warm_drive_config({16: 2}, {}, "Pump"),
    )

    assert results == [True, True]
    assert config[15:17] == bytes((1, 2))


def test_neo_keeps_native_fields_for_poll_after_telemetry_is_cleared():
    host = coordinator_for_layout(True)
    host._notification_callback(FFF2, _warm_drive_status(1, 20, 15))
    expected = host._neo_status_poll_settings()

    host._clear_sensor_values()

    assert expected is not None and host._neo_status_poll_settings() == expected


def test_cbff_bare_ack_cannot_confirm_ventilation_and_short_frame_has_no_runtime():
    protocol = ProtocolCBFF()
    assert not protocol.reports_ventilation(protocol._build_feaa(0x81, 1))
    short = protocol._build_feaa(0x81, 1, status(mode=3)[8:-2])
    assert "remain_run_time" not in protocol.parse(short)
    full = protocol._build_feaa(0x81, 1, status(mode=3)[8:-1])
    assert protocol.reports_ventilation(full)


def test_cronus_rejects_connected_snapshot_with_empty_required_records():
    assert ProtocolCronus().parse_records(
        {"h1_available": b"\x02", "air_state": b"", "air_state_real": b"", "air_mode": b""}
    ) is None


async def test_cronus_failed_required_record_counts_failure_and_reconnects():
    host = create_mock_coordinator()
    host._is_cronus_device = True
    host._client = MagicMock(is_connected=True)
    host._async_read_cronus_record = AsyncMock(return_value=False)
    host._cleanup_connection = AsyncMock()
    host._check_daily_reset = AsyncMock()
    host._check_daily_runtime_reset = AsyncMock()

    await host._async_update_data()

    assert host._consecutive_failures == 1
    host._cleanup_connection.assert_awaited_once()


def test_discarded_heatgenie_report_does_not_extend_freshness_window():
    host = create_mock_coordinator()
    host._protocol_mode = 8
    host._is_heatgenie_device = True
    host._heatgenie_pending_button = (2, 0xAE)
    host._heatgenie_last_status_at = 0

    host._notification_callback(0, heatgenie_status(unit=0))

    assert host._heatgenie_last_status_at == 0
    assert not host._heatgenie_status_event.is_set()


async def test_heatgenie_clock_write_does_not_wait_for_unrelated_telemetry():
    host = create_mock_coordinator()
    host._protocol_mode = 8
    host._protocol = host._protocols[8]
    host._write_gatt = AsyncMock()
    host._wait_for_heatgenie_status = AsyncMock(return_value=False)

    assert await host._send_heatgenie_command(10, 0, 5)
    host._write_gatt.assert_awaited_once()
    host._wait_for_heatgenie_status.assert_not_awaited()


async def test_hcalory_does_not_replay_unacknowledged_toggle():
    host = create_mock_coordinator()
    host._protocol_mode = 7
    host._protocol = ProtocolHcalory()
    host._protocol.set_mvp_version(True)
    host._protocol.mark_password_sent()
    host._client = MagicMock(is_connected=True)
    host._characteristic = MagicMock()
    host._write_gatt = AsyncMock()

    assert not await host._send_command(18, 1)

    assert [args.args[0][7:9] for args in host._write_gatt.await_args_list] == [b"\x0e\x04", b"\x0a\x0a"]


def test_tracking_does_not_backfill_unobserved_hour():
    host = create_mock_coordinator()
    host._last_update_time = time.monotonic() - 3600
    assert host._tracking_elapsed() == host.update_interval.total_seconds()
    host._handle_connection_failure(RuntimeError("offline"))
    assert host._tracking_elapsed() == 0




async def test_auto_offset_clears_existing_correction_when_sensors_agree():
    host = create_mock_coordinator()
    host._protocol_mode = 2
    host.config_entry.data = {"external_temp_sensor": "sensor.reference"}
    host.hass.states.get.return_value.state = "20"
    host.hass.states.get.return_value.attributes = {"unit_of_measurement": "°C"}
    host.data.update(auto_offset_enabled=True, cab_temperature=24, cab_temperature_raw=20)
    host._current_heater_offset = 4
    host._last_auto_offset_time = 0
    host.async_set_heater_offset = AsyncMock()

    await host._async_calculate_auto_offset()

    host.async_set_heater_offset.assert_awaited_once_with(0)


async def test_hcalory_followup_ceases_to_use_host_timezone(monkeypatch):
    from datetime import timezone

    from custom_components.diesel_heater import coordinator as coordinator_module

    host = create_mock_coordinator()
    host._protocol_mode = 7
    host._protocol = ProtocolHcalory()
    host._protocol.set_mvp_version(True)
    host._protocol.mark_password_sent()
    host._client = MagicMock(is_connected=True)
    host._characteristic = MagicMock()
    local_time = datetime(2026, 11, 25, 9, 15, 12, tzinfo=timezone(timedelta(hours=-3, minutes=-30)))
    monkeypatch.setattr(coordinator_module.dt_util, "now", lambda: local_time)

    async def reply(packet):
        if packet[7:9] == b"\x0a\x0a":
            host._notification_data = bytearray(b"status")

    host._write_gatt = AsyncMock(side_effect=reply)
    for bd39 in (True, False):
        host._protocol.set_transport(bd39=bd39)
        expected = host._build_command_packet(1)
        assert await host._send_command(5, 4)
        assert host._write_gatt.await_args.args[0] == expected


async def test_abba_does_not_toggle_on_unrecognized_status():
    host = create_mock_coordinator()
    host._protocol_mode = 5
    host.data.update(running_state=0, running_step=3)
    host._notification_data = bytearray((0xAB, 0xBA, 0x11, 0xCC, 3))
    host._send_command_unlocked = AsyncMock(return_value=True)

    await host.async_turn_on()

    host._send_command_unlocked.assert_awaited_once_with(1, 0)


async def test_split_fff0_off_uses_native_transport_even_with_old_protocol_flag():
    host = coordinator_for_layout(True)
    host._protocol_mode = 5
    host._send_dz06_neo_power = AsyncMock(return_value=True)
    host._set_abba_power = AsyncMock()

    assert await host._power_off()

    host._send_dz06_neo_power.assert_awaited_once_with(False)
    host._set_abba_power.assert_not_awaited()
