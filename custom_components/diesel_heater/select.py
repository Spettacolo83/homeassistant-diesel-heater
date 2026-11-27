"""Select platform for Vevor Diesel Heater."""
from __future__ import annotations

PARALLEL_UPDATES = 1

import logging

from homeassistant.components.select import SelectEntity
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import VevorHeaterConfigEntry
from .const import (
    BACKLIGHT_OPTIONS,
    CBFF_LANGUAGE_OPTIONS,
    DOMAIN,
    HIGH_ALTITUDE_MODE_OPTIONS,
    LANGUAGE_OPTIONS,
    PUMP_TYPE_OPTIONS,
    RUNNING_MODE_LEVEL,
    RUNNING_MODE_TEMPERATURE,
    RUNNING_MODE_VENTILATION,
    RUNNING_MODE_NAMES,
    RUNNING_STATE_OFF,
    RUNNING_STATE_ON,
    RUNNING_STEP_COOLDOWN,
    RUNNING_STEP_NAMES,
    RUNNING_STEP_STANDBY,
    RUNNING_STEP_VENTILATION,
    TANK_VOLUME_OPTIONS,
    WARM_DRIVE_PUMP_FLOW_OPTIONS,
    WARM_DRIVE_TANK_VOLUME_OPTIONS,
)
from .coordinator import VevorHeaterCoordinator

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: VevorHeaterConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Vevor Heater select from config entry.

    Entities are created conditionally based on the detected BLE protocol.
    Mode 0 (unknown) creates all entities as safe fallback.
    """
    coordinator = entry.runtime_data
    mode = coordinator.protocol_mode

    if mode == 9:
        # ThermoConnect makes the four-mode control editable only for air.
        # Water mode is exposed as read-only telemetry instead.
        entities: list[SelectEntity] = (
            [CronusModeSelect(coordinator)]
            if coordinator.data.get("cronus_controller_type") == "air"
            else []
        )
    else:
        entities = [VevorHeaterModeSelect(coordinator)]

    # Warm Drive has its own app-defined tank/pump configuration fields.
    if coordinator.is_warm_drive_controller is True:
        entities.extend([
            VevorHeaterPumpTypeSelect(coordinator),
            VevorHeaterTankVolumeSelect(coordinator),
        ])
    elif mode in (0, 4, 6) and coordinator.is_dz06_neo is not True:
        entities.extend([
            VevorHeaterLanguageSelect(coordinator),
            VevorHeaterPumpTypeSelect(coordinator),
            VevorHeaterTankVolumeSelect(coordinator),
        ])

    # Backlight select (encrypted + CBFF protocols)
    if mode in (0, 2, 4, 6) and coordinator.is_dz06_neo is not True:
        entities.append(VevorBacklightSelect(coordinator))

    # High Altitude Mode (Hcalory MVP2 only - 3 modes: Disabled, Mode 1, Mode 2)
    # @Xev: Hcalory needs selector instead of binary switch (issue #34)
    if mode == 7:
        entities.append(VevorHighAltitudeModeSelect(coordinator))

    async_add_entities(entities)


class CronusModeSelect(SelectEntity):
    """ThermoConnect controller mode selector."""

    _attr_has_entity_name = True
    _attr_name = "Mode"
    _attr_icon = "mdi:hvac"
    _attr_options = ["Heating", "Ventilation", "Boost", "Eco"]

    def __init__(self, coordinator: VevorHeaterCoordinator) -> None:
        """Initialize the ThermoConnect mode selector."""
        self.coordinator = coordinator
        self._attr_unique_id = f"{coordinator.address}_cronus_mode"
        self._attr_device_info = {
            "identifiers": {(DOMAIN, coordinator.address)},
            "name": "Webasto Cronus",
            "manufacturer": "Webasto",
            "model": "Cronus Smart",
        }

    @property
    def available(self) -> bool:
        """Return whether ThermoConnect has identified this controller."""
        return (
            self.coordinator.data.get("connected", False)
            and self.coordinator.data.get("cronus_controller_type") == "air"
        )

    @property
    def current_option(self) -> str | None:
        """Return the mode name supplied by ThermoConnect."""
        mode = self.coordinator.data.get("cronus_mode")
        return mode.capitalize() if mode else None

    async def async_select_option(self, option: str) -> None:
        """Write the app's corresponding controller-mode record."""
        await self.coordinator.async_set_cronus_mode(option.lower())

    async def async_added_to_hass(self) -> None:
        """Subscribe to coordinator state changes."""
        self.async_on_remove(
            self.coordinator.async_add_listener(self._handle_coordinator_update)
        )

    def _handle_coordinator_update(self) -> None:
        """Refresh the entity after the record cache changes."""
        self.async_write_ha_state()

