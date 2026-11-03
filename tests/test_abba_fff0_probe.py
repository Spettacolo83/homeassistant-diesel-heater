"""A shared ECB/FFF0 advertisement must not hide a validated ABBA response."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from custom_components.diesel_heater import coordinator as source
from custom_components.diesel_heater.hcalory import HcaloryVariant
from diesel_heater_ble import ProtocolHcalory
from tests.test_audit_repairs import abba_status
from tests.test_coordinator import create_mock_coordinator
from tests.test_pr_readiness_review import hcalory_status


def candidate(name=None):
    coordinator = create_mock_coordinator()
    coordinator._ble_device.name = name
    coordinator._hcalory_variant = HcaloryVariant.MVP1
    coordinator._protocols[7] = ProtocolHcalory()
    notify = SimpleNamespace(uuid=source.HCALORY_MVP1_NOTIFY_UUID, properties=["notify"])
    write = SimpleNamespace(uuid=source.HCALORY_MVP1_WRITE_UUID, properties=["write"])
    client = SimpleNamespace(
        is_connected=True,
        services=[SimpleNamespace(uuid=source.HCALORY_MVP1_SERVICE_UUID, characteristics=[notify, write])],
        start_notify=AsyncMock(),
        disconnect=AsyncMock(),
    )
    return coordinator, client


@pytest.mark.asyncio
@pytest.mark.parametrize("name", [None, "Heater5593", "Vevor Heater", "Heater5593-EC:B1:D2:00:9C:F8"])
async def test_connect_confirms_abba_without_relying_on_full_name(name):
    coordinator, client = candidate(name)

    async def respond(char, packet, response):
        assert packet[:4] == bytes.fromhex("baab04cc")
        coordinator._notification_callback(0, abba_status(unit=0, target=20))

    client.write_gatt_char = AsyncMock(side_effect=respond)
    with (
        patch.object(source, "establish_connection", AsyncMock(return_value=client)),
        patch.object(source.asyncio, "sleep", AsyncMock()),
    ):
        await coordinator._ensure_connected()
    assert coordinator.protocol_mode == 5
    assert coordinator._is_abba_device and not coordinator._is_hcalory_device
    assert coordinator._hcalory_variant is None
    assert coordinator.data["set_temp"] == 20
    assert not coordinator._legacy_fff0_probe
    assert all(call.args[1][:4] == bytes.fromhex("baab04cc") for call in client.write_gatt_char.await_args_list)


@pytest.mark.asyncio
async def test_real_mvp1_still_uses_its_query_after_unanswered_abba_read():
    coordinator, client = candidate("Heater5816")

    async def respond(char, packet, response):
        if packet[:2] == bytes((0, 2)):
            coordinator._notification_callback(0, hcalory_status(0, 0))

    client.write_gatt_char = AsyncMock(side_effect=respond)
    with (
        patch.object(source, "establish_connection", AsyncMock(return_value=client)),
        patch.object(source.asyncio, "sleep", AsyncMock()),
    ):
        await coordinator._ensure_connected()
    assert coordinator.protocol_mode == 7
    assert coordinator._is_hcalory_device and not coordinator._is_abba_device
    assert coordinator._notification_data is not None
    assert client.write_gatt_char.await_args_list[0].args[1][:4] == bytes.fromhex("baab04cc")
    assert client.write_gatt_char.await_args_list[-1].args[1][:2] == bytes((0, 2))


@pytest.mark.asyncio
async def test_short_abba_reply_does_not_confirm_identity():
    coordinator, client = candidate()

    async def respond(char, packet, response):
        if packet[:2] == bytes.fromhex("baab"):
            coordinator._notification_callback(0, bytearray.fromhex("abba000000000000"))

    client.write_gatt_char = AsyncMock(side_effect=respond)
    with (
        patch.object(source, "establish_connection", AsyncMock(return_value=client)),
        patch.object(source.asyncio, "sleep", AsyncMock()),
    ):
        await coordinator._ensure_connected()
    assert coordinator.protocol_mode == 7
    assert not coordinator.data["connected"]
    assert coordinator._notification_data is None


@pytest.mark.asyncio
async def test_probe_flag_is_cleared_on_cancellation():
    import asyncio

    coordinator, _ = candidate()
    coordinator._is_hcalory_device = True
    coordinator._protocol_mode = 7
    coordinator._write_gatt = AsyncMock(side_effect=asyncio.CancelledError)
    with pytest.raises(asyncio.CancelledError):
        await coordinator._identify_legacy_fff0_response()
    assert not coordinator._legacy_fff0_probe


@pytest.mark.asyncio
@pytest.mark.parametrize("variant", [v for v in HcaloryVariant if v != HcaloryVariant.MVP1])
async def test_versioned_hcalory_does_not_use_legacy_probe(variant):
    coordinator, client = candidate("Hcalory")
    coordinator._hcalory_variant = variant
    coordinator._async_password_handshake = AsyncMock(return_value=True)
    coordinator._send_wake_up_ping = AsyncMock()
    coordinator._identify_legacy_fff0_response = AsyncMock()
    with (
        patch.object(source, "establish_connection", AsyncMock(return_value=client)),
        patch.object(source.asyncio, "sleep", AsyncMock()),
    ):
        await coordinator._ensure_connected()
    coordinator._identify_legacy_fff0_response.assert_not_awaited()


@pytest.mark.asyncio
async def test_dedicated_bd39_transport_does_not_use_legacy_probe():
    coordinator, client = candidate("Hcalory")
    notify = SimpleNamespace(uuid=source.HCALORY_MVP2_NOTIFY_UUID, properties=["notify"])
    write = SimpleNamespace(uuid=source.HCALORY_MVP2_WRITE_UUID, properties=["write"])
    client.services = [SimpleNamespace(uuid=source.HCALORY_MVP2_SERVICE_UUID, characteristics=[notify, write])]
    coordinator._async_password_handshake = AsyncMock(return_value=True)
    coordinator._send_wake_up_ping = AsyncMock()
    coordinator._identify_legacy_fff0_response = AsyncMock()
    with (
        patch.object(source, "establish_connection", AsyncMock(return_value=client)),
        patch.object(source.asyncio, "sleep", AsyncMock()),
    ):
        await coordinator._ensure_connected()
    coordinator._identify_legacy_fff0_response.assert_not_awaited()
    assert coordinator._hcalory_mvp2_device
