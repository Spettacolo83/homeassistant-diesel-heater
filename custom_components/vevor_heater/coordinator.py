"""Coordinator for Vevor Diesel Heater."""
from __future__ import annotations

import asyncio
import logging
import random
import time
from datetime import datetime, timedelta
from typing import Any

from bleak import BleakClient
from bleak.exc import BleakError
from bleak_retry_connector import establish_connection

from homeassistant.components import bluetooth
from homeassistant.components.recorder import get_instance
from homeassistant.components.recorder.statistics import (
    async_add_external_statistics,
    StatisticData,
    StatisticMetaData,
    StatisticMeanType,
)
from homeassistant.const import UnitOfTime, UnitOfVolume
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.storage import Store
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

from homeassistant.helpers.event import async_track_state_change_event

from .const import (
    AUTO_OFFSET_THRESHOLD,
    AUTO_OFFSET_THROTTLE_SECONDS,
    CHARACTERISTIC_UUID,
    CHARACTERISTIC_UUID_ALT,
    CONF_AUTO_OFFSET_MAX,
    CONF_EXTERNAL_TEMP_SENSOR,
    CONF_PIN,
    CONF_TEMPERATURE_OFFSET,
    DEFAULT_AUTO_OFFSET_MAX,
    DEFAULT_PIN,
    DEFAULT_TEMPERATURE_OFFSET,
    DOMAIN,
    ENCRYPTION_KEY,
    FUEL_CONSUMPTION_TABLE,
    MAX_HISTORY_DAYS,
    NOTIFY_UUID,
    RUNNING_MODE_LEVEL,
    RUNNING_MODE_MANUAL,
    RUNNING_MODE_TEMPERATURE,
    RUNNING_STEP_RUNNING,
    SENSOR_TEMP_MAX,
    SENSOR_TEMP_MIN,
    SERVICE_UUID,
    SERVICE_UUID_ALT,
    STORAGE_KEY_DAILY_DATE,
    STORAGE_KEY_DAILY_FUEL,
    STORAGE_KEY_DAILY_HISTORY,
    STORAGE_KEY_DAILY_RUNTIME,
    STORAGE_KEY_DAILY_RUNTIME_DATE,
    STORAGE_KEY_DAILY_RUNTIME_HISTORY,
    STORAGE_KEY_TOTAL_FUEL,
    STORAGE_KEY_TOTAL_RUNTIME,
    UPDATE_INTERVAL,
)

_LOGGER = logging.getLogger(__name__)


def _u8_to_number(value: int) -> int:
    """Convert unsigned 8-bit value."""
    return (value + 256) if (value < 0) else value


def _unsign_to_sign(value: int) -> int:
    """Convert unsigned to signed value."""
    if value > 32767.5:
        value = value | -65536
    return value


def _decrypt_data(data: bytearray) -> bytearray:
    """Decrypt encrypted data using XOR with password key."""
    decrypted = bytearray(data)

    # Decrypt 6 blocks (each of 8 bytes)
    for j in range(6):
        base_index = 8 * j
        for i in range(8):
            if base_index + i < len(decrypted):
                decrypted[base_index + i] = ENCRYPTION_KEY[i] ^ decrypted[base_index + i]

    return decrypted


def _encrypt_data(data: bytearray) -> bytearray:
    """Encrypt data using XOR with password key (same as decrypt since XOR is symmetric)."""
    # XOR encryption is symmetric, so we use the same algorithm
    return _decrypt_data(data)


