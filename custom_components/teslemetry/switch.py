"""Switch platform for Teslemetry integration."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from itertools import chain
from typing import Any

from homeassistant.components.switch import (
    SwitchDeviceClass,
    SwitchEntity,
    SwitchEntityDescription,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.restore_state import RestoreEntity
from homeassistant.helpers.typing import StateType
from tesla_fleet_api.const import Scope
from teslemetry_stream import Signal
from teslemetry_stream.const import DefrostModeState, SentryModeState, DetailedChargeState

from .entity import (
    TeslemetryEnergyInfoEntity,
    TeslemetryVehicleEntity,
    TeslemetryVehicleStreamSingleEntity
)
from .models import (
    TeslemetryEnergyData,
    TeslemetryVehicleData,
)
from .const import DOMAIN
from .helpers import handle_vehicle_command, handle_command


@dataclass(frozen=True, kw_only=True)
class TeslemetrySwitchEntityDescription(SwitchEntityDescription):
    """Describes Teslemetry Switch entity."""

    on_func: Callable
    off_func: Callable | None = None
    scopes: list[Scope] | None = None
    polling_value_fn: Callable[[StateType], bool] = bool
    streaming_key: Signal | None = None
    streaming_value_fn: Callable[[StateType], bool] = bool
    streaming_firmware: str = "2024.26"
    unique_id: str | None = None


VEHICLE_DESCRIPTIONS: tuple[TeslemetrySwitchEntityDescription, ...] = (
    TeslemetrySwitchEntityDescription(
        key="vehicle_state_sentry_mode",
        streaming_key=Signal.SENTRY_MODE,
        on_func=lambda api: api.set_sentry_mode(on=True),
        off_func=lambda api: api.set_sentry_mode(on=False),
        scopes=[Scope.VEHICLE_CMDS],
        streaming_value_fn=lambda x: SentryModeState.get(x) != "Off",
    ),
    TeslemetrySwitchEntityDescription(
        key="vehicle_state_valet_mode",
        streaming_key=Signal.VALET_MODE_ENABLED,
        streaming_firmware="2024.44.25",
        on_func=lambda api: api.set_valet_mode(on=True),
        off_func=lambda api: api.set_valet_mode(on=False),
        scopes=[Scope.VEHICLE_CMDS],
    ),
    TeslemetrySwitchEntityDescription(
        key="climate_state_auto_seat_climate_left",
        streaming_key=Signal.AUTO_SEAT_CLIMATE_LEFT,
        on_func=lambda api: api.remote_auto_seat_climate_request(1, True),
        off_func=lambda api: api.remote_auto_seat_climate_request(
            1, False
        ),
        scopes=[Scope.VEHICLE_CMDS],
    ),
    TeslemetrySwitchEntityDescription(
        key="climate_state_auto_seat_climate_right",
        streaming_key=Signal.AUTO_SEAT_CLIMATE_RIGHT,
        on_func=lambda api: api.remote_auto_seat_climate_request(
            2, True
        ),
        off_func=lambda api: api.remote_auto_seat_climate_request(
            2, False
        ),
        scopes=[Scope.VEHICLE_CMDS],
    ),
    TeslemetrySwitchEntityDescription(
        key="climate_state_auto_steering_wheel_heat",
        streaming_key=Signal.HVAC_STEERING_WHEEL_HEAT_AUTO,
        streaming_firmware="2024.44.25",
        on_func=lambda api: api.remote_auto_steering_wheel_heat_climate_request(
            on=True
        ),
        off_func=lambda api: api.remote_auto_steering_wheel_heat_climate_request(
            on=False
        ),
        scopes=[Scope.VEHICLE_CMDS],
    ),
    TeslemetrySwitchEntityDescription(
        key="climate_state_defrost_mode",
        streaming_key=Signal.DEFROST_MODE,
        streaming_firmware="2024.44.25",
        streaming_value_fn=lambda state: DefrostModeState.get(state) != "Off",
        on_func=lambda api: api.set_preconditioning_max(on=True, manual_override=False),
        off_func=lambda api: api.set_preconditioning_max(
            on=False, manual_override=False
        ),
        scopes=[Scope.VEHICLE_CMDS],
    ),
    TeslemetrySwitchEntityDescription(
        key="charge_state_charging_state",
        unique_id="charge_state_user_charge_enable_request",
        streaming_key=Signal.DETAILED_CHARGE_STATE,
        on_func=lambda api: api.charge_start(),
        off_func=lambda api: api.charge_stop(),
        streaming_value_fn=lambda state: DetailedChargeState.get(state) in {"Starting", "Charging"},
        scopes=[Scope.VEHICLE_CMDS, Scope.VEHICLE_CHARGING_CMDS],
    ),
    TeslemetrySwitchEntityDescription(
        key="vehicle_state_remote_start",
        streaming_key=Signal.REMOTE_START_ENABLED,
        streaming_firmware="2024.44.25",
        on_func=lambda api: api.remote_start_drive(),
        scopes=[Scope.VEHICLE_CMDS],
    ),

)


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Set up the Teslemetry Switch platform from a config entry."""


    async_add_entities(
        chain(
            (
                TeslemetryPollingVehicleSwitchEntity(vehicle, description, entry.runtime_data.scopes)
                if vehicle.api.pre2021 or vehicle.firmware < description.streaming_firmware
                else TeslemetryStreamingVehicleSwitchEntity(vehicle, description, entry.runtime_data.scopes)
                for vehicle in entry.runtime_data.vehicles
                for description in VEHICLE_DESCRIPTIONS
            ),
            (
                TeslemetryStormModeSwitchEntity(energysite, entry.runtime_data.scopes)
                for energysite in entry.runtime_data.energysites
                if energysite.info_coordinator.data.get("components_storm_mode_capable")
            ),
            (
                TeslemetryChargeFromGridSwitchEntity(
                    energysite,
                    entry.runtime_data.scopes,
                )
                for energysite in entry.runtime_data.energysites
                if energysite.info_coordinator.data.get("components_battery")
                and energysite.info_coordinator.data.get("components_solar")
            ),
        )
    )


