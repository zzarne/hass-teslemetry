"""Climate platform for Teslemetry integration."""

from itertools import chain
from typing import Any, cast

from homeassistant.components.climate import ClimateEntity
from homeassistant.components.climate.const import (
    ATTR_HVAC_MODE,
    ClimateEntityFeature,
    HVACMode,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import (
    ATTR_TEMPERATURE,
    PRECISION_HALVES,
    PRECISION_WHOLE,
    UnitOfTemperature,
)
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.restore_state import RestoreEntity
from tesla_fleet_api.const import CabinOverheatProtectionTemp, Scope
from teslemetry_stream import Signal

from .const import DOMAIN, TeslemetryClimateSide
from .entity import (
    TeslemetryVehicleComplexStreamEntity,
    TeslemetryVehicleEntity,
    TeslemetryVehicleStreamEntity,
)
from .models import TeslemetryVehicleData

DEFAULT_MIN_TEMP = 15
DEFAULT_MAX_TEMP = 28

STREAMING_MODES = {
    'Off': "off",
    'On': "keep",
    'Dog': "dog",
    'Party': "camp"
}

PARALLEL_UPDATES = 0

async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Set up the Teslemetry Climate platform from a config entry."""

    async_add_entities(
        chain((
            TeslemetryPollingClimateEntity(
                vehicle, TeslemetryClimateSide.DRIVER, entry.runtime_data.scopes
            )
            if vehicle.api.pre2021 or vehicle.firmware < "2024.44.25"
            else TeslemetryStreamingClimateEntity(
                    vehicle, TeslemetryClimateSide.DRIVER, entry.runtime_data.scopes
                )
            for vehicle in entry.runtime_data.vehicles
        ),(
            TeslemetryPollingCabinOverheatProtectionEntity(
                vehicle, entry.runtime_data.scopes
            )
            if vehicle.api.pre2021 or vehicle.firmware < "2024.44.25"
            else TeslemetryStreamingCabinOverheatProtectionEntity(
                vehicle, entry.runtime_data.scopes
            )
            for vehicle in entry.runtime_data.vehicles
        ))
    )

class TeslemetryClimateEntity(ClimateEntity):
    """Vehicle Climate Control."""

    _attr_precision = PRECISION_HALVES

    _attr_temperature_unit = UnitOfTemperature.CELSIUS
    _attr_hvac_modes = [HVACMode.HEAT_COOL, HVACMode.OFF]
    _attr_preset_modes = ["off", "keep", "dog", "camp"]
    _attr_fan_modes = ["off", "bioweapon"]
    _enable_turn_on_off_backwards_compatibility = False

    # Defaults
    _attr_hvac_mode = None
    _attr_current_temperature = None
    _attr_target_temperature = None
    _attr_fan_mode = None
    _attr_preset_mode = None

    async def async_turn_on(self) -> None:
        """Set the climate state to on."""
        self.raise_for_scope(Scope.VEHICLE_CMDS)

        await self.handle_command(self.api.auto_conditioning_start())

        self._attr_hvac_mode = HVACMode.HEAT_COOL
        self.async_write_ha_state()

    async def async_turn_off(self) -> None:
        """Set the climate state to off."""
        self.raise_for_scope(Scope.VEHICLE_CMDS)

        await self.handle_command(self.api.auto_conditioning_stop())

        self._attr_hvac_mode = HVACMode.OFF
        self._attr_preset_mode = self._attr_preset_modes[0]
        self._attr_fan_mode = self._attr_fan_modes[0]
        self.async_write_ha_state()

    async def async_set_temperature(self, **kwargs: Any) -> None:
        """Set the climate temperature."""

        if temp := kwargs.get(ATTR_TEMPERATURE):
            self.raise_for_scope(Scope.VEHICLE_CMDS)

            await self.handle_command(
                self.api.set_temps(
                    driver_temp=temp,
                    passenger_temp=temp,
                )
            )
            self._attr_target_temperature = temp

        if mode := kwargs.get(ATTR_HVAC_MODE):
            # Set HVAC mode will call write_ha_state
            await self.async_set_hvac_mode(mode)
        else:
            self.async_write_ha_state()

    async def async_set_hvac_mode(self, hvac_mode: HVACMode) -> None:
        """Set the climate mode and state."""
        if hvac_mode == HVACMode.OFF:
            await self.async_turn_off()
        else:
            await self.async_turn_on()

    async def async_set_preset_mode(self, preset_mode: str) -> None:
        """Set the climate preset mode."""
        self.raise_for_scope(Scope.VEHICLE_CMDS)

        await self.handle_command(
            self.api.set_climate_keeper_mode(
                climate_keeper_mode=self._attr_preset_modes.index(preset_mode)
            )
        )
        self._attr_preset_mode = preset_mode
        if preset_mode == self._attr_preset_modes[0]:
            self._attr_hvac_mode = HVACMode.OFF
        else:
            self._attr_hvac_mode = HVACMode.HEAT_COOL
        self.async_write_ha_state()

    async def async_set_fan_mode(self, fan_mode: str) -> None:
        """Set the Bioweapon defense mode."""
        self.raise_for_scope(Scope.VEHICLE_CMDS)

        await self.handle_command(
            self.api.set_bioweapon_mode(
                on=(fan_mode != 'off'),
                manual_override=True,
            )
        )
        self._attr_fan_mode = fan_mode
        if fan_mode == self._attr_fan_modes[1]:
            self._attr_hvac_mode = HVACMode.HEAT_COOL
        self.async_write_ha_state()

class TeslemetryPollingClimateEntity(TeslemetryClimateEntity, TeslemetryVehicleEntity):
    """Polling vehicle climate entity."""

    _attr_supported_features = (
        ClimateEntityFeature.TURN_ON
        | ClimateEntityFeature.TURN_OFF
        | ClimateEntityFeature.TARGET_TEMPERATURE
        | ClimateEntityFeature.PRESET_MODE
        | ClimateEntityFeature.FAN_MODE
    )

    def __init__(
        self,
        data: TeslemetryVehicleData,
        side: TeslemetryClimateSide,
        scopes: Scope,
    ) -> None:
        """Initialize the climate."""
        self.scoped = Scope.VEHICLE_CMDS in scopes
        if not self.scoped:
            self._attr_supported_features = ClimateEntityFeature(0)

        super().__init__(
            data,
            side,
        )

    def _async_update_attrs(self) -> None:
        """Update the attributes of the entity."""
        value = self.get("climate_state_is_climate_on")
        if value is None:
            self._attr_hvac_mode = None
        if value:
            self._attr_hvac_mode = HVACMode.HEAT_COOL
        else:
            self._attr_hvac_mode = HVACMode.OFF

        self._attr_current_temperature = self.get("climate_state_inside_temp")
        self._attr_target_temperature = self.get(f"climate_state_{self.key}_setting")
        self._attr_preset_mode = self.get("climate_state_climate_keeper_mode")
        if self.get("climate_state_bioweapon_mode"):
            self._attr_fan_mode = "bioweapon"
        else:
            self._attr_fan_mode = "off"
        self._attr_min_temp = cast(
            float, self.get("climate_state_min_avail_temp", DEFAULT_MIN_TEMP)
        )
        self._attr_max_temp = cast(
            float, self.get("climate_state_max_avail_temp", DEFAULT_MAX_TEMP)
        )


class TeslemetryStreamingClimateEntity(TeslemetryClimateEntity, TeslemetryVehicleStreamEntity, RestoreEntity):
    """Teslemetry steering wheel climate control."""

    _attr_supported_features = (
        ClimateEntityFeature.TURN_ON
        | ClimateEntityFeature.TURN_OFF
        | ClimateEntityFeature.TARGET_TEMPERATURE
        | ClimateEntityFeature.PRESET_MODE
    )

    side: TeslemetryClimateSide
    rhd: bool

    def __init__(
        self,
        data: TeslemetryVehicleData,
        side: TeslemetryClimateSide,
        scopes: Scope,
    ) -> None:
        """Initialize the climate."""
        self.scoped = Scope.VEHICLE_CMDS in scopes
        if not self.scoped:
            self._attr_supported_features = ClimateEntityFeature(0)
        self.side = side
        super().__init__(
            data,
            side,
        )

        self._attr_min_temp = cast(
            float, data.coordinator.data.get("climate_state_min_avail_temp", DEFAULT_MIN_TEMP)
        )
        self._attr_max_temp = cast(
            float, data.coordinator.data.get("climate_state_max_avail_temp", DEFAULT_MAX_TEMP)
        )
        self.rhd = data.coordinator.data.get("vehicle_config_rhd", False)

    async def async_added_to_hass(self) -> None:
        """Handle entity which will be added."""
        await super().async_added_to_hass()
        if (state := await self.async_get_last_state()) is not None:
            try:
                self._attr_hvac_mode = HVACMode(state.state)
            except ValueError:
                self._attr_hvac_mode = None
            self._attr_current_temperature = state.attributes.get('current_temperature')
            self._attr_target_temperature = state.attributes.get('target_temperature')
            #self._attr_fan_mode = state.attributes.get('fan_mode')
            self._attr_preset_mode = state.attributes.get('preset_mode')

        self.async_on_remove(
            self.stream.listen_InsideTemp(self._async_handle_inside_temp)
        )
        self.async_on_remove(
            self.stream.listen_HvacACEnabled(self._async_handle_hvac_ac_enabled)
        )
        self.async_on_remove(
            self.stream.listen_ClimateKeeperMode(self._async_handle_climate_keeper_mode)
        )

        if self.side == TeslemetryClimateSide.DRIVER:
            if self.rhd:
                self.async_on_remove(self.stream.listen_HvacRightTemperatureRequest(self._async_handle_hvac_temperature_request))
            else:
                self.async_on_remove(self.stream.listen_HvacLeftTemperatureRequest(self._async_handle_hvac_temperature_request))
        elif self.side == TeslemetryClimateSide.PASSENGER:
            if self.rhd:
                self.async_on_remove(self.stream.listen_HvacLeftTemperatureRequest(self._async_handle_hvac_temperature_request))
            else:
                self.async_on_remove(self.stream.listen_HvacRightTemperatureRequest(self._async_handle_hvac_temperature_request))


    def _async_handle_inside_temp(self, data: float | None):
        self._attr_current_temperature = data
        self.async_write_ha_state()

    def _async_handle_hvac_ac_enabled(self, data: bool | None):
        self._attr_hvac_mode = None if data is None else HVACMode.HEAT_COOL if data else HVACMode.OFF
        self.async_write_ha_state()

    def _async_handle_climate_keeper_mode(self, data: str | None):
        self._attr_preset_mode = None if data is None else STREAMING_MODES.get(data)
        self.async_write_ha_state()

    def _async_handle_hvac_temperature_request(self, data: float | None):
        self._attr_target_temperature = data
        self.async_write_ha_state()


COP_MODES = {
    "Off": HVACMode.OFF,
    "On": HVACMode.COOL,
    "FanOnly": HVACMode.FAN_ONLY,
}

COP_LEVELS = {
    "Low": 30,
    "Medium": 35,
    "High": 40,
}


class TeslemetryCabinOverheatProtectionEntity(ClimateEntity):
    """Vehicle Cabin Overheat Protection."""

    _attr_precision = PRECISION_WHOLE
    _attr_target_temperature_step = 5
    _attr_min_temp = 30
    _attr_max_temp = 40
    _attr_temperature_unit = UnitOfTemperature.CELSIUS
    _attr_hvac_modes = list(COP_MODES.values())
    _enable_turn_on_off_backwards_compatibility = False
    _attr_entity_registry_enabled_default = False

    # Defaults
    _attr_hvac_mode = None
    _attr_current_temperature = None
    _attr_target_temperature = None
    _attr_fan_mode = None
    _attr_preset_mode = None

    async def async_turn_on(self) -> None:
        """Set the climate state to on."""
        await self.async_set_hvac_mode(HVACMode.COOL)

    async def async_turn_off(self) -> None:
        """Set the climate state to off."""
        await self.async_set_hvac_mode(HVACMode.OFF)

    async def async_set_temperature(self, **kwargs: Any) -> None:
        """Set the climate temperature."""

        if temp := kwargs.get(ATTR_TEMPERATURE):
            if temp == 30:
                cop_mode = CabinOverheatProtectionTemp.LOW
            elif temp == 35:
                cop_mode = CabinOverheatProtectionTemp.MEDIUM
            elif temp == 40:
                cop_mode = CabinOverheatProtectionTemp.HIGH
            else:
                raise ServiceValidationError(
                translation_domain=DOMAIN,
                translation_key="invalid_cop_temp",
            )
            self.raise_for_scope(Scope.VEHICLE_CMDS)

            await self.handle_command(self.api.set_cop_temp(cop_mode))
            self._attr_target_temperature = temp

        if mode := kwargs.get(ATTR_HVAC_MODE):
            # Set HVAC mode will call write_ha_state
            await self.async_set_hvac_mode(mode)
        else:
            self.async_write_ha_state()

    async def async_set_hvac_mode(self, hvac_mode: HVACMode) -> None:
        """Set the climate mode and state."""
        self.raise_for_scope(Scope.VEHICLE_CMDS)

        if hvac_mode == HVACMode.OFF:
            await self.handle_command(
                self.api.set_cabin_overheat_protection(on=False, fan_only=False)
            )
        elif hvac_mode == HVACMode.COOL:
            await self.handle_command(
                self.api.set_cabin_overheat_protection(on=True, fan_only=False)
            )
        elif hvac_mode == HVACMode.FAN_ONLY:
            await self.handle_command(
                self.api.set_cabin_overheat_protection(on=True, fan_only=True)
            )

        self._attr_hvac_mode = hvac_mode
        self.async_write_ha_state()

class TeslemetryPollingCabinOverheatProtectionEntity(TeslemetryVehicleEntity, TeslemetryCabinOverheatProtectionEntity):
    """Vehicle Cabin Overheat Protection."""

    def __init__(
        self,
        data: TeslemetryVehicleData,
        scopes: list[Scope],
    ) -> None:
        """Initialize the climate."""

        super().__init__(
            data,
            "climate_state_cabin_overheat_protection",
        )

        # Supported Features
        self._attr_supported_features = (
            ClimateEntityFeature.TURN_ON | ClimateEntityFeature.TURN_OFF
        )
        if self.get("vehicle_config_cop_user_set_temp_supported"):
            self._attr_supported_features |= ClimateEntityFeature.TARGET_TEMPERATURE

        # Scopes
        self.scoped = Scope.VEHICLE_CMDS in scopes
        if not self.scoped:
            self._attr_supported_features = ClimateEntityFeature(0)

    def _async_update_attrs(self) -> None:
        """Update the attributes of the entity."""

        if (state := self.get("climate_state_cabin_overheat_protection")) is None:
            self._attr_hvac_mode = None
        else:
            self._attr_hvac_mode = COP_MODES.get(state)

        if (level := self.get("climate_state_cop_activation_temperature")) is None:
            self._attr_target_temperature = None
        else:
            self._attr_target_temperature = COP_LEVELS.get(level)

        self._attr_current_temperature = self.get("climate_state_inside_temp")


class TeslemetryStreamingCabinOverheatProtectionEntity(TeslemetryVehicleComplexStreamEntity, TeslemetryCabinOverheatProtectionEntity):
    """Vehicle Cabin Overheat Protection."""

    def __init__(
        self,
        data: TeslemetryVehicleData,
        scopes: list[Scope],
    ) -> None:
        """Initialize the climate."""

        super().__init__(
            data,
            "climate_state_cabin_overheat_protection",
            [
                Signal.CABIN_OVERHEAT_PROTECTION_MODE,
                Signal.CABIN_OVERHEAT_PROTECTION_TEMPERATURE_LIMIT,
                Signal.INSIDE_TEMP
            ]
        )

        # Supported Features
        self._attr_supported_features = (
            ClimateEntityFeature.TURN_ON | ClimateEntityFeature.TURN_OFF
        )
        if data.coordinator.data.get("vehicle_config_cop_user_set_temp_supported"):
            self._attr_supported_features |= ClimateEntityFeature.TARGET_TEMPERATURE

        # Scopes
        self.scoped = Scope.VEHICLE_CMDS in scopes
        if not self.scoped:
            self._attr_supported_features = ClimateEntityFeature(0)

    def _async_data_from_stream(self, data) -> None:
        """Update the value from the stream."""
        if (value := data.get(Signal.CABIN_OVERHEAT_PROTECTION_MODE)) is not None:
            self._attr_hvac_mode = COP_MODES.get(value.replace("CabinOverheatProtectionModeState",""))
        if (value := data.get(Signal.CABIN_OVERHEAT_PROTECTION_TEMPERATURE_LIMIT)) is not None:
            self._attr_target_temperature = COP_LEVELS.get(value.replace("ClimateOverheatProtectionTempLimit",""))
        if (value := data.get(Signal.INSIDE_TEMP)) is not None:
            self._attr_current_temperature = value
