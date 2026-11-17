"""Per-heater rate overrides and collapsed configuration regression coverage."""
from types import SimpleNamespace

import pytest

from custom_components.diesel_heater import config_flow
from custom_components.diesel_heater.const import FUEL_CONSUMPTION_TABLE
from custom_components.diesel_heater.fuel import fuel_rate_for_level
from tests.test_coordinator import create_mock_coordinator
from tests.test_hcalory_session_fuel import account, coordinator
from tests.test_heater_options import flow


@pytest.mark.parametrize("level", range(1, 11))
def test_defaults_are_unchanged(level):
    assert fuel_rate_for_level(level, None) == FUEL_CONSUMPTION_TABLE[level]


@pytest.mark.parametrize("bad", [None, True, "bad", -0.1, float("nan"), float("inf"), 10**400])
def test_invalid_saved_values_fall_back(bad):
    assert fuel_rate_for_level(10, {"level_10": bad}) == 0.52


@pytest.mark.parametrize("mode", range(1, 9))
def test_per_heater_rates_change_future_table_estimates_only(mode):
    c = create_mock_coordinator()
    c._protocol_mode = mode
    c.config_entry = SimpleNamespace(data={"fuel_rates": {"level_10": 0.34}})
    c.data.update(set_level=10, running_mode=1, tank_capacity=5)
    c._is_running_for_tracking = lambda: True
    c._update_fuel_tracking(3600)
    assert c._total_fuel_consumed == pytest.approx(0.34)
    assert c.data["hourly_fuel_consumption"] == 0.34
    assert c._fuel_consumed_since_reset == pytest.approx(0.34)
    c.config_entry.data["fuel_rates"]["level_10"] = 0.4
    c._update_fuel_tracking(3600)
    assert c._total_fuel_consumed == pytest.approx(0.74)
    assert fuel_rate_for_level(1, c.config_entry.data["fuel_rates"]) == 0.16
    assert FUEL_CONSUMPTION_TABLE[10] == 0.52
    c._is_running_for_tracking = lambda: False
    assert c._calculate_fuel_consumption(3600) == 0


def test_mvp33_session_counters_stay_unscaled():
    c = coordinator()
    c.config_entry = SimpleNamespace(data={"fuel_rates": {"level_5": 9}})
    account(c, 10, 20)
    account(c, 11, 30)
    assert c._total_fuel_consumed == pytest.approx(0.1)
    assert c.data["hcalory_session_fuel_litres"] == 0.3
    assert c.data["hourly_fuel_consumption"] == 9


def test_cronus_profile_is_not_replaced():
    c = create_mock_coordinator()
    c._protocol_mode = 9
    c.config_entry = SimpleNamespace(data={"fuel_rates": {"level_5": 9}})
    c._is_running_for_tracking = lambda: True
    c._cronus_fuel_rate = lambda: 0.4
    c._update_fuel_tracking(3600)
    assert c._total_fuel_consumed == pytest.approx(0.4)
    assert c.data["hourly_fuel_consumption"] == 0.4


@pytest.mark.asyncio
@pytest.mark.parametrize("mode,count", [(1, 10), (5, 6), (7, 10), (8, 10)])
async def test_collapsed_section_defaults_and_level_count(monkeypatch, mode, count):
    # HA's section API is exercised separately with the real installed serializer.
    class Section:
        def __init__(self, schema, options):
            self.schema, self.options = schema, options

        def __call__(self, value):
            return self.schema(value)

    monkeypatch.setattr(config_flow, "section", Section)
    f = flow(mode, data={"fuel_rates": {"level_1": 0.12}})
    form = await f.async_step_init()
    rates = next(v for k, v in form["data_schema"].schema.items() if k.schema == "fuel_rates")
    assert rates.options == {"collapsed": True}
    assert len(rates.schema.schema) == count
    assert rates.schema({})["level_1"] == 0.12
    assert rates.schema({})[f"level_{count}"] == FUEL_CONSUMPTION_TABLE[count]
    assert all(k.schema != "level_1" for k in form["data_schema"].schema)


@pytest.mark.asyncio
@pytest.mark.parametrize("bad", [-1, "nan", "inf", True, None, "bad"])
async def test_invalid_input_does_not_save(bad):
    f = flow(7)
    result = await f.async_step_init({"fuel_rates": {"level_10": bad}})
    assert result["errors"] == {"fuel_rates": "invalid_fuel_rate"}
    f.hass.config_entries.async_update_entry.assert_not_called()


@pytest.mark.asyncio
async def test_saved_rates_restore_and_omission_preserves_them():
    f = flow(7)
    await f.async_step_init({"fuel_rates": {"level_1": 0, "level_10": "0.34"}})
    saved = f.hass.config_entries.async_update_entry.call_args.kwargs["data"]
    assert saved["fuel_rates"]["level_10"] == 0.34
    assert saved["fuel_rates"]["level_1"] == 0
    assert saved["fuel_rates"]["level_2"] == 0.20
    f = flow(7, data=saved)
    assert f._fuel_schema()({})["level_10"] == 0.34
    await f.async_step_init({"preset_away_temp": 10})
    assert f.hass.config_entries.async_update_entry.call_args.kwargs["data"]["fuel_rates"] == saved["fuel_rates"]


@pytest.mark.asyncio
async def test_abba_rejects_levels_outside_its_six_steps():
    f = flow(5)
    result = await f.async_step_init({"fuel_rates": {"level_10": 0.34}})
    assert result["errors"] == {"fuel_rates": "invalid_fuel_rate"}


def test_cbff_ventilation_never_uses_custom_rate():
    c = create_mock_coordinator()
    c._protocol_mode = 6
    c.config_entry = SimpleNamespace(data={"fuel_rates": {"level_5": 0.9}})
    c.data.update(set_level=5, running_mode=3)
    c._is_running_for_tracking = lambda: True
    c._update_fuel_tracking(3600)
    assert c._total_fuel_consumed == 0
    assert c.data["hourly_fuel_consumption"] == 0
