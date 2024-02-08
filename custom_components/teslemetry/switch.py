"""Switch platform for Teslemetry integration."""
from __future__ import annotations
from itertools import chain
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from tesla_fleet_api.const import Scopes

from homeassistant.components.switch import (
    SwitchDeviceClass,
    SwitchEntity,
    SwitchEntityDescription,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .entity import (
    TeslemetryVehicleEntity,
    TeslemetryEnergyInfoEntity,
    TeslemetryEnergyLiveEntity,
)
from .models import (
    TeslemetryVehicleData,
    TeslemetryEnergyData,
)
from .context import handle_command


@dataclass(frozen=True, kw_only=True)
class TeslemetrySwitchEntityDescription(SwitchEntityDescription):
    """Describes Teslemetry Switch entity."""

    on_func: Callable
    off_func: Callable
    scopes: list[Scopes] | None = None


VEHICLE_DESCRIPTIONS: tuple[TeslemetrySwitchEntityDescription, ...] = (
    TeslemetrySwitchEntityDescription(
        key="charge_state_charge_enable_request",
        on_func=lambda api: api.charge_start(),
        off_func=lambda api: api.charge_stop(),
        scopes=[Scopes.VEHICLE_CMDS, Scopes.VEHICLE_CHARGING_CMDS],
    ),
    TeslemetrySwitchEntityDescription(
        key="vehicle_state_sentry_mode",
        on_func=lambda api: api.set_sentry_mode(on=True),
        off_func=lambda api: api.set_sentry_mode(on=False),
        scopes=[Scopes.VEHICLE_CMDS],
    ),
    TeslemetrySwitchEntityDescription(
        key="vehicle_state_valet_mode",
        on_func=lambda api: api.set_valet_mode(on=True),
        off_func=lambda api: api.set_valet_mode(on=False),
        scopes=[Scopes.VEHICLE_CMDS],
    ),
    TeslemetrySwitchEntityDescription(
        key="climate_state_auto_seat_climate_left",
        on_func=lambda api: api.remote_auto_seat_climate_request(0, True),
        off_func=lambda api: api.remote_auto_seat_climate_request(0, False),
        scopes=[Scopes.VEHICLE_CMDS],
    ),
    TeslemetrySwitchEntityDescription(
        key="climate_state_auto_seat_climate_right",
        on_func=lambda api: api.remote_auto_seat_climate_request(1, True),
        off_func=lambda api: api.remote_auto_seat_climate_request(1, False),
        scopes=[Scopes.VEHICLE_CMDS],
    ),
    TeslemetrySwitchEntityDescription(
        key="climate_state_auto_steering_wheel_heat",
        on_func=lambda api: api.remote_auto_steering_wheel_heat_climate_request(
            on=True
        ),
        off_func=lambda api: api.remote_auto_steering_wheel_heat_climate_request(
            on=False
        ),
        scopes=[Scopes.VEHICLE_CMDS],
    ),
)

ENERGY_INFO_DESCRIPTION = TeslemetrySwitchEntityDescription(
    key="components_disallow_charge_from_grid_with_solar_installed",
    on_func=lambda api: api.grid_import_export(
        disallow_charge_from_grid_with_solar_installed=True
    ),
    off_func=lambda api: api.grid_import_export(
        disallow_charge_from_grid_with_solar_installed=False
    ),
    scopes=[Scopes.ENERGY_CMDS],
)


ENERGY_LIVE_DESCRIPTION = TeslemetrySwitchEntityDescription(
    key="storm_mode_enabled",
    on_func=lambda api: api.storm_mode(enabled=True),
    off_func=lambda api: api.storm_mode(enabled=False),
    scopes=[Scopes.ENERGY_CMDS],
)


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Set up the Teslemetry Switch platform from a config entry."""
    data = hass.data[DOMAIN][entry.entry_id]

    async_add_entities(
        chain(
            (
                TeslemetryVehicleSwitchEntity(
                    vehicle,
                    description,
                    any(scope in data.scopes for scope in description.scopes),
                )
                for vehicle in data.vehicles
                for description in VEHICLE_DESCRIPTIONS
            ),
            (
                TeslemetryEnergyLiveSwitchEntity(
                    energysite,
                    ENERGY_INFO_DESCRIPTION,
                    any(
                        scope in data.scopes for scope in ENERGY_INFO_DESCRIPTION.scopes
                    ),
                )
                for energysite in data.energysites
                if ENERGY_INFO_DESCRIPTION.key in energysite.info_coordinator.data
            ),
            (
                TeslemetryEnergyInfoSwitchEntity(
                    energysite,
                    ENERGY_LIVE_DESCRIPTION,
                    any(
                        scope in data.scopes for scope in ENERGY_LIVE_DESCRIPTION.scopes
                    ),
                )
                for energysite in data.energysites
                if ENERGY_LIVE_DESCRIPTION.key in energysite.live_coordinator.data
            ),
        )
    )


class TeslemetrySwitchEntity(SwitchEntity):
    """Base class for all Teslemetry switch entities"""

    _attr_device_class = SwitchDeviceClass.SWITCH
    entity_description: TeslemetrySwitchEntityDescription

    @property
    def is_on(self) -> bool:
        """Return the state of the Switch."""
        value = self.get()
        if value is None:
            return None
        return value

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Turn on the Switch."""
        self.raise_for_scope()
        with handle_command():
            await self.entity_description.on_func(self.api)
        self.set((self.entity_description.key, True))

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Turn off the Switch."""
        self.raise_for_scope()
        with handle_command():
            await self.entity_description.off_func(self.api)
        self.set((self.entity_description.key, False))


class TeslemetryVehicleSwitchEntity(TeslemetryVehicleEntity, TeslemetrySwitchEntity):
    """Base class for Teslemetry vehicle switch entities."""

    def __init__(
        self,
        data: TeslemetryVehicleData,
        description: TeslemetrySwitchEntityDescription,
        scoped: bool,
    ) -> None:
        """Initialize the Switch."""
        super().__init__(data, description.key)
        self.entity_description = description
        self.scoped = scoped

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Turn on the Switch."""
        self.raise_for_scope()
        with handle_command():
            await self.wake_up_if_asleep()
            await self.entity_description.on_func(self.api)
        self.set((self.entity_description.key, True))

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Turn off the Switch."""
        self.raise_for_scope()
        with handle_command():
            await self.wake_up_if_asleep()
            await self.entity_description.off_func(self.api)
        self.set((self.entity_description.key, False))


class TeslemetryEnergyLiveSwitchEntity(
    TeslemetryEnergyLiveEntity, TeslemetrySwitchEntity
):
    """Base class for Teslemetry Switch."""

    def __init__(
        self,
        data: TeslemetryEnergyData,
        description: TeslemetrySwitchEntityDescription,
        scoped: bool,
    ) -> None:
        """Initialize the Switch."""
        super().__init__(data, description.key)
        self.entity_description = description
        self.scoped = scoped


class TeslemetryEnergyInfoSwitchEntity(
    TeslemetryEnergyInfoEntity, TeslemetrySwitchEntity
):
    """Base class for Teslemetry Switch."""

    def __init__(
        self,
        data: TeslemetryEnergyData,
        description: TeslemetrySwitchEntityDescription,
        scoped: bool,
    ) -> None:
        """Initialize the Switch."""
        super().__init__(data, description.key)
        self.entity_description = description
        self.scoped = scoped
