"""APK-backed session decoding, transactional totals and protocol isolation."""

import asyncio
import json
import time
from unittest.mock import AsyncMock, MagicMock

import pytest
from diesel_heater_ble.protocol import ProtocolHcalory

from custom_components.diesel_heater.fuel import SessionFuel
from custom_components.diesel_heater.hcalory import HcaloryVariant
from tests.test_coordinator import create_mock_coordinator


def report(minutes, centilitres):
    return {"session_runtime_minutes": minutes, "session_fuel_centilitres": centilitres}


def frame(minutes, centilitres):
    data = bytearray.fromhex("000200010001000b14000006")
    whole, fraction = divmod(centilitres, 100)
    data += minutes.to_bytes(3, "big") + whole.to_bytes(2, "big") + bytes([fraction])
    data.append(sum(data[8:]) & 255)
    return data


def coordinator():
    c = create_mock_coordinator()
    c._protocol_mode = 7
    c._protocol = ProtocolHcalory()
    c._protocols[7] = c._protocol
    c._hcalory_variant = HcaloryVariant.MVP3_3
    c.data.update(hcalory_status=8, running_state=1, running_step=3, running_mode=1, set_level=5, tank_capacity=5)
    return c


def account(c, minutes, fuel):
    c._session_fuel_delta = c._consume_hcalory_fuel(report(minutes, fuel))
    c._update_fuel_tracking(5)


def test_query_and_decoder_match_apk_exact_fields():
    assert ProtocolHcalory.build_fuel_query().hex() == "0002000100010006140000010015"
    assert ProtocolHcalory.parse_fuel_response(frame(180, 125)) == report(180, 125)
    assert ProtocolHcalory().parse(frame(180, 125)) is None


@pytest.mark.parametrize("minutes", [0, 1, 60, 65536, 0xFFFFFF])
@pytest.mark.parametrize("centilitres", [0, 1, 125, 6553599])
def test_report_large_fields_and_checksum(minutes, centilitres):
    data = frame(minutes, centilitres)
    assert ProtocolHcalory.parse_fuel_response(data) == report(minutes, centilitres)
    data[-1] ^= 1
    assert ProtocolHcalory.parse_fuel_response(data) is None


@pytest.mark.parametrize("data", [b"", bytes(18), bytes(40), bytes.fromhex("0002000100010006140000010015")])
def test_invalid_report_cannot_initialize_source(data):
    assert ProtocolHcalory.parse_fuel_response(data) is None


def test_duplicates_and_out_of_order_do_not_recount_or_lower_high_water():
    c = coordinator()
    account(c, 10, 20)
    assert c._total_fuel_consumed == 0  # Establish baseline, never credit pre-install history.
    for minutes, fuel in [(11, 22), (11, 22), (9, 18), (12, 24), (12, 23), (12, 24)]:
        account(c, minutes, fuel)
    assert c._total_fuel_consumed == pytest.approx(0.04)
    assert c._daily_fuel_consumed == pytest.approx(0.04)
    assert c._fuel_consumed_since_reset == pytest.approx(0.04)
    assert c.data["fuel_remaining"] == 4.96
    assert c._fuel_session().centilitres == 24


def test_explicit_shutdown_reset_new_cycle_and_old_cycle_echo():
    c = coordinator()
    account(c, 100, 100)
    account(c, 101, 102)
    c.data["hcalory_status"] = 0
    account(c, 101, 102)
    account(c, 0, 0)
    account(c, 0, 0)  # Repeated Off must not re-arm reset authority.
    c.data["hcalory_status"] = 8
    account(c, 1, 2)
    account(c, 101, 102)  # Echo of previous session's high-water sample.
    account(c, 2, 4)
    account(c, 1, 2)
    assert c._total_fuel_consumed == pytest.approx(0.06)
    assert not c._fuel_session().off_seen


def test_shutdown_can_be_followed_by_nonzero_new_session_sample():
    c = coordinator()
    account(c, 30, 20)
    c.data["hcalory_status"] = 0
    c._consume_hcalory_fuel(None)
    c.data["hcalory_status"] = 8
    account(c, 1, 1)
    account(c, 2, 3)
    assert c._total_fuel_consumed == pytest.approx(0.03)


def test_reconnect_with_missed_shutdown_rebaselines_without_backfill():
    c = coordinator()
    account(c, 90, 100)
    c._fuel_session().observe_connection()
    account(c, 2, 3)
    assert c._total_fuel_consumed == 0
    account(c, 3, 5)
    assert c._total_fuel_consumed == pytest.approx(0.02)


