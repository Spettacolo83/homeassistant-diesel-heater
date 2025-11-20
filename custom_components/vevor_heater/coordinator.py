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
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.helpers.storage import Store

from .const import (
    CHARACTERISTIC_UUID,
    CONF_FUEL_CALIBRATION,
    CONF_TANK_CAPACITY,
    CONF_TEMPERATURE_OFFSET,
    DEFAULT_FUEL_CALIBRATION,
    DEFAULT_TANK_CAPACITY,
    DEFAULT_TEMPERATURE_OFFSET,
    DOMAIN,
    ENCRYPTION_KEY,
    FUEL_CONSUMPTION_TABLE,
    NOTIFY_UUID,
    RUNNING_MODE_LEVEL,
    RUNNING_MODE_MANUAL,
    RUNNING_MODE_TEMPERATURE,
    RUNNING_STEP_RUNNING,
    SENSOR_TEMP_MAX,
    SENSOR_TEMP_MIN,
    SERVICE_UUID,
    STORAGE_KEY_DAILY_FUEL,
    STORAGE_KEY_DAILY_DATE,
    STORAGE_KEY_DAILY_RUNTIME,
    STORAGE_KEY_DAILY_RUNTIME_DATE,
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

        # Storage for persistent data
        self._store = Store(hass, 1, f"{DOMAIN}_{ble_device.address}")
        self._storage_data: dict[str, Any] = {}

        # Fuel and runtime tracking
        self._last_update_time: float = time.time()
        self._total_fuel_consumed: float = 0.0  # Liters
        self._daily_fuel_consumed: float = 0.0  # Liters
        self._total_runtime: int = 0  # Seconds
        self._daily_runtime: int = 0  # Seconds
        self._last_fuel_date: str = datetime.now().date().isoformat()
        self._last_runtime_date: str = datetime.now().date().isoformat()

        # Current state
        self.data: dict[str, Any] = {
            "running_state": 0,
            "error_code": 0,
            "running_step": 0,
            "altitude": 0,
            "running_mode": 0,
            "set_level": 1,
            "set_temp": None,
            "supply_voltage": 0.0,
            "case_temperature": 0,
            "cab_temperature": 0,
            "connected": False,
            # Fuel tracking
            "hourly_fuel_consumption": 0.0,  # L/h (instantaneous)
            "daily_fuel_consumed": 0.0,  # L (today)
            "total_fuel_consumed": 0.0,  # L (all time)
            # Runtime tracking
            "daily_runtime": 0,  # seconds (today)
            "total_runtime": 0,  # seconds (all time)
            # Tank
            "tank_capacity": DEFAULT_TANK_CAPACITY,  # L
            "fuel_remaining": DEFAULT_TANK_CAPACITY,  # L
            "fuel_level_percent": 100.0,  # %
        }

    async def async_load_data(self) -> None:
        """Load persistent data from storage."""
        try:
            self._storage_data = await self._store.async_load() or {}

            # Load fuel data
            self._total_fuel_consumed = self._storage_data.get(STORAGE_KEY_TOTAL_FUEL, 0.0)
            self._daily_fuel_consumed = self._storage_data.get(STORAGE_KEY_DAILY_FUEL, 0.0)
            self._last_fuel_date = self._storage_data.get(
                STORAGE_KEY_DAILY_DATE,
                datetime.now().date().isoformat()
            )

            # Load runtime data
            self._total_runtime = self._storage_data.get(STORAGE_KEY_TOTAL_RUNTIME, 0)
            self._daily_runtime = self._storage_data.get(STORAGE_KEY_DAILY_RUNTIME, 0)
            self._last_runtime_date = self._storage_data.get(
                STORAGE_KEY_DAILY_RUNTIME_DATE,
                datetime.now().date().isoformat()
            )

            # Update data dict
            self.data["total_fuel_consumed"] = self._total_fuel_consumed
            self.data["daily_fuel_consumed"] = self._daily_fuel_consumed
            self.data["total_runtime"] = self._total_runtime
            self.data["daily_runtime"] = self._daily_runtime

            # Load tank capacity from config
            self.data["tank_capacity"] = self.config_entry.options.get(
                CONF_TANK_CAPACITY,
                DEFAULT_TANK_CAPACITY
            )

            # Check if we need to reset daily counters
            await self._check_daily_reset()

            _LOGGER.debug(
                "Loaded persistent data: fuel=%.2fL, runtime=%ds",
                self._total_fuel_consumed,
                self._total_runtime
            )
        except Exception as err:
            _LOGGER.error("Error loading persistent data: %s", err)

    async def async_save_data(self) -> None:
        """Save persistent data to storage."""
        try:
            self._storage_data[STORAGE_KEY_TOTAL_FUEL] = self._total_fuel_consumed
            self._storage_data[STORAGE_KEY_DAILY_FUEL] = self._daily_fuel_consumed
            self._storage_data[STORAGE_KEY_DAILY_DATE] = self._last_fuel_date
            self._storage_data[STORAGE_KEY_TOTAL_RUNTIME] = self._total_runtime
            self._storage_data[STORAGE_KEY_DAILY_RUNTIME] = self._daily_runtime
            self._storage_data[STORAGE_KEY_DAILY_RUNTIME_DATE] = self._last_runtime_date

            await self._store.async_save(self._storage_data)
        except Exception as err:
            _LOGGER.error("Error saving persistent data: %s", err)

    async def _check_daily_reset(self) -> None:
        """Check if we need to reset daily counters."""
        current_date = datetime.now().date().isoformat()

        # Reset daily fuel if date changed
        if current_date != self._last_fuel_date:
            _LOGGER.info("Resetting daily fuel counter (was %.2fL)", self._daily_fuel_consumed)
            self._daily_fuel_consumed = 0.0
            self._last_fuel_date = current_date
            self.data["daily_fuel_consumed"] = 0.0

        # Reset daily runtime if date changed
        if current_date != self._last_runtime_date:
            _LOGGER.info("Resetting daily runtime counter (was %ds)", self._daily_runtime)
            self._daily_runtime = 0
            self._last_runtime_date = current_date
            self.data["daily_runtime"] = 0

        # Save if anything was reset
        if (current_date != self._last_fuel_date or
            current_date != self._last_runtime_date):
            await self.async_save_data()

    def _calculate_fuel_consumption(self, elapsed_seconds: float) -> float:
        """Calculate fuel consumed based on power level and elapsed time."""
        # Only consume fuel when heater is actively running
        if self.data.get("running_step") != RUNNING_STEP_RUNNING:
            return 0.0

        # Get current power level
        power_level = self.data.get("set_level", 1)
        if power_level < 1 or power_level > 10:
            power_level = 1

        # Get consumption rate from table (L/h)
        base_consumption_rate = FUEL_CONSUMPTION_TABLE.get(power_level, 0.16)

        # Apply calibration factor from config
        calibration = self.config_entry.options.get(
            CONF_FUEL_CALIBRATION,
            DEFAULT_FUEL_CALIBRATION
        )
        consumption_rate = base_consumption_rate * calibration

        # Calculate fuel consumed in this period (L)
        fuel_consumed = (consumption_rate / 3600.0) * elapsed_seconds

        # Update hourly rate for display
        self.data["hourly_fuel_consumption"] = consumption_rate

        return fuel_consumed

    def _update_fuel_tracking(self, elapsed_seconds: float) -> None:
        """Update fuel consumption tracking."""
        fuel_consumed = self._calculate_fuel_consumption(elapsed_seconds)

        if fuel_consumed > 0:
            self._total_fuel_consumed += fuel_consumed
            self._daily_fuel_consumed += fuel_consumed

            self.data["total_fuel_consumed"] = round(self._total_fuel_consumed, 3)
            self.data["daily_fuel_consumed"] = round(self._daily_fuel_consumed, 3)

            # Update tank level
            tank_capacity = self.data["tank_capacity"]
            fuel_remaining = max(0, tank_capacity - self._total_fuel_consumed)
            fuel_level_percent = (fuel_remaining / tank_capacity * 100) if tank_capacity > 0 else 0

            self.data["fuel_remaining"] = round(fuel_remaining, 2)
            self.data["fuel_level_percent"] = round(fuel_level_percent, 1)

    def _update_runtime_tracking(self, elapsed_seconds: float) -> None:
        """Update runtime tracking."""
        # Only count runtime when heater is actively running
        if self.data.get("running_step") == RUNNING_STEP_RUNNING:
            self._total_runtime += int(elapsed_seconds)
            self._daily_runtime += int(elapsed_seconds)

            self.data["total_runtime"] = self._total_runtime
            self.data["daily_runtime"] = self._daily_runtime

    async def _async_update_data(self) -> dict[str, Any]:
        """Update data from the heater."""
        # Calculate elapsed time since last update
        current_time = time.time()
        elapsed_seconds = current_time - self._last_update_time
        self._last_update_time = current_time

        # Check for daily reset
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
                return self.data

        try:
            # Request status
            status = await self._send_command(1, 0, 85)

            if status:
                self.data["connected"] = True

                # Update fuel and runtime tracking
                self._update_fuel_tracking(elapsed_seconds)
                self._update_runtime_tracking(elapsed_seconds)

                # Save data periodically (every 5 minutes to reduce wear)
                if int(current_time) % 300 < UPDATE_INTERVAL:
                    await self.async_save_data()

                return self.data
            else:
                _LOGGER.warning("No status received from heater")
                self.data["connected"] = False

        except Exception as err:
            _LOGGER.error("Error updating data: %s", err)
            self.data["connected"] = False

        return self.data

    async def _ensure_connected(self) -> None:
        """Ensure BLE connection is established with exponential backoff."""
        if self._client and self._client.is_connected:
            self._connection_attempts = 0  # Reset on successful connection
            return

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

        self._client = await establish_connection(
            BleakClient,
            self._ble_device,
            self._ble_device.address,
        )

        # Get characteristic first
        for service in self._client.services:
            if service.uuid.lower() == SERVICE_UUID.lower():
                for char in service.characteristics:
                    if char.uuid.lower() == CHARACTERISTIC_UUID.lower():
                        self._characteristic = char
                        break

        if not self._characteristic:
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

        self._connection_attempts = 0  # Reset on successful connection
        _LOGGER.info("Connected to Vevor Heater")

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
        
        if header == 0xAA55 and len(data) == 20:
            # Protocol 1: 0xAA 0x55, 20 bytes, not encrypted
            self._parse_protocol_aa55(data)
        elif header == 0xAA66 and len(data) == 20:
            # Protocol 2: 0xAA 0x66, 20 bytes, not encrypted
            self._parse_protocol_aa66(data)
        elif len(data) == 48:
            # Protocol 3/4: 48 bytes, encrypted
            decrypted = _decrypt_data(data)
            header = (_u8_to_number(decrypted[0]) << 8) | _u8_to_number(decrypted[1])
            
            if header == 0xAA55:
                self._parse_protocol_aa55_encrypted(decrypted)
            elif header == 0xAA66:
                self._parse_protocol_aa66_encrypted(decrypted)
        else:
            _LOGGER.debug("Unknown protocol, length: %d, header: 0x%04X", len(data), header)

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

    async def _send_command(self, command: int, argument: int, n: int) -> bool:
        """Send command to heater."""
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
        
        # Build command packet
        packet = bytearray([0xAA, n % 256, 0, 0, 0, 0, 0, 0])
        
        if n == 136:
            packet[2] = random.randint(0, 255)
            packet[3] = random.randint(0, 255)
        else:  # n == 85
            packet[2] = self._passkey // 100
            packet[3] = self._passkey % 100
        
        packet[4] = command % 256
        packet[5] = argument % 256
        packet[6] = argument // 256
        packet[7] = (packet[2] + packet[3] + packet[4] + packet[5] + packet[6]) % 256

        _LOGGER.info("📤 Sending command: %s (cmd=%d, arg=%d)", packet.hex(), command, argument)
        
        try:
            self._notification_data = None
            await self._client.write_gatt_char(self._characteristic, packet)
            
            # Wait for notification
            for _ in range(20):  # Wait up to 2 seconds
                await asyncio.sleep(0.1)
                if self._notification_data:
                    return True
            
            _LOGGER.warning("No response received")
            return False
            
        except Exception as err:
            _LOGGER.error("Error sending command: %s", err)
            return False

    async def async_turn_on(self) -> None:
        """Turn heater on."""
        # Command 3, arg=1 for ON (verified with BYD heater)
        await self._send_command(3, 1, 85)
        await self.async_request_refresh()

    async def async_turn_off(self) -> None:
        """Turn heater off."""
        # Command 3, arg=0 for OFF (verified with BYD heater)
        await self._send_command(3, 0, 85)
        await self.async_request_refresh()

    async def async_set_level(self, level: int) -> None:
        """Set heater level (1-10)."""
        # Command 4 for level (verified with BYD heater)
        level = max(1, min(10, level))
        await self._send_command(4, level, 85)
        await self.async_request_refresh()

    async def async_set_temperature(self, temperature: int) -> None:
        """Set target temperature."""
        # Command 4 for temperature (1-36°C)
        temperature = max(1, min(36, temperature))
        await self._send_command(4, temperature, 85)
        await self.async_request_refresh()

    async def async_set_mode(self, mode: int) -> None:
        """Set running mode (0=Manual, 1=Level, 2=Temperature)."""
        # Command 2 for mode (needs verification)
        mode = max(0, min(2, mode))
        _LOGGER.info("Setting running mode to %d", mode)
        await self._send_command(2, mode, 85)
        await self.async_request_refresh()

    async def async_shutdown(self) -> None:
        """Shutdown coordinator."""
        if self._client and self._client.is_connected:
            try:
                await self._client.stop_notify(NOTIFY_UUID)
                await self._client.disconnect()
            except Exception:
                pass
        self._client = None
