"""Setpoint numbers, adapted to whichever value family the device reports.

A POWER unit ("North Europe" build) has no temperature concept at all - the
user picks an abstract level 1-10. Those units get a manual-setpoint number;
Celsius and Fahrenheit units get a climate entity instead and only the three
preset setpoints appear here.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from homeassistant.components.number import (
    NumberDeviceClass,
    NumberEntity,
    NumberMode,
)
from homeassistant.const import UnitOfTemperature
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .coordinator import IrcaConfigEntry, IrcaCoordinator
from .entity import IrcaEntity
from .ircable import protocol as P
from .ircable.const import (
    CELSIUS_MAX,
    CELSIUS_MIN,
    CELSIUS_STEP,
    FAHRENHEIT_MAX,
    FAHRENHEIT_MIN,
    FAHRENHEIT_STEP,
    POWER_MAX,
    POWER_MIN,
    POWER_STEP,
)


def family_range(mode_settings: int) -> tuple[float, float, float]:
    """(min, max, step) for the device's own value family."""
    if mode_settings == P.MS_CELSIUS:
        return CELSIUS_MIN, CELSIUS_MAX, CELSIUS_STEP
    if mode_settings == P.MS_FAHRENHEIT:
        return FAHRENHEIT_MIN, FAHRENHEIT_MAX, FAHRENHEIT_STEP
    return POWER_MIN, POWER_MAX, POWER_STEP


def family_unit(mode_settings: int) -> str | None:
    if mode_settings == P.MS_CELSIUS:
        return UnitOfTemperature.CELSIUS
    if mode_settings == P.MS_FAHRENHEIT:
        return UnitOfTemperature.FAHRENHEIT
    return None            # a power level is dimensionless


@dataclass(frozen=True)
class SetpointDesc:
    key: str
    name: str
    action: P.Action
    value: Callable[[P.Status], float | None]
    icon: str


PRESETS: tuple[SetpointDesc, ...] = (
    SetpointDesc("comfort", "Comfort setpoint", P.Action.SET_TEMP_COMFORT,
                 lambda s: s.comfort, "mdi:sofa"),
    SetpointDesc("eco", "Eco setpoint", P.Action.SET_TEMP_ECO,
                 lambda s: s.eco, "mdi:leaf"),
    SetpointDesc("antifreeze", "Antifreeze setpoint", P.Action.SET_TEMP_ANTIFREEZE,
                 lambda s: s.antifreeze, "mdi:snowflake"),
)


async def async_setup_entry(
    hass: HomeAssistant, entry: IrcaConfigEntry, add_entities: AddEntitiesCallback
) -> None:
    coordinator = entry.runtime_data
    status = coordinator.data
    mode_settings = (
        status.mode_settings
        if status is not None and status.mode_settings is not None
        else P.MS_POWER
    )

    entities: list[NumberEntity] = [
        IrcaPresetSetpoint(coordinator, desc) for desc in PRESETS
    ]
    if mode_settings == P.MS_POWER:
        # No climate entity for this family, so the live setpoint lives here.
        entities.append(IrcaManualSetpoint(coordinator))
    add_entities(entities)


class _IrcaNumberBase(IrcaEntity, NumberEntity):
    _attr_mode = NumberMode.SLIDER

    @property
    def native_unit_of_measurement(self) -> str | None:
        return family_unit(self._mode_settings)

    @property
    def device_class(self) -> NumberDeviceClass | None:
        # Only claim "temperature" when the value really is one; a power level
        # with a temperature device class renders as degrees and lies.
        if self._mode_settings in (P.MS_CELSIUS, P.MS_FAHRENHEIT):
            return NumberDeviceClass.TEMPERATURE
        return None

    @property
    def native_min_value(self) -> float:
        return family_range(self._mode_settings)[0]

    @property
    def native_max_value(self) -> float:
        return family_range(self._mode_settings)[1]

    @property
    def native_step(self) -> float:
        return family_range(self._mode_settings)[2]


class IrcaManualSetpoint(_IrcaNumberBase):
    """The live setpoint on a POWER-family unit (SET_TEMP_MANUAL, 0x03)."""

    _attr_name = "Power level"
    _attr_icon = "mdi:gauge"

    def __init__(self, coordinator: IrcaCoordinator) -> None:
        super().__init__(coordinator, "power_level")

    @property
    def native_value(self) -> float | None:
        status = self.status
        if status is None or status.setpoint is None:
            return None
        return status.setpoint

    async def async_set_native_value(self, value: float) -> None:
        ms = self._mode_settings
        await self.coordinator.async_execute(
            lambda c, v=value, m=ms: c.set_manual_setpoint(v, m),
            label="Set power level",
        )


class IrcaPresetSetpoint(_IrcaNumberBase):
    """One of the three stored setpoints (eco / comfort / antifreeze)."""

    _attr_entity_category = EntityCategory.CONFIG

    def __init__(self, coordinator: IrcaCoordinator, desc: SetpointDesc) -> None:
        super().__init__(coordinator, f"setpoint_{desc.key}")
        self._desc = desc
        self._attr_name = desc.name
        self._attr_icon = desc.icon

    @property
    def native_value(self) -> float | None:
        status = self.status
        return None if status is None else self._desc.value(status)

    async def async_set_native_value(self, value: float) -> None:
        ms = self._mode_settings
        await self.coordinator.async_execute(
            lambda c, v=value, m=ms, a=self._desc.action:
                c.set_preset_setpoint(a, v, m),
            label=f"Set {self._desc.name.lower()}",
        )
