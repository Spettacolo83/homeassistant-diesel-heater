"""Config flow for Vevor Diesel Heater integration."""
from __future__ import annotations

import logging
import math
import re
from typing import Any

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.components import bluetooth
from homeassistant.components.bluetooth import BluetoothServiceInfoBleak
from homeassistant.const import CONF_ADDRESS
from homeassistant.data_entry_flow import FlowResult, section
from homeassistant.helpers import selector

from .const import (
    ABBA_MAX_LEVEL,
    MAX_LEVEL,
    CONF_FUEL_RATES,
    CONF_AUTO_OFFSET_MAX,
    CONF_CRONUS_HEATER_MODEL,
    CONF_EXTERNAL_TEMP_SENSOR,
    CONF_FORCE_TEMP_UNIT,
    CONF_HCALORY_VARIANT,
    CONF_NEO_PASSWORD,
    CONF_NEO_CONTROLLER_TYPE,
    CONF_PIN,
    CONF_PRESET_AWAY_TEMP,
    CONF_PRESET_COMFORT_TEMP,
    CRONUS_HEATER_MODEL_OPTIONS,
    DEFAULT_AUTO_OFFSET_MAX,
    DEFAULT_CRONUS_HEATER_MODEL,
    DEFAULT_FORCE_TEMP_UNIT,
    DEFAULT_HCALORY_PIN,
    DEFAULT_NEO_PASSWORD,
    DEFAULT_PIN,
    DEFAULT_PRESET_AWAY_TEMP,
    DEFAULT_PRESET_COMFORT_TEMP,
    DOMAIN,
    FORCE_TEMP_UNIT_OPTIONS,
    HCALORY_MVP2_SERVICE_UUID,
    HEATGENIE_SERVICE_UUID,
    MAX_AUTO_OFFSET_MAX,
    MAX_NEO_PASSWORD,
    MAX_PIN,
    MIN_AUTO_OFFSET_MAX,
    MIN_NEO_PASSWORD,
    MIN_PIN,
)
from .hcalory import hcalory_variant_from_discovery, is_abba_named_controller
from .fuel import fuel_rate_for_level

_LOGGER = logging.getLogger(__name__)
HEATGENIE_NAME_PATTERN = re.compile(r"^C1:[0-9A-F]{2}:[0-9A-F]{2}:[0-9A-F]{2}:FE:[0-9A-F]{2}$")


def _is_heatgenie_device(discovery_info: BluetoothServiceInfoBleak) -> bool:
    """Return True only for the HeatGenie identities recognized by its app."""
    service_uuids = {uuid.lower() for uuid in discovery_info.service_uuids}
    if HEATGENIE_SERVICE_UUID.lower() not in service_uuids:
        return False
    name = (discovery_info.name or "").upper()
    return "BOYGU" in name or bool(HEATGENIE_NAME_PATTERN.fullmatch(name))


def _default_pin_for_discovery(discovery_info: BluetoothServiceInfoBleak) -> int:
    """Return the APK-defined default PIN for a discovered controller."""
    service_uuids = {uuid.lower() for uuid in discovery_info.service_uuids}
    if HCALORY_MVP2_SERVICE_UUID.lower() in service_uuids:
        return DEFAULT_HCALORY_PIN
    return DEFAULT_PIN


def _is_warm_drive_device(discovery_info: BluetoothServiceInfoBleak) -> bool:
    """Return whether the device has Warm Drive's exact advertised name."""
    return discovery_info.name == "Air Heater"


def _warm_drive_controller_type(
    discovery_info: BluetoothServiceInfoBleak,
) -> str | None:
    """Return the controller type encoded by Warm Drive's scan record."""
    if not _is_warm_drive_device(discovery_info):
        return None
    for payload in discovery_info.manufacturer_data.values():
        if len(payload) == 14:
            return "air" if payload[2] == 1 else "water"
    return None


HEATER_NAME_PREFIXES = (
    "BAC-",
    "BYD-",
    "HC-",
    "HCALORY",
)


