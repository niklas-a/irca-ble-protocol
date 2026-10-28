"""Climate entity, created only for Celsius and Fahrenheit units.

A POWER-family unit carries an abstract level 1-10, not a temperature. Home
Assistant's climate platform is built around a real target temperature, so
modelling a power level as one produces a thermostat card claiming "5 °C" and
lets users ask for physically meaningless values. Those units get `number`
entities instead - see number.py.

NOTE: untested against hardware. The unit this protocol was reverse-engineered
from is POWER-family, so this code path has never run against a real device.
"""
from __future__ import annotations

from typing import Any

from homeassistant.components.climate import (
    ClimateEntity,
    ClimateEntityFeature,
    HVACAction,
    HVACMode,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import ATTR_TEMPERATURE, UnitOfTemperature
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .coordinator import IrcaCoordinator
from .entity import IrcaEntity
from .ircable import protocol as P
from .number import family_range

PRESET_TO_MODE = {
    "comfort": P.Mode.COMFORT,
    "eco": P.Mode.ECO,
    "antifreeze": P.Mode.ANTIFREEZE,
    "boost": P.Mode.BOOST,
    "schedule": P.Mode.SCHEDULE,
    "manual": P.Mode.MANUAL,
}
MODE_TO_PRESET = {v: k for k, v in PRESET_TO_MODE.items()}


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, add_entities: AddEntitiesCallback
) -> None:
    coordinator: IrcaCoordinator = hass.data[DOMAIN][entry.entry_id]
    status = coordinator.data
    mode_settings = status.mode_settings if status is not None else None
    if mode_settings in (P.MS_CELSIUS, P.MS_FAHRENHEIT):
        add_entities([IrcaClimate(coordinator)])


class IrcaClimate(IrcaEntity, ClimateEntity):
    _attr_name = None                      # the device name is enough
    _attr_hvac_modes = [HVACMode.HEAT, HVACMode.OFF]
    _attr_supported_features = (
        ClimateEntityFeature.TARGET_TEMPERATURE
        | ClimateEntityFeature.PRESET_MODE
        | ClimateEntityFeature.TURN_ON
        | ClimateEntityFeature.TURN_OFF
    )
    _attr_preset_modes = list(PRESET_TO_MODE)
    # We implement async_turn_on/off via set_hvac_mode and declare the
    # features explicitly, so opt out of HA's compatibility shim.
    _enable_turn_on_off_backwards_compatibility = False

    def __init__(self, coordinator: IrcaCoordinator) -> None:
        super().__init__(coordinator, "climate")

    @property
    def temperature_unit(self) -> str:
        return (
            UnitOfTemperature.FAHRENHEIT
            if self._mode_settings == P.MS_FAHRENHEIT
            else UnitOfTemperature.CELSIUS
        )

    @property
    def min_temp(self) -> float:
        return family_range(self._mode_settings)[0]

    @property
    def max_temp(self) -> float:
        return family_range(self._mode_settings)[1]

    @property
    def target_temperature_step(self) -> float:
        return family_range(self._mode_settings)[2]

    @property
    def target_temperature(self) -> float | None:
        status = self.status
        if status is None or status.setpoint is None:
            return None
        return status.setpoint

    @property
    def hvac_mode(self) -> HVACMode:
        return HVACMode.HEAT if self._is_on else HVACMode.OFF

    @property
    def hvac_action(self) -> HVACAction:
        # The protocol reports the configured mode, not whether the element is
        # drawing power right now. CIP looked like it might mean that but
        # provably does not (spec §12.3), so this is the configured state and
        # nothing finer.
        return HVACAction.HEATING if self._is_on else HVACAction.OFF

    @property
    def preset_mode(self) -> str | None:
        status = self.status
        if status is None or status.mode is None:
            return None
        try:
            return MODE_TO_PRESET.get(P.Mode(status.mode))
        except ValueError:
            return None

    async def async_set_temperature(self, **kwargs: Any) -> None:
        temperature = kwargs.get(ATTR_TEMPERATURE)
        if temperature is None:
            return
        ms = self._mode_settings
        await self.coordinator.async_execute(
            lambda c, v=float(temperature), m=ms: c.set_manual_setpoint(v, m),
            label="Set temperature",
        )

    async def async_set_hvac_mode(self, hvac_mode: HVACMode) -> None:
        if hvac_mode == HVACMode.OFF:
            await self.coordinator.async_execute(
                lambda c: c.turn_off(), label="Turn off"
            )
        else:
            await self.coordinator.async_execute(
                lambda c: c.turn_on(), label="Turn on"
            )

    async def async_set_preset_mode(self, preset_mode: str) -> None:
        mode = PRESET_TO_MODE[preset_mode]
        await self.coordinator.async_execute(
            lambda c, m=mode: c.set_mode(m), label=f"Set preset {preset_mode}"
        )
