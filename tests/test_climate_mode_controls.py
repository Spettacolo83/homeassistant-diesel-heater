"""Temperature controls must reflect the selected heater operating mode."""

from enum import IntFlag
from unittest.mock import AsyncMock

import pytest
from homeassistant.exceptions import HomeAssistantError

from custom_components.diesel_heater import climate as climate_module
from custom_components.diesel_heater.const import (
    RUNNING_MODE_LEVEL,
    RUNNING_MODE_TEMPERATURE,
    RUNNING_MODE_VENTILATION,
    RUNNING_STEP_RUNNING,
    RUNNING_STEP_VENTILATION,
)

from .test_climate import create_mock_config_entry, create_mock_coordinator


class Features(IntFlag):
    """Real bit operations despite the suite's lightweight HA module stubs."""

    TARGET_TEMPERATURE = 1
    PRESET_MODE = 16
    TURN_OFF = 128
    TURN_ON = 256


@pytest.fixture
def climate(monkeypatch):
    monkeypatch.setattr(climate_module, "ClimateEntityFeature", Features)
    monkeypatch.setattr(
        climate_module.VevorHeaterClimate,
        "_attr_supported_features",
        Features.TARGET_TEMPERATURE | Features.PRESET_MODE | Features.TURN_OFF | Features.TURN_ON,
    )
    coordinator = create_mock_coordinator()
    coordinator.protocol_mode = 4
    return climate_module.VevorHeaterClimate(coordinator, create_mock_config_entry())


@pytest.mark.parametrize("mode", [None, 0, RUNNING_MODE_LEVEL, RUNNING_MODE_VENTILATION])
async def test_non_temperature_modes_hide_target_and_reject_temperature_writes(climate, mode):
    climate.coordinator.data["running_mode"] = mode

    assert climate.target_temperature is None
    assert climate.preset_modes is None
    assert climate.preset_mode is None
    assert climate.current_temperature == 20.5
    assert climate.supported_features == Features.TURN_ON | Features.TURN_OFF
    with pytest.raises(HomeAssistantError, match="Temperature mode"):
        await climate.async_set_temperature(temperature=25)
    with pytest.raises(HomeAssistantError, match="Temperature mode"):
        await climate.async_set_preset_mode(climate_module.PRESET_COMFORT)
    climate.coordinator.async_set_temperature.assert_not_awaited()


async def test_temperature_mode_exposes_target_and_presets(climate):
    climate.coordinator.data["running_mode"] = RUNNING_MODE_TEMPERATURE
    assert climate.target_temperature == 22
    assert climate.supported_features & Features.TARGET_TEMPERATURE
    assert climate.supported_features & Features.PRESET_MODE
    assert climate.preset_modes == climate._attr_preset_modes
    await climate.async_set_temperature(temperature=25)
    climate.coordinator.async_set_temperature.assert_awaited_once_with(25)


@pytest.mark.parametrize("restricted", ["ventilation", "burnoff"])
async def test_ventilation_and_burnoff_hide_temperature_controls(climate, restricted):
    climate.coordinator.data["running_mode"] = RUNNING_MODE_TEMPERATURE
    if restricted == "ventilation":
        climate.coordinator.data["running_step"] = RUNNING_STEP_VENTILATION
    else:
        climate.coordinator.burnoff_active = True
    assert climate.target_temperature is None
    assert climate.preset_mode is None
    assert climate.preset_modes is None
    assert climate.supported_features == Features.TURN_ON | Features.TURN_OFF


@pytest.mark.parametrize(
    ("controller", "mode", "temperature"),
    [("air", "heating", True), ("air", "ventilation", False), ("water", "heating", False)],
)
def test_cronus_existing_capability_rules_are_preserved(climate, controller, mode, temperature):
    climate.coordinator.protocol_mode = 9
    climate.coordinator.data.update(cronus_controller_type=controller, cronus_mode=mode)
    assert bool(climate.supported_features & Features.TARGET_TEMPERATURE) is temperature
    assert not climate.supported_features & Features.PRESET_MODE
    assert climate.preset_modes is None


def test_abba_restored_target_is_only_visible_in_temperature_mode(climate):
    climate.coordinator.protocol_mode = 5
    climate.coordinator.data.update(set_temp=None, running_mode=RUNNING_MODE_LEVEL)
    climate._restored_abba_target = 21
    assert climate.target_temperature is None
    climate.coordinator.data["running_mode"] = RUNNING_MODE_TEMPERATURE
    assert climate.target_temperature == 21


async def test_power_controls_remain_available_in_level_mode(climate):
    climate.coordinator.data.update(running_mode=RUNNING_MODE_LEVEL, running_step=RUNNING_STEP_RUNNING)
    climate.coordinator.async_turn_on = AsyncMock()
    climate.coordinator.async_turn_off = AsyncMock()
    await climate.async_turn_on()
    await climate.async_turn_off()
    climate.coordinator.async_turn_on.assert_awaited_once()
    climate.coordinator.async_turn_off.assert_awaited_once()