class TeslemetryVehicleSwitchEntity(SwitchEntity):
    """Base class for Teslemetry vehicle switch entities."""

    _attr_device_class = SwitchDeviceClass.SWITCH
    entity_description: TeslemetrySwitchEntityDescription

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Turn on the Switch."""
        self.raise_for_scope(Scope.VEHICLE_CMDS)

        await handle_vehicle_command(self.entity_description.on_func(self.api))
        self._attr_is_on = True
        self.async_write_ha_state()

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Turn off the Switch."""
        if not self.entity_description.off_func:
            raise ServiceValidationError(
               translation_domain=DOMAIN,
               translation_key="no_off",
               translation_placeholders={"name": self.name},
            )

        self.raise_for_scope(Scope.VEHICLE_CMDS)

        await handle_vehicle_command(self.entity_description.off_func(self.api))
        self._attr_is_on = False
        self.async_write_ha_state()


class TeslemetryPollingVehicleSwitchEntity(TeslemetryVehicleEntity, TeslemetryVehicleSwitchEntity):
    """Base class for Teslemetry vehicle switch entities."""

    def __init__(
        self,
        data: TeslemetryVehicleData,
        description: TeslemetrySwitchEntityDescription,
        scopes: list[Scope],
    ) -> None:
        """Initialize the Switch."""

        self.entity_description = description
        self.scoped = any(scope in scopes for scope in description.scopes)

        super().__init__(
            data, description.key
        )
        if description.unique_id:
            self._attr_unique_id = f"{data.vin}-{description.unique_id}"

    def _async_update_attrs(self) -> None:
        """Update the attributes of the sensor."""
        if self._value is None:
            if self.entity_description.key == "charge_state_user_charge_enable_request":
                self._attr_is_on = self.get("charge_state_charge_enable_request")
            else:
                self._attr_is_on = None
        else:
            self._attr_is_on = self.entity_description.polling_value_fn(self._value)