def _is_likely_heater(discovery_info: BluetoothServiceInfoBleak) -> bool:
    """Return True if a BLE advertisement has an app-recognized heater name."""
    raw_name = discovery_info.name or ""
    name = raw_name.upper()
    return (
        _is_heatgenie_device(discovery_info)
        or is_abba_named_controller(raw_name)
        or _is_warm_drive_device(discovery_info)
        or hcalory_variant_from_discovery(discovery_info) is not None
        or any(name.startswith(prefix) for prefix in HEATER_NAME_PREFIXES)
        or "CRONUS" in raw_name
        or (name.startswith("HEATER") and name[6:].isdigit())
    )


class VevorHeaterConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Vevor Diesel Heater."""

    VERSION = 1

    def __init__(self) -> None:
        """Initialize the config flow."""
        self._discovery_info: BluetoothServiceInfoBleak | None = None
        self._discovered_devices: dict[str, BluetoothServiceInfoBleak] = {}

    async def async_step_bluetooth(
        self, discovery_info: BluetoothServiceInfoBleak
    ) -> FlowResult:
        """Handle the bluetooth discovery step."""
        if not _is_likely_heater(discovery_info):
            _LOGGER.debug(
                "Ignoring Diesel Heater Bluetooth discovery for %s (%s)",
                discovery_info.address,
                discovery_info.name,
            )
            return self.async_abort(reason="not_supported")

        _LOGGER.debug("Discovered Vevor Heater: %s", discovery_info.address)

        await self.async_set_unique_id(discovery_info.address)
        self._abort_if_unique_id_configured()

        self._discovery_info = discovery_info

        return await self.async_step_confirm()

    async def async_step_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Confirm discovery."""
        assert self._discovery_info is not None
        default_pin = _default_pin_for_discovery(self._discovery_info)
        default_neo_password = DEFAULT_NEO_PASSWORD

        if user_input is not None:
            data = {
                CONF_ADDRESS: self._discovery_info.address,
                CONF_PIN: user_input.get(CONF_PIN, default_pin),
                CONF_NEO_PASSWORD: user_input.get(
                    CONF_NEO_PASSWORD, default_neo_password
                ),
            }
            if controller_type := _warm_drive_controller_type(self._discovery_info):
                data[CONF_NEO_CONTROLLER_TYPE] = controller_type
            if variant := hcalory_variant_from_discovery(self._discovery_info):
                data[CONF_HCALORY_VARIANT] = variant.value
            return self.async_create_entry(
                title=f"Vevor Heater {self._discovery_info.address[-5:].replace(':', '')}",
                data=data,
            )

        self._set_confirm_only()

        return self.async_show_form(
            step_id="confirm",
            data_schema=vol.Schema({
                vol.Optional(
                    CONF_PIN,
                    default=default_pin,
                ): vol.All(
                    vol.Coerce(int),
                    vol.Range(min=MIN_PIN, max=MAX_PIN),
                ),
                vol.Optional(
                    CONF_NEO_PASSWORD,
                    default=default_neo_password,
                ): vol.All(
                    vol.Coerce(int),
                    vol.Range(min=MIN_NEO_PASSWORD, max=MAX_NEO_PASSWORD),
                ),
            }),
            description_placeholders={
                "name": f"Vevor Heater {self._discovery_info.address[-5:].replace(':', '')}"
            },
        )

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Handle the user step to pick discovered device."""
        if user_input is not None:
            address = user_input[CONF_ADDRESS]
            await self.async_set_unique_id(address)
            self._abort_if_unique_id_configured()

            if discovery_info := self._discovered_devices.get(address):
                self._discovery_info = discovery_info
                return await self.async_step_confirm()

            return self.async_create_entry(
                title=f"Vevor Heater {address[-5:].replace(':', '')}",
                data={
                    CONF_ADDRESS: address,
                    CONF_PIN: user_input.get(CONF_PIN, DEFAULT_PIN),
                    CONF_NEO_PASSWORD: user_input.get(CONF_NEO_PASSWORD, DEFAULT_NEO_PASSWORD),
                },
            )

        # Get current bluetooth devices
        current_addresses = self._async_current_ids()

        # Scan for Vevor heaters
        discovered = bluetooth.async_discovered_service_info(self.hass)

        _LOGGER.debug("Scanning for Vevor heaters, found %d BLE devices", len(discovered))

        # Add explicit check for known Vevor heater MAC address A4:C1:37:24:B8:64
        for discovery_info in discovered:
            address = discovery_info.address

            # Skip already configured devices
            if address in current_addresses or address in self._discovered_devices:
                continue

            device_name = discovery_info.name or ""
            is_heater_name = _is_likely_heater(discovery_info)

            _LOGGER.debug(
                "Device %s (%s): name_match=%s",
                address,
                device_name,
                is_heater_name,
            )

            if is_heater_name:
                self._discovered_devices[address] = discovery_info
                _LOGGER.info("Found potential Vevor heater: %s (%s)", address, device_name)

        if not self._discovered_devices:
            _LOGGER.warning(
                "No Vevor heaters found. Make sure the heater is powered on and within Bluetooth range. "
                "If using ESPHome Bluetooth Proxy, ensure it has available connection slots (max 3 connections)."
            )
            # Allow manual entry if no devices found
            return await self.async_step_manual()

        # Create selection list
        devices = {
            address: f"{info.name or 'Vevor Heater'} ({address})"
            for address, info in self._discovered_devices.items()
        }

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema({
                vol.Required(CONF_ADDRESS): vol.In(devices),
                vol.Optional(
                    CONF_PIN,
                    default=DEFAULT_PIN
                ): vol.All(
                    vol.Coerce(int),
                    vol.Range(min=MIN_PIN, max=MAX_PIN),
                ),
                vol.Optional(
                    CONF_NEO_PASSWORD,
                    default=DEFAULT_NEO_PASSWORD,
                ): vol.All(
                    vol.Coerce(int),
                    vol.Range(min=MIN_NEO_PASSWORD, max=MAX_NEO_PASSWORD),
                ),
            }),
        )

    async def async_step_manual(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Handle manual MAC address entry."""
        errors = {}

        if user_input is not None:
            address = user_input[CONF_ADDRESS].strip().upper().replace("-", ":")

            # Validate MAC address format
            if not re.match(r"^([0-9A-F]{2}:){5}[0-9A-F]{2}$", address):
                errors[CONF_ADDRESS] = "invalid_mac"
            else:
                await self.async_set_unique_id(address)
                self._abort_if_unique_id_configured()
                if any(
                    (entry.data.get(CONF_ADDRESS) or "").replace("-", ":").upper() == address
                    for entry in self._async_current_entries()
                ):
                    return self.async_abort(reason="already_configured")

                return self.async_create_entry(
                    title=f"Vevor Heater {address[-5:].replace(':', '')}",
                    data={
                        CONF_ADDRESS: address,
                        CONF_PIN: user_input.get(CONF_PIN, DEFAULT_PIN),
                        CONF_NEO_PASSWORD: user_input.get(CONF_NEO_PASSWORD, DEFAULT_NEO_PASSWORD),
                    },
                )

        return self.async_show_form(
            step_id="manual",
            data_schema=vol.Schema({
                vol.Required(CONF_ADDRESS, description="Bluetooth MAC Address (e.g., A4:C1:37:24:B8:64)"): str,
                vol.Optional(
                    CONF_PIN,
                    default=DEFAULT_PIN
                ): vol.All(
                    vol.Coerce(int),
                    vol.Range(min=MIN_PIN, max=MAX_PIN),
                ),
                vol.Optional(
                    CONF_NEO_PASSWORD,
                    default=DEFAULT_NEO_PASSWORD,
                ): vol.All(
                    vol.Coerce(int),
                    vol.Range(min=MIN_NEO_PASSWORD, max=MAX_NEO_PASSWORD),
                ),
            }),
            errors=errors,
            description_placeholders={
                "info": "Enter the Bluetooth MAC address of your Vevor heater. "
                        "You can find this in your Home Assistant Bluetooth logs or using a BLE scanner app."
            }
        )

    @staticmethod
    def async_get_options_flow(
        config_entry: config_entries.ConfigEntry,
    ) -> config_entries.OptionsFlow:
        """Get the options flow for this handler."""
        return VevorHeaterOptionsFlowHandler()


