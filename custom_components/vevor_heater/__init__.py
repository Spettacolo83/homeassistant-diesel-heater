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

from .const import DOMAIN
from .coordinator import VevorHeaterCoordinator

_LOGGER = logging.getLogger(__name__)

# Service constants
SERVICE_SEND_COMMAND = "send_command"
ATTR_COMMAND = "command"
ATTR_ARGUMENT = "argument"
ATTR_ARGUMENT2 = "argument2"

SERVICE_SEND_COMMAND_SCHEMA = vol.Schema({
    vol.Required(ATTR_COMMAND): vol.All(vol.Coerce(int), vol.Range(min=0, max=255)),
    vol.Required(ATTR_ARGUMENT): vol.All(vol.Coerce(int), vol.Range(min=0, max=255)),
    vol.Optional(ATTR_ARGUMENT2, default=85): vol.All(vol.Coerce(int), vol.Range(min=0, max=255)),
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


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Vevor Diesel Heater from a config entry."""
    address: str = entry.data[CONF_ADDRESS]
    
    _LOGGER.debug("Setting up Vevor Heater with address: %s", address)
    
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

    # Store coordinator (even if connection failed - will retry in background)
    hass.data.setdefault(DOMAIN, {})
    hass.data[DOMAIN][entry.entry_id] = coordinator

    # Forward entry setup to platforms
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    # Register debug service (only once)
    if not hass.services.has_service(DOMAIN, SERVICE_SEND_COMMAND):
        async def async_send_command(call: ServiceCall) -> None:
            """Handle send_command service call for debugging."""
            command = call.data[ATTR_COMMAND]
            argument = call.data[ATTR_ARGUMENT]
            argument2 = call.data.get(ATTR_ARGUMENT2, 85)

            _LOGGER.info(
                "Service %s.%s called: command=%d, argument=%d, argument2=%d",
                DOMAIN, SERVICE_SEND_COMMAND, command, argument, argument2
            )

            # Send to all configured heaters
            for entry_id, coord in hass.data[DOMAIN].items():
                if isinstance(coord, VevorHeaterCoordinator):
                    await coord.async_send_raw_command(command, argument, argument2)

        hass.services.async_register(
            DOMAIN,
            SERVICE_SEND_COMMAND,
            async_send_command,
            schema=SERVICE_SEND_COMMAND_SCHEMA,
        )
        _LOGGER.debug("Registered debug service: %s.%s", DOMAIN, SERVICE_SEND_COMMAND)

    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    if unload_ok := await hass.config_entries.async_unload_platforms(entry, PLATFORMS):
        coordinator: VevorHeaterCoordinator = hass.data[DOMAIN].pop(entry.entry_id)
        # Save fuel data before shutdown
        await coordinator.async_save_data()
        await coordinator.async_shutdown()

    return unload_ok
