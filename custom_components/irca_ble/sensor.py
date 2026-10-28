"""Diagnostic sensors.

Note what is deliberately absent: the CIP field. It was the obvious candidate
for a power sensor, but it did not change at all across a full on/off cycle
while drifting upward over twenty idle minutes (spec §12.3). Whatever it
counts, it is not instantaneous power, and shipping it with a power device
class would put fiction in users' energy dashboards.
"""
from __future__ import annotations

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .coordinator import IrcaConfigEntry, IrcaCoordinator
from .entity import IrcaEntity
from .ircable import protocol as P

ALARM_STATES = ["ok", "ntc_fault", "load_fault", "date_fault", "eeprom_fault"]
WINDOW_STATES = [
    "disabled",
    "trigger_off_window_closed",
    "trigger_on_window_closed",
    "trigger_on_window_opened",
    "unknown",
]


async def async_setup_entry(
    hass: HomeAssistant, entry: IrcaConfigEntry, add_entities: AddEntitiesCallback
) -> None:
    coordinator = entry.runtime_data
    add_entities(
        [
            IrcaAlarmSensor(coordinator),
            IrcaWindowDetectionSensor(coordinator),
        ]
    )


class IrcaAlarmSensor(IrcaEntity, SensorEntity):
    _attr_name = "Alarm"
    _attr_icon = "mdi:alert-circle-outline"
    _attr_device_class = SensorDeviceClass.ENUM
    _attr_options = ALARM_STATES
    _attr_translation_key = "alarm"
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, coordinator: IrcaCoordinator) -> None:
        super().__init__(coordinator, "alarm")

    @property
    def native_value(self) -> str | None:
        status = self.status
        if status is None or status.alarm is None:
            return None
        if 0 <= status.alarm < len(ALARM_STATES):
            return ALARM_STATES[status.alarm]
        return None


class IrcaWindowDetectionSensor(IrcaEntity, SensorEntity):
    """Open-window detection setting.

    Real hardware returned 0xFF here, which is outside the documented 0..3
    enum, so anything unrecognised maps to "unknown" rather than crashing.
    """

    _attr_name = "Open window detection"
    _attr_icon = "mdi:window-open-variant"
    _attr_device_class = SensorDeviceClass.ENUM
    _attr_options = WINDOW_STATES
    _attr_translation_key = "window_detection"
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, coordinator: IrcaCoordinator) -> None:
        super().__init__(coordinator, "window_detection")

    @property
    def native_value(self) -> str | None:
        status = self.status
        if status is None or status.window_detection is None:
            return None
        try:
            return WINDOW_STATES[P.WindowDetection(status.window_detection).value]
        except (ValueError, IndexError):
            return "unknown"
