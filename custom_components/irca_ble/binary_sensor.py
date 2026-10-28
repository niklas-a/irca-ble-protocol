"""Binary sensors: holiday mode and a problem flag."""
from __future__ import annotations

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .coordinator import IrcaConfigEntry, IrcaCoordinator
from .entity import IrcaEntity


async def async_setup_entry(
    hass: HomeAssistant, entry: IrcaConfigEntry, add_entities: AddEntitiesCallback
) -> None:
    coordinator = entry.runtime_data
    add_entities([IrcaProblemSensor(coordinator), IrcaHolidaySensor(coordinator)])


class IrcaProblemSensor(IrcaEntity, BinarySensorEntity):
    """On when the heater reports any alarm other than OK."""

    _attr_name = "Problem"
    _attr_device_class = BinarySensorDeviceClass.PROBLEM
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, coordinator: IrcaCoordinator) -> None:
        super().__init__(coordinator, "problem")

    @property
    def is_on(self) -> bool | None:
        status = self.status
        if status is None or status.alarm is None:
            return None
        return status.alarm != 0


class IrcaHolidaySensor(IrcaEntity, BinarySensorEntity):
    _attr_name = "Holiday mode"
    _attr_icon = "mdi:bag-suitcase"
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, coordinator: IrcaCoordinator) -> None:
        super().__init__(coordinator, "holiday")

    @property
    def is_on(self) -> bool | None:
        status = self.status
        return None if status is None else bool(status.holiday)
