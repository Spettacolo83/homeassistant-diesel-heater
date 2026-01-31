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
    ABBA_CMD_STATUS,
    ABBA_NOTIFY_UUID,
    ABBA_SERVICE_UUID,
    ABBA_WRITE_UUID,
    AUTO_OFFSET_THRESHOLD,
    AUTO_OFFSET_THROTTLE_SECONDS,
    CHARACTERISTIC_UUID,
    CHARACTERISTIC_UUID_ALT,
    CONF_AUTO_OFFSET_ENABLED,
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
    MAX_HEATER_OFFSET,
    MAX_HISTORY_DAYS,
    MIN_HEATER_OFFSET,
    NOTIFY_UUID,
    PROTOCOL_HEADER_ABBA,
    PROTOCOL_HEADER_CBFF,
    PROTOCOL_HEADER_AA77,
    CBFF_RUN_STATE_OFF,
    ABBA_ERROR_NAMES,
    ABBA_STATUS_MAP,
    RUNNING_MODE_LEVEL,
    RUNNING_MODE_MANUAL,
    RUNNING_MODE_TEMPERATURE,
    RUNNING_STEP_COOLDOWN,
    RUNNING_STEP_RUNNING,
    RUNNING_STEP_STANDBY,
    RUNNING_STEP_VENTILATION,
    SENSOR_TEMP_MAX,
    SENSOR_TEMP_MIN,
    SERVICE_UUID,
    SERVICE_UUID_ALT,
    STORAGE_KEY_AUTO_OFFSET_ENABLED,
    STORAGE_KEY_FUEL_SINCE_RESET,
    STORAGE_KEY_LAST_REFUELED,
    STORAGE_KEY_TANK_CAPACITY,
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


