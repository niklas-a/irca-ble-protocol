"""Switches: main power and child lock."""
from __future__ import annotations

from typing import Any

from homeassistant.components.switch import SwitchEntity, SwitchDeviceClass
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .coordinator import IrcaConfigEntry, IrcaCoordinator
from .entity import IrcaEntity


async def async_setup_entry(
    hass: HomeAssistant, entry: IrcaConfigEntry, add_entities: AddEntitiesCallback
) -> None:
    coordinator = entry.runtime_data
    add_entities([IrcaPowerSwitch(coordinator), IrcaChildLockSwitch(coordinator)])


class IrcaPowerSwitch(IrcaEntity, SwitchEntity):
    """On/off for the heater."""

    _attr_name = "Power"
    _attr_device_class = SwitchDeviceClass.SWITCH

    def __init__(self, coordinator: IrcaCoordinator) -> None:
        super().__init__(coordinator, "power")

    @property
    def is_on(self) -> bool:
        return self._is_on

    @property
    def icon(self) -> str:
        return "mdi:radiator" if self._is_on else "mdi:radiator-off"

    async def async_turn_on(self, **kwargs: Any) -> None:
        # SET_ON resumes the device's stored mode rather than a neutral state
        # (spec §12.3), so the coordinator reads back what actually happened
        # instead of assuming.
        await self.coordinator.async_execute(
            lambda c: c.turn_on(), label="Turn on"
        )

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self.coordinator.async_execute(
            lambda c: c.turn_off(), label="Turn off"
        )


class IrcaChildLockSwitch(IrcaEntity, SwitchEntity):
    """Front-panel child lock (SET_LOCK, 0x55 / 0xAA)."""

    _attr_name = "Child lock"
    _attr_icon = "mdi:lock"
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(self, coordinator: IrcaCoordinator) -> None:
        super().__init__(coordinator, "child_lock")

    @property
    def is_on(self) -> bool:
        status = self.status
        return bool(status is not None and status.lock)

    async def async_turn_on(self, **kwargs: Any) -> None:
        await self.coordinator.async_execute(
            lambda c: c.set_child_lock(True), label="Lock"
        )

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self.coordinator.async_execute(
            lambda c: c.set_child_lock(False), label="Unlock"
        )
