"""Exercise protocol capabilities, entity registration, and registry cleanup."""

from types import SimpleNamespace
from unittest.mock import MagicMock, call, patch

import pytest

from custom_components.diesel_heater import binary_sensor, select, sensor, switch
from custom_components.diesel_heater.capabilities import (
    async_remove_unsupported_entities,
    controller_capabilities,
)
from custom_components.diesel_heater.hcalory import HcaloryVariant
from diesel_heater_ble import ProtocolAA55Encrypted, ProtocolAA66Encrypted, ProtocolHcalory

from .test_coordinator import create_mock_coordinator
from .test_protocol import _make_aa66enc_data


@pytest.mark.asyncio
@pytest.mark.parametrize("auto,co_present", [(255, 0), (0, 1), (1, 1), (2, 0)])
async def test_aa66_reports_drive_entity_creation_in_level_mode(auto, co_present):
    coordinator = create_mock_coordinator()
    coordinator._protocol_mode = 4
    frame = _make_aa66enc_data(
        auto_start_stop=auto,
        co_present=co_present,
        co_ppm_raw=0,
        tank_volume=255,
        pump_byte=20,
        language=255,
    )
    frame[25] = 255
    coordinator.data.update(ProtocolAA66Encrypted().parse(frame))
    coordinator.data["connected"] = True
    coordinator.data["running_mode"] = 1
    entry = SimpleNamespace(runtime_data=coordinator)
    collected = []
    for platform in (binary_sensor, select, sensor, switch):
        await platform.async_setup_entry(coordinator.hass, entry, collected.extend)
    entities = {type(entity).__name__: entity for entity in collected}
    has_auto = auto in (0, 1)
    assert ("VevorAutoStartStopSwitch" in entities) == has_auto
    assert ("VevorAutoStartStopSensor" in entities) == has_auto
    if has_auto:
        switch_entity = entities["VevorAutoStartStopSwitch"]
        assert switch_entity.is_on == (auto == 1)
        assert not switch_entity.available
    assert ("VevorCOSensor" in entities) == bool(co_present)
    if co_present:
        assert entities["VevorCOSensor"].native_value == 0
    assert "VevorHeaterLanguageSelect" not in entities
    assert "VevorHeaterPumpTypeSelect" not in entities
    assert "VevorHeaterTankVolumeSelect" not in entities
    assert "VevorTimerSwitch" not in entities


@pytest.mark.parametrize(
    "mode,neo,warm,kind,expected_true,expected_false",
    [
        (1, False, False, None, "auto_offset", "co_sensor"),
        (2, False, False, None, "heater_offset", "abba"),
        (3, False, False, None, "level_fan", "timer"),
        (4, False, False, None, "auto_offset", "abba"),
        (5, False, False, None, "abba", "cbff"),
        (6, False, False, None, "cbff", "abba"),
        (7, False, False, None, "auto_start_stop", "altitude"),
        (8, False, False, None, "heatgenie", "auto_start_stop"),
        (9, False, False, "air", "cronus_air", "cronus_water"),
        (9, False, False, "water", "cronus_water", "level_number"),
        (0, True, False, None, "burnoff", "level_number"),
        (5, True, True, "air", "level_fan", "warm_drive_water"),
        (5, True, True, "water", "warm_drive_water", "level_fan"),
    ],
)
def test_capabilities_across_controller_families(mode, neo, warm, kind, expected_true, expected_false):
    coordinator = SimpleNamespace(
        protocol_mode=mode,
        is_dz06_neo=neo,
        is_warm_drive_controller=warm,
        supports_time_sync=True,
        has_cronus_fuel_estimate=False,
        data={"cronus_controller_type": kind, "neo_controller_type": kind},
    )
    capabilities = controller_capabilities(coordinator)
    assert capabilities[expected_true] is True
    assert capabilities[expected_false] is False


@pytest.mark.parametrize("connected,mode", [(True, 4), (False, 4), (True, 0)])
def test_cleanup_only_removes_proven_unsupported_entities_for_validated_heater(connected, mode):
    coordinator = create_mock_coordinator()
    coordinator._protocol_mode = mode
    coordinator.data.update(connected=connected, supports_co_sensor=False)
    entry = SimpleNamespace(entry_id="heater")
    entities = [
        SimpleNamespace(
            entity_id=f"{domain}.{name}",
            domain=domain,
            platform=platform,
            unique_id=f"{address}_{name}",
        )
        for domain, name, platform, address in (
            ("sensor", "hardware_version", "diesel_heater", coordinator.address),
            ("sensor", "software_version", "diesel_heater", coordinator.address),
            ("switch", "high_altitude", "diesel_heater", coordinator.address),
            ("sensor", "co_ppm", "diesel_heater", coordinator.address),
            ("switch", "auto_start_stop", "diesel_heater", coordinator.address),
            ("sensor", "co_ppm", "other_platform", coordinator.address),
            ("sensor", "co_ppm", "diesel_heater", "00:00:00:00:00:01"),
            ("sensor", "unknown_legacy_entity", "diesel_heater", coordinator.address),
        )
    ]
    registry = MagicMock()
    path = "custom_components.diesel_heater.capabilities.er"
    with (
        patch(f"{path}.async_get", return_value=registry),
        patch(f"{path}.async_entries_for_config_entry", return_value=entities) as entries,
    ):
        async_remove_unsupported_entities(coordinator.hass, entry, coordinator)
    if connected and mode == 4:
        entries.assert_called_once_with(registry, "heater")
        assert registry.async_remove.call_args_list == [
            call("sensor.hardware_version"),
            call("sensor.software_version"),
            call("switch.high_altitude"),
            call("sensor.co_ppm"),
        ]
    else:
        registry.async_remove.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "variant,raw,expected",
    [
        (HcaloryVariant.MVP2_2, 0, 0),
        (HcaloryVariant.MVP2_3, 25, 25),
        (HcaloryVariant.MVP2_3, 65535, None),
        (HcaloryVariant.MVP1_2, 25, None),
        (HcaloryVariant.MVP3_3, 25, None),
        (None, 25, None),
    ],
)
async def test_hcalory_co_registration_matches_app_model_and_report(variant, raw, expected):
    coordinator = create_mock_coordinator()
    coordinator._protocol = ProtocolHcalory()
    coordinator._protocols[7] = coordinator._protocol
    coordinator._protocol_mode = 7
    coordinator._is_hcalory_device = True
    coordinator._hcalory_variant = variant
    frame = bytearray.fromhex("00010001000100230300001EFFFF01F40000000085014602007800102C00023000000000000100000000C9")
    frame[12:14] = raw.to_bytes(2, "big")
    frame[-1] = sum(frame[8:-1]) & 255
    coordinator._parse_response(frame)

    entities = []
    await sensor.async_setup_entry(coordinator.hass, SimpleNamespace(runtime_data=coordinator), entities.extend)
    co = [entity for entity in entities if isinstance(entity, sensor.VevorCOSensor)]
    if expected is None:
        assert not co
    else:
        assert len(co) == 1
        assert co[0].native_value == expected


@pytest.mark.parametrize("protocol", [ProtocolAA55Encrypted(), ProtocolAA66Encrypted()])
@pytest.mark.parametrize("enable,expected", [(0, True), (1, True), (255, False), (2, None)])
def test_timer_enable_is_independent_of_duration(protocol, enable, expected):
    frame = bytearray(48)
    frame[21:26] = bytes((0, 120, 255, 255, enable))
    report = protocol.parse(frame)
    assert report["supports_timer"] is expected
    assert report["timer_enabled"] is (enable == 1)
