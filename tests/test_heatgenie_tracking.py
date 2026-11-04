"""Passive HeatGenie reports must not postpone periodic accounting (#160)."""
from unittest.mock import MagicMock

from tests.test_audit_repairs import heatgenie_status
from tests.test_coordinator import create_mock_coordinator


def test_valid_f2_notifies_without_resetting_refresh_schedule():
    coordinator = create_mock_coordinator()
    coordinator._is_heatgenie_device = True
    coordinator._protocol_mode = 8
    coordinator._protocol = coordinator._protocols[8]
    coordinator.async_update_listeners = MagicMock()
    coordinator.last_update_success = False
    for _ in range(90):
        coordinator._parse_response(heatgenie_status(unit=0))
    assert coordinator.async_update_listeners.call_count == 90
    coordinator.async_set_updated_data.assert_not_called()
    assert coordinator.last_update_success is True
    assert coordinator._heatgenie_status_event.is_set()


def test_invalid_f2_does_not_notify_or_restore_update_success():
    coordinator = create_mock_coordinator()
    coordinator._is_heatgenie_device = True
    coordinator._protocol_mode = 8
    coordinator._protocol = coordinator._protocols[8]
    coordinator.async_update_listeners = MagicMock()
    coordinator.last_update_success = False
    frame = heatgenie_status(unit=0)
    frame[-1] ^= 1
    coordinator._parse_response(frame)
    coordinator.async_update_listeners.assert_not_called()
    coordinator.async_set_updated_data.assert_not_called()
    assert coordinator.last_update_success is False


def test_button_ack_is_not_a_new_status_update():
    coordinator = create_mock_coordinator()
    coordinator._is_heatgenie_device = True
    coordinator._protocol_mode = 8
    coordinator._protocol = coordinator._protocols[8]
    coordinator.last_update_success = False
    coordinator._heatgenie_pending_button = (2, 0xAE)
    ack = bytearray((0xAA, 0, 0x41, 0, 0xAE, 0, 0, 0))
    ack[-2:] = coordinator._protocol.crc16(ack[:-2]).to_bytes(2, "big")
    coordinator._parse_response(ack)
    coordinator.async_update_listeners.assert_not_called()
    assert coordinator.last_update_success is False