class TeslemetryStreamingVehicleSwitchEntity(TeslemetryVehicleStreamSingleEntity, TeslemetryVehicleSwitchEntity, RestoreEntity):
    """Base class for Teslemetry vehicle switch entities."""

    def __init__(
        self,
        data: TeslemetryVehicleData,
        description: TeslemetrySwitchEntityDescription,
        scopes: list[Scope],
    ) -> None:
        """Initialize the Switch."""

        self.entity_description = description
        self.scoped = any(scope in scopes for scope in description.scopes)

        assert description.streaming_key
        super().__init__(
            data, description.key, description.streaming_key
        )
        if description.unique_id:
            self._attr_unique_id = f"{data.vin}-{description.unique_id}"

    async def async_added_to_hass(self) -> None:
        """Handle entity which will be added."""
        await super().async_added_to_hass()
        if (state := await self.async_get_last_state()) is not None:
            if (state.state == "on"):
                self._attr_is_on = True
            elif (state.state == "off"):
                self._attr_is_on = False


    def _async_value_from_stream(self, value) -> None:
        """Update the value of the entity."""
        if value is None:
            self._attr_is_on = None
        else:
            self._attr_is_on = self.entity_description.streaming_value_fn(value)


class TeslemetryStormModeSwitchEntity(
    TeslemetryEnergyInfoEntity, SwitchEntity
):
    """Entity class for Storm Watch switch."""

    _attr_device_class = SwitchDeviceClass.SWITCH
    entity_description: TeslemetrySwitchEntityDescription

    def __init__(
        self,
        data: TeslemetryEnergyData,
        scopes: list[Scope],
    ) -> None:
        """Initialize the Switch."""
        super().__init__(data, "user_settings_storm_mode_enabled")
        self.scoped = Scope.ENERGY_CMDS in scopes

    def _async_update_attrs(self) -> None:
        """Update the attributes of the sensor."""
        self._attr_is_on = self._value

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Turn on the Switch."""
        self.raise_for_scope(Scope.ENERGY_CMDS)
        if(await handle_command(self.api.storm_mode(enabled=True))):
            self._attr_is_on = True
            self.async_write_ha_state()

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Turn off the Switch."""
        self.raise_for_scope(Scope.ENERGY_CMDS)
        if(await handle_command(self.api.storm_mode(enabled=False))):
            self._attr_is_on = False
            self.async_write_ha_state()


class TeslemetryChargeFromGridSwitchEntity(
    TeslemetryEnergyInfoEntity, SwitchEntity
):
    """Entity class for Charge From Grid switch."""

    _attr_device_class = SwitchDeviceClass.SWITCH
    entity_description: TeslemetrySwitchEntityDescription

    def __init__(
        self,
        data: TeslemetryEnergyData,
        scopes: list[Scope],
    ) -> None:
        """Initialize the Switch."""
        self.scoped = Scope.ENERGY_CMDS in scopes
        super().__init__(
            data, "components_disallow_charge_from_grid_with_solar_installed"
        )

    def _async_update_attrs(self) -> None:
        """Update the attributes of the entity."""
        # When disallow_charge_from_grid_with_solar_installed is missing, its Off.
        # But this sensor is flipped to match how the Tesla app works.
        self._attr_is_on = not self.get(self.key, False)

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Turn on the Switch."""
        self.raise_for_scope(Scope.ENERGY_CMDS)
        if(await handle_command(
            self.api.grid_import_export(
                disallow_charge_from_grid_with_solar_installed=False
            )
        )):
            self._attr_is_on = True
            self.async_write_ha_state()

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Turn off the Switch."""
        self.raise_for_scope(Scope.ENERGY_CMDS)
        if(await handle_command(
            self.api.grid_import_export(
                disallow_charge_from_grid_with_solar_installed=True
            )
        )):
            self._attr_is_on = False
            self.async_write_ha_state()
