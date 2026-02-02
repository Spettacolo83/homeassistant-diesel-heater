"""The Vevor Diesel Heater integration."""
from __future__ import annotations

import asyncio
import logging
from typing import Any

import voluptuous as vol

from homeassistant.components import bluetooth
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_ADDRESS, Platform
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.exceptions import ConfigEntryNotReady
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers import entity_registry as er

from .const import DOMAIN
from .coordinator import VevorHeaterCoordinator

VevorHeaterConfigEntry = ConfigEntry[VevorHeaterCoordinator]

_LOGGER = logging.getLogger(__name__)

# Entity unique_id suffix migrations: old_suffix -> new_suffix
# These preserve entity history when unique_ids are renamed across versions.
_UNIQUE_ID_MIGRATIONS: dict[str, str] = {
    # v1.0.27-beta.19: renamed fuel sensors with "est" prefix
    "_hourly_fuel_consumption": "_est_hourly_fuel_consumption",
    "_daily_fuel_consumed": "_est_daily_fuel_consumed",
    "_total_fuel_consumed": "_est_total_fuel_consumed",
    "_daily_fuel_history": "_est_daily_fuel_history",
    # v1.0.27-beta.19: renamed fuel reset button
    "_reset_fuel_level": "_reset_est_fuel_remaining",
}

# Entity unique_id suffixes to remove (replaced by entities on a different platform)
_UNIQUE_IDS_TO_REMOVE: set[str] = {
    # v1.0.27-beta.20: backlight number entity replaced by backlight select entity
    "_backlight",
}

# Service constants
SERVICE_SEND_COMMAND = "send_command"
ATTR_COMMAND = "command"
ATTR_ARGUMENT = "argument"
ATTR_DEVICE_ID = "device_id"

SERVICE_SEND_COMMAND_SCHEMA = vol.Schema({
    vol.Optional(ATTR_DEVICE_ID): cv.string,
    vol.Required(ATTR_COMMAND): vol.All(vol.Coerce(int), vol.Range(min=0, max=255)),
    vol.Required(ATTR_ARGUMENT): vol.All(vol.Coerce(int), vol.Range(min=-128, max=127)),
})

PLATFORMS: list[Platform] = [
    Platform.BINARY_SENSOR,
    Platform.BUTTON,
    Platform.CLIMATE,
    Platform.FAN,
    Platform.NUMBER,
    Platform.SELECT,
    Platform.SENSOR,
    Platform.SWITCH,
]


def _migrate_entity_unique_ids(
    hass: HomeAssistant,
    entry: ConfigEntry,
) -> None:
    """Migrate entity unique_ids from older versions to preserve history."""
    registry = er.async_get(hass)

    for entity in er.async_entries_for_config_entry(registry, entry.entry_id):
        # Migrate renamed unique_ids (same platform)
        for old_suffix, new_suffix in _UNIQUE_ID_MIGRATIONS.items():
            if entity.unique_id.endswith(old_suffix):
                new_unique_id = entity.unique_id[: -len(old_suffix)] + new_suffix
                _LOGGER.info(
                    "Migrating entity %s unique_id: %s -> %s",
                    entity.entity_id,
                    entity.unique_id,
                    new_unique_id,
                )
                registry.async_update_entity(
                    entity.entity_id, new_unique_id=new_unique_id
                )
                break

        # Remove entities that were replaced by a different platform entity
        for suffix in _UNIQUE_IDS_TO_REMOVE:
            if entity.unique_id.endswith(suffix):
                _LOGGER.info(
                    "Removing deprecated entity %s (unique_id: %s, "
                    "replaced by new entity on different platform)",
                    entity.entity_id,
                    entity.unique_id,
                )
                registry.async_remove(entity.entity_id)
                break