def _validate_fuel_rate(value: Any) -> float:
    """Reject negative/non-finite rates before storing user estimates."""
    try:
        rate = float(value)
    except (TypeError, ValueError, OverflowError) as err:
        raise vol.Invalid("Enter a non-negative litres-per-hour value") from err
    if isinstance(value, bool) or not math.isfinite(rate) or rate < 0:
        raise vol.Invalid("Enter a non-negative litres-per-hour value")
    return rate


class VevorHeaterOptionsFlowHandler(config_entries.OptionsFlow):
    """Handle options flow for Vevor Heater."""

    def _applicable_options(self) -> set[str]:
        """Use detected transport capabilities, not a configured field's presence."""
        coordinator = getattr(self.config_entry, "runtime_data", None)
        mode = getattr(coordinator, "protocol_mode", None)
        # An unloaded entry has no validated protocol. Keep recovery credentials
        # editable, but never advertise Cronus model selection without evidence.
        known = type(mode) is int and mode in range(1, 10)
        neo = (
            getattr(coordinator, "is_dz06_neo", False) is True
            or (not known and self.config_entry.data.get(CONF_NEO_CONTROLLER_TYPE) in ("air", "water"))
        )
        keys: set[str] = set()
        if neo or not known:
            keys.add(CONF_NEO_PASSWORD)
        if not neo and (not known or mode in (1, 2, 3, 4, 6, 7)):
            keys.add(CONF_PIN)
        if not neo and mode == 9:
            keys.add(CONF_CRONUS_HEATER_MODEL)
        else:
            keys.update((CONF_PRESET_AWAY_TEMP, CONF_PRESET_COMFORT_TEMP))
        if not neo and (not known or mode in (1, 2, 3, 4, 6)):
            keys.update((CONF_EXTERNAL_TEMP_SENSOR, CONF_AUTO_OFFSET_MAX))
        if not neo and (not known or mode in (4, 5, 6, 7)):
            keys.add(CONF_FORCE_TEMP_UNIT)
        if known and not neo and mode != 9:
            keys.add(CONF_FUEL_RATES)
        return keys

    def _fuel_schema(self) -> vol.Schema:
        """Build only the selected heater's supported level inputs."""
        mode = getattr(getattr(self.config_entry, "runtime_data", None), "protocol_mode", None)
        maximum = ABBA_MAX_LEVEL if mode == 5 else MAX_LEVEL
        saved = self.config_entry.data.get(CONF_FUEL_RATES)
        return vol.Schema({
            vol.Optional(f"level_{level}", default=fuel_rate_for_level(level, saved)):
                vol.All(vol.Coerce(float), vol.Range(min=0))
            for level in range(1, maximum + 1)
        })

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Manage the options."""
        applicable = self._applicable_options()
        if user_input is not None:
            user_input = {key: value for key, value in user_input.items() if key in applicable}
            if CONF_FUEL_RATES in user_input:
                try:
                    raw_rates = user_input[CONF_FUEL_RATES]
                    if isinstance(raw_rates, dict):
                        for value in raw_rates.values():
                            _validate_fuel_rate(value)
                    user_input[CONF_FUEL_RATES] = {
                        key: _validate_fuel_rate(value)
                        for key, value in self._fuel_schema()(user_input[CONF_FUEL_RATES]).items()
                    }
                except vol.Invalid:
                    return self.async_show_form(
                        step_id="init", data_schema=self._options_schema(),
                        errors={CONF_FUEL_RATES: "invalid_fuel_rate"},
                    )
            # Handle clearing of external sensor
            # EntitySelector returns None when cleared, store as empty string
            if CONF_EXTERNAL_TEMP_SENSOR in applicable and (
                CONF_EXTERNAL_TEMP_SENSOR not in user_input
                or user_input.get(CONF_EXTERNAL_TEMP_SENSOR) is None
            ):
                user_input[CONF_EXTERNAL_TEMP_SENSOR] = ""
                # Also clear auto_offset_max when sensor is cleared
                user_input.pop(CONF_AUTO_OFFSET_MAX, None)

            # Update config entry with new settings
            # Merge with existing data, but remove keys that were cleared
            new_data = {**self.config_entry.data}
            for key, value in user_input.items():
                if value == "" or value is None:
                    new_data.pop(key, None)
                else:
                    new_data[key] = value

            reload_fields = {
                CONF_PIN, CONF_NEO_PASSWORD, CONF_FORCE_TEMP_UNIT,
                CONF_EXTERNAL_TEMP_SENSOR, CONF_CRONUS_HEATER_MODEL,
            }
            reload_needed = any(
                self.config_entry.data.get(key) != new_data.get(key) for key in reload_fields
            )
            self.hass.config_entries.async_update_entry(self.config_entry, data=new_data)
            if reload_needed:
                self.hass.config_entries.async_schedule_reload(self.config_entry.entry_id)
            return self.async_create_entry(title="", data={})

        return self.async_show_form(
            step_id="init", data_schema=self._options_schema()
        )

    def _options_schema(self) -> vol.Schema:
        """Keep advanced fuel estimates collapsed within the existing form."""
        applicable = self._applicable_options()
        # Get current external sensor value (may be empty string or None)
        current_external_sensor = self.config_entry.data.get(CONF_EXTERNAL_TEMP_SENSOR)
        # EntitySelector expects None for empty, not empty string
        if not current_external_sensor:
            current_external_sensor = None

        # Build schema - only show auto_offset_max if external sensor is configured
        schema_dict = {
            vol.Optional(
                CONF_PIN,
                default=self.config_entry.data.get(CONF_PIN, DEFAULT_PIN)
            ): vol.All(
                vol.Coerce(int),
                vol.Range(min=MIN_PIN, max=MAX_PIN),
            ),
            vol.Optional(
                CONF_NEO_PASSWORD,
                default=self.config_entry.data.get(CONF_NEO_PASSWORD, DEFAULT_NEO_PASSWORD),
            ): vol.All(
                vol.Coerce(int),
                vol.Range(min=MIN_NEO_PASSWORD, max=MAX_NEO_PASSWORD),
            ),
            vol.Optional(
                CONF_PRESET_AWAY_TEMP,
                default=self.config_entry.data.get(CONF_PRESET_AWAY_TEMP, DEFAULT_PRESET_AWAY_TEMP)
            ): vol.All(
                vol.Coerce(int),
                vol.Range(min=8, max=36),
            ),
            vol.Optional(
                CONF_PRESET_COMFORT_TEMP,
                default=self.config_entry.data.get(CONF_PRESET_COMFORT_TEMP, DEFAULT_PRESET_COMFORT_TEMP)
            ): vol.All(
                vol.Coerce(int),
                vol.Range(min=8, max=36),
            ),
            vol.Optional(
                CONF_EXTERNAL_TEMP_SENSOR,
                description={"suggested_value": current_external_sensor}
            ): selector.EntitySelector(
                selector.EntitySelectorConfig(
                    domain="sensor",
                    device_class="temperature",
                )
            ),
            vol.Optional(
                CONF_FORCE_TEMP_UNIT,
                default=self.config_entry.data.get(
                    CONF_FORCE_TEMP_UNIT, DEFAULT_FORCE_TEMP_UNIT
                ),
            ): selector.SelectSelector(
                selector.SelectSelectorConfig(
                    options=list(FORCE_TEMP_UNIT_OPTIONS),
                    translation_key=CONF_FORCE_TEMP_UNIT,
                    mode=selector.SelectSelectorMode.DROPDOWN,
                )
            ),
            vol.Optional(
                CONF_CRONUS_HEATER_MODEL,
                default=self.config_entry.data.get(
                    CONF_CRONUS_HEATER_MODEL, DEFAULT_CRONUS_HEATER_MODEL
                ),
            ): selector.SelectSelector(
                selector.SelectSelectorConfig(
                    options=list(CRONUS_HEATER_MODEL_OPTIONS),
                    translation_key=CONF_CRONUS_HEATER_MODEL,
                    mode=selector.SelectSelectorMode.DROPDOWN,
                )
            ),
        }

        # Only show auto_offset_max if external sensor is configured
        if current_external_sensor:
            schema_dict[vol.Optional(
                CONF_AUTO_OFFSET_MAX,
                default=self.config_entry.data.get(CONF_AUTO_OFFSET_MAX, DEFAULT_AUTO_OFFSET_MAX)
            )] = vol.All(
                vol.Coerce(int),
                vol.Range(min=MIN_AUTO_OFFSET_MAX, max=MAX_AUTO_OFFSET_MAX),
            )

        schema_dict = {
            key: validator for key, validator in schema_dict.items()
            if key.schema in applicable
        }

        if CONF_FUEL_RATES in applicable:
            schema_dict[vol.Optional(CONF_FUEL_RATES)] = section(
                self._fuel_schema(), {"collapsed": True}
            )
        return vol.Schema(schema_dict)