class _HeaterLoggerAdapter(logging.LoggerAdapter):
    """Logger adapter that prefixes messages with heater ID."""

    def process(self, msg, kwargs):
        return f"[{self.extra['heater_id']}] {msg}", kwargs


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
        # Per-instance logger with heater ID prefix for multi-heater support
        self._logger = _HeaterLoggerAdapter(
            _LOGGER, {"heater_id": ble_device.address[-5:]}
        )
        self._client: BleakClient | None = None
        self._characteristic = None
        self._active_char_uuid: str | None = None  # Track which UUID variant is active
        self._notification_data: bytearray | None = None
        # Get passkey from config, default to 1234 (factory default for most heaters)
        self._passkey = config_entry.data.get(CONF_PIN, DEFAULT_PIN)
        self._protocol_mode = 0  # Will be detected from response (1-4 Vevor, 5 ABBA)
        self._is_abba_device = False  # True if using ABBA/HeaterCC protocol
        self._abba_write_char = None  # ABBA devices use separate write characteristic
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
            "cab_temperature_raw": None,  # Raw temperature before any offset
            "heater_offset": 0,  # Current offset sent to heater (cmd 20)
            "connected": False,
            "auto_start_stop": None,  # Automatic Start/Stop flag (byte 31)
            "auto_offset_enabled": False,  # Auto offset adjustment enabled
            # Configuration settings (bytes 26-30)
            "language": None,  # byte 26: Voice notification language
            "temp_unit": None,  # byte 27: 0=Celsius, 1=Fahrenheit
            "tank_volume": None,  # byte 28: Tank volume in liters
            "pump_type": None,  # byte 29: Oil pump type
            "altitude_unit": None,  # byte 30: 0=Meters, 1=Feet
            "rf433_enabled": None,  # byte 29 value 20/21 indicates RF433 status
            # Fuel consumption tracking
            "hourly_fuel_consumption": None,
            "daily_fuel_consumed": 0.0,
            "total_fuel_consumed": 0.0,
            # Runtime tracking
            "daily_runtime_hours": 0.0,
            "total_runtime_hours": 0.0,
            # Fuel level tracking
            "tank_capacity": None,  # User-defined tank capacity in liters (1-100)
            "fuel_remaining": None,
            "fuel_consumed_since_reset": 0.0,
            "last_refueled": None,  # ISO timestamp of last refuel reset
        }

        # Fuel consumption tracking (minimal)
        self._store = Store(hass, 1, f"{DOMAIN}_{ble_device.address}")
        self._last_update_time: float = time.time()
        self._total_fuel_consumed: float = 0.0
        self._daily_fuel_consumed: float = 0.0
        self._daily_fuel_history: dict[str, float] = {}  # date -> liters consumed
        self._fuel_consumed_since_reset: float = 0.0  # Fuel since last refuel reset
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
        self._current_heater_offset: int = 0  # Current offset sent to heater via cmd 12

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
                        self._logger.info("New day detected at startup, resetting daily fuel counter")
                        # Save yesterday's consumption to history before resetting
                        if self._daily_fuel_consumed > 0:
                            self._daily_fuel_history[saved_date] = round(self._daily_fuel_consumed, 2)
                            self._logger.info("Saved %s: %.2fL to history", saved_date, self._daily_fuel_consumed)
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
                        self._logger.info("New day detected at startup, resetting daily runtime counter")
                        # Save yesterday's runtime to history before resetting
                        if self._daily_runtime_seconds > 0:
                            hours = round(self._daily_runtime_seconds / 3600.0, 2)
                            self._daily_runtime_history[saved_runtime_date] = hours
                            self._logger.info("Saved %s: %.2fh to runtime history", saved_runtime_date, hours)
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

                self._logger.debug(
                    "Loaded fuel data: total=%.2fL, daily=%.2fL, history entries=%d",
                    self._total_fuel_consumed,
                    self._daily_fuel_consumed,
                    len(self._daily_fuel_history)
                )
                self._logger.debug(
                    "Loaded runtime data: total=%.2fh, daily=%.2fh, history entries=%d",
                    self._total_runtime_seconds / 3600.0,
                    self._daily_runtime_seconds / 3600.0,
                    len(self._daily_runtime_history)
                )

                # Load fuel level tracking
                self._fuel_consumed_since_reset = data.get(STORAGE_KEY_FUEL_SINCE_RESET, 0.0)
                self.data["fuel_consumed_since_reset"] = round(self._fuel_consumed_since_reset, 2)
                tank_capacity = data.get(STORAGE_KEY_TANK_CAPACITY)
                if tank_capacity is not None:
                    self.data["tank_capacity"] = tank_capacity
                last_refueled = data.get(STORAGE_KEY_LAST_REFUELED)
                if last_refueled is not None:
                    self.data["last_refueled"] = last_refueled
                self._update_fuel_remaining()
                self._logger.debug(
                    "Loaded fuel level data: consumed_since_reset=%.2fL, tank_capacity=%s, last_refueled=%s",
                    self._fuel_consumed_since_reset, self.data.get("tank_capacity"), self.data.get("last_refueled")
                )

                # Load auto offset enabled state
                auto_offset_enabled = data.get(STORAGE_KEY_AUTO_OFFSET_ENABLED, False)
                self.data["auto_offset_enabled"] = auto_offset_enabled
                self._logger.debug("Loaded auto_offset_enabled: %s", auto_offset_enabled)

                # Import existing history into statistics for native graphing
                await self._import_all_history_statistics()
                await self._import_all_runtime_history_statistics()
        except Exception as err:
            self._logger.warning("Could not load data: %s", err)

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
            self._logger.debug("No external temperature sensor configured")
            return

        self._logger.info(
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
        The offset is sent to the heater via BLE command 12, so the heater itself
        uses the corrected temperature for auto-start/stop logic.

        The offset is limited by CONF_AUTO_OFFSET_MAX and throttled to avoid
        frequent BLE commands.
        """
        # Check if auto offset is enabled
        if not self.data.get("auto_offset_enabled", False):
            self._logger.debug("Auto offset disabled")
            return

        external_sensor = self.config_entry.data.get(CONF_EXTERNAL_TEMP_SENSOR, "")
        if not external_sensor:
            self._logger.debug("No external temperature sensor configured")
            return

        # Throttle offset updates to avoid too many BLE commands
        current_time = time.time()
        if current_time - self._last_auto_offset_time < AUTO_OFFSET_THROTTLE_SECONDS:
            self._logger.debug("Auto offset throttled (last update %.0fs ago)",
                         current_time - self._last_auto_offset_time)
            return

        # Get external sensor state
        state = self.hass.states.get(external_sensor)
        if state is None or state.state in ("unknown", "unavailable"):
            self._logger.debug("External sensor %s unavailable", external_sensor)
            return

        try:
            external_temp = float(state.state)
        except (ValueError, TypeError):
            self._logger.warning("Invalid external sensor value: %s", state.state)
            return

        # Get heater's raw cab temperature (before any offset)
        raw_heater_temp = self.data.get("cab_temperature_raw")
        if raw_heater_temp is None:
            self._logger.debug("Heater raw temperature not available yet")
            return

        # Round external temp to nearest integer (heater only accepts integer offset)
        external_temp_rounded = round(external_temp)

        # Calculate the difference: positive offset means heater reads lower than external
        # If external=22°C and heater=25°C, we need offset=-3 to make heater think it's 22°C
        difference = external_temp_rounded - raw_heater_temp

        # Only adjust if difference is significant (>= 1°C)
        if abs(difference) < AUTO_OFFSET_THRESHOLD:
            self._logger.debug(
                "Auto offset: difference (%.1f°C) below threshold (%.1f°C), no adjustment",
                difference, AUTO_OFFSET_THRESHOLD
            )
            return

        # Calculate new offset (clamped to -max to +max range)
        # Both positive and negative offsets now work via BLE
        max_offset = self.config_entry.data.get(CONF_AUTO_OFFSET_MAX, DEFAULT_AUTO_OFFSET_MAX)
        max_offset = min(max_offset, MAX_HEATER_OFFSET)  # Cap at 10
        new_offset = int(max(-max_offset, min(max_offset, difference)))

        # Only send command if offset changed
        if new_offset != self._current_heater_offset:
            old_offset = self._current_heater_offset
            self._last_auto_offset_time = current_time

            self._logger.info(
                "Auto offset: external=%.1f°C (rounded=%d), heater_raw=%.1f°C, "
                "difference=%.1f°C, sending offset: %d → +%d°C",
                external_temp, external_temp_rounded, raw_heater_temp,
                difference, old_offset, new_offset
            )

            # Send the offset command to the heater
            await self.async_set_heater_offset(new_offset)

    async def async_save_data(self) -> None:
        """Save persistent fuel consumption, runtime data, and settings."""
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
                # Fuel level tracking
                STORAGE_KEY_FUEL_SINCE_RESET: self._fuel_consumed_since_reset,
                STORAGE_KEY_TANK_CAPACITY: self.data.get("tank_capacity"),
                STORAGE_KEY_LAST_REFUELED: self.data.get("last_refueled"),
                # Settings
                STORAGE_KEY_AUTO_OFFSET_ENABLED: self.data.get("auto_offset_enabled", False),
            }
            await self._store.async_save(data)
            self._logger.debug(
                "Saved data: fuel history=%d entries, runtime history=%d entries, auto_offset=%s",
                len(self._daily_fuel_history),
                len(self._daily_runtime_history),
                self.data.get("auto_offset_enabled", False)
            )
        except Exception as err:
            self._logger.warning("Could not save data: %s", err)

    def _clean_old_history(self) -> None:
        """Remove history entries older than MAX_HISTORY_DAYS."""
        if not self._daily_fuel_history:
            return

        cutoff_date = (datetime.now().date() - timedelta(days=MAX_HISTORY_DAYS)).isoformat()
        old_keys = [date for date in self._daily_fuel_history if date < cutoff_date]

        for date in old_keys:
            del self._daily_fuel_history[date]

        if old_keys:
            self._logger.debug("Removed %d old fuel history entries (before %s)", len(old_keys), cutoff_date)

    def _clean_old_runtime_history(self) -> None:
        """Remove runtime history entries older than MAX_HISTORY_DAYS."""
        if not self._daily_runtime_history:
            return

        cutoff_date = (datetime.now().date() - timedelta(days=MAX_HISTORY_DAYS)).isoformat()
        old_keys = [date for date in self._daily_runtime_history if date < cutoff_date]

        for date in old_keys:
            del self._daily_runtime_history[date]

        if old_keys:
            self._logger.debug("Removed %d old runtime history entries (before %s)", len(old_keys), cutoff_date)

    async def _import_statistics(self, date_str: str, liters: float) -> None:
        """Import daily fuel consumption into Home Assistant statistics for graphing."""
        # Skip if recorder is not available
        if not (recorder := get_instance(self.hass)):
            self._logger.debug("Recorder not available, skipping statistics import")
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
            unit_class="volume",
        )

        # Parse date and create timestamp at midnight (start of hour required by HA)
        try:
            date_obj = datetime.fromisoformat(date_str)
            # Use midnight (00:00:00) - HA requires timestamps at top of hour
            midnight = datetime.combine(date_obj.date(), datetime.min.time())
            # Make it timezone-aware
            timestamp = dt_util.as_utc(midnight)
        except (ValueError, TypeError) as err:
            self._logger.error("Failed to parse date %s: %s", date_str, err)
            return

        # Create statistic data point
        statistic = StatisticData(
            start=timestamp,
            state=liters,
            sum=liters,  # Sum for this day
        )

        # Import the statistic (wrapped in try-except to prevent crashes)
        # Use async_add_external_statistics for external statistics (uses : delimiter)
        self._logger.info(
            "Importing fuel statistic: id=%s, date=%s, value=%.2fL",
            statistic_id, date_str, liters
        )
        try:
            async_add_external_statistics(self.hass, metadata, [statistic])
            self._logger.debug("Successfully imported fuel statistic for %s", date_str)
        except Exception as err:
            self._logger.warning(
                "Could not import fuel statistic for %s: %s (statistic_id=%s)",
                date_str, err, statistic_id
            )

    async def _import_all_history_statistics(self) -> None:
        """Import all existing history data into statistics (called at startup)."""
        if not self._daily_fuel_history:
            self._logger.debug("No history to import into statistics")
            return

        self._logger.info("Importing %d days of fuel history into statistics", len(self._daily_fuel_history))

        for date_str, liters in sorted(self._daily_fuel_history.items()):
            await self._import_statistics(date_str, liters)

        self._logger.info("Completed import of fuel history into statistics")

    async def _import_runtime_statistics(self, date_str: str, hours: float) -> None:
        """Import daily runtime into Home Assistant statistics for graphing."""
        # Skip if recorder is not available
        if not (recorder := get_instance(self.hass)):
            self._logger.debug("Recorder not available, skipping runtime statistics import")
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
            unit_class="duration",
        )

        # Parse date and create timestamp at midnight (start of hour required by HA)
        try:
            date_obj = datetime.fromisoformat(date_str)
            # Use midnight (00:00:00) - HA requires timestamps at top of hour
            midnight = datetime.combine(date_obj.date(), datetime.min.time())
            # Make it timezone-aware
            timestamp = dt_util.as_utc(midnight)
        except (ValueError, TypeError) as err:
            self._logger.error("Failed to parse date %s: %s", date_str, err)
            return

        # Create statistic data point
        statistic = StatisticData(
            start=timestamp,
            state=hours,
            sum=hours,  # Sum for this day
        )

        # Import the statistic (wrapped in try-except to prevent crashes)
        # Use async_add_external_statistics for external statistics (uses : delimiter)
        self._logger.info(
            "Importing runtime statistic: id=%s, date=%s, value=%.2fh",
            statistic_id, date_str, hours
        )
        try:
            async_add_external_statistics(self.hass, metadata, [statistic])
            self._logger.debug("Successfully imported runtime statistic for %s", date_str)
        except Exception as err:
            self._logger.warning(
                "Could not import runtime statistic for %s: %s (statistic_id=%s)",
                date_str, err, statistic_id
            )

    async def _import_all_runtime_history_statistics(self) -> None:
        """Import all existing runtime history data into statistics (called at startup)."""
        if not self._daily_runtime_history:
            self._logger.debug("No runtime history to import into statistics")
            return

        self._logger.info("Importing %d days of runtime history into statistics", len(self._daily_runtime_history))

        for date_str, hours in sorted(self._daily_runtime_history.items()):
            await self._import_runtime_statistics(date_str, hours)

        self._logger.info("Completed import of runtime history into statistics")

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
            self._fuel_consumed_since_reset += fuel_consumed

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
        self.data["fuel_consumed_since_reset"] = round(self._fuel_consumed_since_reset, 2)
        self._update_fuel_remaining()

    def _update_fuel_remaining(self) -> None:
        """Update estimated fuel remaining based on tank capacity and consumption since reset."""
        tank_capacity = self.data.get("tank_capacity")
        if tank_capacity is None or tank_capacity <= 0:
            # Tank capacity not set — can't estimate
            self.data["fuel_remaining"] = None
            return

        remaining = tank_capacity - self._fuel_consumed_since_reset
        self.data["fuel_remaining"] = round(max(0.0, remaining), 2)

    async def async_reset_fuel_level(self) -> None:
        """Reset fuel level tracking (called when user refuels)."""
        self._fuel_consumed_since_reset = 0.0
        self.data["fuel_consumed_since_reset"] = 0.0
        self.data["last_refueled"] = dt_util.now().isoformat()
        self._update_fuel_remaining()
        await self.async_save_data()
        self._logger.info("⛽ Fuel level reset (tank refueled at %s)", self.data["last_refueled"])
        self.async_set_updated_data(self.data)

    async def async_set_tank_capacity(self, capacity: int) -> None:
        """Set the user-defined tank capacity in liters (1-100)."""
        capacity = max(1, min(100, capacity))
        self.data["tank_capacity"] = capacity
        self._update_fuel_remaining()
        await self.async_save_data()
        self._logger.info("⛽ Tank capacity set to %dL", capacity)
        self.async_set_updated_data(self.data)

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
                self._logger.info(
                    "New day detected: saved %s consumption (%.2fL) to history",
                    self._last_reset_date,
                    liters_consumed
                )

                # Import into statistics for native graphing
                await self._import_statistics(self._last_reset_date, liters_consumed)

            self._logger.info(
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
                self._logger.info(
                    "New day detected: saved %s runtime (%.2fh) to history",
                    self._last_runtime_reset_date,
                    hours_running
                )

                # Import into statistics for native graphing
                await self._import_runtime_statistics(self._last_runtime_reset_date, hours_running)

            self._logger.info(
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
            self._logger.debug(
                "Connection failed (attempt %d/%d), keeping last values: %s",
                self._consecutive_failures,
                self._max_stale_cycles,
                err
            )
        else:
            # Too many failures, clear values
            self._clear_sensor_values()
            if self._consecutive_failures == self._max_stale_cycles + 1:
                self._logger.warning(
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
            status = await self._send_command(1, 0)

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
            self._logger.debug("Error updating data: %s", err)
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
                self._logger.debug(
                    "Waiting %.1fs before reconnection attempt %d",
                    remaining,
                    self._connection_attempts + 1
                )
                await asyncio.sleep(remaining)

        self._connection_attempts += 1
        self._last_connection_attempt = time.time()

        self._logger.debug(
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
                self._logger.warning("No services discovered, triggering service refresh")
                # Services might not be cached, disconnect and let next attempt retry
                await self._cleanup_connection()
                raise BleakError("No services available")

            # Get characteristic - try Vevor UUIDs first, then ABBA
            self._characteristic = None
            self._active_char_uuid = None
            self._is_abba_device = False
            self._abba_write_char = None

            # First, check for ABBA/HeaterCC device (service fff0)
            for service in self._client.services:
                if service.uuid.lower() == ABBA_SERVICE_UUID.lower():
                    self._logger.info("🔍 Detected ABBA/HeaterCC heater (service fff0)")
                    self._is_abba_device = True
                    self._protocol_mode = 5  # ABBA protocol

                    # Log all characteristics in this service for debugging
                    char_list = [f"{c.uuid} (props: {c.properties})" for c in service.characteristics]
                    self._logger.info("📋 ABBA service characteristics: %s", char_list)

                    # Find notify and write characteristics
                    for char in service.characteristics:
                        if char.uuid.lower() == ABBA_NOTIFY_UUID.lower():
                            self._characteristic = char
                            self._active_char_uuid = ABBA_NOTIFY_UUID
                            self._logger.info("✅ Found ABBA notify characteristic (fff1): %s", char.uuid)
                        elif char.uuid.lower() == ABBA_WRITE_UUID.lower():
                            self._abba_write_char = char
                            self._logger.info("✅ Found ABBA write characteristic (fff2): %s", char.uuid)

                    # Warning if write characteristic not found
                    if not self._abba_write_char:
                        self._logger.warning(
                            "⚠️ ABBA device but fff2 write characteristic not found! "
                            "Will try writing to fff1 as fallback."
                        )
                        # Fall back to using fff1 for writing if fff2 not available
                        self._abba_write_char = self._characteristic
                    break

            # If not ABBA, try Vevor UUIDs
            if not self._is_abba_device:
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
                                    self._logger.info(
                                        "Found Vevor heater characteristic: %s (service: %s)",
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
                self._logger.error(
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
                self._logger.debug("Started notifications on %s", self._active_char_uuid)
            else:
                self._logger.warning("Characteristic does not support notify")

            # Send a wake-up ping to ensure device is responsive
            # Some heaters go into deep sleep and need a nudge
            self._logger.debug("Sending wake-up ping to device")
            await self._send_wake_up_ping()

            self._connection_attempts = 0  # Reset on successful connection
            self._logger.info("Successfully connected to Vevor Heater")

        except Exception as err:
            # Clean up on any connection failure
            await self._cleanup_connection()
            raise

    @callback
    def _notification_callback(self, _sender: int, data: bytearray) -> None:
        """Handle notification from heater."""
        # Log ALL received data for debugging
        self._logger.info(
            "📩 Received BLE data (%d bytes): %s",
            len(data),
            data.hex()
        )
        try:
            self._parse_response(data)
        except Exception as err:
            self._logger.error("Error parsing notification: %s", err)

    def _parse_response(self, data: bytearray) -> None:
        """Parse response from heater."""
        if len(data) < 8:
            # AA77 ACK is 10 bytes - check before discarding
            header_short = (_u8_to_number(data[0]) << 8) | _u8_to_number(data[1]) if len(data) >= 2 else 0
            if header_short == PROTOCOL_HEADER_AA77:
                self._logger.debug("AA77 ACK received (%d bytes)", len(data))
                self._notification_data = data
                return
            self._logger.debug("Response too short: %d bytes", len(data))
            return

        # Check protocol type
        header = (_u8_to_number(data[0]) << 8) | _u8_to_number(data[1])
        old_protocol = self._protocol_mode

        # Check for CBFF protocol (Sunster/v2.1 heaters)
        if header == PROTOCOL_HEADER_CBFF:
            self._logger.info("Detected protocol: CBFF/Sunster v2.1 (mode=6, %d bytes)", len(data))
            self._parse_protocol_cbff(data)
            return

        # Check for AA77 command ACK (Sunster heaters respond to AA55 with AA77)
        if header == PROTOCOL_HEADER_AA77:
            self._logger.debug("AA77 ACK received (%d bytes)", len(data))
            self._notification_data = data
            return

        # Check for ABBA protocol (HeaterCC heaters)
        if header == PROTOCOL_HEADER_ABBA or self._is_abba_device:
            self._logger.info("Detected protocol: ABBA/HeaterCC (mode=5, %d bytes)", len(data))
            self._parse_protocol_abba(data)
            return

        if len(data) < 17:
            self._logger.debug("Response too short for Vevor protocol: %d bytes", len(data))
            return

        if header == 0xAA55 and len(data) in (18, 20):
            # Protocol 1: 0xAA 0x55, 18-20 bytes, not encrypted
            self._logger.info("Detected protocol: AA55 unencrypted (mode=1, %d bytes)", len(data))
            self._parse_protocol_aa55(data)
        elif header == 0xAA66 and len(data) == 20:
            # Protocol 3: 0xAA 0x66, 20 bytes, not encrypted
            self._logger.info("Detected protocol: AA66 unencrypted (mode=3)")
            self._parse_protocol_aa66(data)
        elif len(data) == 48:
            # Protocol 2/4: 48 bytes, encrypted
            decrypted = _decrypt_data(data)
            header = (_u8_to_number(decrypted[0]) << 8) | _u8_to_number(decrypted[1])
            self._logger.debug("Decrypted header: 0x%04X", header)

            if header == 0xAA55:
                self._logger.info("🔍 Detected protocol: AA55 encrypted (mode=2)")
                self._parse_protocol_aa55_encrypted(decrypted)
            elif header == 0xAA66:
                self._logger.info("🔍 Detected protocol: AA66 encrypted (mode=4)")
                self._parse_protocol_aa66_encrypted(decrypted)
            else:
                self._logger.warning(
                    "🔍 Unknown encrypted protocol, decrypted header: 0x%04X",
                    header
                )
        else:
            self._logger.warning(
                "🔍 Unknown protocol, length: %d, header: 0x%04X",
                len(data), header
            )

        # Log protocol change
        if old_protocol != self._protocol_mode:
            self._logger.info(
                "📋 Protocol mode changed: %d → %d (commands will now use %s format)",
                old_protocol, self._protocol_mode,
                "CBFF/Sunster v2.1" if self._protocol_mode == 6 else
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

        self._logger.debug("Parsed AA55: %s", self.data)
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

        self._logger.debug("Parsed AA66: %s", self.data)
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

        # Byte 34: Temperature offset reported by heater
        if len(data) > 34:
            heater_offset_raw = data[34]
            if heater_offset_raw > 127:
                heater_offset = heater_offset_raw - 256
            else:
                heater_offset = heater_offset_raw
            self.data["heater_offset"] = heater_offset
            self._logger.debug("🌡️ Heater offset byte 34: %d", heater_offset)

        # Byte 36: Backlight brightness (0=Off, 1-10, 20-100)
        if len(data) > 36:
            brightness = _u8_to_number(data[36])
            if brightness != 0:
                self.data["backlight"] = brightness
            else:
                self.data["backlight"] = 0

        # Byte 37: CO sensor present (boolean), Bytes 38-39: CO PPM (big endian)
        if len(data) > 39:
            co_present = _u8_to_number(data[37])
            if co_present == 1:
                co_ppm = (_u8_to_number(data[38]) << 8) | _u8_to_number(data[39])
                self.data["co_ppm"] = float(co_ppm)
            else:
                self.data["co_ppm"] = None

        # Bytes 40-43: Part number (uint32 little endian, stored as hex string)
        if len(data) > 43:
            part_number = (
                _u8_to_number(data[40])
                | (_u8_to_number(data[41]) << 8)
                | (_u8_to_number(data[42]) << 16)
                | (_u8_to_number(data[43]) << 24)
            )
            if part_number != 0:
                self.data["part_number"] = format(part_number, 'x')

        # Byte 44: Motherboard version
        if len(data) > 44:
            mb_version = _u8_to_number(data[44])
            if mb_version != 0:
                self.data["motherboard_version"] = mb_version

        # Apply temperature calibration
        self._apply_temperature_calibration()

        self._logger.debug("Parsed AA55 encrypted: %s", self.data)
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
        self.data["temp_unit"] = temp_unit_byte  # Store for UI switch
        self._logger.debug("🌡️ Temperature unit byte 27: %d (%s)",
                     temp_unit_byte, "Fahrenheit" if self._heater_uses_fahrenheit else "Celsius")

        # Read raw set_temp value
        raw_set_temp = _u8_to_number(data[9])
        self._logger.debug("🌡️ Raw set_temp from heater: %d (byte 9)", raw_set_temp)

        # Convert to Celsius if heater uses Fahrenheit
        if self._heater_uses_fahrenheit:
            set_temp_celsius = round((raw_set_temp - 32) * 5 / 9)
            self._logger.debug("🌡️ Converted from Fahrenheit: %d°F → %d°C", raw_set_temp, set_temp_celsius)
            self.data["set_temp"] = max(8, min(36, set_temp_celsius))
        else:
            self._logger.debug("🌡️ Heater uses Celsius: %d°C", raw_set_temp)
            self.data["set_temp"] = max(8, min(36, raw_set_temp))

        # Byte 31: Automatic Start/Stop flag
        # When enabled in Temperature mode, heater will stop when room reaches target temp
        auto_start_stop_byte = _u8_to_number(data[31])
        self.data["auto_start_stop"] = (auto_start_stop_byte == 1)
        self._logger.debug("🔄 Auto Start/Stop byte 31: %d (%s)",
                     auto_start_stop_byte, "Enabled" if self.data["auto_start_stop"] else "Disabled")

        # Configuration settings (bytes 26, 28, 29, 30)
        # Byte 26: Language of voice notifications
        if len(data) > 26:
            self.data["language"] = _u8_to_number(data[26])
            self._logger.debug("🗣️ Language byte 26: %d", self.data["language"])

        # Byte 28: Tank volume in liters
        if len(data) > 28:
            self.data["tank_volume"] = _u8_to_number(data[28])
            self._logger.debug("⛽ Tank volume byte 28: %d L", self.data["tank_volume"])

        # Byte 29: Pump type / RF433 status
        # Values 20/21 indicate RF433 remote: 20=off, 21=on
        if len(data) > 29:
            pump_byte = _u8_to_number(data[29])
            if pump_byte == 20:
                self.data["rf433_enabled"] = False
                self.data["pump_type"] = None  # RF433 mode, no pump type
            elif pump_byte == 21:
                self.data["rf433_enabled"] = True
                self.data["pump_type"] = None  # RF433 mode, no pump type
            else:
                self.data["pump_type"] = pump_byte
                self.data["rf433_enabled"] = None  # Standard mode
            self._logger.debug("🔧 Pump type byte 29: %d (rf433=%s)", pump_byte, self.data["rf433_enabled"])

        # Byte 30: Altitude unit (0=Meters, 1=Feet)
        if len(data) > 30:
            self.data["altitude_unit"] = _u8_to_number(data[30])
            self._logger.debug("📏 Altitude unit byte 30: %d (%s)",
                         self.data["altitude_unit"],
                         "Feet" if self.data["altitude_unit"] == 1 else "Meters")

        self.data["supply_voltage"] = (256 * data[11] + data[12]) / 10
        self.data["case_temperature"] = _unsign_to_sign(256 * data[13] + data[14])
        self.data["cab_temperature"] = _unsign_to_sign(256 * data[32] + data[33]) / 10

        # Byte 34: Temperature offset reported by heater
        # This is a signed value (-10 to +10 typically)
        if len(data) > 34:
            heater_offset_raw = data[34]
            # Convert unsigned byte to signed (-128 to 127)
            if heater_offset_raw > 127:
                heater_offset = heater_offset_raw - 256
            else:
                heater_offset = heater_offset_raw
            self.data["heater_offset"] = heater_offset
            self._logger.debug("🌡️ Heater offset byte 34: %d (raw=%d)", heater_offset, heater_offset_raw)

        # Byte 36: Backlight brightness (0=Off, 1-10, 20-100)
        if len(data) > 36:
            brightness = _u8_to_number(data[36])
            if brightness != 0:
                self.data["backlight"] = brightness
            else:
                self.data["backlight"] = 0

        # Byte 37: CO sensor present (boolean), Bytes 38-39: CO PPM (big endian)
        if len(data) > 39:
            co_present = _u8_to_number(data[37])
            if co_present == 1:
                co_ppm = (_u8_to_number(data[38]) << 8) | _u8_to_number(data[39])
                self.data["co_ppm"] = float(co_ppm)
            else:
                self.data["co_ppm"] = None

        # Bytes 40-43: Part number (uint32 little endian, stored as hex string)
        if len(data) > 43:
            part_number = (
                _u8_to_number(data[40])
                | (_u8_to_number(data[41]) << 8)
                | (_u8_to_number(data[42]) << 16)
                | (_u8_to_number(data[43]) << 24)
            )
            if part_number != 0:
                self.data["part_number"] = format(part_number, 'x')

        # Byte 44: Motherboard version
        if len(data) > 44:
            mb_version = _u8_to_number(data[44])
            if mb_version != 0:
                self.data["motherboard_version"] = mb_version

        # Apply temperature calibration
        self._apply_temperature_calibration()

        self._logger.debug("Parsed AA66 encrypted: %s", self.data)
        self._notification_data = data

    def _parse_protocol_abba(self, data: bytearray) -> None:
        """Parse ABBA protocol response (HeaterCC heaters).

        ABBA protocol is used by HeaterCC/AirHeaterCC app heaters.
        Header is 0xABBA (notifications) or 0xBAAB (commands).

        Byte mapping (verified by @Xev and @postal):
        - Bytes 0-1: Header (0xABBA)
        - Bytes 2-3: Packet type (0x11CC for status)
        - Byte 4: Status (0=Off, 1=Heating, 2=Cooling)
        - Byte 5: Mode (0=Manual, 1=Thermostat)
        - Byte 6: Gear/Target temp (Manual → level 1-6, Thermostat → target °C)
        - Byte 7: Submode/Flag
        - Byte 8: Auto Start/Stop (0=Off, 1=On)
        - Byte 9: Voltage (decimal V)
        - Byte 10: Temperature Unit (0=Celsius, 1=Fahrenheit)
        - Byte 11: Environment Temperature (subtract 30 for C, 22 for F)
        - Bytes 12-13: Device Temperature (uint16)
        - Byte 14: Altitude unit (0=Meters, 1=Feet)
        - Byte 15: High-altitude mode (0=Normal, 1=High)
        - Bytes 16-17: Altitude (uint16)
        - Byte 20: Checksum
        """
        self._protocol_mode = 5

        self._logger.info("🔍 Parsing ABBA protocol response (%d bytes): %s", len(data), data.hex())

        # ABBA responses have header 0xABBA
        header = (_u8_to_number(data[0]) << 8) | _u8_to_number(data[1])
        if header != PROTOCOL_HEADER_ABBA:
            self._logger.debug("ABBA: Unexpected header 0x%04X, expected 0xABBA", header)

        # Need at least 21 bytes for full status response
        if len(data) < 21:
            self._logger.warning("ABBA: Response too short (%d bytes), need 21", len(data))
            self.data["connected"] = True
            self._notification_data = data
            return

        try:
            self.data["connected"] = True

            # Byte 4: Status (0x00=Off, 0x01=Running, 0x02=Cooldown, 0x04=Ventilation, 0x06=Standby)
            status_byte = _u8_to_number(data[4])
            # Running state: 1 if actively heating (status 0x01), 0 otherwise
            self.data["running_state"] = 1 if status_byte == 0x01 else 0

            # Map ABBA status to running_step using the status map
            self.data["running_step"] = ABBA_STATUS_MAP.get(status_byte, status_byte)

            self._logger.debug("ABBA status byte 4: 0x%02X → running_state=%d, running_step=%d",
                         status_byte, self.data["running_state"], self.data["running_step"])

            # Byte 5: Mode (0x00=Level, 0x01=Temperature, 0xFF=Error)
            mode_byte = _u8_to_number(data[5])

            # Check for error condition: if byte 5 = 0xFF, byte 6 contains error code
            if mode_byte == 0xFF:
                error_code = _u8_to_number(data[6])
                self.data["error_code"] = error_code
                error_name = ABBA_ERROR_NAMES.get(error_code, f"E{error_code} - Unknown error")
                self._logger.warning("⚠️ ABBA error detected: byte 5=0xFF, error_code=%d (%s)",
                               error_code, error_name)
                # Keep last known mode when in error state
            else:
                # Normal mode: 0x00=Level, 0x01=Temperature
                self.data["error_code"] = 0
                if mode_byte == 0x00:
                    self.data["running_mode"] = RUNNING_MODE_LEVEL
                elif mode_byte == 0x01:
                    self.data["running_mode"] = RUNNING_MODE_TEMPERATURE
                else:
                    self.data["running_mode"] = mode_byte
                self._logger.debug("ABBA mode byte 5: 0x%02X → running_mode=%d", mode_byte, self.data["running_mode"])

            # Byte 6: Gear/Target temp (depends on mode)
            gear_byte = _u8_to_number(data[6])
            if self.data["running_mode"] == RUNNING_MODE_LEVEL:
                # Manual mode: gear is power level (1-6 for ABBA, we'll scale to 1-10)
                # ABBA uses 1-6, Vevor uses 1-10
                self.data["set_level"] = max(1, min(10, gear_byte))
                self._logger.debug("ABBA gear byte 6: %d → set_level=%d", gear_byte, self.data["set_level"])
            else:
                # Thermostat mode: gear is target temperature
                self.data["set_temp"] = max(8, min(36, gear_byte))
                self._logger.debug("ABBA gear byte 6: %d → set_temp=%d", gear_byte, self.data["set_temp"])

            # Byte 8: Auto Start/Stop
            auto_byte = _u8_to_number(data[8])
            self.data["auto_start_stop"] = (auto_byte == 1)
            self._logger.debug("ABBA auto byte 8: %d → auto_start_stop=%s", auto_byte, self.data["auto_start_stop"])

            # Byte 9: Supply voltage (direct decimal value in V)
            self.data["supply_voltage"] = float(_u8_to_number(data[9]))
            self._logger.debug("ABBA voltage byte 9: %d V", self.data["supply_voltage"])

            # Byte 10: Temperature unit (0=Celsius, 1=Fahrenheit)
            temp_unit_byte = _u8_to_number(data[10])
            self.data["temp_unit"] = temp_unit_byte
            self._heater_uses_fahrenheit = (temp_unit_byte == 1)
            self._logger.debug("ABBA temp_unit byte 10: %d (%s)",
                         temp_unit_byte, "Fahrenheit" if self._heater_uses_fahrenheit else "Celsius")

            # Byte 11: Environment/Cabin temperature
            # Need to subtract 30 for Celsius, 22 for Fahrenheit
            env_temp_raw = _u8_to_number(data[11])
            if self._heater_uses_fahrenheit:
                env_temp = env_temp_raw - 22
            else:
                env_temp = env_temp_raw - 30
            self.data["cab_temperature"] = float(env_temp)
            self.data["cab_temperature_raw"] = float(env_temp)
            self._logger.debug("ABBA env_temp byte 11: raw=%d, converted=%d°%s",
                         env_temp_raw, env_temp, "F" if self._heater_uses_fahrenheit else "C")

            # Bytes 12-13: Device/Case temperature (uint16, little endian)
            case_temp = _u8_to_number(data[12]) | (_u8_to_number(data[13]) << 8)
            self.data["case_temperature"] = float(case_temp)
            self._logger.debug("ABBA case_temp bytes 12-13: %d°C", case_temp)

            # Byte 14: Altitude unit (0=Meters, 1=Feet)
            altitude_unit_byte = _u8_to_number(data[14])
            self.data["altitude_unit"] = altitude_unit_byte
            self._logger.debug("ABBA altitude_unit byte 14: %d (%s)",
                         altitude_unit_byte, "Feet" if altitude_unit_byte == 1 else "Meters")

            # Byte 15: High-altitude mode (0=Off, 1=On)
            high_alt_byte = _u8_to_number(data[15])
            self.data["high_altitude"] = high_alt_byte
            self._logger.debug("ABBA high_altitude byte 15: %d (%s)",
                         high_alt_byte, "On" if high_alt_byte else "Off")

            # Bytes 16-17: Altitude (uint16, little endian)
            altitude = _u8_to_number(data[16]) | (_u8_to_number(data[17]) << 8)
            self.data["altitude"] = altitude
            self._logger.debug("ABBA altitude bytes 16-17: %d", altitude)

            # Build status name for logging
            status_names = {0x00: "Off", 0x01: "Heating", 0x02: "Cooldown", 0x04: "Ventilation", 0x06: "Standby"}
            status_name = status_names.get(status_byte, f"Unknown(0x{status_byte:02X})")

            # Log error if present
            error_code = self.data.get("error_code", 0)
            if error_code > 0:
                error_name = ABBA_ERROR_NAMES.get(error_code, f"E{error_code}")
                self._logger.info(
                    "⚠️ ABBA parsed: status=%s, ERROR=%s, cab=%d°C, case=%d°C, voltage=%dV",
                    status_name, error_name,
                    self.data["cab_temperature"],
                    self.data["case_temperature"],
                    self.data["supply_voltage"]
                )
            else:
                mode_name = "Thermostat" if self.data.get("running_mode") == RUNNING_MODE_TEMPERATURE else "Level"
                self._logger.info(
                    "✅ ABBA parsed: status=%s, mode=%s, level/temp=%s, cab=%d°C, case=%d°C, voltage=%dV",
                    status_name, mode_name,
                    self.data.get("set_temp") or self.data.get("set_level"),
                    self.data["cab_temperature"],
                    self.data["case_temperature"],
                    self.data["supply_voltage"]
                )

        except Exception as err:
            self._logger.error("ABBA parse error: %s", err)
            # Set minimal data to show device is connected
            self.data["connected"] = True
            self.data["running_state"] = 0
            self.data["running_step"] = 0
            self.data["error_code"] = 0

        self._notification_data = data

    def _parse_protocol_cbff(self, data: bytearray) -> None:
        """Parse CBFF protocol response (Sunster/v2.1 heaters, 47 bytes).

        This is a newer protocol used by Sunster TB10Pro WiFi and similar heaters.
        The heater sends 47-byte CBFF notifications with status data.
        Commands use standard AA55 format, heater ACKs with AA77.

        Byte mapping (reverse-engineered from Sunster app by @Xev):
        - Byte 2: protocol_version
        - Byte 8: mainboard_type
        - Byte 10: run_state (2/5/6=OFF, others=ON)
        - Byte 11: run_mode (1/3/4=Level, 2=Temperature)
        - Byte 12: run_param (temp or gear depending on mode)
        - Byte 13: now_gear (current gear level)
        - Byte 14: run_step
        - Byte 15: fault_display
        - Byte 16: fault_code
        - Byte 17: temp_unit (0=C, 1=F)
        - Bytes 18-19: detect_temp (cabin temp, int16 LE)
        - Byte 20: altitude_unit
        - Bytes 21-22: altitude (uint16 LE)
        - Bytes 23-24: voltage (uint16 LE, /10)
        - Bytes 25-26: skin_temp (case temp, int16 LE, /10)
        - Bytes 27-28: co (CO sensor PPM, uint16 LE, /10)
        - Byte 29: pwr_onoff
        - Byte 34: temp_comp (int8, temperature offset)
        - Byte 35: broadcast_language
        - Byte 36: oil_volume (tank volume index)
        - Byte 37: pump_model
        - Byte 42: i_stop (auto start/stop)
        - Byte 43: heater_mode
        - Bytes 44-45: remain_run_time (uint16 LE)
        """
        self._protocol_mode = 6

        self._logger.info("Parsing CBFF/v2.1 protocol response (%d bytes): %s", len(data), data.hex())

        if len(data) < 46:
            self._logger.warning("CBFF: Response too short (%d bytes), need 46+", len(data))
            self.data["connected"] = True
            self._notification_data = data
            return

        try:
            self.data["connected"] = True

            # Byte 10: run_state (2/5/6 = OFF, others = ON)
            run_state = _u8_to_number(data[10])
            self.data["running_state"] = 0 if run_state in CBFF_RUN_STATE_OFF else 1

            # Byte 14: run_step (direct value, same meaning as AA55)
            self.data["running_step"] = _u8_to_number(data[14])

            # Byte 11: run_mode (1/3/4 = Level, 2 = Temperature)
            run_mode = _u8_to_number(data[11])
            if run_mode in (1, 3, 4):
                self.data["running_mode"] = RUNNING_MODE_LEVEL
            elif run_mode == 2:
                self.data["running_mode"] = RUNNING_MODE_TEMPERATURE
            else:
                self.data["running_mode"] = RUNNING_MODE_MANUAL

            # Byte 12: run_param (temp or gear depending on mode)
            run_param = _u8_to_number(data[12])
            if self.data["running_mode"] == RUNNING_MODE_LEVEL:
                self.data["set_level"] = max(1, min(10, run_param))
            else:
                self.data["set_temp"] = max(8, min(36, run_param))

            # Byte 13: now_gear (current gear even in temp mode)
            now_gear = _u8_to_number(data[13])
            if self.data["running_mode"] == RUNNING_MODE_TEMPERATURE:
                self.data["set_level"] = max(1, min(10, now_gear))

            # Byte 15-16: fault_display and fault_code
            fault_display = _u8_to_number(data[15])
            fault_code = _u8_to_number(data[16])
            # fault_code >= 128 overrides fault_display
            if fault_code >= 128:
                self.data["error_code"] = fault_display & 0x3F
            else:
                self.data["error_code"] = fault_display & 0x3F

            # Byte 17: temp_unit
            temp_unit_byte = _u8_to_number(data[17])
            # Sunster app uses checkIsFunction nibble logic for temp_unit
            # Lower nibble = actual value, upper nibble = feature flag
            temp_unit_value = temp_unit_byte & 0x0F
            self.data["temp_unit"] = temp_unit_value
            self._heater_uses_fahrenheit = (temp_unit_value == 1)

            # Bytes 18-19: detect_temp (cabin temperature, int16 LE)
            cab_temp_raw = data[18] | (data[19] << 8)
            if cab_temp_raw >= 32768:
                cab_temp_raw -= 65536
            self.data["cab_temperature"] = float(cab_temp_raw)

            # Byte 20: altitude_unit
            altitude_unit_byte = _u8_to_number(data[20])
            self.data["altitude_unit"] = altitude_unit_byte & 0x0F

            # Bytes 21-22: altitude (uint16 LE)
            altitude = data[21] | (data[22] << 8)
            self.data["altitude"] = altitude

            # Bytes 23-24: voltage (uint16 LE, /10)
            voltage_raw = data[23] | (data[24] << 8)
            self.data["supply_voltage"] = voltage_raw / 10.0

            # Bytes 25-26: skin_temp / case temperature (int16 LE, /10)
            case_temp_raw = data[25] | (data[26] << 8)
            if case_temp_raw >= 32768:
                case_temp_raw -= 65536
            self.data["case_temperature"] = case_temp_raw / 10.0

            # Bytes 27-28: CO sensor (uint16 LE, /10, in PPM)
            co_raw = data[27] | (data[28] << 8)
            co_ppm = co_raw / 10.0
            if co_ppm < 6553:  # Valid reading (app checks < 6553)
                self.data["co_ppm"] = co_ppm
            else:
                self.data["co_ppm"] = None  # No CO sensor or invalid

            # Byte 34: temp_comp (temperature offset, int8)
            temp_comp = data[34]
            if temp_comp > 127:
                temp_comp -= 256
            self.data["heater_offset"] = temp_comp

            # Byte 35: broadcast_language
            lang_byte = _u8_to_number(data[35])
            if lang_byte != 255:
                self.data["language"] = lang_byte

            # Byte 36: oil_volume (tank volume index)
            tank_vol = _u8_to_number(data[36])
            if tank_vol != 255:
                self.data["tank_volume"] = tank_vol

            # Byte 37: pump_model
            pump_byte = _u8_to_number(data[37])
            if pump_byte != 255:
                if pump_byte == 20:
                    self.data["rf433_enabled"] = False
                    self.data["pump_type"] = None
                elif pump_byte == 21:
                    self.data["rf433_enabled"] = True
                    self.data["pump_type"] = None
                else:
                    self.data["pump_type"] = pump_byte
                    self.data["rf433_enabled"] = None

            # Byte 42: i_stop (auto start/stop)
            auto_byte = _u8_to_number(data[42])
            self.data["auto_start_stop"] = (auto_byte == 1)

            # Apply temperature calibration
            self._apply_temperature_calibration()

            self._logger.info(
                "CBFF parsed: run_state=%d, step=%d, mode=%d, temp=%s, level=%s, "
                "cab=%.1f°C, case=%.1f°C, voltage=%.1fV, co=%s PPM",
                run_state, self.data["running_step"], run_mode,
                self.data.get("set_temp"), self.data.get("set_level"),
                self.data["cab_temperature"], self.data["case_temperature"],
                self.data["supply_voltage"],
                self.data.get("co_ppm", "N/A")
            )

        except Exception as err:
            self._logger.error("CBFF parse error: %s", err)
            self.data["connected"] = True
            self.data["running_state"] = 0
            self.data["running_step"] = 0
            self.data["error_code"] = 0

        self._notification_data = data

    def _apply_temperature_calibration(self) -> None:
        """Store raw temperature and apply manual HA-side offset calibration.

        The heater offset (sent via cmd 12) is handled separately.
        This only applies the manual HA-side display offset from config.
        """
        # Get reported temperature (already set by protocol parser)
        # This is AFTER the heater's internal offset has been applied
        reported_temp = self.data.get("cab_temperature")
        if reported_temp is None:
            return

        # Calculate the TRUE raw sensor temperature (before heater's internal offset)
        # Formula: raw_sensor_temp = reported_temp - heater_offset
        # Example: reported=18°C, heater_offset=-2°C → raw_sensor=18-(-2)=20°C
        heater_offset = self.data.get("heater_offset", 0)
        raw_sensor_temp = reported_temp - heater_offset
        self.data["cab_temperature_raw"] = raw_sensor_temp

        # Get configured manual offset (default to 0.0 if not set)
        # This is an HA-side display offset, separate from the heater offset
        manual_offset = self.config_entry.data.get(CONF_TEMPERATURE_OFFSET, DEFAULT_TEMPERATURE_OFFSET)

        # Apply manual offset for display purposes
        if manual_offset != 0.0:
            calibrated_temp = reported_temp + manual_offset

            # Clamp to sensor range
            calibrated_temp = max(SENSOR_TEMP_MIN, min(SENSOR_TEMP_MAX, calibrated_temp))

            # Round to 1 decimal place
            calibrated_temp = round(calibrated_temp, 1)

            # Update data with calibrated value
            self.data["cab_temperature"] = calibrated_temp

            self._logger.debug(
                "Applied HA display offset: reported=%s°C, ha_offset=%s°C, display=%s°C, raw_sensor=%s°C (heater_offset=%s°C)",
                reported_temp, manual_offset, calibrated_temp, raw_sensor_temp, heater_offset
            )

        # Note: heater_offset is now read from byte 34 of the response,
        # so we don't overwrite it here. It shows what the heater reports.

    async def _cleanup_connection(self) -> None:
        """Clean up BLE connection properly."""
        if self._client:
            try:
                if self._client.is_connected:
                    # Stop notifications using the active UUID
                    if self._characteristic and self._active_char_uuid and "notify" in self._characteristic.properties:
                        try:
                            await self._client.stop_notify(self._active_char_uuid)
                            self._logger.debug("Stopped notifications on %s", self._active_char_uuid)
                        except Exception as err:
                            self._logger.debug("Could not stop notifications: %s", err)

                    # Disconnect
                    await self._client.disconnect()
                    self._logger.debug("Disconnected from heater")
            except Exception as err:
                self._logger.debug("Error during cleanup: %s", err)
            finally:
                self._client = None
                self._characteristic = None
                self._active_char_uuid = None

    async def _write_gatt(self, packet: bytearray) -> None:
        """Write a packet to the appropriate BLE characteristic.

        Uses response=False to avoid authorization issues with BLE
        proxies (e.g., ESPHome BLE proxy). The heater sends a notification as response.
        """
        if self._is_abba_device and self._abba_write_char:
            write_char = self._abba_write_char
            protocol_name = "ABBA"
        else:
            write_char = self._characteristic
            protocol_name = "AAXX"

        await self._client.write_gatt_char(write_char, packet, response=False)
        self._logger.debug("Packet %s written to %s BLE characteristic", packet.hex(), protocol_name)

    async def _send_wake_up_ping(self) -> None:
        """Send a wake-up ping to the device to ensure it's responsive."""
        try:
            if self._client and (self._characteristic or self._abba_write_char):
                packet = self._build_command_packet(1)
                await self._write_gatt(packet)
                await asyncio.sleep(0.5)
                self._logger.debug("Wake-up ping sent")
        except Exception as err:
            self._logger.debug("Wake-up ping failed (non-critical): %s", err)

    def _build_abba_command(self, cmd_hex: str) -> bytearray:
        """Build ABBA protocol command packet.

        ABBA commands have format: baab + length + cmd + data + checksum
        Checksum is (sum of all bytes) & 0xFF
        """
        # Convert hex string to bytes
        cmd_bytes = bytes.fromhex(cmd_hex.replace(" ", ""))

        # Calculate checksum (sum of all bytes & 0xFF)
        checksum = sum(cmd_bytes) & 0xFF
        packet = bytearray(cmd_bytes) + bytearray([checksum])

        self._logger.debug("ABBA command packet: %s", packet.hex())
        return packet

    def _build_command_packet(self, command: int, argument: int = 0) -> bytearray:
        """Build command packet for the heater.

        For Vevor heaters: Always use AA55 protocol (heater only accepts AA55).
        For ABBA/HeaterCC heaters: Use ABBA protocol with BAAB header.
        Argument is optional (defaults to 0).
        """
        # ABBA/HeaterCC protocol
        if self._is_abba_device:
            return self._build_abba_command_for_vevor_cmd(command, argument)

        # Build 8-byte command packet (ALWAYS unencrypted AA55)
        packet = bytearray([0xAA, 0x55, 0, 0, 0, 0, 0, 0])
        packet[2] = self._passkey // 100
        packet[3] = self._passkey % 100
        packet[4] = command % 256
        packet[5] = argument % 256  # For negative: -4 % 256 = 252 (0xfc)
        packet[6] = (argument // 256) % 256  # For negative: (-4 // 256) % 256 = 255 (0xff)
        packet[7] = (packet[2] + packet[3] + packet[4] + packet[5] + packet[6]) % 256

        self._logger.debug("Command packet (8 bytes, AA55): %s", packet.hex())
        return packet

    def _build_abba_command_for_vevor_cmd(self, command: int, argument: int) -> bytearray:
        """Translate Vevor-style command to ABBA protocol.

        Maps Vevor command codes to ABBA hex commands.
        """
        # Map Vevor commands to ABBA commands
        if command == 1:
            # Status request
            return self._build_abba_command("baab04cc000000")
        elif command == 3:
            # Power on/off
            if argument == 1:
                return self._build_abba_command("baab04bba10000")  # Heat on
            else:
                return self._build_abba_command("baab04bba40000")  # 吹风 cooldown/off
        elif command == 4:
            # Set temperature/level - depends on mode
            # For temperature mode, use set temp command
            temp_hex = format(argument, '02x')
            # baab04db + temp + 00 + unit (00=Celsius)
            return self._build_abba_command(f"baab04db{temp_hex}0000")
        elif command == 2:
            # Running mode
            if argument == 2:  # Temperature mode
                return self._build_abba_command("baab04bbac0000")  # Const temp mode
            else:
                return self._build_abba_command("baab04bbad0000")  # Other mode
        elif command == 15:
            # Temperature unit
            if argument == 1:  # Fahrenheit
                return self._build_abba_command("baab04bba80000")
            else:  # Celsius
                return self._build_abba_command("baab04bba70000")
        elif command == 19:
            # Altitude unit
            if argument == 1:  # Feet
                return self._build_abba_command("baab04bbaa0000")
            else:  # Meters
                return self._build_abba_command("baab04bba90000")
        elif command == 99:
            # High Altitude Mode toggle (ABBA-only)
            return self._build_abba_command("baab04bba50000")
        else:
            # Unknown command - send status request as fallback
            self._logger.warning("ABBA: Unknown command %d, sending status request", command)
            return self._build_abba_command("baab04cc000000")

    async def _send_command(self, command: int, argument: int, timeout: float = 5.0) -> bool:
        """Send command to heater with configurable timeout.

        Args:
            command: Command code (1=status, 2=mode, 3=on/off, 4=level/temp, etc.)
            argument: Command argument
            timeout: Timeout in seconds for waiting response
        """
        if not self._client or not self._client.is_connected:
            self._logger.error(
                "Cannot send command: heater not connected. "
                "The integration will attempt to reconnect automatically."
            )
            return False

        if not self._characteristic:
            self._logger.error(
                "Cannot send command: BLE characteristic not found. "
                "Try reloading the integration."
            )
            return False

        # Build protocol-aware command packet
        packet = self._build_command_packet(command, argument)

        self._logger.info(
            "📤 Sending command: %s (cmd=%d, arg=%d, protocol=%d, len=%d)",
            packet.hex(), command, argument, self._protocol_mode, len(packet)
        )

        try:
            self._notification_data = None

            await self._write_gatt(packet)

            # For ABBA devices, send a follow-up status request after commands
            # (as per HeaterCC app behavior)
            if self._is_abba_device and command != 1:  # Don't loop on status request
                await asyncio.sleep(0.5)
                status_packet = self._build_abba_command("baab04cc000000")
                await self._write_gatt(status_packet)
                self._logger.debug("ABBA: Sent follow-up status request")

            # Wait for notification with configurable timeout
            # Increased from 2s to 5s default to handle slow BLE responses
            iterations = int(timeout / 0.1)
            for i in range(iterations):
                await asyncio.sleep(0.1)
                if self._notification_data:
                    self._logger.info(
                        "✅ Received response after %.1fs (protocol=%d)",
                        i * 0.1, self._protocol_mode
                    )
                    return True

            self._logger.warning("⚠️ No response received after %.1fs", timeout)
            return False

        except Exception as err:
            self._logger.error("❌ Error sending command: %s", err)
            # On write error, the connection might be dead
            await self._cleanup_connection()
            return False

    async def async_turn_on(self) -> None:
        """Turn heater on."""
        # Command 3, arg=1 for ON (verified with BYD heater)
        success = await self._send_command(3, 1)
        if success:
            await self.async_request_refresh()

    async def async_turn_off(self) -> None:
        """Turn heater off."""
        # Command 3, arg=0 for OFF (verified with BYD heater)
        success = await self._send_command(3, 0)
        if success:
            await self.async_request_refresh()

    async def async_set_level(self, level: int) -> None:
        """Set heater level (1-10)."""
        # Command 4 for level (verified with BYD heater)
        level = max(1, min(10, level))
        success = await self._send_command(4, level)
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
            self._logger.info(
                "🌡️ SET TEMPERATURE REQUEST: target=%d°C (%d°F), current=%s, mode=%s, protocol=%d (heater uses Fahrenheit)",
                temperature, temp_fahrenheit, current_temp, current_mode, self._protocol_mode
            )
            command_temp = temp_fahrenheit
        else:
            self._logger.info(
                "🌡️ SET TEMPERATURE REQUEST: target=%d°C, current=%s, mode=%s, protocol=%d (heater uses Celsius)",
                temperature, current_temp, current_mode, self._protocol_mode
            )
            command_temp = temperature

        success = await self._send_command(4, command_temp)

        if success:
            await self.async_request_refresh()
            # Log result after refresh
            new_temp = self.data.get("set_temp", "unknown")
            self._logger.info(
                "🌡️ SET TEMPERATURE RESULT: requested=%d°C, heater_reports=%s°C, %s",
                temperature, new_temp,
                "✅ SUCCESS" if new_temp == temperature else "❌ FAILED - heater did not accept"
            )
        else:
            self._logger.warning("🌡️ SET TEMPERATURE FAILED: command not sent successfully")

    async def async_set_mode(self, mode: int) -> None:
        """Set running mode (0=Manual, 1=Level, 2=Temperature)."""
        # Command 2 for mode (needs verification)
        mode = max(0, min(2, mode))
        self._logger.info("Setting running mode to %d", mode)
        success = await self._send_command(2, mode)
        if success:
            await self.async_request_refresh()

    async def async_set_auto_start_stop(self, enabled: bool) -> None:
        """Set Automatic Start/Stop mode (cmd 18).

        When enabled in Temperature mode, the heater will completely stop
        when the room temperature reaches 2°C above the target, and restart
        when it drops 2°C below the target.
        """
        self._logger.info("Setting Auto Start/Stop to %s", "enabled" if enabled else "disabled")
        # Command 18, arg=1 for enabled, arg=0 for disabled
        success = await self._send_command(18, 1 if enabled else 0)
        if success:
            await self.async_request_refresh()

    async def async_sync_time(self) -> None:
        """Sync heater time with Home Assistant time (cmd 10).

        The time is sent as: 60 * hours + minutes
        Example: 14:30 = 60 * 14 + 30 = 870
        """
        now = datetime.now()
        time_value = 60 * now.hour + now.minute
        self._logger.info("Syncing heater time to %02d:%02d (value=%d)", now.hour, now.minute, time_value)
        # Command 10 for time sync
        success = await self._send_command(10, time_value)
        if success:
            self._logger.info("✅ Time sync successful")
        else:
            self._logger.warning("❌ Time sync failed")

    async def async_set_heater_offset(self, offset: int) -> None:
        """Set temperature offset on the heater (cmd 20).

        This sends the offset value directly to the heater's control board.
        The heater will then use this offset for its own temperature readings
        and auto-start/stop logic.

        Both positive and negative offsets are supported via BLE.
        Encoding discovered by @Xev:
        - arg1 (packet[5]) = offset % 256 (value in two's complement)
        - arg2 (packet[6]) = (offset // 256) % 256 (0x00 for positive, 0xff for negative)

        Args:
            offset: Temperature offset in °C (-10 to +10, clamped)
        """
        # Clamp to valid range
        offset = max(MIN_HEATER_OFFSET, min(MAX_HEATER_OFFSET, offset))

        self._logger.info("🌡️ Setting heater temperature offset to %d°C (cmd 20)", offset)

        # Command 20 for temperature offset
        # Pass offset directly - _build_command_packet handles encoding
        success = await self._send_command(20, offset)

        if success:
            self._current_heater_offset = offset
            self.data["heater_offset"] = offset
            self._logger.info("✅ Heater offset set to %d°C", offset)
            await self.async_request_refresh()
        else:
            self._logger.warning("❌ Failed to set heater offset")

    async def async_set_language(self, language: int) -> None:
        """Set voice notification language (cmd 14).

        Args:
            language: Language code (0=Chinese, 1=English, 2=Russian, etc.)
        """
        self._logger.info("🗣️ Setting language to %d (cmd 14)", language)
        success = await self._send_command(14, language)
        if success:
            self.data["language"] = language
            self._logger.info("✅ Language set to %d", language)
            await self.async_request_refresh()
        else:
            self._logger.warning("❌ Failed to set language")

    async def async_set_temp_unit(self, use_fahrenheit: bool) -> None:
        """Set temperature unit (cmd 15).

        Args:
            use_fahrenheit: True for Fahrenheit, False for Celsius
        """
        value = 1 if use_fahrenheit else 0
        unit_name = "Fahrenheit" if use_fahrenheit else "Celsius"
        self._logger.info("🌡️ Setting temperature unit to %s (cmd 15, value=%d)", unit_name, value)
        success = await self._send_command(15, value)
        if success:
            self.data["temp_unit"] = value
            self._heater_uses_fahrenheit = use_fahrenheit
            self._logger.info("✅ Temperature unit set to %s", unit_name)
            await self.async_request_refresh()
        else:
            self._logger.warning("❌ Failed to set temperature unit")

    async def async_set_altitude_unit(self, use_feet: bool) -> None:
        """Set altitude unit (cmd 19).

        Args:
            use_feet: True for Feet, False for Meters
        """
        value = 1 if use_feet else 0
        unit_name = "Feet" if use_feet else "Meters"
        self._logger.info("📏 Setting altitude unit to %s (cmd 19, value=%d)", unit_name, value)
        success = await self._send_command(19, value)
        if success:
            self.data["altitude_unit"] = value
            self._logger.info("✅ Altitude unit set to %s", unit_name)
            await self.async_request_refresh()
        else:
            self._logger.warning("❌ Failed to set altitude unit")

    async def async_set_high_altitude(self, enabled: bool) -> None:
        """Toggle high altitude mode (ABBA-only, cmd 99).

        The ABBA protocol uses a toggle command for high altitude mode.
        """
        if not self._is_abba_device:
            self._logger.warning("High altitude mode is only available for ABBA/HeaterCC devices")
            return
        state_name = "ON" if enabled else "OFF"
        self._logger.info("🏔️ Setting high altitude mode to %s", state_name)
        success = await self._send_command(99, 0)
        if success:
            self.data["high_altitude"] = 1 if enabled else 0
            self._logger.info("✅ High altitude mode set to %s", state_name)
            await self.async_request_refresh()
        else:
            self._logger.warning("❌ Failed to set high altitude mode")

    async def async_set_tank_volume(self, volume_index: int) -> None:
        """Set tank volume by index (cmd 16).

        The heater uses index-based values, not actual liters:
        0=None, 1=5L, 2=10L, 3=15L, 4=20L, 5=25L, 6=30L, 7=35L, 8=40L, 9=45L, 10=50L

        Args:
            volume_index: Tank volume index (0-10)
        """
        volume_index = max(0, min(10, volume_index))
        self._logger.info("⛽ Setting tank volume to index %d (cmd 16)", volume_index)
        success = await self._send_command(16, volume_index)
        if success:
            self.data["tank_volume"] = volume_index
            self._logger.info("✅ Tank volume set to index %d", volume_index)
            await self.async_request_refresh()
        else:
            self._logger.warning("❌ Failed to set tank volume")

    async def async_set_pump_type(self, pump_type: int) -> None:
        """Set oil pump type (cmd 17).

        Pump types: 0=16µl, 1=22µl, 2=28µl, 3=32µl

        Args:
            pump_type: Pump type (0-3)
        """
        pump_type = max(0, min(3, pump_type))
        self._logger.info("🔧 Setting pump type to %d (cmd 17)", pump_type)
        success = await self._send_command(17, pump_type)
        if success:
            self.data["pump_type"] = pump_type
            self._logger.info("✅ Pump type set to %d", pump_type)
            await self.async_request_refresh()
        else:
            self._logger.warning("❌ Failed to set pump type")

    async def async_set_backlight(self, level: int) -> None:
        """Set display backlight brightness (cmd 21).

        Values: 0=Off, 1-10, 20-100 (in steps of 10).
        The heater may round to nearest supported value.

        Args:
            level: Brightness level (0-100)
        """
        level = max(0, min(100, level))
        self._logger.info("Setting backlight to %d (cmd 21)", level)
        success = await self._send_command(21, level)
        if success:
            self.data["backlight"] = level
            self._logger.info("Backlight set to %d", level)
            await self.async_request_refresh()
        else:
            self._logger.warning("Failed to set backlight")

    async def async_set_auto_offset_enabled(self, enabled: bool) -> None:
        """Enable or disable automatic temperature offset adjustment.

        When enabled, the integration will automatically calculate and send
        temperature offset commands to the heater based on an external
        temperature sensor.

        Args:
            enabled: True to enable, False to disable
        """
        self._logger.info("Setting auto offset to %s", "enabled" if enabled else "disabled")
        self.data["auto_offset_enabled"] = enabled

        # Persist the setting immediately
        await self.async_save_data()

        if enabled:
            # Trigger initial calculation
            await self._async_calculate_auto_offset()
        else:
            # Reset heater offset to 0 when disabling
            if self._current_heater_offset != 0:
                self._logger.info("Resetting heater offset to 0")
                await self.async_set_heater_offset(0)

    async def async_send_raw_command(self, command: int, argument: int) -> bool:
        """Send a raw command to the heater for debugging purposes.

        This allows testing different command numbers to discover the correct
        command for various heater functions.

        Args:
            command: Command number (0-255)
            argument: Argument value (-128 to 127, encoded as two's complement)

        Returns:
            True if command was sent successfully
        """
        self._logger.info(
            "🔧 DEBUG: Sending raw command: cmd=%d, arg=%d",
            command, argument
        )

        success = await self._send_command(command, argument)

        if success:
            self._logger.info("✅ DEBUG: Raw command sent successfully")
            await self.async_request_refresh()
        else:
            self._logger.warning("❌ DEBUG: Failed to send raw command")

        return success

    async def async_shutdown(self) -> None:
        """Shutdown coordinator."""
        self._logger.debug("Shutting down Vevor Heater coordinator")

        # Clean up external sensor listener
        if self._auto_offset_unsub:
            self._auto_offset_unsub()
            self._auto_offset_unsub = None

        await self._cleanup_connection()
