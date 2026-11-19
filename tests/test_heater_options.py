"""Options must follow validated heater capabilities and preserve hidden data."""
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from custom_components.diesel_heater.config_flow import VevorHeaterOptionsFlowHandler

COMMON = {"preset_away_temp", "preset_comfort_temp"}
OFFSET = {"external_temp_sensor", "auto_offset_max"}


def flow(mode, neo=False, data=None):
    result = VevorHeaterOptionsFlowHandler()
    result._config_entry = MagicMock()
    result._config_entry.data = {"external_temp_sensor": "sensor.room", **(data or {})}
    result._config_entry.runtime_data = SimpleNamespace(protocol_mode=mode, is_dz06_neo=neo)
    return result


@pytest.mark.asyncio
@pytest.mark.parametrize("mode,expected", [
    (1, COMMON | OFFSET | {"pin"}),
    (2, COMMON | OFFSET | {"pin"}),
    (3, COMMON | OFFSET | {"pin"}),
    (4, COMMON | OFFSET | {"pin", "force_temp_unit"}),
    (5, COMMON | {"force_temp_unit"}),
    (6, COMMON | OFFSET | {"pin", "force_temp_unit"}),
    (7, COMMON | {"pin", "force_temp_unit"}),
    (8, COMMON),
    (9, {"cronus_heater_model"}),
])
async def test_detected_family_options(mode, expected):
    f = flow(mode)
    form = await f.async_step_init()
    if mode != 9:
        expected = expected | {"fuel_rates"}
    assert {k.schema for k in form["data_schema"].schema} == expected


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", [0, 5])
@pytest.mark.parametrize("controller_type", [None, "air", "water"])
async def test_split_transport_has_only_neo_password_and_presets(mode, controller_type):
    f = flow(mode, neo=True, data={"neo_controller_type": controller_type})
    form = await f.async_step_init()
    assert {k.schema for k in form["data_schema"].schema} == COMMON | {"neo_password"}


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", [5, 7, 8, 9])
async def test_saving_supported_options_does_not_clear_hidden_settings(mode):
    f = flow(mode, data={"auto_offset_max": 4, "neo_password": 123456789})
    await f.async_step_init({"preset_away_temp": 12, "cronus_heater_model": "unconfigured"})
    saved = f.hass.config_entries.async_update_entry.call_args.kwargs["data"]
    assert saved["external_temp_sensor"] == "sensor.room"
    assert saved["auto_offset_max"] == 4
    assert saved["neo_password"] == 123456789
    assert ("cronus_heater_model" in saved) == (mode == 9)
    assert ("preset_away_temp" in saved) == (mode != 9)


@pytest.mark.asyncio
async def test_unloaded_entry_keeps_recovery_credentials_without_cronus_guess():
    f = flow(None)
    form = await f.async_step_init()
    keys = {k.schema for k in form["data_schema"].schema}
    assert {"pin", "neo_password"} <= keys
    assert "cronus_heater_model" not in keys


@pytest.mark.asyncio
async def test_saved_warm_drive_identity_recovers_password_without_coordinator():
    f = flow(None, data={"neo_controller_type": "water"})
    form = await f.async_step_init()
    assert {k.schema for k in form["data_schema"].schema} == COMMON | {"neo_password"}


@pytest.mark.asyncio
async def test_validated_protocol_overrides_stale_stored_identity():
    f = flow(9, data={"neo_controller_type": "air"})
    form = await f.async_step_init()
    assert {k.schema for k in form["data_schema"].schema} == {"cronus_heater_model"}