class VevorHeaterModeSelect(SelectEntity):
    """Select entity for Vevor Heater running mode.

    Includes a "Ventilation" option only when the connected controller
    explicitly advertises fan-only support.
    """

    _attr_has_entity_name = True
    _attr_name = "Running Mode"
    _attr_icon = "mdi:cog"

    def __init__(self, coordinator: VevorHeaterCoordinator) -> None:
        """Initialize the select entity."""
        self.coordinator = coordinator
        self._attr_device_info = {
            "identifiers": {(DOMAIN, coordinator.address)},
            "name": "Vevor Heater",
            "manufacturer": "Vevor",
            "model": "Diesel Heater",
        }
        self._attr_unique_id = f"{coordinator.address}_running_mode"

    @property
    def options(self) -> list[str]:
        """Include the displayed state so Home Assistant can render it."""
        options = self._writable_options()
        if (reported := self.current_option) is not None and reported not in options:
            options.append(reported)
        return options

    def _writable_options(self) -> list[str]:
        """Return available running mode options.

        ABBA exposes fan-only only from standby. AA66 controllers expose it
        only when their app-advertised motherboard capability says it exists.
        """
        base_options = [
            RUNNING_MODE_NAMES[RUNNING_MODE_LEVEL],
            RUNNING_MODE_NAMES[RUNNING_MODE_TEMPERATURE],
        ]

        # ABBA uses a dedicated ventilation command available from standby.
        if self.coordinator.protocol_mode == 5:  # ABBA protocol
            running_step = self.coordinator.data.get("running_step")
            if running_step in (RUNNING_STEP_STANDBY, RUNNING_STEP_VENTILATION):
                base_options.append(RUNNING_MODE_NAMES[RUNNING_MODE_VENTILATION])

        # Sunster's AA66 app only exposes ventilation for explicitly
        # advertised controller revisions; do not make it a generic AA66 mode.
        elif (
            self.coordinator.protocol_mode == 4
            and self.coordinator.supports_aa66_ventilation
        ) or (
            self.coordinator.protocol_mode == 6
            and self.coordinator.supports_cbff_ventilation
        ):
            base_options.append(RUNNING_MODE_NAMES[RUNNING_MODE_VENTILATION])

        return base_options

    @property
    def available(self) -> bool:
        """Return if entity is available.

        Locked while burn-off is active: running mode is snapshotted at start
        and restored afterwards.
        """
        if self.coordinator.burnoff_active:
            return False
        return self.coordinator.data.get("connected", False)

    @property
    def current_option(self) -> str | None:
        """Return the reported control mode or a known operating state."""
        coordinator = self.coordinator
        data = coordinator.data
        protocol = coordinator.protocol_mode
        step = data.get("running_step")
        mode = data.get("running_mode")
        if not data.get("connected"):
            return None

        if protocol == 8:
            # HeatGenie F2 machine states are independent of its heat mode.
            special_mode = {
                7: "Manual Fuel Pump",
                8: "Ventilation",
                9: "Start/Stop Mode",
                10: "Start/Stop Mode",
            }.get(data.get("heatgenie_raw_state"))
            if special_mode is not None:
                return special_mode

        # Hcalory also reports the fan step while starting a burn; its
        # status nibble is what identifies actual ventilation.
        neo = protocol == 0 and coordinator.is_dz06_neo is True
        if (protocol == 7 and data.get("hcalory_status") == 0xC) or (
            (protocol == 5 or neo) and step == RUNNING_STEP_VENTILATION
        ):
            return RUNNING_MODE_NAMES[RUNNING_MODE_VENTILATION]
        if mode in (RUNNING_MODE_LEVEL, RUNNING_MODE_TEMPERATURE):
            return RUNNING_MODE_NAMES[mode]
        if (
            (protocol == 6 or (protocol == 4 and coordinator.supports_aa66_ventilation))
            and mode == RUNNING_MODE_VENTILATION
            and data.get("running_state") == RUNNING_STATE_ON
        ):
            return RUNNING_MODE_NAMES[RUNNING_MODE_VENTILATION]

        # Preserve a reported heat mode above, including while the device is
        # stopped. If it reports no heat mode, show only substantiated states.
        if protocol == 7 and data.get("hcalory_status") == 0xF:
            return "Fault"
        if protocol == 8:
            return {
                0: "Resetting",
                4: "Cooldown",
                5: "Standby",
                6: "Fault",
            }.get(data.get("heatgenie_raw_state"))
        if protocol in (1, 2, 3, 4, 5, 6, 7) or neo:
            if step == RUNNING_STEP_COOLDOWN:
                return RUNNING_STEP_NAMES[RUNNING_STEP_COOLDOWN]
            # AirHeaterBLE also lists its closed/Standby state at step 5.
            standby = step == RUNNING_STEP_STANDBY or (protocol in (1, 2, 3, 4) and step == 5)
            if standby and data.get("running_state") == RUNNING_STATE_OFF:
                return RUNNING_STEP_NAMES[RUNNING_STEP_STANDBY]
        return None

    async def async_select_option(self, option: str) -> None:
        """Send a mode change only for controller-supported controls."""
        if option not in self._writable_options():
            # Display-only states may appear as options, including after a
            # state transition that removed them from the current list.
            return
        for mode, name in RUNNING_MODE_NAMES.items():
            if name == option:
                _LOGGER.info("Changing running mode to: %s (value: %d)", option, mode)
                await self.coordinator.async_set_mode(mode)
                return

    async def async_added_to_hass(self) -> None:
        """When entity is added to hass."""
        self.async_on_remove(
            self.coordinator.async_add_listener(self._handle_coordinator_update)
        )

    def _handle_coordinator_update(self) -> None:
        """Handle updated data from the coordinator."""
        self.async_write_ha_state()