def test_reconnect_with_same_session_recovers_positive_difference():
    c = coordinator()
    account(c, 10, 20)
    c._fuel_session().observe_connection()
    account(c, 20, 30)
    assert c._total_fuel_consumed == pytest.approx(0.10)


def test_report_loss_after_activation_never_adds_generic_fuel_again():
    c = coordinator()
    assert c._calculate_fuel_consumption(3600) == pytest.approx(0.32)
    account(c, 10, 20)
    c._session_fuel_delta = c._consume_hcalory_fuel(None)
    c._update_fuel_tracking(3600)
    assert c._total_fuel_consumed == 0
    account(c, 20, 25)
    assert c._total_fuel_consumed == pytest.approx(0.05)
    assert c._calculate_fuel_consumption(3600) == 0  # Consume the same delta only once.


@pytest.mark.parametrize("variant", list(HcaloryVariant))
def test_other_variants_keep_existing_estimate_and_ignore_session_report(variant):
    c = coordinator()
    c._hcalory_variant = variant
    if variant == HcaloryVariant.MVP3_3:
        return
    assert c._consume_hcalory_fuel(report(10, 20)) is None
    assert c._calculate_fuel_consumption(3600) == pytest.approx(0.32)
    assert not c._fuel_session().active


@pytest.mark.parametrize("mode", [1, 2, 3, 4, 5, 6, 8])
@pytest.mark.parametrize("level,expected", [(1, 0.16), (5, 0.32), (10, 0.52)])
def test_established_other_protocol_estimates_unchanged(mode, level, expected):
    c = coordinator()
    c._protocol_mode = mode
    c.data["set_level"] = level
    assert c._consume_hcalory_fuel(report(10, 20)) is None
    assert c._calculate_fuel_consumption(3600) == pytest.approx(expected)


async def test_saved_baseline_and_totals_restore_atomically():
    c = coordinator()
    account(c, 10, 20)
    account(c, 11, 25)
    assert await c.async_save_data()
    payload = json.loads(json.dumps(c._store.async_save.await_args.args[0]))
    restored = coordinator()
    restored._store.async_load = AsyncMock(return_value=payload)
    restored._import_all_history_statistics = AsyncMock()
    restored._import_all_runtime_statistics = AsyncMock()
    await restored.async_load_data()
    assert restored._total_fuel_consumed == pytest.approx(0.05)
    account(restored, 11, 25)
    account(restored, 12, 27)
    assert restored._total_fuel_consumed == pytest.approx(0.07)
    assert restored._fuel_consumed_since_reset == pytest.approx(0.07)


@pytest.mark.parametrize(
    "value", [None, {}, False, {"active": True}, {"active": True, "minutes": True, "centilitres": -1}]
)
def test_invalid_saved_baseline_cannot_credit_history(value):
    tracker = SessionFuel.restore(value)
    assert not tracker.active
    assert tracker.accept(10, 500) is None


async def test_optional_request_routes_reply_without_satisfying_status_command():
    c = coordinator()
    c._client = MagicMock(is_connected=True)

    async def send(packet):
        assert packet == ProtocolHcalory.build_fuel_query()
        before = c._notification_data
        c._parse_response(frame(10, 20))
        assert c._notification_data is before

    c._write_gatt = AsyncMock(side_effect=send)
    assert await c._read_hcalory_fuel() == report(10, 20)
    assert c.data["running_step"] == 3
    assert not c._fuel_session().active  # Accounting belongs to validated update, not notification.
    assert not c._hcalory_fuel_waiting


async def test_optional_failure_does_not_cleanup_or_replace_status():
    c = coordinator()
    c._client = MagicMock(is_connected=True)
    c._write_gatt = AsyncMock(side_effect=OSError("proxy write failed"))
    c._cleanup_connection = AsyncMock()
    assert await c._read_hcalory_fuel() is None
    c._cleanup_connection.assert_not_awaited()
    assert c.data["running_step"] == 3
    assert not c._hcalory_fuel_waiting