class VevorHeaterCoordinator(DataUpdateCoordinator):
    """Vevor Heater coordinator."""

    def __init__(
        self,
        hass: HomeAssistant,
        ble_device: bluetooth.BleakDevice,
        config_entry: Any,
    ) -> None:
        """Initialize the coordinator."""
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=timedelta(seconds=UPDATE_INTERVAL),
        )

        self.address = ble_device.address
        self._ble_device = ble_device
        self.config_entry = config_entry
        self._client: BleakClient | None = None
        self._characteristic = None
        self._active_char_uuid: str | None = None  # Track which UUID variant is active
        self._notification_data: bytearray | None = None
        # Get passkey from config, default to 1234 (factory default for most heaters)
        self._passkey = config_entry.data.get(CONF_PIN, DEFAULT_PIN)
        self._protocol_mode = 0  # Will be detected from response
        self._connection_attempts = 0
        self._last_connection_attempt = 0.0
        self._consecutive_failures = 0  # Track consecutive update failures
        self._max_stale_cycles = 3  # Keep last values for this many failed cycles
        self._last_valid_data: dict[str, Any] = {}  # Cache of last valid sensor readings
        self._heater_uses_fahrenheit: bool = False  # Detected from heater response
        
        # Current state
        self.data: dict[str, Any] = {
            "running_state": None,
            "error_code": None,
            "running_step": None,
            "altitude": None,
            "running_mode": None,
            "set_level": None,
            "set_temp": None,
            "supply_voltage": None,
            "case_temperature": None,
            "cab_temperature": None,
            "connected": False,
            "auto_start_stop": None,  # Automatic Start/Stop flag (byte 31)
            # Fuel consumption tracking
            "hourly_fuel_consumption": None,
            "daily_fuel_consumed": 0.0,
            "total_fuel_consumed": 0.0,
            # Runtime tracking
            "daily_runtime_hours": 0.0,
            "total_runtime_hours": 0.0,
        }

        # Fuel consumption tracking (minimal)
        self._store = Store(hass, 1, f"{DOMAIN}_{ble_device.address}")
        self._last_update_time: float = time.time()
        self._total_fuel_consumed: float = 0.0
        self._daily_fuel_consumed: float = 0.0
        self._daily_fuel_history: dict[str, float] = {}  # date -> liters consumed
        self._last_save_time: float = time.time()
        self._last_reset_date: str = datetime.now().date().isoformat()

        # Runtime tracking
        self._total_runtime_seconds: float = 0.0
        self._daily_runtime_seconds: float = 0.0
        self._daily_runtime_history: dict[str, float] = {}  # date -> hours running
        self._last_runtime_reset_date: str = datetime.now().date().isoformat()

        # Auto temperature offset from external sensor
        self._auto_offset_unsub: callable | None = None
        self._last_auto_offset_time: float = 0.0
        self._current_auto_offset: float = 0.0  # Current auto-calculated offset

    async def async_load_data(self) -> None:
        """Load persistent fuel consumption and runtime data."""
        try:
            data = await self._store.async_load()
            if data:
                # Load fuel consumption data
                self._total_fuel_consumed = data.get(STORAGE_KEY_TOTAL_FUEL, 0.0)
                self._daily_fuel_consumed = data.get(STORAGE_KEY_DAILY_FUEL, 0.0)
                self._daily_fuel_history = data.get(STORAGE_KEY_DAILY_HISTORY, {})

                # Load runtime tracking data
                self._total_runtime_seconds = data.get(STORAGE_KEY_TOTAL_RUNTIME, 0.0)
                self._daily_runtime_seconds = data.get(STORAGE_KEY_DAILY_RUNTIME, 0.0)
                self._daily_runtime_history = data.get(STORAGE_KEY_DAILY_RUNTIME_HISTORY, {})

                # Clean old history entries (keep only last MAX_HISTORY_DAYS)
                self._clean_old_history()
                self._clean_old_runtime_history()

                # Check if we need to reset daily fuel counter
                saved_date = data.get(STORAGE_KEY_DAILY_DATE)
                if saved_date:
                    today = datetime.now().date().isoformat()
                    if saved_date != today:
                        _LOGGER.info("New day detected at startup, resetting daily fuel counter")
                        # Save yesterday's consumption to history before resetting
                        if self._daily_fuel_consumed > 0:
                            self._daily_fuel_history[saved_date] = round(self._daily_fuel_consumed, 2)
                            _LOGGER.info("Saved %s: %.2fL to history", saved_date, self._daily_fuel_consumed)
                        self._daily_fuel_consumed = 0.0
                        self._last_reset_date = today
                    else:
                        self._last_reset_date = saved_date
                else:
                    # No saved date, use today
                    self._last_reset_date = datetime.now().date().isoformat()

                # Check if we need to reset daily runtime counter
                saved_runtime_date = data.get(STORAGE_KEY_DAILY_RUNTIME_DATE)
                if saved_runtime_date:
                    today = datetime.now().date().isoformat()
                    if saved_runtime_date != today:
                        _LOGGER.info("New day detected at startup, resetting daily runtime counter")
                        # Save yesterday's runtime to history before resetting
                        if self._daily_runtime_seconds > 0:
                            hours = round(self._daily_runtime_seconds / 3600.0, 2)
                            self._daily_runtime_history[saved_runtime_date] = hours
                            _LOGGER.info("Saved %s: %.2fh to runtime history", saved_runtime_date, hours)
                        self._daily_runtime_seconds = 0.0
                        self._last_runtime_reset_date = today
                    else:
                        self._last_runtime_reset_date = saved_runtime_date
                else:
                    # No saved date, use today
                    self._last_runtime_reset_date = datetime.now().date().isoformat()

                # Update data dictionary with loaded values
                self.data["total_fuel_consumed"] = round(self._total_fuel_consumed, 2)
                self.data["daily_fuel_consumed"] = round(self._daily_fuel_consumed, 2)
                self.data["daily_fuel_history"] = self._daily_fuel_history
                self.data["daily_runtime_hours"] = round(self._daily_runtime_seconds / 3600.0, 2)
                self.data["total_runtime_hours"] = round(self._total_runtime_seconds / 3600.0, 2)
                self.data["daily_runtime_history"] = self._daily_runtime_history

                _LOGGER.debug(
                    "Loaded fuel data: total=%.2fL, daily=%.2fL, history entries=%d",
                    self._total_fuel_consumed,
                    self._daily_fuel_consumed,
                    len(self._daily_fuel_history)
                )
                _LOGGER.debug(
                    "Loaded runtime data: total=%.2fh, daily=%.2fh, history entries=%d",
                    self._total_runtime_seconds / 3600.0,
                    self._daily_runtime_seconds / 3600.0,
                    len(self._daily_runtime_history)
                )

                # Import existing history into statistics for native graphing
                await self._import_all_history_statistics()
                await self._import_all_runtime_history_statistics()
        except Exception as err:
            _LOGGER.warning("Could not load data: %s", err)

        # Set up external temperature sensor listener for auto offset
        await self._setup_external_temp_listener()

    async def _setup_external_temp_listener(self) -> None:
        """Set up listener for external temperature sensor state changes."""
        # Clean up any existing listener
        if self._auto_offset_unsub:
            self._auto_offset_unsub()
            self._auto_offset_unsub = None

        # Get external sensor entity_id from config
        external_sensor = self.config_entry.data.get(CONF_EXTERNAL_TEMP_SENSOR, "")
        if not external_sensor:
            _LOGGER.debug("No external temperature sensor configured")
            return

        _LOGGER.info(
            "Setting up auto offset from external sensor: %s (max offset: %d°C)",
            external_sensor,
            self.config_entry.data.get(CONF_AUTO_OFFSET_MAX, DEFAULT_AUTO_OFFSET_MAX)
        )

        # Subscribe to state changes
        self._auto_offset_unsub = async_track_state_change_event(
            self.hass,
            [external_sensor],
            self._async_external_temp_changed
        )

        # Calculate initial offset
        await self._async_calculate_auto_offset()

    @callback
    def _async_external_temp_changed(self, event) -> None:
        """Handle external temperature sensor state changes."""
        # Schedule the async calculation
        self.hass.async_create_task(self._async_calculate_auto_offset())

    async def _async_calculate_auto_offset(self) -> None:
        """Calculate and apply auto temperature offset based on external sensor.

        This compares the heater's internal temperature sensor with an external
        reference sensor and calculates an offset to compensate for any difference.
        The offset is limited by CONF_AUTO_OFFSET_MAX and throttled to avoid
        frequent changes.
        """
        external_sensor = self.config_entry.data.get(CONF_EXTERNAL_TEMP_SENSOR, "")
        if not external_sensor:
            return

        # Throttle offset updates
        current_time = time.time()
        if current_time - self._last_auto_offset_time < AUTO_OFFSET_THROTTLE_SECONDS:
            _LOGGER.debug("Auto offset throttled (last update %.0fs ago)",
                         current_time - self._last_auto_offset_time)
            return

        # Get external sensor state
        state = self.hass.states.get(external_sensor)
        if state is None or state.state in ("unknown", "unavailable"):
            _LOGGER.debug("External sensor %s unavailable", external_sensor)
            return

        try:
            external_temp = float(state.state)
        except (ValueError, TypeError):
            _LOGGER.warning("Invalid external sensor value: %s", state.state)
            return

        # Get heater's raw cab temperature (before any offset)
        # We need the uncalibrated value for comparison
        raw_heater_temp = self.data.get("cab_temperature")
        if raw_heater_temp is None:
            _LOGGER.debug("Heater temperature not available")
            return

        # Remove current offsets to get raw value
        manual_offset = self.config_entry.data.get(CONF_TEMPERATURE_OFFSET, DEFAULT_TEMPERATURE_OFFSET)
        raw_heater_temp = raw_heater_temp - manual_offset - self._current_auto_offset

        # Calculate the difference: positive means heater reads lower than external
        difference = external_temp - raw_heater_temp

        # Only adjust if difference is significant
        if abs(difference) < AUTO_OFFSET_THRESHOLD:
            _LOGGER.debug(
                "Auto offset: difference (%.1f°C) below threshold (%.1f°C), no adjustment",
                difference, AUTO_OFFSET_THRESHOLD
            )
            return

        # Calculate new offset (clamped to max)
        max_offset = self.config_entry.data.get(CONF_AUTO_OFFSET_MAX, DEFAULT_AUTO_OFFSET_MAX)
        new_auto_offset = max(-max_offset, min(max_offset, difference))

        # Only update if offset changed significantly
        if abs(new_auto_offset - self._current_auto_offset) >= 0.5:
            old_offset = self._current_auto_offset
            self._current_auto_offset = new_auto_offset
            self._last_auto_offset_time = current_time

            _LOGGER.info(
                "Auto offset updated: external=%.1f°C, heater_raw=%.1f°C, "
                "difference=%.1f°C, offset: %.1f → %.1f°C",
                external_temp, raw_heater_temp, difference, old_offset, new_auto_offset
            )

    async def async_save_data(self) -> None:
        """Save persistent fuel consumption and runtime data."""
        try:
            data = {
                # Fuel data
                STORAGE_KEY_TOTAL_FUEL: self._total_fuel_consumed,
                STORAGE_KEY_DAILY_FUEL: self._daily_fuel_consumed,
                STORAGE_KEY_DAILY_DATE: datetime.now().date().isoformat(),
                STORAGE_KEY_DAILY_HISTORY: self._daily_fuel_history,
                # Runtime data
                STORAGE_KEY_TOTAL_RUNTIME: self._total_runtime_seconds,
                STORAGE_KEY_DAILY_RUNTIME: self._daily_runtime_seconds,
                STORAGE_KEY_DAILY_RUNTIME_DATE: datetime.now().date().isoformat(),
                STORAGE_KEY_DAILY_RUNTIME_HISTORY: self._daily_runtime_history,
            }
            await self._store.async_save(data)
            _LOGGER.debug(
                "Saved data: fuel history=%d entries, runtime history=%d entries",
                len(self._daily_fuel_history),
                len(self._daily_runtime_history)
            )
        except Exception as err:
            _LOGGER.warning("Could not save data: %s", err)

    def _clean_old_history(self) -> None:
        """Remove history entries older than MAX_HISTORY_DAYS."""
        if not self._daily_fuel_history:
            return

        cutoff_date = (datetime.now().date() - timedelta(days=MAX_HISTORY_DAYS)).isoformat()
        old_keys = [date for date in self._daily_fuel_history if date < cutoff_date]

        for date in old_keys:
            del self._daily_fuel_history[date]

        if old_keys:
            _LOGGER.debug("Removed %d old fuel history entries (before %s)", len(old_keys), cutoff_date)

    def _clean_old_runtime_history(self) -> None:
        """Remove runtime history entries older than MAX_HISTORY_DAYS."""
        if not self._daily_runtime_history:
            return

        cutoff_date = (datetime.now().date() - timedelta(days=MAX_HISTORY_DAYS)).isoformat()
        old_keys = [date for date in self._daily_runtime_history if date < cutoff_date]

        for date in old_keys:
            del self._daily_runtime_history[date]

        if old_keys:
            _LOGGER.debug("Removed %d old runtime history entries (before %s)", len(old_keys), cutoff_date)

    async def _import_statistics(self, date_str: str, liters: float) -> None:
        """Import daily fuel consumption into Home Assistant statistics for graphing."""
        # Skip if recorder is not available
        if not (recorder := get_instance(self.hass)):
            _LOGGER.debug("Recorder not available, skipping statistics import")
            return

        # Define statistic metadata
        # statistic_id must be unique per device and lowercase with valid characters
        device_id = self.address.replace(":", "_").lower()
        statistic_id = f"{DOMAIN}:{device_id}_daily_fuel_consumed"
        metadata = StatisticMetaData(
            has_mean=False,
            has_sum=True,
            mean_type=StatisticMeanType.NONE,
            name=f"Daily Fuel Consumption ({self.address[-5:]})",
            source=DOMAIN,
            statistic_id=statistic_id,
            unit_of_measurement=UnitOfVolume.LITERS,
        )

        # Parse date and create timestamp at midnight (start of hour required by HA)
        try:
            date_obj = datetime.fromisoformat(date_str)
            # Use midnight (00:00:00) - HA requires timestamps at top of hour
            midnight = datetime.combine(date_obj.date(), datetime.min.time())
            # Make it timezone-aware
            timestamp = dt_util.as_utc(midnight)
        except (ValueError, TypeError) as err:
            _LOGGER.error("Failed to parse date %s: %s", date_str, err)
            return

        # Create statistic data point
        statistic = StatisticData(
            start=timestamp,
            state=liters,
            sum=liters,  # Sum for this day
        )

        # Import the statistic (wrapped in try-except to prevent crashes)
        # Use async_add_external_statistics for external statistics (uses : delimiter)
        _LOGGER.info(
            "Importing fuel statistic: id=%s, date=%s, value=%.2fL",
            statistic_id, date_str, liters
        )
        try:
            async_add_external_statistics(self.hass, metadata, [statistic])
            _LOGGER.debug("Successfully imported fuel statistic for %s", date_str)
        except Exception as err:
            _LOGGER.warning(
                "Could not import fuel statistic for %s: %s (statistic_id=%s)",
                date_str, err, statistic_id
            )

    async def _import_all_history_statistics(self) -> None:
        """Import all existing history data into statistics (called at startup)."""
        if not self._daily_fuel_history:
            _LOGGER.debug("No history to import into statistics")
            return

        _LOGGER.info("Importing %d days of fuel history into statistics", len(self._daily_fuel_history))

        for date_str, liters in sorted(self._daily_fuel_history.items()):
            await self._import_statistics(date_str, liters)

        _LOGGER.info("Completed import of fuel history into statistics")

    async def _import_runtime_statistics(self, date_str: str, hours: float) -> None:
        """Import daily runtime into Home Assistant statistics for graphing."""
        # Skip if recorder is not available
        if not (recorder := get_instance(self.hass)):
            _LOGGER.debug("Recorder not available, skipping runtime statistics import")
            return

        # Define statistic metadata
        # statistic_id must be unique per device and lowercase with valid characters
        device_id = self.address.replace(":", "_").lower()
        statistic_id = f"{DOMAIN}:{device_id}_daily_runtime_hours"
        metadata = StatisticMetaData(
            has_mean=False,
            has_sum=True,
            mean_type=StatisticMeanType.NONE,
            name=f"Daily Runtime ({self.address[-5:]})",
            source=DOMAIN,
            statistic_id=statistic_id,
            unit_of_measurement=UnitOfTime.HOURS,
        )

        # Parse date and create timestamp at midnight (start of hour required by HA)
        try:
            date_obj = datetime.fromisoformat(date_str)
            # Use midnight (00:00:00) - HA requires timestamps at top of hour
            midnight = datetime.combine(date_obj.date(), datetime.min.time())
            # Make it timezone-aware
            timestamp = dt_util.as_utc(midnight)
        except (ValueError, TypeError) as err:
            _LOGGER.error("Failed to parse date %s: %s", date_str, err)
            return

        # Create statistic data point
        statistic = StatisticData(
            start=timestamp,
            state=hours,
            sum=hours,  # Sum for this day
        )

        # Import the statistic (wrapped in try-except to prevent crashes)
        # Use async_add_external_statistics for external statistics (uses : delimiter)
        _LOGGER.info(
            "Importing runtime statistic: id=%s, date=%s, value=%.2fh",
            statistic_id, date_str, hours
        )
        try:
            async_add_external_statistics(self.hass, metadata, [statistic])
            _LOGGER.debug("Successfully imported runtime statistic for %s", date_str)
        except Exception as err:
            _LOGGER.warning(
                "Could not import runtime statistic for %s: %s (statistic_id=%s)",
                date_str, err, statistic_id
            )

    async def _import_all_runtime_history_statistics(self) -> None:
        """Import all existing runtime history data into statistics (called at startup)."""
        if not self._daily_runtime_history:
            _LOGGER.debug("No runtime history to import into statistics")
            return

        _LOGGER.info("Importing %d days of runtime history into statistics", len(self._daily_runtime_history))

        for date_str, hours in sorted(self._daily_runtime_history.items()):
            await self._import_runtime_statistics(date_str, hours)

        _LOGGER.info("Completed import of runtime history into statistics")

    def _calculate_fuel_consumption(self, elapsed_seconds: float) -> float:
        """Calculate fuel consumed based on power level and elapsed time.
        
        Returns fuel consumed in liters.
        """
        # Only consume fuel when actually running
        if self.data.get("running_step") != RUNNING_STEP_RUNNING:
            return 0.0
            
        power_level = self.data.get("set_level", 1)
        consumption_rate = FUEL_CONSUMPTION_TABLE.get(power_level, 0.16)  # L/h
        
        # Calculate fuel consumed in this interval
        hours_elapsed = elapsed_seconds / 3600.0
        fuel_consumed = consumption_rate * hours_elapsed
        
        return fuel_consumed

    def _update_fuel_tracking(self, elapsed_seconds: float) -> None:
        """Update fuel consumption tracking."""
        fuel_consumed = self._calculate_fuel_consumption(elapsed_seconds)

        if fuel_consumed > 0:
            self._total_fuel_consumed += fuel_consumed
            self._daily_fuel_consumed += fuel_consumed

        # Calculate instantaneous consumption rate
        power_level = self.data.get("set_level", 1)
        if self.data.get("running_step") == RUNNING_STEP_RUNNING:
            hourly_consumption = FUEL_CONSUMPTION_TABLE.get(power_level, 0.16)
        else:
            hourly_consumption = 0.0

        # Update data dictionary
        self.data["hourly_fuel_consumption"] = round(hourly_consumption, 2)
        self.data["daily_fuel_consumed"] = round(self._daily_fuel_consumed, 2)
        self.data["total_fuel_consumed"] = round(self._total_fuel_consumed, 2)

    def _update_runtime_tracking(self, elapsed_seconds: float) -> None:
        """Update runtime tracking."""
        # Only count runtime when heater is actually running
        if self.data.get("running_step") == RUNNING_STEP_RUNNING:
            self._total_runtime_seconds += elapsed_seconds
            self._daily_runtime_seconds += elapsed_seconds

        # Update data dictionary (convert to hours for display)
        self.data["daily_runtime_hours"] = round(self._daily_runtime_seconds / 3600.0, 2)
        self.data["total_runtime_hours"] = round(self._total_runtime_seconds / 3600.0, 2)

    async def _check_daily_reset(self) -> None:
        """Check if we need to reset daily fuel counter (runs every update, even if offline)."""
        current_date = datetime.now().date().isoformat()
        if current_date != self._last_reset_date:
            # Save yesterday's consumption to history before resetting
            if self._daily_fuel_consumed > 0:
                liters_consumed = round(self._daily_fuel_consumed, 2)
                self._daily_fuel_history[self._last_reset_date] = liters_consumed
                _LOGGER.info(
                    "New day detected: saved %s consumption (%.2fL) to history",
                    self._last_reset_date,
                    liters_consumed
                )

                # Import into statistics for native graphing
                await self._import_statistics(self._last_reset_date, liters_consumed)

            _LOGGER.info(
                "Resetting daily fuel counter from %.2fL to 0.0L (was %s, now %s)",
                self._daily_fuel_consumed,
                self._last_reset_date,
                current_date
            )

            self._daily_fuel_consumed = 0.0
            self._last_reset_date = current_date
            self.data["daily_fuel_consumed"] = 0.0

            # Clean old history and update data
            self._clean_old_history()
            self.data["daily_fuel_history"] = self._daily_fuel_history

            # Save immediately after reset to persist the new day and history
            await self.async_save_data()

    async def _check_daily_runtime_reset(self) -> None:
        """Check if we need to reset daily runtime counter (runs every update, even if offline)."""
        current_date = datetime.now().date().isoformat()
        if current_date != self._last_runtime_reset_date:
            # Save yesterday's runtime to history before resetting
            if self._daily_runtime_seconds > 0:
                hours_running = round(self._daily_runtime_seconds / 3600.0, 2)
                self._daily_runtime_history[self._last_runtime_reset_date] = hours_running
                _LOGGER.info(
                    "New day detected: saved %s runtime (%.2fh) to history",
                    self._last_runtime_reset_date,
                    hours_running
                )

                # Import into statistics for native graphing
                await self._import_runtime_statistics(self._last_runtime_reset_date, hours_running)

            _LOGGER.info(
                "Resetting daily runtime counter from %.2fh to 0.0h (was %s, now %s)",
                self._daily_runtime_seconds / 3600.0,
                self._last_runtime_reset_date,
                current_date
            )

            self._daily_runtime_seconds = 0.0
            self._last_runtime_reset_date = current_date
            self.data["daily_runtime_hours"] = 0.0

            # Clean old history and update data
            self._clean_old_runtime_history()
            self.data["daily_runtime_history"] = self._daily_runtime_history

            # Save immediately after reset to persist the new day and history
            await self.async_save_data()

    def _clear_sensor_values(self) -> None:
        """Clear sensor values to show as unavailable."""
        self.data["case_temperature"] = None
        self.data["cab_temperature"] = None
        self.data["supply_voltage"] = None
        self.data["running_step"] = None
        self.data["running_mode"] = None
        self.data["set_level"] = None
        self.data["altitude"] = None
        self.data["error_code"] = None
        self.data["hourly_fuel_consumption"] = None

    def _restore_stale_data(self) -> None:
        """Restore last valid sensor values during temporary connection issues."""
        if self._last_valid_data:
            for key in ["case_temperature", "cab_temperature", "supply_voltage",
                       "running_step", "running_mode", "set_level", "altitude",
                       "error_code", "hourly_fuel_consumption"]:
                if key in self._last_valid_data:
                    self.data[key] = self._last_valid_data[key]

    def _save_valid_data(self) -> None:
        """Save current sensor values as last valid data."""
        self._last_valid_data = {
            "case_temperature": self.data.get("case_temperature"),
            "cab_temperature": self.data.get("cab_temperature"),
            "supply_voltage": self.data.get("supply_voltage"),
            "running_step": self.data.get("running_step"),
            "running_mode": self.data.get("running_mode"),
            "set_level": self.data.get("set_level"),
            "altitude": self.data.get("altitude"),
            "error_code": self.data.get("error_code"),
            "hourly_fuel_consumption": self.data.get("hourly_fuel_consumption"),
        }

    def _handle_connection_failure(self, err: Exception) -> None:
        """Handle connection failure with stale data tolerance."""
        self._consecutive_failures += 1
        self.data["connected"] = False

        if self._consecutive_failures <= self._max_stale_cycles:
            # Keep last valid values for a few cycles
            self._restore_stale_data()
            _LOGGER.debug(
                "Connection failed (attempt %d/%d), keeping last values: %s",
                self._consecutive_failures,
                self._max_stale_cycles,
                err
            )
        else:
            # Too many failures, clear values
            self._clear_sensor_values()
            if self._consecutive_failures == self._max_stale_cycles + 1:
                _LOGGER.warning(
                    "Vevor Heater offline after %d attempts: %s",
                    self._consecutive_failures,
                    err
                )

    async def _async_update_data(self) -> dict[str, Any]:
        """Update data from the heater."""
        # Check for daily reset FIRST, even if heater is offline
        # This ensures the daily counters reset at midnight regardless of connection status
        await self._check_daily_reset()
        await self._check_daily_runtime_reset()

        if not self._client or not self._client.is_connected:
            try:
                await self._ensure_connected()
            except Exception as err:
                self._handle_connection_failure(err)
                raise UpdateFailed(f"Failed to connect: {err}")

        try:
            # Request status
            status = await self._send_command(1, 0, 85)

            if status:
                self.data["connected"] = True
                # Reset failure counter and save valid data on success
                self._consecutive_failures = 0
                self._save_valid_data()

                # Update fuel consumption and runtime tracking
                current_time = time.time()
                elapsed_seconds = current_time - self._last_update_time
                self._last_update_time = current_time

                self._update_fuel_tracking(elapsed_seconds)
                self._update_runtime_tracking(elapsed_seconds)

                # Save data periodically (every 5 minutes)
                if current_time - self._last_save_time >= 300:
                    await self.async_save_data()
                    self._last_save_time = current_time

                return self.data
            else:
                self._handle_connection_failure(Exception("No status received"))
                raise UpdateFailed("No status received from heater")

        except UpdateFailed:
            raise
        except Exception as err:
            _LOGGER.debug("Error updating data: %s", err)
            self._handle_connection_failure(err)
            raise UpdateFailed(f"Error updating data: {err}")

    async def _ensure_connected(self) -> None:
        """Ensure BLE connection is established with exponential backoff."""
        # Check if already connected
        if self._client and self._client.is_connected:
            self._connection_attempts = 0  # Reset on successful connection
            return

        # Clean up any stale client before attempting new connection
        await self._cleanup_connection()

        # Exponential backoff: 5s, 10s, 20s, 40s
        current_time = time.time()
        if self._connection_attempts > 0:
            backoff_delays = [5, 10, 20, 40]
            delay_index = min(self._connection_attempts - 1, len(backoff_delays) - 1)
            required_delay = backoff_delays[delay_index]
            time_since_last = current_time - self._last_connection_attempt

            if time_since_last < required_delay:
                remaining = required_delay - time_since_last
                _LOGGER.debug(
                    "Waiting %.1fs before reconnection attempt %d",
                    remaining,
                    self._connection_attempts + 1
                )
                await asyncio.sleep(remaining)

        self._connection_attempts += 1
        self._last_connection_attempt = time.time()

        _LOGGER.debug(
            "Connecting to Vevor Heater at %s (attempt %d)",
            self._ble_device.address,
            self._connection_attempts
        )

        try:
            # Establish connection with limited retries to avoid log spam
            # bleak_retry_connector will handle internal retries
            self._client = await establish_connection(
                BleakClient,
                self._ble_device,
                self._ble_device.address,
                max_attempts=3,  # Limit internal retries
            )

            # Verify services are available
            if not self._client.services:
                _LOGGER.warning("No services discovered, triggering service refresh")
                # Services might not be cached, disconnect and let next attempt retry
                await self._cleanup_connection()
                raise BleakError("No services available")

            # Get characteristic - try both UUID variants (FFE0/FFE1 and FFF0/FFF1)
            self._characteristic = None
            self._active_char_uuid = None

            # Define UUID pairs to try: (service_uuid, characteristic_uuid)
            uuid_pairs = [
                (SERVICE_UUID, CHARACTERISTIC_UUID),
                (SERVICE_UUID_ALT, CHARACTERISTIC_UUID_ALT),
            ]

            for service_uuid, char_uuid in uuid_pairs:
                for service in self._client.services:
                    if service.uuid.lower() == service_uuid.lower():
                        for char in service.characteristics:
                            if char.uuid.lower() == char_uuid.lower():
                                self._characteristic = char
                                self._active_char_uuid = char_uuid
                                _LOGGER.info(
                                    "Found heater characteristic: %s (service: %s)",
                                    char_uuid, service_uuid
                                )
                                break
                        if self._characteristic:
                            break
                if self._characteristic:
                    break

            if not self._characteristic:
                # Log available services for debugging
                available_services = [s.uuid for s in self._client.services]
                _LOGGER.error(
                    "Could not find heater characteristic. Available services: %s",
                    available_services
                )
                await self._cleanup_connection()
                raise BleakError("Could not find heater characteristic")

            # Start notifications on the discovered characteristic
            if "notify" in self._characteristic.properties:
                await self._client.start_notify(
                    self._active_char_uuid, self._notification_callback
                )
                _LOGGER.debug("Started notifications on %s", self._active_char_uuid)
            else:
                _LOGGER.warning("Characteristic does not support notify")

            # Send a wake-up ping to ensure device is responsive
            # Some heaters go into deep sleep and need a nudge
            _LOGGER.debug("Sending wake-up ping to device")
            await self._send_wake_up_ping()

            self._connection_attempts = 0  # Reset on successful connection
            _LOGGER.info("Successfully connected to Vevor Heater")

        except Exception as err:
            # Clean up on any connection failure
            await self._cleanup_connection()
            raise

    @callback
    def _notification_callback(self, _sender: int, data: bytearray) -> None:
        """Handle notification from heater."""
        # Log ALL received data for debugging
        _LOGGER.info(
            "📩 Received BLE data (%d bytes): %s",
            len(data),
            data.hex()
        )
        try:
            self._parse_response(data)
        except Exception as err:
            _LOGGER.error("Error parsing notification: %s", err)

    def _parse_response(self, data: bytearray) -> None:
        """Parse response from heater."""
        if len(data) < 17:
            _LOGGER.debug("Response too short: %d bytes", len(data))
            return

        # Check protocol type
        header = (_u8_to_number(data[0]) << 8) | _u8_to_number(data[1])
        old_protocol = self._protocol_mode

        if header == 0xAA55 and len(data) in (18, 20):
            # Protocol 1: 0xAA 0x55, 18-20 bytes, not encrypted
            _LOGGER.info("🔍 Detected protocol: AA55 unencrypted (mode=1, %d bytes)", len(data))
            self._parse_protocol_aa55(data)
        elif header == 0xAA66 and len(data) == 20:
            # Protocol 3: 0xAA 0x66, 20 bytes, not encrypted
            _LOGGER.info("🔍 Detected protocol: AA66 unencrypted (mode=3)")
            self._parse_protocol_aa66(data)
        elif len(data) == 48:
            # Protocol 2/4: 48 bytes, encrypted
            decrypted = _decrypt_data(data)
            header = (_u8_to_number(decrypted[0]) << 8) | _u8_to_number(decrypted[1])
            _LOGGER.debug("Decrypted header: 0x%04X", header)

            if header == 0xAA55:
                _LOGGER.info("🔍 Detected protocol: AA55 encrypted (mode=2)")
                self._parse_protocol_aa55_encrypted(decrypted)
            elif header == 0xAA66:
                _LOGGER.info("🔍 Detected protocol: AA66 encrypted (mode=4)")
                self._parse_protocol_aa66_encrypted(decrypted)
            else:
                _LOGGER.warning(
                    "🔍 Unknown encrypted protocol, decrypted header: 0x%04X",
                    header
                )
        else:
            _LOGGER.warning(
                "🔍 Unknown protocol, length: %d, header: 0x%04X",
                len(data), header
            )

        # Log protocol change
        if old_protocol != self._protocol_mode:
            _LOGGER.info(
                "📋 Protocol mode changed: %d → %d (commands will now use %s format)",
                old_protocol, self._protocol_mode,
                "AA66 encrypted" if self._protocol_mode == 4 else
                "AA66 unencrypted" if self._protocol_mode == 3 else
                "AA55 encrypted" if self._protocol_mode == 2 else
                "AA55 unencrypted"
            )

    def _parse_protocol_aa55(self, data: bytearray) -> None:
        """Parse protocol AA55 (18-20 bytes, unencrypted)."""
        self._protocol_mode = 1
        
        self.data["running_state"] = _u8_to_number(data[3])
        self.data["error_code"] = _u8_to_number(data[4])
        self.data["running_step"] = _u8_to_number(data[5])
        self.data["altitude"] = _u8_to_number(data[6]) + 256 * _u8_to_number(data[7])
        self.data["running_mode"] = _u8_to_number(data[8])
        
        if self.data["running_mode"] == RUNNING_MODE_LEVEL:
            self.data["set_level"] = _u8_to_number(data[9])
        elif self.data["running_mode"] == RUNNING_MODE_TEMPERATURE:
            self.data["set_temp"] = _u8_to_number(data[9])
            self.data["set_level"] = _u8_to_number(data[10]) + 1
        elif self.data["running_mode"] == RUNNING_MODE_MANUAL:
            self.data["set_level"] = _u8_to_number(data[10]) + 1
        
        self.data["supply_voltage"] = (
            (256 * _u8_to_number(data[12]) + _u8_to_number(data[11])) / 10
        )
        self.data["case_temperature"] = _unsign_to_sign(256 * data[14] + data[13])
        self.data["cab_temperature"] = _unsign_to_sign(256 * data[16] + data[15])

        # Apply temperature calibration
        self._apply_temperature_calibration()

        _LOGGER.debug("Parsed AA55: %s", self.data)
        self._notification_data = data

    def _parse_protocol_aa66(self, data: bytearray) -> None:
        """Parse protocol AA66 (20 bytes, unencrypted) - BYD/Vevor variant."""
        self._protocol_mode = 3

        # Based on actual BYD heater response: aa660101000382000219008b009b001a000000e1
        # Byte 3: running state (0=OFF, 1=ON)
        self.data["running_state"] = _u8_to_number(data[3])

        # Byte 4: error code
        self.data["error_code"] = _u8_to_number(data[4])

        # Byte 5: running step
        self.data["running_step"] = _u8_to_number(data[5])

        # Byte 6: altitude compensation (0x82 = 130 → stored as is, not multiplied)
        self.data["altitude"] = _u8_to_number(data[6])

        # Byte 8: running mode (0=Manual, 1=Level, 2=Temperature)
        self.data["running_mode"] = _u8_to_number(data[8])

        # Byte 9: set level or temperature depending on mode
        if self.data["running_mode"] == RUNNING_MODE_LEVEL:
            self.data["set_level"] = max(1, min(10, _u8_to_number(data[9])))
        elif self.data["running_mode"] == RUNNING_MODE_TEMPERATURE:
            self.data["set_temp"] = max(8, min(36, _u8_to_number(data[9])))

        # Bytes 11-12: Supply voltage in 0.1V (little endian)
        # 0x8b 0x00 = 0x008b = 139 → 139 * 0.1 = 13.9V
        voltage_raw = _u8_to_number(data[11]) | (_u8_to_number(data[12]) << 8)
        self.data["supply_voltage"] = voltage_raw / 10.0

        # Bytes 13-14: Case temperature (little endian)
        # Some heaters send 0.1°C format (need /10), others send direct °C
        # Auto-detect: if raw > 350, definitely 0.1°C format (350°C case is impossible)
        case_temp_raw = _u8_to_number(data[13]) | (_u8_to_number(data[14]) << 8)
        if case_temp_raw > 350:
            self.data["case_temperature"] = case_temp_raw / 10.0
        else:
            self.data["case_temperature"] = float(case_temp_raw)

        # Byte 15: Cabin/interior temperature in °C (direct value)
        # 0x1a = 26 → 26°C
        self.data["cab_temperature"] = _u8_to_number(data[15])

        # Apply temperature calibration
        self._apply_temperature_calibration()

        _LOGGER.debug("Parsed AA66: %s", self.data)
        self._notification_data = data

    def _parse_protocol_aa55_encrypted(self, data: bytearray) -> None:
        """Parse encrypted protocol AA55 (48 bytes)."""
        self._protocol_mode = 2
        
        self.data["running_state"] = _u8_to_number(data[3])
        self.data["error_code"] = _u8_to_number(data[4])
        self.data["running_step"] = _u8_to_number(data[5])
        self.data["altitude"] = (_u8_to_number(data[7]) + 256 * _u8_to_number(data[6])) / 10
        self.data["running_mode"] = _u8_to_number(data[8])
        self.data["set_level"] = max(1, min(10, _u8_to_number(data[10])))
        self.data["set_temp"] = max(8, min(36, _u8_to_number(data[9])))
        
        self.data["supply_voltage"] = (256 * data[11] + data[12]) / 10
        self.data["case_temperature"] = _unsign_to_sign(256 * data[13] + data[14])
        self.data["cab_temperature"] = _unsign_to_sign(256 * data[32] + data[33]) / 10

        # Apply temperature calibration
        self._apply_temperature_calibration()

        _LOGGER.debug("Parsed AA55 encrypted: %s", self.data)
        self._notification_data = data

    def _parse_protocol_aa66_encrypted(self, data: bytearray) -> None:
        """Parse encrypted protocol AA66 (48 bytes).

        Protocol byte mapping (from warehog/esphome-diesel-heater-ble):
        - Byte 27: Temperature unit (0=Celsius, 1=Fahrenheit)
        - Byte 31: Automatic Start/Stop flag (0=disabled, 1=enabled)
        """
        self._protocol_mode = 4

        self.data["running_state"] = _u8_to_number(data[3])
        self.data["error_code"] = _u8_to_number(data[35])  # Different position!
        self.data["running_step"] = _u8_to_number(data[5])
        self.data["altitude"] = (_u8_to_number(data[7]) + 256 * _u8_to_number(data[6])) / 10
        self.data["running_mode"] = _u8_to_number(data[8])
        self.data["set_level"] = max(1, min(10, _u8_to_number(data[10])))

        # Byte 27: Temperature unit detection (more reliable than >50 heuristic)
        # 0 = Celsius, 1 = Fahrenheit
        temp_unit_byte = _u8_to_number(data[27])
        self._heater_uses_fahrenheit = (temp_unit_byte == 1)
        _LOGGER.debug("🌡️ Temperature unit byte 27: %d (%s)",
                     temp_unit_byte, "Fahrenheit" if self._heater_uses_fahrenheit else "Celsius")

        # Read raw set_temp value
        raw_set_temp = _u8_to_number(data[9])
        _LOGGER.debug("🌡️ Raw set_temp from heater: %d (byte 9)", raw_set_temp)

        # Convert to Celsius if heater uses Fahrenheit
        if self._heater_uses_fahrenheit:
            set_temp_celsius = round((raw_set_temp - 32) * 5 / 9)
            _LOGGER.debug("🌡️ Converted from Fahrenheit: %d°F → %d°C", raw_set_temp, set_temp_celsius)
            self.data["set_temp"] = max(8, min(36, set_temp_celsius))
        else:
            _LOGGER.debug("🌡️ Heater uses Celsius: %d°C", raw_set_temp)
            self.data["set_temp"] = max(8, min(36, raw_set_temp))

        # Byte 31: Automatic Start/Stop flag
        # When enabled in Temperature mode, heater will stop when room reaches target temp
        auto_start_stop_byte = _u8_to_number(data[31])
        self.data["auto_start_stop"] = (auto_start_stop_byte == 1)
        _LOGGER.debug("🔄 Auto Start/Stop byte 31: %d (%s)",
                     auto_start_stop_byte, "Enabled" if self.data["auto_start_stop"] else "Disabled")

        self.data["supply_voltage"] = (256 * data[11] + data[12]) / 10
        self.data["case_temperature"] = _unsign_to_sign(256 * data[13] + data[14])
        self.data["cab_temperature"] = _unsign_to_sign(256 * data[32] + data[33]) / 10

        # Apply temperature calibration
        self._apply_temperature_calibration()

        _LOGGER.debug("Parsed AA66 encrypted: %s", self.data)
        self._notification_data = data

    def _apply_temperature_calibration(self) -> None:
        """Apply temperature offset calibration to cab_temperature.

        Applies both manual offset (from config) and auto offset (from external sensor).
        Total offset = manual_offset + auto_offset
        """
        # Get configured manual offset (default to 0.0 if not set)
        manual_offset = self.config_entry.data.get(CONF_TEMPERATURE_OFFSET, DEFAULT_TEMPERATURE_OFFSET)

        # Get raw temperature
        raw_temp = self.data.get("cab_temperature")
        if raw_temp is None:
            return

        # Calculate total offset (manual + auto)
        total_offset = manual_offset + self._current_auto_offset

        # Apply combined offset
        calibrated_temp = raw_temp + total_offset

        # Clamp to sensor range
        calibrated_temp = max(SENSOR_TEMP_MIN, min(SENSOR_TEMP_MAX, calibrated_temp))

        # Round to 1 decimal place
        calibrated_temp = round(calibrated_temp, 1)

        # Update data with calibrated value
        self.data["cab_temperature"] = calibrated_temp

        # Log calibration if any offset is applied
        if total_offset != 0.0:
            _LOGGER.debug(
                "Applied temperature calibration: raw=%s°C, manual=%s°C, auto=%s°C, total=%s°C, calibrated=%s°C",
                raw_temp, manual_offset, self._current_auto_offset, total_offset, calibrated_temp
            )

    async def _cleanup_connection(self) -> None:
        """Clean up BLE connection properly."""
        if self._client:
            try:
                if self._client.is_connected:
                    # Stop notifications using the active UUID
                    if self._characteristic and self._active_char_uuid and "notify" in self._characteristic.properties:
                        try:
                            await self._client.stop_notify(self._active_char_uuid)
                            _LOGGER.debug("Stopped notifications on %s", self._active_char_uuid)
                        except Exception as err:
                            _LOGGER.debug("Could not stop notifications: %s", err)

                    # Disconnect
                    await self._client.disconnect()
                    _LOGGER.debug("Disconnected from heater")
            except Exception as err:
                _LOGGER.debug("Error during cleanup: %s", err)
            finally:
                self._client = None
                self._characteristic = None
                self._active_char_uuid = None

    async def _send_wake_up_ping(self) -> None:
        """Send a wake-up ping to the device to ensure it's responsive."""
        try:
            # Send a simple status request to wake the device
            # Don't wait for response, just send it
            packet = bytearray([0xAA, 85, 0, 0, 0, 0, 0, 0])
            packet[2] = self._passkey // 100
            packet[3] = self._passkey % 100
            packet[4] = 1  # Status command
            packet[5] = 0
            packet[6] = 0
            packet[7] = (packet[2] + packet[3] + packet[4] + packet[5] + packet[6]) % 256

            if self._client and self._characteristic:
                await self._client.write_gatt_char(self._characteristic, packet, response=False)
                await asyncio.sleep(0.5)  # Give device time to wake up
                _LOGGER.debug("Wake-up ping sent")
        except Exception as err:
            _LOGGER.debug("Wake-up ping failed (non-critical): %s", err)

    def _build_command_packet(self, command: int, argument: int) -> bytearray:
        """Build command packet for the heater.

        IMPORTANT DISCOVERY: The heater ALWAYS accepts AA55 commands,
        regardless of what protocol it uses for responses!

        - Heater accepts: AA55 unencrypted 8-byte commands
        - Heater responds: AA66 encrypted 48-byte data (for newer models)

        The response protocol (AA55 vs AA66, encrypted vs not) only affects
        how we PARSE responses, not how we SEND commands.
        """
        _LOGGER.info(
            "🔧 Building command packet: protocol_mode=%d, cmd=%d, arg=%d",
            self._protocol_mode, command, argument
        )

        # ALWAYS use AA55 header for commands - the heater only accepts AA55!
        # This was discovered through testing: AA66 commands are ignored,
        # but AA55 commands work even when heater responds with AA66 data.
        header_byte = 0x55
        _LOGGER.debug("Using AA55 protocol header (heater only accepts AA55 commands)")

        # Build 8-byte command packet (ALWAYS unencrypted AA55)
        packet = bytearray([0xAA, header_byte, 0, 0, 0, 0, 0, 0])
        packet[2] = self._passkey // 100
        packet[3] = self._passkey % 100
        packet[4] = command % 256
        packet[5] = argument % 256
        packet[6] = argument // 256
        packet[7] = (packet[2] + packet[3] + packet[4] + packet[5] + packet[6]) % 256

        _LOGGER.debug("Command packet (8 bytes, AA55): %s", packet.hex())

        return packet

    async def _send_command(self, command: int, argument: int, n: int = 85, timeout: float = 5.0) -> bool:
        """Send command to heater with configurable timeout.

        Args:
            command: Command code (1=status, 2=mode, 3=on/off, 4=level/temp)
            argument: Command argument
            n: Legacy parameter (ignored, kept for compatibility)
            timeout: Timeout in seconds for waiting response
        """
        if not self._client or not self._client.is_connected:
            _LOGGER.error(
                "Cannot send command: heater not connected. "
                "The integration will attempt to reconnect automatically."
            )
            return False

        if not self._characteristic:
            _LOGGER.error(
                "Cannot send command: BLE characteristic not found. "
                "Try reloading the integration."
            )
            return False

        # Build protocol-aware command packet
        packet = self._build_command_packet(command, argument)

        _LOGGER.info(
            "📤 Sending command: %s (cmd=%d, arg=%d, protocol=%d, len=%d)",
            packet.hex(), command, argument, self._protocol_mode, len(packet)
        )

        try:
            self._notification_data = None
            # Use response=False to avoid authorization issues with BLE proxies
            # (e.g., ESPHome BLE proxy). The heater sends a notification as response.
            await self._client.write_gatt_char(self._characteristic, packet, response=False)
            _LOGGER.debug("Command written to BLE characteristic")

            # Wait for notification with configurable timeout
            # Increased from 2s to 5s default to handle slow BLE responses
            iterations = int(timeout / 0.1)
            for i in range(iterations):
                await asyncio.sleep(0.1)
                if self._notification_data:
                    _LOGGER.info(
                        "✅ Received response after %.1fs (protocol=%d)",
                        i * 0.1, self._protocol_mode
                    )
                    return True

            _LOGGER.warning("⚠️ No response received after %.1fs", timeout)
            return False

        except Exception as err:
            _LOGGER.error("❌ Error sending command: %s", err)
            # On write error, the connection might be dead
            await self._cleanup_connection()
            return False

    async def async_turn_on(self) -> None:
        """Turn heater on."""
        # Command 3, arg=1 for ON (verified with BYD heater)
        success = await self._send_command(3, 1, 85)
        if success:
            await self.async_request_refresh()

    async def async_turn_off(self) -> None:
        """Turn heater off."""
        # Command 3, arg=0 for OFF (verified with BYD heater)
        success = await self._send_command(3, 0, 85)
        if success:
            await self.async_request_refresh()

    async def async_set_level(self, level: int) -> None:
        """Set heater level (1-10)."""
        # Command 4 for level (verified with BYD heater)
        level = max(1, min(10, level))
        success = await self._send_command(4, level, 85)
        if success:
            await self.async_request_refresh()

    async def async_set_temperature(self, temperature: int) -> None:
        """Set target temperature (8-36°C).

        Note: Temperature mode only accepts values 8-36°C.
        Values below 8 will be clamped to 8.

        The temperature unit (Celsius or Fahrenheit) is auto-detected from the
        heater's response. We send commands in the same unit the heater uses.
        """
        # Clamp to valid Celsius range
        temperature = max(8, min(36, temperature))
        current_temp = self.data.get("set_temp", "unknown")
        current_mode = self.data.get("running_mode", "unknown")

        # Send temperature in the unit the heater expects (detected from response)
        # Some mode 4 heaters use Fahrenheit, others use Celsius
        if self._heater_uses_fahrenheit:
            temp_fahrenheit = round(temperature * 9 / 5 + 32)
            _LOGGER.info(
                "🌡️ SET TEMPERATURE REQUEST: target=%d°C (%d°F), current=%s, mode=%s, protocol=%d (heater uses Fahrenheit)",
                temperature, temp_fahrenheit, current_temp, current_mode, self._protocol_mode
            )
            command_temp = temp_fahrenheit
        else:
            _LOGGER.info(
                "🌡️ SET TEMPERATURE REQUEST: target=%d°C, current=%s, mode=%s, protocol=%d (heater uses Celsius)",
                temperature, current_temp, current_mode, self._protocol_mode
            )
            command_temp = temperature

        success = await self._send_command(4, command_temp, 85)

        if success:
            await self.async_request_refresh()
            # Log result after refresh
            new_temp = self.data.get("set_temp", "unknown")
            _LOGGER.info(
                "🌡️ SET TEMPERATURE RESULT: requested=%d°C, heater_reports=%s°C, %s",
                temperature, new_temp,
                "✅ SUCCESS" if new_temp == temperature else "❌ FAILED - heater did not accept"
            )
        else:
            _LOGGER.warning("🌡️ SET TEMPERATURE FAILED: command not sent successfully")

    async def async_set_mode(self, mode: int) -> None:
        """Set running mode (0=Manual, 1=Level, 2=Temperature)."""
        # Command 2 for mode (needs verification)
        mode = max(0, min(2, mode))
        _LOGGER.info("Setting running mode to %d", mode)
        success = await self._send_command(2, mode, 85)
        if success:
            await self.async_request_refresh()

    async def async_set_auto_start_stop(self, enabled: bool) -> None:
        """Set Automatic Start/Stop mode (cmd 18).

        When enabled in Temperature mode, the heater will completely stop
        when the room temperature reaches 2°C above the target, and restart
        when it drops 2°C below the target.
        """
        _LOGGER.info("Setting Auto Start/Stop to %s", "enabled" if enabled else "disabled")
        # Command 18, arg=1 for enabled, arg=0 for disabled
        success = await self._send_command(18, 1 if enabled else 0, 85)
        if success:
            await self.async_request_refresh()

    async def async_sync_time(self) -> None:
        """Sync heater time with Home Assistant time (cmd 10).

        The time is sent as: 60 * hours + minutes
        Example: 14:30 = 60 * 14 + 30 = 870
        """
        now = datetime.now()
        time_value = 60 * now.hour + now.minute
        _LOGGER.info("Syncing heater time to %02d:%02d (value=%d)", now.hour, now.minute, time_value)
        # Command 10 for time sync
        success = await self._send_command(10, time_value, 85)
        if success:
            _LOGGER.info("✅ Time sync successful")
        else:
            _LOGGER.warning("❌ Time sync failed")

    async def async_shutdown(self) -> None:
        """Shutdown coordinator."""
        _LOGGER.debug("Shutting down Vevor Heater coordinator")

        # Clean up external sensor listener
        if self._auto_offset_unsub:
            self._auto_offset_unsub()
            self._auto_offset_unsub = None

        await self._cleanup_connection()