class VevorHeaterLanguageSelect(SelectEntity):
    """Select entity for Vevor Heater voice notification language."""

    _attr_has_entity_name = True
    _attr_name = "Language"
    _attr_icon = "mdi:translate"
    _attr_entity_category = EntityCategory.CONFIG
    _attr_options = list(LANGUAGE_OPTIONS.values())

    def __init__(self, coordinator: VevorHeaterCoordinator) -> None:
        """Initialize the select entity."""
        self.coordinator = coordinator
        self._attr_device_info = {
            "identifiers": {(DOMAIN, coordinator.address)},
            "name": "Vevor Heater",
            "manufacturer": "Vevor",
            "model": "Diesel Heater",
        }
        self._attr_unique_id = f"{coordinator.address}_language"

    @property
    def options(self) -> list[str]:
        """Return the family-specific, currently supported language choices."""
        if self.coordinator.protocol_mode != 6:
            return list(LANGUAGE_OPTIONS.values())
        mask = self.coordinator.data.get("cbff_language_mask")
        if type(mask) is int and 0 <= mask <= 0xFFFF:
            return [
                name for code, name in CBFF_LANGUAGE_OPTIONS.items()
                if code == 0 or mask & (1 << (code - 1))
            ]
        # Before metadata arrives, only echo a valid observed value or turn off.
        current = self.coordinator.data.get("language")
        return [
            name for code, name in CBFF_LANGUAGE_OPTIONS.items()
            if code == 0 or code == current
        ]

    @property
    def available(self) -> bool:
        """Return whether the controller exposes a usable language setting."""
        if self.coordinator.protocol_mode == 6:
            return (
                self.coordinator.data.get("connected", False)
                and self.coordinator.data.get("language") in CBFF_LANGUAGE_OPTIONS
            )
        return self.coordinator.data.get("connected", False)

    @property
    def current_option(self) -> str | None:
        """Return the current language using this controller's mapping."""
        language_code = self.coordinator.data.get("language")
        if self.coordinator.protocol_mode == 6:
            return CBFF_LANGUAGE_OPTIONS.get(language_code)
        if language_code is not None:
            return LANGUAGE_OPTIONS.get(language_code, f"Unknown ({language_code})")
        return None

    async def async_select_option(self, option: str) -> None:
        """Change language only when the current options permit it."""
        if option not in self.options:
            _LOGGER.error("Unavailable language option: %s", option)
            return
        if self.coordinator.protocol_mode == 6 and not self.available:
            _LOGGER.error("CBFF language setting unavailable")
            return
        mapping = CBFF_LANGUAGE_OPTIONS if self.coordinator.protocol_mode == 6 else LANGUAGE_OPTIONS
        language_code = next(code for code, name in mapping.items() if name == option)
        _LOGGER.info("Changing language to: %s (code: %d)", option, language_code)
        await self.coordinator.async_set_language(language_code)

    async def async_added_to_hass(self) -> None:
        """When entity is added to hass."""
        self.async_on_remove(
            self.coordinator.async_add_listener(self._handle_coordinator_update)
        )

    def _handle_coordinator_update(self) -> None:
        """Handle updated data from the coordinator."""
        self.async_write_ha_state()