async def test_fuel_and_control_transactions_share_the_same_lock():
    c = coordinator()
    c._client = MagicMock(is_connected=True)
    entered = asyncio.Event()
    release = asyncio.Event()
    order = []

    async def send(packet):
        order.append("fuel")
        entered.set()
        await release.wait()
        c._parse_response(frame(10, 20))

    async def control(*args):
        order.append("control")
        return True

    c._write_gatt = AsyncMock(side_effect=send)
    c._send_command_unlocked = AsyncMock(side_effect=control)
    read = asyncio.create_task(c._read_hcalory_fuel())
    await entered.wait()
    write = asyncio.create_task(c._send_command(3, 0))
    await asyncio.sleep(0)
    assert order == ["fuel"]
    release.set()
    await asyncio.gather(read, write)
    assert order == ["fuel", "control"]


async def test_cancelled_optional_read_releases_lock_and_wait_state():
    c = coordinator()
    c._client = MagicMock(is_connected=True)
    entered = asyncio.Event()

    async def send(packet):
        entered.set()

    c._write_gatt = AsyncMock(side_effect=send)
    task = asyncio.create_task(c._read_hcalory_fuel())
    await entered.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert not c._hcalory_lock().locked() and not c._hcalory_fuel_waiting


async def test_refuel_reads_boundary_without_overwriting_lifetime():
    c = coordinator()
    account(c, 10, 20)
    account(c, 11, 25)
    c._read_hcalory_fuel = AsyncMock(return_value=report(12, 27))
    c.async_set_updated_data = MagicMock()
    await c.async_reset_fuel_level()
    assert c._total_fuel_consumed == pytest.approx(0.07)
    assert c._fuel_consumed_since_reset == 0
    account(c, 13, 29)
    assert c._total_fuel_consumed == pytest.approx(0.09)
    assert c._fuel_consumed_since_reset == pytest.approx(0.02)


async def test_partial_refill_boundary_preserves_total_and_remaining_level():
    c = coordinator()
    account(c, 10, 20)
    account(c, 11, 25)
    c._read_hcalory_fuel = AsyncMock(return_value=report(12, 27))
    c.async_set_updated_data = MagicMock()
    await c.async_set_current_fuel_level(4.6)
    account(c, 13, 29)
    assert c._total_fuel_consumed == pytest.approx(0.09)
    assert c._fuel_consumed_since_reset == pytest.approx(0.42)
    assert c.data["fuel_remaining"] == 4.58


async def test_missing_refuel_boundary_keeps_lifetime_but_rebases_tank_estimate():
    c = coordinator()
    account(c, 10, 20)
    c._read_hcalory_fuel = AsyncMock(return_value=None)
    c.async_set_updated_data = MagicMock()
    await c.async_reset_fuel_level()
    account(c, 9, 18)  # Regressive report must not consume the rebase flag.
    assert c._hcalory_refuel_rebase
    account(c, 12, 25)
    assert c._total_fuel_consumed == pytest.approx(0.05)
    assert c._fuel_consumed_since_reset == 0
    account(c, 13, 27)
    assert c._fuel_consumed_since_reset == pytest.approx(0.02)


async def test_production_update_queries_and_saves_session_totals():
    c = coordinator()
    account(c, 10, 20)
    c._client = MagicMock(is_connected=True)
    c._send_command = AsyncMock(return_value=True)
    c._read_hcalory_fuel = AsyncMock(return_value=report(11, 25))
    c._check_daily_reset = AsyncMock()
    c._check_daily_runtime_reset = AsyncMock()
    c._last_update_time = time.time() - 5
    c._last_save_time = time.time()
    result = await c._async_update_data()
    c._read_hcalory_fuel.assert_awaited_once()
    assert result["total_fuel_consumed"] == 0.05
    payload = c._store.async_save.await_args.args[0]
    assert payload["hcalory_session_fuel"]["centilitres"] == 25
    assert payload["total_fuel_consumed"] == pytest.approx(0.05)


async def test_daily_reset_does_not_reset_session_baseline():
    c = coordinator()
    account(c, 10, 20)
    account(c, 11, 25)
    c._last_reset_date = "2020-01-01"
    c._import_statistics = AsyncMock()
    await c._check_daily_reset()
    assert c._daily_fuel_consumed == 0
    account(c, 12, 27)
    assert c._daily_fuel_consumed == pytest.approx(0.02)
    assert c._total_fuel_consumed == pytest.approx(0.07)


