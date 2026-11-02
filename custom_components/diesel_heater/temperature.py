"""Native temperature metadata shared by temperature entities."""

from homeassistant.const import UnitOfTemperature


def temperature_bounds(coordinator):
    """Return bounds in the same unit as the coordinator's values."""
    mode = coordinator.protocol_mode
    if coordinator.is_dz06_neo:
        low = coordinator.data.get("neo_min_target")
        high = coordinator.data.get("neo_max_target")
        low, high = (8 if low is None else low), (36 if high is None else high)
    elif mode == 9:
        low, high = 5, 35
    elif mode == 7:
        low, high = 0, 40
    elif mode == 8:
        low, high = 10, 40
    else:
        low, high = 8, 36
    if coordinator._heater_uses_fahrenheit:
        convert = int if coordinator.is_dz06_neo else round
        return convert(low * 9 / 5 + 32), convert(high * 9 / 5 + 32)
    return low, high


class NativeTemperatureMixin:
    """Follow native units when a controller changes its display settings."""

    @property
    def native_unit_of_measurement(self):
        return UnitOfTemperature.FAHRENHEIT if self.coordinator._heater_uses_fahrenheit else UnitOfTemperature.CELSIUS


def convert_native_temperature(value: float, was_fahrenheit: bool, is_fahrenheit: bool) -> float:
    """Convert a cached value only when its native unit actually changes."""
    if was_fahrenheit == is_fahrenheit:
        return value
    return value * 9 / 5 + 32 if is_fahrenheit else (value - 32) * 5 / 9
