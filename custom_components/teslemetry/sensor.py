"""Sensor platform for Teslemetry integration."""

from __future__ import annotations
from datetime import timedelta

from teslemetry_stream import Signal
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import cast

from homeassistant.components.sensor import (
    SensorEntity,
    RestoreSensor,
    SensorEntityDescription,
    SensorDeviceClass,
    SensorStateClass,
)
from homeassistant.const import (
    PERCENTAGE,
    EntityCategory,
    UnitOfElectricCurrent,
    UnitOfElectricPotential,
    UnitOfEnergy,
    UnitOfLength,
    UnitOfPower,
    UnitOfPressure,
    UnitOfSpeed,
    UnitOfTemperature,
    UnitOfTime,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.typing import StateType
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.util import dt as dt_util
from homeassistant.util.variance import ignore_variance


from .const import MODELS, ENERGY_HISTORY_FIELDS

from .entity import (
    TeslemetryEnergyInfoEntity,
    TeslemetryEnergyLiveEntity,
    TeslemetryVehicleEntity,
    TeslemetryVehicleStreamEntity,
    TeslemetryWallConnectorEntity,
    TeslemetryEnergyHistoryEntity,
)
from .models import TeslemetryEnergyData, TeslemetryVehicleData

from .helpers import ignore_drop

CHARGE_STATES = {
    "Starting": "starting",
    "Charging": "charging",
    "Stopped": "stopped",
    "Complete": "complete",
    "Disconnected": "disconnected",
    "NoPower": "no_power",
}

WALL_CONNECTOR_STATES = {
    0: "booting",
    1: "charging",
    2: "not_connected",
    4: "connected",
    5: "scheduled",
    6: "negotiating",  # unseen
    7: "error",  # unseen
    8: "charging_finished",  # seen, unconfirmed
    9: "waiting_car",  # unseen
    10: "charging_reduced",  # unseen
}

SHIFT_STATES = {"P": "p", "D": "d", "R": "r", "N": "n"}

@dataclass(frozen=True, kw_only=True)
class TeslemetrySensorEntityDescription(SensorEntityDescription):
    """Describes Teslemetry Sensor entity."""

    polling: bool = False
    polling_value_fn: Callable[[StateType], StateType | datetime] = lambda x: x
    polling_available_fn: Callable[[StateType], StateType | datetime] = lambda x: x is not None
    streaming_key: Signal | None = None
    streaming_value_fn: Callable[[StateType], StateType | datetime] = lambda x: x
    streaming_firmware: str = "2024.26"


VEHICLE_DESCRIPTIONS: tuple[TeslemetrySensorEntityDescription, ...] = (
    TeslemetrySensorEntityDescription(
        key="charge_state_charging_state",
        polling=True,
        streaming_key=Signal.DETAILED_CHARGE_STATE,
        polling_value_fn=lambda value: CHARGE_STATES.get(cast(str, value)),
        streaming_value_fn=lambda value: CHARGE_STATES.get(cast(str, value)),
        device_class=SensorDeviceClass.ENUM,
        options=list(CHARGE_STATES.values()),
    ),
    TeslemetrySensorEntityDescription(
        key="charge_state_battery_level",
        polling=True,
        streaming_key=Signal.BATTERY_LEVEL,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=PERCENTAGE,
        device_class=SensorDeviceClass.BATTERY,
        suggested_display_precision=1,
    ),
    TeslemetrySensorEntityDescription(
        key="charge_state_usable_battery_level",
        polling=True,

        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=PERCENTAGE,
        device_class=SensorDeviceClass.BATTERY,
        entity_registry_enabled_default=False,
    ),
    TeslemetrySensorEntityDescription(
        key="charge_state_charge_energy_added",
        polling=True,
        streaming_key=Signal.AC_CHARGING_ENERGY_IN,

        state_class=SensorStateClass.TOTAL_INCREASING,
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        device_class=SensorDeviceClass.ENERGY,
        suggested_display_precision=1,
    ),
    TeslemetrySensorEntityDescription(
        key="charge_state_charger_power",
        polling=True,
        streaming_key=Signal.AC_CHARGING_POWER,

        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfPower.KILO_WATT,
        device_class=SensorDeviceClass.POWER,
    ),
    TeslemetrySensorEntityDescription(
        key="charge_state_charger_voltage",
        polling=True,

        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        device_class=SensorDeviceClass.VOLTAGE,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    TeslemetrySensorEntityDescription(
        key="charge_state_charger_actual_current",
        polling=True,
        streaming_key=Signal.CHARGE_AMPS,

        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfElectricCurrent.AMPERE,
        device_class=SensorDeviceClass.CURRENT,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    TeslemetrySensorEntityDescription(
        key="charge_state_charge_rate",
        polling=True,

        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfSpeed.MILES_PER_HOUR,
        device_class=SensorDeviceClass.SPEED,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    TeslemetrySensorEntityDescription(
        key="charge_state_conn_charge_cable",
        polling=True,
        streaming_key=Signal.CHARGING_CABLE_TYPE,

        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
    ),
    TeslemetrySensorEntityDescription(
        key="charge_state_fast_charger_type",
        polling=True,
        streaming_key=Signal.FAST_CHARGER_TYPE,

        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
    ),
    TeslemetrySensorEntityDescription(
        key="charge_state_battery_range",
        polling=True,

        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfLength.MILES,
        device_class=SensorDeviceClass.DISTANCE,
        suggested_display_precision=1,
        entity_registry_enabled_default=False,
    ),
    TeslemetrySensorEntityDescription(
        key="charge_state_est_battery_range",
        polling=True,
        streaming_key=Signal.EST_BATTERY_RANGE,

        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfLength.MILES,
        device_class=SensorDeviceClass.DISTANCE,
        suggested_display_precision=1,
        entity_registry_enabled_default=True,
    ),
    TeslemetrySensorEntityDescription(
        key="charge_state_ideal_battery_range",
        polling=True,
        streaming_key=Signal.IDEAL_BATTERY_RANGE,

        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfLength.MILES,
        device_class=SensorDeviceClass.DISTANCE,
        suggested_display_precision=1,
        entity_registry_enabled_default=False,
    ),
    TeslemetrySensorEntityDescription(
        key="drive_state_speed",
        streaming_key=Signal.VEHICLE_SPEED,
        polling=True,
        polling_value_fn=lambda value: value or 0,

        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfSpeed.MILES_PER_HOUR,
        device_class=SensorDeviceClass.SPEED,
        entity_registry_enabled_default=False,

    ),
    TeslemetrySensorEntityDescription(
        key="drive_state_power",
        polling=True,
        polling_value_fn=lambda value: value or 0,

        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfPower.KILO_WATT,
        device_class=SensorDeviceClass.POWER,
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
    ),
    TeslemetrySensorEntityDescription(
        key="drive_state_shift_state",
        polling=True,
        streaming_key=Signal.GEAR,
        polling_value_fn=lambda x: SHIFT_STATES.get(str(x), "p"),
        polling_available_fn=lambda x: True,
        streaming_value_fn=lambda x: SHIFT_STATES.get(str(x)),
        device_class=SensorDeviceClass.ENUM,
        options=list(SHIFT_STATES.values()),
        entity_registry_enabled_default=False,
    ),
    TeslemetrySensorEntityDescription(
        key="vehicle_state_odometer",
        polling=True,
        streaming_key=Signal.ODOMETER,

        state_class=SensorStateClass.TOTAL_INCREASING,
        native_unit_of_measurement=UnitOfLength.MILES,
        device_class=SensorDeviceClass.DISTANCE,
        suggested_display_precision=0,
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
    ),
    TeslemetrySensorEntityDescription(
        key="vehicle_state_tpms_pressure_fl",
        polling=True,
        streaming_key=Signal.TPMS_PRESSURE_FL,

        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfPressure.BAR,
        suggested_unit_of_measurement=UnitOfPressure.PSI,
        device_class=SensorDeviceClass.PRESSURE,
        suggested_display_precision=1,
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
    ),
    TeslemetrySensorEntityDescription(
        key="vehicle_state_tpms_pressure_fr",
        polling=True,
        streaming_key=Signal.TPMS_PRESSURE_FR,

        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfPressure.BAR,
        suggested_unit_of_measurement=UnitOfPressure.PSI,
        device_class=SensorDeviceClass.PRESSURE,
        suggested_display_precision=1,
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
    ),
    TeslemetrySensorEntityDescription(
        key="vehicle_state_tpms_pressure_rl",
        polling=True,
        streaming_key=Signal.TPMS_PRESSURE_RL,

        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfPressure.BAR,
        suggested_unit_of_measurement=UnitOfPressure.PSI,
        device_class=SensorDeviceClass.PRESSURE,
        suggested_display_precision=1,
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
    ),
    TeslemetrySensorEntityDescription(
        key="vehicle_state_tpms_pressure_rr",
        polling=True,
        streaming_key=Signal.TPMS_PRESSURE_RR,

        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfPressure.BAR,
        suggested_unit_of_measurement=UnitOfPressure.PSI,
        device_class=SensorDeviceClass.PRESSURE,
        suggested_display_precision=1,
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
    ),
    TeslemetrySensorEntityDescription(
        key="climate_state_inside_temp",
        polling=True,
        streaming_key=Signal.INSIDE_TEMP,

        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        device_class=SensorDeviceClass.TEMPERATURE,
        suggested_display_precision=1,
    ),
    TeslemetrySensorEntityDescription(
        key="climate_state_outside_temp",
        polling=True,
        streaming_key=Signal.OUTSIDE_TEMP,

        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        device_class=SensorDeviceClass.TEMPERATURE,
        suggested_display_precision=1,
    ),
    TeslemetrySensorEntityDescription(
        key="climate_state_driver_temp_setting",
        polling=True,

        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        device_class=SensorDeviceClass.TEMPERATURE,
        suggested_display_precision=1,
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
    ),
    TeslemetrySensorEntityDescription(
        key="climate_state_passenger_temp_setting",
        polling=True,

        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        device_class=SensorDeviceClass.TEMPERATURE,
        suggested_display_precision=1,
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
    ),
    TeslemetrySensorEntityDescription(
        key="drive_state_active_route_traffic_minutes_delay",
        polling=True,
        streaming_key=Signal.ROUTE_TRAFFIC_MINUTES_DELAY,

        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfTime.MINUTES,
        device_class=SensorDeviceClass.DURATION,
        entity_registry_enabled_default=False,
    ),
    TeslemetrySensorEntityDescription(
        key="drive_state_active_route_energy_at_arrival",
        polling=True,
        streaming_key=Signal.EXPECTED_ENERGY_PERCENT_AT_TRIP_ARRIVAL,

        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=PERCENTAGE,
        device_class=SensorDeviceClass.BATTERY,
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        suggested_display_precision=1
    ),
    TeslemetrySensorEntityDescription(
        key="drive_state_active_route_miles_to_arrival",
        polling=True,
        streaming_key=Signal.MILES_TO_ARRIVAL,

        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfLength.MILES,
        device_class=SensorDeviceClass.DISTANCE,
    ),
    TeslemetrySensorEntityDescription(
        # This entity isnt allowed in core
        key="charge_state_time_to_full_charge",
        polling=True,
        streaming_key=Signal.TIME_TO_FULL_CHARGE,
        polling_available_fn=lambda x: x is not None and float(x) > 0,

        device_class=SensorDeviceClass.DURATION,
        native_unit_of_measurement=UnitOfTime.HOURS,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    TeslemetrySensorEntityDescription(
        # This entity isnt allowed in core
        key="drive_state_active_route_minutes_to_arrival",
        polling=True,
        streaming_key=Signal.MINUTES_TO_ARRIVAL,

        device_class=SensorDeviceClass.DURATION,
        native_unit_of_measurement=UnitOfTime.MINUTES,
    ),
    TeslemetrySensorEntityDescription(
        key="vehicle_state_tpms_last_seen_pressure_time_fl",
        polling=True,
        streaming_key=Signal.TPMS_LAST_SEEN_PRESSURE_TIME_FL,
        polling_value_fn=lambda x: dt_util.utc_from_timestamp(int(x)),
        streaming_value_fn=lambda x: dt_util.utc_from_timestamp(int(x)),

        device_class=SensorDeviceClass.TIMESTAMP,
        entity_registry_enabled_default=False,
    ),
    TeslemetrySensorEntityDescription(
        key="vehicle_state_tpms_last_seen_pressure_time_fr",
        polling=True,
        streaming_key=Signal.TPMS_LAST_SEEN_PRESSURE_TIME_FR,
        polling_value_fn=lambda x: dt_util.utc_from_timestamp(int(x)),
        streaming_value_fn=lambda x: dt_util.utc_from_timestamp(int(x)),

        device_class=SensorDeviceClass.TIMESTAMP,
        entity_registry_enabled_default=False,
    ),
    TeslemetrySensorEntityDescription(
        key="vehicle_state_tpms_last_seen_pressure_time_rl",
        polling=True,
        streaming_key=Signal.TPMS_LAST_SEEN_PRESSURE_TIME_RL,
        polling_value_fn=lambda x: dt_util.utc_from_timestamp(int(x)),
        streaming_value_fn=lambda x: dt_util.utc_from_timestamp(int(x)),

        device_class=SensorDeviceClass.TIMESTAMP,
        entity_registry_enabled_default=False,
    ),
    TeslemetrySensorEntityDescription(
        key="vehicle_state_tpms_last_seen_pressure_time_rr",
        polling=True,
        streaming_key=Signal.TPMS_LAST_SEEN_PRESSURE_TIME_RR,
        polling_value_fn=lambda x: dt_util.utc_from_timestamp(int(x)),
        streaming_value_fn=lambda x: dt_util.utc_from_timestamp(int(x)),

        device_class=SensorDeviceClass.TIMESTAMP,
        entity_registry_enabled_default=False,
    ),
    TeslemetrySensorEntityDescription(
        key="vehicle_config_roof_color",
        polling=True,
        streaming_key=Signal.ROOF_COLOR,
        streaming_value_fn=lambda x: str(x).replace("RoofColor", ""),
        entity_registry_enabled_default=False,
    ),
    TeslemetrySensorEntityDescription(
        key="charge_state_scheduled_charging_mode",
        polling=True,
        streaming_key=Signal.SCHEDULED_CHARGING_MODE,
        streaming_value_fn=lambda x: str(x).replace("ScheduledChargingMode", ""),
        options=["Unknown", "Off", "StartAt", "DepartBy"],
        device_class=SensorDeviceClass.ENUM,
        entity_registry_enabled_default=False,
    ),
    TeslemetrySensorEntityDescription(
        key="charge_state_scheduled_charging_start_time",
        polling=True,
        polling_value_fn=lambda x: dt_util.utc_from_timestamp(int(x)),
        streaming_key=Signal.SCHEDULED_CHARGING_START_TIME,
        streaming_value_fn=lambda x: dt_util.utc_from_timestamp(int(x)),

        device_class=SensorDeviceClass.TIMESTAMP,
        entity_registry_enabled_default=False,
    ),
    TeslemetrySensorEntityDescription(
        key="charge_state_scheduled_departure_time",
        polling=True,
        polling_value_fn=lambda x: dt_util.utc_from_timestamp(int(x)),
        streaming_key=Signal.SCHEDULED_DEPARTURE_TIME,
        streaming_value_fn=lambda x: dt_util.utc_from_timestamp(int(x)),

        device_class=SensorDeviceClass.TIMESTAMP,
        entity_registry_enabled_default=False,
    ),
    TeslemetrySensorEntityDescription(
        key="vehicle_config_exterior_color",
        polling=True,
        streaming_key=Signal.EXTERIOR_COLOR,

        entity_registry_enabled_default=False,
    ),
    TeslemetrySensorEntityDescription(
        key="bms_state",
        streaming_key=Signal.BMS_STATE,

        entity_registry_enabled_default=False,
        streaming_value_fn=lambda x: x,
    ),
    TeslemetrySensorEntityDescription(
        key="brake_pedal_position",
        streaming_key=Signal.BRAKE_PEDAL_POS,

        native_unit_of_measurement=PERCENTAGE,
        entity_registry_enabled_default=False,
    ),
    TeslemetrySensorEntityDescription(
        key="brick_voltage_max",
        streaming_key=Signal.BRICK_VOLTAGE_MAX,
        device_class=SensorDeviceClass.VOLTAGE,
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=2,
        entity_registry_enabled_default=False,
        streaming_value_fn=lambda x: float(x),
    ),
    TeslemetrySensorEntityDescription(
        key="brick_voltage_min",
        streaming_key=Signal.BRICK_VOLTAGE_MIN,
        device_class=SensorDeviceClass.VOLTAGE,
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=2,
        entity_registry_enabled_default=False,
        streaming_value_fn=lambda x: float(x),
    ),
    TeslemetrySensorEntityDescription(
        key="car_type",
        streaming_key=Signal.CAR_TYPE,
        entity_registry_enabled_default=False,
        streaming_value_fn=lambda x: x,
    ),
    TeslemetrySensorEntityDescription(
        key="charge_current_request_max",
        streaming_key=Signal.CHARGE_CURRENT_REQUEST_MAX,
        device_class=SensorDeviceClass.CURRENT,
        native_unit_of_measurement=UnitOfElectricCurrent.AMPERE,
        entity_registry_enabled_default=False,
        streaming_value_fn=lambda x: int(x),
    ),
    TeslemetrySensorEntityDescription(
        key="charge_port",
        streaming_key=Signal.CHARGE_PORT,
        entity_registry_enabled_default=False,
        streaming_value_fn=lambda x: x,
    ),
    TeslemetrySensorEntityDescription(
        key="cruise_follow_distance",
        streaming_key=Signal.CRUISE_FOLLOW_DISTANCE,
        entity_registry_enabled_default=False,
    ),
    TeslemetrySensorEntityDescription(
        key="cruise_set_speed",
        streaming_key=Signal.CRUISE_SET_SPEED,
        entity_registry_enabled_default=False,
        device_class=SensorDeviceClass.SPEED,
        native_unit_of_measurement=UnitOfSpeed.KILOMETERS_PER_HOUR,  # Might be dynamic
    ),
    TeslemetrySensorEntityDescription(
        key="dc_charging_engery_in",
        streaming_key=Signal.DC_CHARGING_ENERGY_IN,
        entity_registry_enabled_default=False,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR, #Unconfirmed
        device_class=SensorDeviceClass.ENERGY,
        streaming_value_fn=lambda x: float(x),
    ),
    TeslemetrySensorEntityDescription(
        key="dc_charging_power",
        streaming_key=Signal.DC_CHARGING_POWER,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfPower.KILO_WATT, #Unconfirmed
        device_class=SensorDeviceClass.POWER,
        entity_registry_enabled_default=False,
    ),
    TeslemetrySensorEntityDescription(
        key="di_axle_speed_front",
        streaming_key=Signal.DI_AXLE_SPEED_F,
        entity_registry_enabled_default=False,
    ),
    TeslemetrySensorEntityDescription(
        key="di_axle_speed_rear",
        streaming_key=Signal.DI_AXLE_SPEED_R,
        entity_registry_enabled_default=False,
    ),
    TeslemetrySensorEntityDescription(
        key="di_axle_speed_rear_left",
        streaming_key=Signal.DI_AXLE_SPEED_REL,
        entity_registry_enabled_default=False,
    ),
    TeslemetrySensorEntityDescription(
        key="di_axle_speed_rear_right",
        streaming_key=Signal.DI_AXLE_SPEED_RER,
        entity_registry_enabled_default=False,
    ),
    TeslemetrySensorEntityDescription(
        key="di_heatsink_temp_front",
        streaming_key=Signal.DI_HEATSINK_TF,
        entity_registry_enabled_default=False,
    ),
    TeslemetrySensorEntityDescription(
        key="di_heatsink_temp_rear",
        streaming_key=Signal.DI_HEATSINK_TR,
        entity_registry_enabled_default=False,
    ),
    TeslemetrySensorEntityDescription(
        key="di_heatsink_temp_rear_left",
        streaming_key=Signal.DI_HEATSINK_TREL,
        entity_registry_enabled_default=False,
    ),
    TeslemetrySensorEntityDescription(
        key="di_heatsink_temp_rear_right",
        streaming_key=Signal.DI_HEATSINK_TRER,
        entity_registry_enabled_default=False,
    ),
    TeslemetrySensorEntityDescription(
        key="di_motor_current_front",
        streaming_key=Signal.DI_MOTOR_CURRENT_F,
        entity_registry_enabled_default=False,
    ),
    TeslemetrySensorEntityDescription(
        key="di_motor_current_rear",
        streaming_key=Signal.DI_MOTOR_CURRENT_R,
        entity_registry_enabled_default=False,
    ),
    TeslemetrySensorEntityDescription(
        key="di_motor_current_rear_left",
        streaming_key=Signal.DI_MOTOR_CURRENT_REL,
        entity_registry_enabled_default=False,
    ),
    TeslemetrySensorEntityDescription(
        key="di_motor_current_rear_right",
        streaming_key=Signal.DI_MOTOR_CURRENT_RER,
        entity_registry_enabled_default=False,
    ),
    TeslemetrySensorEntityDescription(
        key="di_salve_torque_command",
        streaming_key=Signal.DI_SLAVE_TORQUE_CMD,
        entity_registry_enabled_default=False,
    ),
    TeslemetrySensorEntityDescription(
        key="di_state_front",
        streaming_key=Signal.DI_STATE_F,
        entity_registry_enabled_default=False,
    ),
    TeslemetrySensorEntityDescription(
        key="di_state_rear",
        streaming_key=Signal.DI_STATE_R,
        entity_registry_enabled_default=False,
    ),
    TeslemetrySensorEntityDescription(
        key="di_state_rear_left",
        streaming_key=Signal.DI_STATE_REL,
        entity_registry_enabled_default=False,
    ),
    TeslemetrySensorEntityDescription(
        key="di_state_rear_right",
        streaming_key=Signal.DI_STATE_RER,
        entity_registry_enabled_default=False,
    ),
    TeslemetrySensorEntityDescription(
        key="di_stator_temp_front",
        streaming_key=Signal.DI_STATOR_TEMP_F,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        device_class=SensorDeviceClass.TEMPERATURE,
        suggested_display_precision=1,
        entity_registry_enabled_default=False,
    ),
    TeslemetrySensorEntityDescription(
        key="di_stator_temp_rear",
        streaming_key=Signal.DI_STATOR_TEMP_R,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        device_class=SensorDeviceClass.TEMPERATURE,
        suggested_display_precision=1,
        streaming_value_fn=lambda x: float(x),
        entity_registry_enabled_default=False,
    ),
    TeslemetrySensorEntityDescription(
        key="di_stator_temp_rear_left",
        streaming_key=Signal.DI_STATOR_TEMP_REL,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        device_class=SensorDeviceClass.TEMPERATURE,
        suggested_display_precision=1,
        streaming_value_fn=lambda x: float(x),
        entity_registry_enabled_default=False,
    ),
    TeslemetrySensorEntityDescription(
        key="di_stator_temp_rear_right",
        streaming_key=Signal.DI_STATOR_TEMP_RER,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        device_class=SensorDeviceClass.TEMPERATURE,
        suggested_display_precision=1,
        streaming_value_fn=lambda x: float(x),
        entity_registry_enabled_default=False,
    ),
    TeslemetrySensorEntityDescription(
        key="di_torque_actual_front",
        streaming_key=Signal.DI_TORQUE_ACTUAL_F,
        entity_registry_enabled_default=False,
    ),
    TeslemetrySensorEntityDescription(
        key="di_torque_actual_rear",
        streaming_key=Signal.DI_TORQUE_ACTUAL_R,
        entity_registry_enabled_default=False,
    ),
    TeslemetrySensorEntityDescription(
        key="di_torque_actual_rear_left",
        streaming_key=Signal.DI_TORQUE_ACTUAL_REL,
        entity_registry_enabled_default=False,
    ),
    TeslemetrySensorEntityDescription(
        key="di_torque_actual_rear_right",
        streaming_key=Signal.DI_TORQUE_ACTUAL_RER,
        entity_registry_enabled_default=False,
    ),
    TeslemetrySensorEntityDescription(
        key="di_torque_motor",
        streaming_key=Signal.DI_TORQUEMOTOR,
        entity_registry_enabled_default=False,
    ),
    TeslemetrySensorEntityDescription(
        key="di_voltage_battery_front",
        streaming_key=Signal.DI_V_BAT_F,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        device_class=SensorDeviceClass.VOLTAGE,
        suggested_display_precision=1,
        streaming_value_fn=lambda x: float(x),
        entity_registry_enabled_default=False,
    ),
    TeslemetrySensorEntityDescription(
        key="di_voltage_battery_rear",
        streaming_key=Signal.DI_V_BAT_R,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        device_class=SensorDeviceClass.VOLTAGE,
        suggested_display_precision=1,
        streaming_value_fn=lambda x: float(x),
        entity_registry_enabled_default=False,
    ),
    TeslemetrySensorEntityDescription(
        key="di_voltage_battery_rear_left",
        streaming_key=Signal.DI_V_BAT_REL,
        entity_registry_enabled_default=False,
    ),
    TeslemetrySensorEntityDescription(
        key="di_voltage_battery_rear_right",
        streaming_key=Signal.DI_V_BAT_RER,
        entity_registry_enabled_default=False,
    ),
    TeslemetrySensorEntityDescription(
        key="emergency_lane_departure_avoidance",
        streaming_key=Signal.EMERGENCY_LANE_DEPARTURE_AVOIDANCE,
        entity_registry_enabled_default=False,
    ),
    TeslemetrySensorEntityDescription(
        key="energy_remaining",
        streaming_key=Signal.ENERGY_REMAINING,
        streaming_value_fn=lambda x: float(x),

        state_class=SensorStateClass.TOTAL,
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        device_class=SensorDeviceClass.ENERGY,
        suggested_display_precision=1,
        entity_registry_enabled_default=False,
    ),
    TeslemetrySensorEntityDescription(
        key="forward_collision_warning",
        streaming_key=Signal.FORWARD_COLLISION_WARNING,
        entity_registry_enabled_default=False,
        streaming_value_fn=lambda x: str(x).replace("ForwardCollisionSensitivity",""),
    ),
    TeslemetrySensorEntityDescription(
        key="gps_heading",
        streaming_key=Signal.GPS_HEADING,
        # Unit of direction?
        entity_registry_enabled_default=False,
        suggested_display_precision=1,
    ),
    TeslemetrySensorEntityDescription(
        key="guest_mode_mobile_access_state",
        streaming_key=Signal.GUEST_MODE_MOBILE_ACCESS_STATE,
        entity_registry_enabled_default=False,
        streaming_value_fn=lambda x: str(x).replace("GuestModeMobileAccess", "")
    ),
    TeslemetrySensorEntityDescription(
        key="hvil",
        streaming_key=Signal.HVIL,
        entity_registry_enabled_default=False,
        streaming_value_fn=lambda x: str(x).replace("HvilStatus", "")
    ),
    TeslemetrySensorEntityDescription(
        key="isolation_resistance",
        streaming_key=Signal.ISOLATION_RESISTANCE,
        state_class=SensorStateClass.MEASUREMENT,
        entity_registry_enabled_default=False,
        streaming_value_fn=lambda x: int(x)
    ),
    TeslemetrySensorEntityDescription(
        key="lane_departure_avoidance",
        streaming_key=Signal.LANE_DEPARTURE_AVOIDANCE,
        entity_registry_enabled_default=False,
        options=["Unknown","None","Warning","Assist"],
        device_class=SensorDeviceClass.ENUM,
        streaming_value_fn=lambda x: str(x).replace("LaneAssistLevel", "")
    ),
    TeslemetrySensorEntityDescription(
        key="lateral_acceleration",
        streaming_key=Signal.LATERAL_ACCELERATION,
        entity_registry_enabled_default=False,
        streaming_value_fn=lambda x: float(x),
        suggested_display_precision=3,
    ),
    TeslemetrySensorEntityDescription(
        key="lifetime_energy_gained_regen",
        streaming_key=Signal.LIFETIME_ENERGY_GAINED_REGEN,
        entity_registry_enabled_default=False,
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        suggested_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        device_class=SensorDeviceClass.ENERGY,
        suggested_display_precision=2,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    TeslemetrySensorEntityDescription(
        key="lifetime_energy_used",
        streaming_key=Signal.LIFETIME_ENERGY_USED,
        entity_registry_enabled_default=False,
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        suggested_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        device_class=SensorDeviceClass.ENERGY,
        suggested_display_precision=2,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    TeslemetrySensorEntityDescription(
        key="lifetime_energy_used_drive",
        streaming_key=Signal.LIFETIME_ENERGY_USED_DRIVE,
        entity_registry_enabled_default=False,
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        suggested_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        device_class=SensorDeviceClass.ENERGY,
        suggested_display_precision=2,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    TeslemetrySensorEntityDescription(
        key="longitudinal_acceleration",
        streaming_key=Signal.LONGITUDINAL_ACCELERATION,
        entity_registry_enabled_default=False,
        streaming_value_fn=lambda x: float(x),
        suggested_display_precision=3,
    ),
    TeslemetrySensorEntityDescription(
        key="module_temp_max",
        streaming_key=Signal.MODULE_TEMP_MAX,
        device_class=SensorDeviceClass.TEMPERATURE,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        state_class=SensorStateClass.MEASUREMENT,
        entity_registry_enabled_default=False,
        suggested_display_precision=0,
    ),
    TeslemetrySensorEntityDescription(
        key="module_temp_min",
        streaming_key=Signal.MODULE_TEMP_MIN,
        device_class=SensorDeviceClass.TEMPERATURE,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        state_class=SensorStateClass.MEASUREMENT,
        entity_registry_enabled_default=False,
        suggested_display_precision=0
    ),
    TeslemetrySensorEntityDescription(
        key="no_enough_power_to_heat",
        streaming_key=Signal.NOT_ENOUGH_POWER_TO_HEAT,
        entity_registry_enabled_default=False,
    ),
    TeslemetrySensorEntityDescription(
        key="brick_number_voltage_max",
        streaming_key=Signal.NUM_BRICK_VOLTAGE_MAX,
        entity_registry_enabled_default=False,
    ),
    TeslemetrySensorEntityDescription(
        key="brick_number_voltage_min",
        streaming_key=Signal.NUM_BRICK_VOLTAGE_MIN,
        entity_registry_enabled_default=False,
    ),
    TeslemetrySensorEntityDescription(
        key="module_number_temp_max",
        streaming_key=Signal.NUM_MODULE_TEMP_MAX,
        entity_registry_enabled_default=False,
    ),
    TeslemetrySensorEntityDescription(
        key="module_number_temp_min",
        streaming_key=Signal.NUM_MODULE_TEMP_MIN,
        entity_registry_enabled_default=False,
    ),
    TeslemetrySensorEntityDescription(
        key="pack_current",
        streaming_key=Signal.PACK_CURRENT,
        suggested_display_precision=1,
        device_class=SensorDeviceClass.CURRENT,
        native_unit_of_measurement=UnitOfElectricCurrent.AMPERE,
        state_class=SensorStateClass.MEASUREMENT,
        entity_registry_enabled_default=False,
    ),
    TeslemetrySensorEntityDescription(
        key="pack_voltage",
        suggested_display_precision=1,
        streaming_key=Signal.PACK_VOLTAGE,
        device_class=SensorDeviceClass.VOLTAGE,
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        state_class=SensorStateClass.MEASUREMENT,
        entity_registry_enabled_default=False,
    ),
    TeslemetrySensorEntityDescription(
        key="paired_key_quantity",
        streaming_key=Signal.PAIRED_PHONE_KEY_AND_KEY_FOB_QTY,
        entity_registry_enabled_default=False,
        #streaming_value_fn=lambda x: int(x),
    ),
    TeslemetrySensorEntityDescription(
        key="pedal_position",
        streaming_key=Signal.PEDAL_POSITION,
        suggested_display_precision=0,
        entity_registry_enabled_default=False,
    ),
    TeslemetrySensorEntityDescription(
        key="rated_range",
        streaming_key=Signal.RATED_RANGE,
        device_class=SensorDeviceClass.DISTANCE,
        native_unit_of_measurement=UnitOfLength.MILES,
        suggested_display_precision=1,
        entity_registry_enabled_default=False,
    ),
    TeslemetrySensorEntityDescription(
        key="sentry_mode",
        streaming_key=Signal.SENTRY_MODE,
        entity_registry_enabled_default=False,
        options=["Unknown", "Off", "Idle", "Armed", "Aware", "Panic", "Quiet"],
        device_class=SensorDeviceClass.ENUM,
        streaming_value_fn=lambda x: str(x).replace("SentryModeState",""),
    ),
    TeslemetrySensorEntityDescription(
        key="state_of_charge",
        streaming_key=Signal.SOC,
        device_class=SensorDeviceClass.BATTERY,
        native_unit_of_measurement=PERCENTAGE,
        entity_registry_enabled_default=False,
        suggested_display_precision=1,
    ),
    TeslemetrySensorEntityDescription(
        key="speed_limit_warning",
        streaming_key=Signal.SPEED_LIMIT_WARNING,
        entity_registry_enabled_default=False,
        options=["Unknown","None","Display","Chime"],
        device_class=SensorDeviceClass.ENUM,
        streaming_value_fn=lambda x: str(x).replace("SpeedAssistLevel",""),
    ),
    TeslemetrySensorEntityDescription(
        key="supercharger_session_trip_planner",
        streaming_key=Signal.SUPERCHARGER_SESSION_TRIP_PLANNER,
        entity_registry_enabled_default=False,
        # Maybe a binary?
    ),
    TeslemetrySensorEntityDescription(
        key="trim",
        streaming_key=Signal.TRIM,
        entity_registry_enabled_default=False,
    ),
    TeslemetrySensorEntityDescription(
        key="vehicle_name",
        streaming_key=Signal.VEHICLE_NAME,
        entity_registry_enabled_default=False,
    ),
    TeslemetrySensorEntityDescription(
        key="center_display",
        streaming_key=Signal.CENTER_DISPLAY,
        device_class=SensorDeviceClass.ENUM,
        options=[
          "Off",
          "Dim",
          "Accessory",
          "On",
          "Driving",
          "Charging",
          "Lock",
          "Sentry",
          "Dog",
          "Entertainment"
        ],
        streaming_value_fn=lambda x: str(x).replace("DisplayState",""),
        entity_registry_enabled_default=False,
    ),
    TeslemetrySensorEntityDescription(
        key="efficiency_package",
        streaming_key=Signal.EFFICIENCY_PACKAGE,
        entity_registry_enabled_default=False,
    ),
)

@dataclass(frozen=True, kw_only=True)
class TeslemetryTimeEntityDescription(SensorEntityDescription):
    """Describes Teslemetry Sensor entity."""

    polling: bool = False
    variance: int = 60
    streaming_key: Signal | None = None
    streaming_firmware: str = "2024.26"


VEHICLE_TIME_DESCRIPTIONS: tuple[TeslemetryTimeEntityDescription, ...] = (
    TeslemetryTimeEntityDescription(
        key="charge_state_time_to_full_charge",
        polling=True,
        streaming_key=Signal.TIME_TO_FULL_CHARGE,
        device_class=SensorDeviceClass.TIMESTAMP,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    TeslemetryTimeEntityDescription(
        key="drive_state_active_route_minutes_to_arrival",
        polling=True,
        streaming_key=Signal.MINUTES_TO_ARRIVAL,
        device_class=SensorDeviceClass.TIMESTAMP,
    ),
    TeslemetryTimeEntityDescription(
        key="route_last_updated",
        streaming_key=Signal.ROUTE_LAST_UPDATED,
        entity_registry_enabled_default=False,
    ),
)


@dataclass(frozen=True, kw_only=True)
class TeslemetryEnergySensorEntityDescription(SensorEntityDescription):
    """Describes Teslemetry Sensor entity."""

    value_fn: Callable[[StateType], StateType | datetime] = lambda x: x

ENERGY_LIVE_DESCRIPTIONS: tuple[TeslemetryEnergySensorEntityDescription, ...] = (
    TeslemetryEnergySensorEntityDescription(
        key="grid_status",
    ),
    TeslemetryEnergySensorEntityDescription(
        key="solar_power",
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfPower.WATT,
        suggested_unit_of_measurement=UnitOfPower.KILO_WATT,
        suggested_display_precision=2,
        device_class=SensorDeviceClass.POWER,
    ),
    TeslemetryEnergySensorEntityDescription(
        # Tesla may have removed this from the API
        key="energy_left",
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfEnergy.WATT_HOUR,
        suggested_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        suggested_display_precision=2,
        device_class=SensorDeviceClass.ENERGY_STORAGE,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    TeslemetryEnergySensorEntityDescription(
        # Tesla may have removed this from the API
        key="total_pack_energy",
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfEnergy.WATT_HOUR,
        suggested_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        suggested_display_precision=2,
        device_class=SensorDeviceClass.ENERGY_STORAGE,
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
    ),
    TeslemetryEnergySensorEntityDescription(
        key="percentage_charged",
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=PERCENTAGE,
        device_class=SensorDeviceClass.BATTERY,
        suggested_display_precision=2,
        value_fn=lambda value: value or 0,
    ),
    TeslemetryEnergySensorEntityDescription(
        key="battery_power",
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfPower.WATT,
        suggested_unit_of_measurement=UnitOfPower.KILO_WATT,
        suggested_display_precision=2,
        device_class=SensorDeviceClass.POWER,
    ),
    TeslemetryEnergySensorEntityDescription(
        key="load_power",
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfPower.WATT,
        suggested_unit_of_measurement=UnitOfPower.KILO_WATT,
        suggested_display_precision=2,
        device_class=SensorDeviceClass.POWER,
    ),
    TeslemetryEnergySensorEntityDescription(
        key="grid_power",
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfPower.WATT,
        suggested_unit_of_measurement=UnitOfPower.KILO_WATT,
        suggested_display_precision=2,
        device_class=SensorDeviceClass.POWER,
    ),
    TeslemetryEnergySensorEntityDescription(
        key="grid_services_power",
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfPower.WATT,
        suggested_unit_of_measurement=UnitOfPower.KILO_WATT,
        suggested_display_precision=2,
        device_class=SensorDeviceClass.POWER,
    ),
    TeslemetryEnergySensorEntityDescription(
        key="generator_power",
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfPower.WATT,
        suggested_unit_of_measurement=UnitOfPower.KILO_WATT,
        suggested_display_precision=2,
        device_class=SensorDeviceClass.POWER,
        entity_registry_enabled_default=False,
    ),
    TeslemetryEnergySensorEntityDescription(
        key="island_status",
        device_class=SensorDeviceClass.ENUM,
        options=[
            "on_grid",
            "off_grid",
            "off_grid_intentional",
            "off_grid_unintentional",
            "island_status_unknown",
        ],
    ),
)


WALL_CONNECTOR_DESCRIPTIONS: tuple[
    TeslemetryEnergySensorEntityDescription, ...
] = (
    TeslemetryEnergySensorEntityDescription(
        key="wall_connector_state",
        entity_category=EntityCategory.DIAGNOSTIC,
        options=list(WALL_CONNECTOR_STATES.values()),
        device_class=SensorDeviceClass.ENUM,
        value_fn=lambda value: WALL_CONNECTOR_STATES.get(cast(str, value)),
    ),
    TeslemetryEnergySensorEntityDescription(
        key="wall_connector_fault_state",
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
    ),
    TeslemetryEnergySensorEntityDescription(
        key="wall_connector_power",
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfPower.WATT,
        suggested_unit_of_measurement=UnitOfPower.KILO_WATT,
        suggested_display_precision=2,
        device_class=SensorDeviceClass.POWER,
    ),
)

ENERGY_INFO_DESCRIPTIONS: tuple[SensorEntityDescription, ...] = (
    SensorEntityDescription(
        key="vpp_backup_reserve_percent",
        entity_category=EntityCategory.DIAGNOSTIC,
        device_class=SensorDeviceClass.BATTERY,
        native_unit_of_measurement=PERCENTAGE,
    ),
    SensorEntityDescription(key="version"),
)


ENERGY_HISTORY_DESCRIPTIONS: tuple[TeslemetryEnergySensorEntityDescription, ...] = tuple(
    TeslemetryEnergySensorEntityDescription(
        key=key,
        device_class=SensorDeviceClass.ENERGY,
        native_unit_of_measurement=UnitOfEnergy.WATT_HOUR,
        suggested_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        suggested_display_precision=2,
        state_class=SensorStateClass.TOTAL_INCREASING,
        entity_registry_enabled_default=(key.startswith("total") or key=="grid_energy_imported"),
        value_fn=lambda x: x.get(key, 0),
    ) for key in ENERGY_HISTORY_FIELDS
)


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Set up the Teslemetry sensor platform from a config entry."""

    entities = []
    for vehicle in entry.runtime_data.vehicles:
        if not vehicle.api.pre2021:
            entities.extend((
                TeslemetryVehicleEventSensorEntity(vehicle, "alerts"),
                TeslemetryVehicleEventSensorEntity(vehicle, "errors")
            ))
        for description in VEHICLE_DESCRIPTIONS:
            if not vehicle.api.pre2021 and description.streaming_key and vehicle.firmware >= description.streaming_firmware:
                entities.append(TeslemetryVehicleStreamSensorEntity(vehicle, description))
            elif description.polling:
                entities.append(TeslemetryVehiclePollingSensorEntity(vehicle, description))
        for description in VEHICLE_TIME_DESCRIPTIONS:
            if not vehicle.api.pre2021 and vehicle.firmware >= description.streaming_firmware:
                entities.append(TeslemetryVehicleTimeStreamSensorEntity(vehicle, description))
            elif description.polling:
                entities.append(TeslemetryVehicleTimeSensorEntity(vehicle, description))

    for energysite in entry.runtime_data.energysites:
        for description in ENERGY_LIVE_DESCRIPTIONS:
            if description.key in energysite.live_coordinator.data:
                entities.append(TeslemetryEnergyLiveSensorEntity(energysite, description))
        for din in energysite.live_coordinator.data.get("wall_connectors", {}):
            for description in WALL_CONNECTOR_DESCRIPTIONS:
                entities.append(TeslemetryWallConnectorSensorEntity(energysite, din, description))
            entities.append(TeslemetryWallConnectorVehicleSensorEntity(energysite, din, entry.runtime_data.vehicles))
        for description in ENERGY_INFO_DESCRIPTIONS:
            if description.key in energysite.info_coordinator.data:
                entities.append(TeslemetryEnergyInfoSensorEntity(energysite, description))
        if energysite.history_coordinator is not None:
            for description in ENERGY_HISTORY_DESCRIPTIONS:
                entities.append(TeslemetryEnergyHistorySensorEntity(energysite, description))

    async_add_entities(entities)


class TeslemetryVehiclePollingSensorEntity(TeslemetryVehicleEntity, SensorEntity):
    """Base class for Teslemetry vehicle metric sensors."""

    entity_description: TeslemetrySensorEntityDescription

    def __init__(
        self,
        data: TeslemetryVehicleData,
        description: TeslemetrySensorEntityDescription,
    ) -> None:
        """Initialize the sensor."""
        self.entity_description = description
        super().__init__(data, description.key)

    def _async_update_attrs(self) -> None:
        """Update the attributes of the sensor."""

        if self.entity_description.polling_available_fn(self._value):
            self._attr_available = True
            self._attr_native_value = self.entity_description.polling_value_fn(self._value)
        else:
            self._attr_available = False
            self._attr_native_value = None

class TeslemetryVehicleStreamSensorEntity(TeslemetryVehicleStreamEntity, RestoreSensor):
    """Base class for Teslemetry vehicle streaming sensors."""

    entity_description: TeslemetrySensorEntityDescription

    def __init__(
        self,
        data: TeslemetryVehicleData,
        description: TeslemetrySensorEntityDescription,
    ) -> None:
        """Initialize the sensor."""
        self.entity_description = description
        assert description.streaming_key
        super().__init__(data, description.key, description.streaming_key)

    async def async_added_to_hass(self) -> None:
        """Handle entity which will be added."""
        await super().async_added_to_hass()

        if (sensor_data := await self.async_get_last_sensor_data()) is not None:
            if sensor_data.native_value is not None:
                self._attr_native_value = sensor_data.native_value

    def _async_value_from_stream(self, value) -> None:
        """Update the value of the entity."""
        if (value is None):
            self._attr_native_value = None
        else:
            self._attr_native_value = self.entity_description.streaming_value_fn(value)


class TeslemetryVehicleEventSensorEntity(RestoreSensor):
    """Base class for Teslemetry vehicle streaming sensors."""

    def __init__(
        self,
        data: TeslemetryVehicleData,
        type: str
    ) -> None:
        """Initialize the sensor."""
        self.type = type
        self.stream = data.stream
        self.vin = data.vin
        self._attr_translation_key = type
        self._attr_unique_id = f"{data.vin}-{type}"
        self._attr_device_info = data.device
        self._last = 0

    async def async_added_to_hass(self) -> None:
        """When entity is added to hass."""
        await super().async_added_to_hass()
        print(f"Listening for events {self.type}")
        self.async_on_remove(
            self.stream.async_add_listener(
                self._handle_stream_update,
                {"vin": self.vin, type: None},
            )
        )

        if (sensor_data := await self.async_get_last_sensor_data()) is not None:
            self._attr_native_value = sensor_data.native_value

    def _handle_stream_update(self, data) -> None:
        """Update the value of the entity."""
        print(f"Received events {data}")
        for event in data[self.type].sorted(key=lambda event: event["startedAt"]).filter(lambda event: event["startedAt"] > self._last):
            print(f"Received event {event}")
            self._last = event["startedAt"]
            self._attr_native_value = event["name"]
            self.async_write_ha_state()


class TeslemetryVehicleTimeSensorEntity(TeslemetryVehicleEntity, SensorEntity):
    """Base class for Teslemetry vehicle metric sensors."""

    entity_description: TeslemetryTimeEntityDescription
    _last_value: int | None = None

    def __init__(
        self,
        data: TeslemetryVehicleData,
        description: TeslemetryTimeEntityDescription,
    ) -> None:
        """Initialize the sensor."""
        self.entity_description = description
        self._time_value = ignore_variance(
            func=lambda value: dt_util.utcnow() + description.value_fn(value),
            ignored_variance=timedelta(minutes=1),
        )

        super().__init__(data, description.key)
        self._attr_translation_key = f"{self.entity_description.key}_timestamp"
        self._attr_unique_id = f"{data.vin}-{description.key}_timestamp"

    def _async_update_attrs(self) -> None:
        """Update the attributes of the sensor."""

        value = self._value
        self._attr_available = value is not None and value > 0

        if value == self._last_value:
            # No change
            return
        self._last_value = value
        if isinstance(value, int | float):
            self._attr_native_value = self._time_value(float(value))
        else:
            self._attr_native_value = None


class TeslemetryVehicleTimeStreamSensorEntity(TeslemetryVehicleStreamEntity, SensorEntity):
    """Base class for Teslemetry vehicle metric sensors."""

    entity_description: TeslemetryTimeEntityDescription
    _last_value: int | None = None

    def __init__(
        self,
        data: TeslemetryVehicleData,
        description: TeslemetryTimeEntityDescription,
    ) -> None:
        """Initialize the sensor."""
        self.entity_description = description
        self._get_timestamp = ignore_variance(
            func=lambda value: dt_util.utcnow() + timedelta(minutes=value),
            ignored_variance=timedelta(minutes=1),
        )
        assert description.streaming_key
        super().__init__(data, description.key, description.streaming_key)
        self._attr_translation_key = f"{self.entity_description.key}_timestamp"
        self._attr_unique_id = f"{data.vin}-{description.key}_timestamp"

    def _async_value_from_stream(self, value) -> None:
        """Update the attributes of the sensor."""

        self._attr_available = value is not None and value > 0

        if value == self._last_value:
            # No change
            return
        self._last_value = value
        if isinstance(value, int | float):
            self._attr_native_value = self._get_timestamp(value)
        else:
            self._attr_native_value = None


class TeslemetryEnergyLiveSensorEntity(TeslemetryEnergyLiveEntity, SensorEntity):
    """Base class for Teslemetry energy site metric sensors."""

    entity_description: TeslemetryEnergySensorEntityDescription

    def __init__(
        self,
        data: TeslemetryEnergyData,
        description: TeslemetryEnergySensorEntityDescription,
    ) -> None:
        """Initialize the sensor."""
        self.entity_description = description
        super().__init__(data, description.key)

    def _async_update_attrs(self) -> None:
        """Update the attributes of the sensor."""
        self._attr_available = not self.exactly(None)
        self._attr_native_value = self.entity_description.value_fn(self._value)


class TeslemetryWallConnectorSensorEntity(TeslemetryWallConnectorEntity, SensorEntity):
    """Base class for Teslemetry Wall Connector sensors."""

    entity_description: TeslemetryEnergySensorEntityDescription

    def __init__(
        self,
        data: TeslemetryEnergyData,
        din: str,
        description: TeslemetryEnergySensorEntityDescription,
    ) -> None:
        """Initialize the sensor."""
        self.entity_description = description
        super().__init__(
            data,
            din,
            description.key,
        )

    def _async_update_attrs(self) -> None:
        """Update the attributes of the sensor."""

        if not self.has:
            return

        self._attr_available = not self.exactly(None)
        self._attr_native_value = self.entity_description.value_fn(self._value)


class TeslemetryWallConnectorVehicleSensorEntity(
    TeslemetryWallConnectorEntity, SensorEntity
):
    """Entity for Teslemetry wall connector vehicle sensors."""

    entity_description: TeslemetryEnergySensorEntityDescription

    def __init__(
        self,
        data: TeslemetryEnergyData,
        din: str,
        vehicles: list[TeslemetryVehicleData],
    ) -> None:
        """Initialize the sensor."""
        self._vehicles = vehicles
        super().__init__(
            data,
            din,
            "vin",
        )

    def _async_update_attrs(self) -> None:
        """Update the attributes of the sensor."""

        if not self.has:
            return

        if self.exactly(None):
            self._attr_native_value = "None"
            self._attr_extra_state_attributes = {}
            return

        value = self._value
        for vehicle in self._vehicles:
            if vehicle.vin == value:
                self._attr_native_value = vehicle.device["name"]
                self._attr_extra_state_attributes = {
                    "vin": vehicle.vin,
                    "model": vehicle.device["model"],
                }
                return
        self._attr_native_value = value
        self._attr_extra_state_attributes = {
            "vin": value,
            "model": MODELS.get(value[3]),
        }


class TeslemetryEnergyInfoSensorEntity(TeslemetryEnergyInfoEntity, SensorEntity):
    """Base class for Teslemetry energy site metric sensors."""

    entity_description: SensorEntityDescription

    def __init__(
        self,
        data: TeslemetryEnergyData,
        description: SensorEntityDescription,
    ) -> None:
        """Initialize the sensor."""
        self.entity_description = description
        super().__init__(data, description.key)

    def _async_update_attrs(self) -> None:
        """Update the attributes of the sensor."""
        self._attr_available = not self.exactly(None)
        self._attr_native_value = self._value


class TeslemetryEnergyHistorySensorEntity(TeslemetryEnergyHistoryEntity, SensorEntity):
    """Base class for Teslemetry energy site metric sensors."""

    entity_description: SensorEntityDescription

    def __init__(
        self,
        data: TeslemetryEnergyData,
        description: SensorEntityDescription,
    ) -> None:
        """Initialize the sensor."""

        self.entity_description = description
        super().__init__(data, description.key)

    def _async_update_attrs(self) -> None:
        """Update the attributes of the sensor."""
        self._attr_native_value = self._value


class TeslemetryVehicleEventEntity(RestoreSensor):
    """Parent class for Teslemetry Vehicle Stream entities."""

    _attr_has_entity_name = True

    def __init__(
        self, data: TeslemetryVehicleData, key: str
    ) -> None:
        """Initialize common aspects of a Teslemetry entity."""

        self.key = key
        self._attr_translation_key = f"event_{key}"
        self.stream = data.stream
        self.vin = data.vin

        self._attr_unique_id = f"{data.vin}-event_{key}"
        self._attr_device_info = data.device

    async def async_added_to_hass(self) -> None:
        """Handle entity which will be added."""
        await super().async_added_to_hass()

        if (sensor_data := await self.async_get_last_sensor_data()) is not None:
            self._attr_native_value = sensor_data.native_value

        if self.stream.server:
            self.async_on_remove(
                self.stream.async_add_listener(
                    self._handle_stream_update,
                    {"vin": self.vin, self.key: None},
                )
            )

    def _handle_stream_update(self, data: dict[str, list]) -> None:
        """Handle updated data from the stream."""
        self._attr_available = self.stream.connected
        self._attr_native_value = data[self.key][0]['name']
        self.async_write_ha_state()