class VevorHeaterPumpTypeSelect(SelectEntity):
    """Select entity for Vevor Heater oil pump type."""

    _attr_has_entity_name = True
    _attr_name = "Pump Type"
    _attr_icon = "mdi:pump"
    _attr_entity_category = EntityCategory.CONFIG
    _attr_options = list(PUMP_TYPE_OPTIONS.values())

    def __init__(self, coordinator: VevorHeaterCoordinator) -> None:
        """Initialize the select entity."""
        self.coordinator = coordinator
        if coordinator.is_warm_drive_controller is True:
            self._attr_name = "Pump Flow"
            self._attr_options = list(WARM_DRIVE_PUMP_FLOW_OPTIONS.values())
        self._attr_device_info = {
            "identifiers": {(DOMAIN, coordinator.address)},
            "name": "Vevor Heater",
            "manufacturer": "Vevor",
            "model": "Diesel Heater",
        }
        self._attr_unique_id = f"{coordinator.address}_pump_type"

    @property
    def available(self) -> bool:
        """Return if entity is available."""
        # Not available if RF433 mode is active (pump_type will be None)
        return (
            self.coordinator.data.get("connected", False)
            and self.coordinator.data.get("pump_type") is not None
        )

    @property
    def current_option(self) -> str | None:
        """Return the current pump type."""
        pump_type = self.coordinator.data.get("pump_type")
        if pump_type is not None:
            options = (
                WARM_DRIVE_PUMP_FLOW_OPTIONS
                if self.coordinator.is_warm_drive_controller is True
                else PUMP_TYPE_OPTIONS
            )
            return options.get(pump_type, f"Type {pump_type}")
        return None

    async def async_select_option(self, option: str) -> None:
        """Change the pump type."""
        # Find the pump type code for the selected option
        pump_code = None
        options = (
            WARM_DRIVE_PUMP_FLOW_OPTIONS
            if self.coordinator.is_warm_drive_controller is True
            else PUMP_TYPE_OPTIONS
        )
        for code, name in options.items():
            if name == option:
                pump_code = code
                break

        if pump_code is not None:
            _LOGGER.info("Changing pump type to: %s (code: %d)", option, pump_code)
            await self.coordinator.async_set_pump_type(pump_code)
        else:
            _LOGGER.error("Unknown pump type: %s", option)

    async def async_added_to_hass(self) -> None:
        """When entity is added to hass."""
        self.async_on_remove(
            self.coordinator.async_add_listener(self._handle_coordinator_update)
        )

    def _handle_coordinator_update(self) -> None:
        """Handle updated data from the coordinator."""
        self.async_write_ha_state()


class VevorHeaterTankVolumeSelect(SelectEntity):
    """Select entity for Vevor Heater tank volume."""

    _attr_has_entity_name = True
    _attr_name = "Tank Volume"
    _attr_icon = "mdi:gas-station"
    _attr_entity_category = EntityCategory.CONFIG
    _attr_options = list(TANK_VOLUME_OPTIONS.values())

    def __init__(self, coordinator: VevorHeaterCoordinator) -> None:
        """Initialize the select entity."""
        self.coordinator = coordinator
        if coordinator.is_warm_drive_controller is True:
            self._attr_options = list(WARM_DRIVE_TANK_VOLUME_OPTIONS.values())
        self._attr_device_info = {
            "identifiers": {(DOMAIN, coordinator.address)},
            "name": "Vevor Heater",
            "manufacturer": "Vevor",
            "model": "Diesel Heater",
        }
        self._attr_unique_id = f"{coordinator.address}_tank_volume_select"

    @property
    def available(self) -> bool:
        """Return if entity is available."""
        return self.coordinator.data.get("connected", False)

    @property
    def current_option(self) -> str | None:
        """Return the current tank volume."""
        tank_volume = self.coordinator.data.get("tank_volume")
        if tank_volume is not None:
            # Return exact match or closest option
            options = (
                WARM_DRIVE_TANK_VOLUME_OPTIONS
                if self.coordinator.is_warm_drive_controller is True
                else TANK_VOLUME_OPTIONS
            )
            if tank_volume in options:
                return options[tank_volume]
            # If not an exact match, show the raw value
            return f"{tank_volume} L"
        return None

    async def async_select_option(self, option: str) -> None:
        """Change the tank volume."""
        # Find the volume value for the selected option
        volume = None
        options = (
            WARM_DRIVE_TANK_VOLUME_OPTIONS
            if self.coordinator.is_warm_drive_controller is True
            else TANK_VOLUME_OPTIONS
        )
        for vol, name in options.items():
            if name == option:
                volume = vol
                break

        if volume is not None:
            _LOGGER.info("Changing tank volume to: %s (value: %d)", option, volume)
            await self.coordinator.async_set_tank_volume(volume)
        else:
            _LOGGER.error("Unknown tank volume: %s", option)

    async def async_added_to_hass(self) -> None:
        """When entity is added to hass."""
        self.async_on_remove(
            self.coordinator.async_add_listener(self._handle_coordinator_update)
        )

    def _handle_coordinator_update(self) -> None:
        """Handle updated data from the coordinator."""
        self.async_write_ha_state()