async def async_setup_entry(hass: HomeAssistant, entry: VevorHeaterConfigEntry) -> bool:
    """Set up Vevor Diesel Heater from a config entry."""
    address: str = entry.data[CONF_ADDRESS]

    _LOGGER.debug("Setting up Vevor Heater with address: %s", address)

    # Migrate entity unique_ids from older versions (preserves history)
    _migrate_entity_unique_ids(hass, entry)
    
    # Get BLE device from Home Assistant's bluetooth integration
    ble_device = bluetooth.async_ble_device_from_address(
        hass, address.upper(), connectable=True
    )
    
    if not ble_device:
        raise ConfigEntryNotReady(
            f"Could not find Vevor Heater with address {address}"
        )
    
    # Create coordinator
    coordinator = VevorHeaterCoordinator(hass, ble_device, entry)

    # Load persistent fuel data
    await coordinator.async_load_data()

    # Initial data fetch with timeout
    # Allow setup to complete even if connection fails - entities will show as unavailable
    # and the coordinator will keep retrying in background every 30 seconds
    try:
        await asyncio.wait_for(
            coordinator.async_config_entry_first_refresh(),
            timeout=30.0
        )
        _LOGGER.info("Successfully connected to Vevor Heater at %s", address)
    except asyncio.TimeoutError:
        _LOGGER.warning(
            "Initial connection to Vevor Heater at %s timed out after 30 seconds. "
            "Setup will complete anyway and retry in background. "
            "Entities will show as unavailable until connection succeeds. "
            "Make sure the heater is powered on, in Bluetooth range, and the Vevor app is disconnected.",
            address
        )
    except Exception as err:
        _LOGGER.warning(
            "Initial connection to Vevor Heater at %s failed: %s. "
            "Setup will complete anyway and retry in background. "
            "Entities will show as unavailable until connection succeeds. "
            "Make sure the heater is powered on, in Bluetooth range, and the Vevor app is disconnected.",
            address,
            err
        )

    # Store coordinator on the config entry (even if connection failed - will retry in background)
    entry.runtime_data = coordinator

    # Forward entry setup to platforms
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    # Register debug service (only once)
    if not hass.services.has_service(DOMAIN, SERVICE_SEND_COMMAND):
        async def async_send_command(call: ServiceCall) -> None:
            """Handle send_command service call for debugging."""
            command = call.data[ATTR_COMMAND]
            argument = call.data[ATTR_ARGUMENT]
            device_id = call.data.get(ATTR_DEVICE_ID)

            _LOGGER.info(
                "Service %s.%s called: command=%d, argument=%d, device_id=%s",
                DOMAIN, SERVICE_SEND_COMMAND, command, argument, device_id
            )

            # Find target heaters
            target_coords = []
            for config_entry in hass.config_entries.async_entries(DOMAIN):
                coord = getattr(config_entry, "runtime_data", None)
                if not isinstance(coord, VevorHeaterCoordinator):
                    continue
                if device_id:
                    # Match by MAC address (last 5 chars or full address)
                    if (device_id.upper() in coord.address.upper() or
                        coord.address.upper().endswith(device_id.upper().replace(":", ""))):
                        target_coords.append(coord)
                else:
                    # No device_id specified, send to all
                    target_coords.append(coord)

            if not target_coords:
                _LOGGER.warning("No matching heater found for device_id: %s", device_id)
                return

            for coord in target_coords:
                _LOGGER.info("Sending command to heater: %s", coord.address)
                await coord.async_send_raw_command(command, argument)

        hass.services.async_register(
            DOMAIN,
            SERVICE_SEND_COMMAND,
            async_send_command,
            schema=SERVICE_SEND_COMMAND_SCHEMA,
        )
        _LOGGER.debug("Registered debug service: %s.%s", DOMAIN, SERVICE_SEND_COMMAND)

    return True


async def async_unload_entry(hass: HomeAssistant, entry: VevorHeaterConfigEntry) -> bool:
    """Unload a config entry."""
    if unload_ok := await hass.config_entries.async_unload_platforms(entry, PLATFORMS):
        coordinator: VevorHeaterCoordinator = entry.runtime_data
        # Save fuel data before shutdown
        await coordinator.async_save_data()
        await coordinator.async_shutdown()

    return unload_ok
