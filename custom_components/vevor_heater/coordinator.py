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
    async_import_statistics,
    StatisticData,
    StatisticMetaData,
)
from homeassistant.const import UnitOfVolume
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.storage import Store
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

from .const import (
    CHARACTERISTIC_UUID,
    CONF_TEMPERATURE_OFFSET,
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
    STORAGE_KEY_DAILY_DATE,
    STORAGE_KEY_DAILY_FUEL,
    STORAGE_KEY_DAILY_HISTORY,
    STORAGE_KEY_TOTAL_FUEL,
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
        self._notification_data: bytearray | None = None
        self._passkey = 1234  # Passkey for BYD/Vevor heaters
        self._protocol_mode = 0  # Will be detected from response
        self._connection_attempts = 0
        self._last_connection_attempt = 0.0
        
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
            # Fuel consumption tracking
            "hourly_fuel_consumption": None,
            "daily_fuel_consumed": 0.0,
            "total_fuel_consumed": 0.0,
        }

        # Fuel consumption tracking (minimal)
        self._store = Store(hass, 1, f"{DOMAIN}_{ble_device.address}")
        self._last_update_time: float = time.time()
        self._total_fuel_consumed: float = 0.0
        self._daily_fuel_consumed: float = 0.0
        self._daily_fuel_history: dict[str, float] = {}  # date -> liters consumed
        self._last_save_time: float = time.time()
        self._last_reset_date: str = datetime.now().date().isoformat()

    async def async_load_data(self) -> None:
        """Load persistent fuel consumption data."""
        try:
            data = await self._store.async_load()
            if data:
                self._total_fuel_consumed = data.get(STORAGE_KEY_TOTAL_FUEL, 0.0)
                self._daily_fuel_consumed = data.get(STORAGE_KEY_DAILY_FUEL, 0.0)
                self._daily_fuel_history = data.get(STORAGE_KEY_DAILY_HISTORY, {})

                # Clean old history entries (keep only last MAX_HISTORY_DAYS)
                self._clean_old_history()

                # Check if we need to reset daily counter
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

                # Update data dictionary with loaded values
                self.data["total_fuel_consumed"] = round(self._total_fuel_consumed, 2)
                self.data["daily_fuel_consumed"] = round(self._daily_fuel_consumed, 2)
                self.data["daily_fuel_history"] = self._daily_fuel_history

                _LOGGER.debug(
                    "Loaded fuel data: total=%.2fL, daily=%.2fL, history entries=%d",
                    self._total_fuel_consumed,
                    self._daily_fuel_consumed,
                    len(self._daily_fuel_history)
                )

                # Import existing history into statistics for native graphing
                await self._import_all_history_statistics()
        except Exception as err:
            _LOGGER.warning("Could not load fuel data: %s", err)

    async def async_save_data(self) -> None:
        """Save persistent fuel consumption data."""
        try:
            data = {
                STORAGE_KEY_TOTAL_FUEL: self._total_fuel_consumed,
                STORAGE_KEY_DAILY_FUEL: self._daily_fuel_consumed,
                STORAGE_KEY_DAILY_DATE: datetime.now().date().isoformat(),
                STORAGE_KEY_DAILY_HISTORY: self._daily_fuel_history,
            }
            await self._store.async_save(data)
            _LOGGER.debug("Saved fuel data with %d history entries", len(self._daily_fuel_history))
        except Exception as err:
            _LOGGER.warning("Could not save fuel data: %s", err)

    def _clean_old_history(self) -> None:
        """Remove history entries older than MAX_HISTORY_DAYS."""
        if not self._daily_fuel_history:
            return

        cutoff_date = (datetime.now().date() - timedelta(days=MAX_HISTORY_DAYS)).isoformat()
        old_keys = [date for date in self._daily_fuel_history if date < cutoff_date]

        for date in old_keys:
            del self._daily_fuel_history[date]

        if old_keys:
            _LOGGER.debug("Removed %d old history entries (before %s)", len(old_keys), cutoff_date)

    async def _import_statistics(self, date_str: str, liters: float) -> None:
        """Import daily fuel consumption into Home Assistant statistics for graphing."""
        # Skip if recorder is not available
        if not (recorder := get_instance(self.hass)):
            _LOGGER.debug("Recorder not available, skipping statistics import")
            return

        # Define statistic metadata
        statistic_id = f"{DOMAIN}:daily_fuel_consumed"
        metadata = StatisticMetaData(
            has_mean=False,
            has_sum=True,
            name="Daily Fuel Consumption History",
            source=DOMAIN,
            statistic_id=statistic_id,
            unit_of_measurement=UnitOfVolume.LITERS,
        )

        # Parse date and create timestamp for end of day (23:59:59)
        try:
            date_obj = datetime.fromisoformat(date_str)
            # Set time to 23:59:59 to represent the day's end
            end_of_day = datetime.combine(date_obj.date(), datetime.max.time())
            # Make it timezone-aware
            timestamp = dt_util.as_utc(end_of_day)
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
        try:
            async_import_statistics(self.hass, metadata, [statistic])
            _LOGGER.debug("Imported statistic for %s: %.2fL", date_str, liters)
        except Exception as err:
            _LOGGER.warning("Could not import statistic for %s: %s - Statistics graph may not work", date_str, err)

    async def _import_all_history_statistics(self) -> None:
        """Import all existing history data into statistics (called at startup)."""
        if not self._daily_fuel_history:
            _LOGGER.debug("No history to import into statistics")
            return

        _LOGGER.info("Importing %d days of fuel history into statistics", len(self._daily_fuel_history))

        for date_str, liters in sorted(self._daily_fuel_history.items()):
            await self._import_statistics(date_str, liters)

        _LOGGER.info("Completed import of fuel history into statistics")

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

    async def _async_update_data(self) -> dict[str, Any]:
        """Update data from the heater."""
        # Check for daily reset FIRST, even if heater is offline
        # This ensures the daily counter resets at midnight regardless of connection status
        await self._check_daily_reset()

        if not self._client or not self._client.is_connected:
            try:
                await self._ensure_connected()
            except Exception as err:
                _LOGGER.warning(
                    "Failed to connect to Vevor Heater (attempt %d): %s. "
                    "Will retry automatically.",
                    self._connection_attempts,
                    err
                )
                self.data["connected"] = False
                # Clear sensor values when offline so they show as unavailable
                self.data["case_temperature"] = None
                self.data["cab_temperature"] = None
                self.data["supply_voltage"] = None
                self.data["running_step"] = None
                self.data["running_mode"] = None
                self.data["set_level"] = None
                self.data["altitude"] = None
                self.data["error_code"] = None
                self.data["hourly_fuel_consumption"] = None
                raise UpdateFailed(f"Failed to connect: {err}")
        
        try:
            # Request status
            status = await self._send_command(1, 0, 85)

            if status:
                self.data["connected"] = True

                # Update fuel consumption tracking
                current_time = time.time()
                elapsed_seconds = current_time - self._last_update_time
                self._last_update_time = current_time

                self._update_fuel_tracking(elapsed_seconds)

                # Save fuel data periodically (every 5 minutes)
                if current_time - self._last_save_time >= 300:
                    await self.async_save_data()
                    self._last_save_time = current_time

                return self.data
            else:
                _LOGGER.warning("No status received from heater")
                self.data["connected"] = False
                # Clear sensor values when offline
                self.data["case_temperature"] = None
                self.data["cab_temperature"] = None
                self.data["supply_voltage"] = None
                self.data["running_step"] = None
                self.data["running_mode"] = None
                self.data["set_level"] = None
                self.data["altitude"] = None
                self.data["error_code"] = None
                self.data["hourly_fuel_consumption"] = None
                raise UpdateFailed("No status received from heater")

        except UpdateFailed:
            raise
        except Exception as err:
            _LOGGER.error("Error updating data: %s", err)
            self.data["connected"] = False
            # Clear sensor values when offline
            self.data["case_temperature"] = None
            self.data["cab_temperature"] = None
            self.data["supply_voltage"] = None
            self.data["running_step"] = None
            self.data["running_mode"] = None
            self.data["set_level"] = None
            self.data["altitude"] = None
            self.data["error_code"] = None
            self.data["hourly_fuel_consumption"] = None
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

            # Get characteristic
            self._characteristic = None
            for service in self._client.services:
                if service.uuid.lower() == SERVICE_UUID.lower():
                    for char in service.characteristics:
                        if char.uuid.lower() == CHARACTERISTIC_UUID.lower():
                            self._characteristic = char
                            break

            if not self._characteristic:
                await self._cleanup_connection()
                raise BleakError("Could not find heater characteristic")

            # Start notifications on the same characteristic (ffe1)
            # Some Vevor heaters use ffe1 for both write and notify
            if "notify" in self._characteristic.properties:
                await self._client.start_notify(
                    CHARACTERISTIC_UUID, self._notification_callback
                )
                _LOGGER.debug("Started notifications on %s", CHARACTERISTIC_UUID)
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

        if header == 0xAA55 and len(data) == 20:
            # Protocol 1: 0xAA 0x55, 20 bytes, not encrypted
            _LOGGER.info("🔍 Detected protocol: AA55 unencrypted (mode=1)")
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
        """Parse protocol AA55 (20 bytes, unencrypted)."""
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

        # Bytes 13-14: Case temperature in 0.1°C (little endian)
        # 0x9b 0x00 = 0x009b = 155 → 155 * 0.1 = 15.5°C
        case_temp_raw = _u8_to_number(data[13]) | (_u8_to_number(data[14]) << 8)
        self.data["case_temperature"] = case_temp_raw / 10.0

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
        """Parse encrypted protocol AA66 (48 bytes)."""
        self._protocol_mode = 4
        
        self.data["running_state"] = _u8_to_number(data[3])
        self.data["error_code"] = _u8_to_number(data[35])  # Different position!
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

        _LOGGER.debug("Parsed AA66 encrypted: %s", self.data)
        self._notification_data = data

    def _apply_temperature_calibration(self) -> None:
        """Apply temperature offset calibration to cab_temperature."""
        # Get configured offset (default to 0.0 if not set)
        offset = self.config_entry.data.get(CONF_TEMPERATURE_OFFSET, DEFAULT_TEMPERATURE_OFFSET)

        # Get raw temperature
        raw_temp = self.data.get("cab_temperature")
        if raw_temp is None:
            return

        # Apply offset
        calibrated_temp = raw_temp + offset

        # Clamp to sensor range
        calibrated_temp = max(SENSOR_TEMP_MIN, min(SENSOR_TEMP_MAX, calibrated_temp))

        # Round to 1 decimal place
        calibrated_temp = round(calibrated_temp, 1)

        # Update data with calibrated value
        self.data["cab_temperature"] = calibrated_temp

        # Log calibration if offset is non-zero
        if offset != 0.0:
            _LOGGER.debug(
                "Applied temperature calibration: raw=%s°C, offset=%s°C, calibrated=%s°C",
                raw_temp, offset, calibrated_temp
            )

    async def _cleanup_connection(self) -> None:
        """Clean up BLE connection properly."""
        if self._client:
            try:
                if self._client.is_connected:
                    # Stop notifications using the CORRECT UUID
                    if self._characteristic and "notify" in self._characteristic.properties:
                        try:
                            await self._client.stop_notify(CHARACTERISTIC_UUID)
                            _LOGGER.debug("Stopped notifications on %s", CHARACTERISTIC_UUID)
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
        """Build command packet based on detected protocol mode.

        Protocol modes:
        - 1: AA55 unencrypted (20 bytes response)
        - 2: AA55 encrypted (48 bytes response)
        - 3: AA66 unencrypted (20 bytes response)
        - 4: AA66 encrypted (48 bytes response)

        IMPORTANT: Even for encrypted protocols (2, 4), the heater accepts
        UNENCRYPTED commands. It only sends encrypted responses.
        So we always send 8-byte unencrypted commands with the correct header.
        """
        _LOGGER.info(
            "🔧 Building command packet: protocol_mode=%d, cmd=%d, arg=%d",
            self._protocol_mode, command, argument
        )

        # Determine header based on protocol (AA55 vs AA66)
        if self._protocol_mode in [3, 4]:
            # AA66 protocol - heater expects AA66 header in commands
            header_byte = 0x66
            _LOGGER.debug("Using AA66 protocol header (mode %d)", self._protocol_mode)
        else:
            # AA55 protocol (default)
            header_byte = 0x55
            _LOGGER.debug("Using AA55 protocol header (mode %d)", self._protocol_mode)

        # Build 8-byte command packet (ALWAYS unencrypted)
        # The heater accepts unencrypted commands but sends encrypted responses
        packet = bytearray([0xAA, header_byte, 0, 0, 0, 0, 0, 0])
        packet[2] = self._passkey // 100
        packet[3] = self._passkey % 100
        packet[4] = command % 256
        packet[5] = argument % 256
        packet[6] = argument // 256
        packet[7] = (packet[2] + packet[3] + packet[4] + packet[5] + packet[6]) % 256

        _LOGGER.debug("Command packet (8 bytes, unencrypted): %s", packet.hex())

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
        """
        # Command 4 for temperature - valid range is 8-36°C (not 1-36!)
        temperature = max(8, min(36, temperature))
        current_temp = self.data.get("set_temp", "unknown")
        current_mode = self.data.get("running_mode", "unknown")

        _LOGGER.info(
            "🌡️ SET TEMPERATURE REQUEST: target=%d°C, current=%s°C, mode=%s, protocol=%d",
            temperature, current_temp, current_mode, self._protocol_mode
        )

        success = await self._send_command(4, temperature, 85)

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

    async def async_shutdown(self) -> None:
        """Shutdown coordinator."""
        _LOGGER.debug("Shutting down Vevor Heater coordinator")
        await self._cleanup_connection()