class VevorBacklightSelect(SelectEntity):
    """Select entity for display backlight brightness (cmd 21).

    Discrete brightness values matching the Vevor app:
    Off, 1-10, 20, 30, ..., 100.
    Replaces the old 0-100 number slider which was hard to use.
    """

    _attr_has_entity_name = True
    _attr_name = "Backlight"
    _attr_icon = "mdi:brightness-6"
    _attr_entity_category = EntityCategory.CONFIG
    _attr_options = list(BACKLIGHT_OPTIONS.values())

    def __init__(self, coordinator: VevorHeaterCoordinator) -> None:
        """Initialize the select entity."""
        self.coordinator = coordinator
        self._attr_device_info = {
            "identifiers": {(DOMAIN, coordinator.address)},
            "name": "Vevor Heater",
            "manufacturer": "Vevor",
            "model": "Diesel Heater",
        }
        self._attr_unique_id = f"{coordinator.address}_backlight_select"

    @property
    def available(self) -> bool:
        """Return if entity is available."""
        return self.coordinator.data.get("backlight") is not None

    @property
    def current_option(self) -> str | None:
        """Return the current backlight level."""
        backlight = self.coordinator.data.get("backlight")
        if backlight is not None:
            if backlight in BACKLIGHT_OPTIONS:
                return BACKLIGHT_OPTIONS[backlight]
            return str(backlight)
        return None

    async def async_select_option(self, option: str) -> None:
        """Change the backlight brightness."""
        for value, name in BACKLIGHT_OPTIONS.items():
            if name == option:
                _LOGGER.info("Setting backlight to: %s (value: %d)", option, value)
                await self.coordinator.async_set_backlight(value)
                return
        _LOGGER.error("Unknown backlight option: %s", option)

    async def async_added_to_hass(self) -> None:
        """When entity is added to hass."""
        self.async_on_remove(
            self.coordinator.async_add_listener(self._handle_coordinator_update)
        )

    def _handle_coordinator_update(self) -> None:
        """Handle updated data from the coordinator."""
        self.async_write_ha_state()


class VevorHighAltitudeModeSelect(SelectEntity):
    """High Altitude Mode select entity (Hcalory MVP2 only).

    Hcalory has 3 altitude modes instead of binary on/off:
    - Disabled (0): Normal operation
    - Mode 1 (1): High altitude compensation level 1
    - Mode 2 (2): High altitude compensation level 2

    Per @Xev analysis (issue #34): Cannot switch directly from Disabled to Mode 2
    with a binary switch, so selector is needed.
    """

    _attr_has_entity_name = True
    _attr_name = "High Altitude Mode"
    _attr_icon = "mdi:mountain"
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(self, coordinator: VevorHeaterCoordinator) -> None:
        """Initialize the select entity."""
        self.coordinator = coordinator
        self._attr_device_info = {
            "identifiers": {(DOMAIN, coordinator.address)},
        }
        self._attr_unique_id = f"{coordinator.address}_high_altitude_mode"
        self._attr_options = list(HIGH_ALTITUDE_MODE_OPTIONS.values())

    @property
    def available(self) -> bool:
        """Return if entity is available."""
        return self.coordinator.data.get("high_altitude") is not None

    @property
    def current_option(self) -> str | None:
        """Return the current high altitude mode."""
        altitude = self.coordinator.data.get("high_altitude")
        if altitude is not None:
            if altitude in HIGH_ALTITUDE_MODE_OPTIONS:
                return HIGH_ALTITUDE_MODE_OPTIONS[altitude]
            return str(altitude)
        return None

    async def async_select_option(self, option: str) -> None:
        """Change the high altitude mode."""
        for value, name in HIGH_ALTITUDE_MODE_OPTIONS.items():
            if name == option:
                _LOGGER.info("Setting high altitude mode to: %s (value: %d)", option, value)
                await self.coordinator.async_set_altitude_mode(value)
                return
        _LOGGER.error("Unknown high altitude mode option: %s", option)

    async def async_added_to_hass(self) -> None:
        """When entity is added to hass."""
        self.async_on_remove(
            self.coordinator.async_add_listener(self._handle_coordinator_update)
        )

    def _handle_coordinator_update(self) -> None:
        """Handle updated data from the coordinator."""
        self.async_write_ha_state()