async def test_optional_read_timeout_covers_hung_gatt_write(monkeypatch):
    from custom_components.diesel_heater import coordinator as module

    c = coordinator()
    c._client = MagicMock(is_connected=True)
    original = asyncio.timeout
    monkeypatch.setattr(module.asyncio, "timeout", lambda seconds: original(0.001))

    async def write(packet):
        await asyncio.Event().wait()

    c._write_gatt = AsyncMock(side_effect=write)
    assert await c._read_hcalory_fuel() is None
    assert not c._hcalory_lock().locked() and not c._hcalory_fuel_waiting


async def test_successful_status_stays_online_when_optional_report_times_out():
    c = coordinator()
    c._client = MagicMock(is_connected=True)
    c._send_command = AsyncMock(return_value=True)
    c._read_hcalory_fuel = AsyncMock(return_value=None)
    c._check_daily_reset = AsyncMock()
    c._check_daily_runtime_reset = AsyncMock()
    c._last_update_time = time.time() - 5
    c._last_save_time = time.time()
    assert (await c._async_update_data())["connected"] is True
    assert c._consecutive_failures == 0


async def test_storage_failure_keeps_dirty_for_retry_next_poll():
    c = coordinator()
    account(c, 10, 20)
    c._client = MagicMock(is_connected=True)
    c._send_command = AsyncMock(return_value=True)
    c._read_hcalory_fuel = AsyncMock(return_value=report(11, 25))
    c._check_daily_reset = AsyncMock()
    c._check_daily_runtime_reset = AsyncMock()
    c._last_update_time = time.time() - 5
    c._last_save_time = time.time()
    c._store.async_save = AsyncMock(side_effect=OSError("disk unavailable"))
    await c._async_update_data()
    assert c._session_fuel_dirty
    assert c._total_fuel_consumed == pytest.approx(0.05)
    c._store.async_save.side_effect = None
    await c._async_update_data()
    assert c._total_fuel_consumed == pytest.approx(0.05)
    assert not c._session_fuel_dirty


def test_entity_attributes_distinguish_accumulated_source_and_hourly_estimate():
    from custom_components.diesel_heater.sensor import VevorHourlyFuelConsumptionSensor, VevorTotalFuelConsumedSensor

    c = coordinator()
    account(c, 10, 20)
    total = VevorTotalFuelConsumedSensor(c)
    hourly = VevorHourlyFuelConsumptionSensor(c)
    assert total.extra_state_attributes["estimate_basis"] == "controller_session"
    assert hourly.extra_state_attributes["estimate_basis"] == "level_table"
    c._consume_hcalory_fuel(None)
    assert total.extra_state_attributes["report_available"] is False


@pytest.mark.parametrize("variant", list(HcaloryVariant))
async def test_only_app_supported_variant_can_send_optional_query(variant):
    c = coordinator()
    c._hcalory_variant = variant
    c._client = MagicMock(is_connected=True)
    c._write_gatt = AsyncMock(side_effect=OSError("skip wait"))
    await c._read_hcalory_fuel()
    assert c._write_gatt.await_count == (1 if variant == HcaloryVariant.MVP3_3 else 0)


async def test_status_report_during_fuel_request_does_not_confirm_it():
    c = coordinator()
    c._client = MagicMock(is_connected=True)

    async def send(packet):
        normal = bytearray(40)
        normal[:2] = b"\x00\x02"
        normal[8] = 3
        normal[20] = 0x85
        normal[21] = 2
        normal[22] = 5
        normal[-1] = sum(normal[8:-1]) & 255
        c._parse_response(normal)
        assert not c._hcalory_fuel_event.is_set()
        c._parse_response(frame(10, 20))

    c._write_gatt = AsyncMock(side_effect=send)
    assert await c._read_hcalory_fuel() == report(10, 20)


def test_stale_nonzero_report_during_shutdown_is_not_a_new_session():
    c = coordinator()
    account(c, 100, 100)
    c.data["hcalory_status"] = 0
    account(c, 99, 99)
    assert c._total_fuel_consumed == 0
    account(c, 0, 0)
    c.data["hcalory_status"] = 8
    account(c, 1, 2)
    assert c._total_fuel_consumed == pytest.approx(0.02)


def test_empty_old_session_does_not_authorize_a_later_false_reset():
    c = coordinator()
    account(c, 0, 0)
    c.data["hcalory_status"] = 0
    account(c, 0, 0)
    c.data["hcalory_status"] = 8
    account(c, 0, 1)
    account(c, 0, 0)
    account(c, 1, 2)
    assert c._total_fuel_consumed == pytest.approx(0.02)
