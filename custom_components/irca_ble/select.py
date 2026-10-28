"""Operating-mode select (SET_MODE, 0x02)."""
from __future__ import annotations

from homeassistant.components.select import SelectEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .coordinator import IrcaConfigEntry, IrcaCoordinator
from .entity import IrcaEntity
from .ircable import protocol as P

# "Off" is deliberately absent: the power switch owns that, and offering two
# ways to turn the heater off invites them to disagree.
MODE_OPTIONS: dict[str, P.Mode] = {
    "comfort": P.Mode.COMFORT,
    "eco": P.Mode.ECO,
    "antifreeze": P.Mode.ANTIFREEZE,
    "boost": P.Mode.BOOST,
    "schedule": P.Mode.SCHEDULE,
    "manual": P.Mode.MANUAL,
}
_BY_VALUE = {mode: name for name, mode in MODE_OPTIONS.items()}


async def async_setup_entry(
    hass: HomeAssistant, entry: IrcaConfigEntry, add_entities: AddEntitiesCallback
) -> None:
    coordinator = entry.runtime_data
    add_entities([IrcaModeSelect(coordinator)])


class IrcaModeSelect(IrcaEntity, SelectEntity):
    _attr_name = "Mode"
    _attr_icon = "mdi:thermostat"
    _attr_options = list(MODE_OPTIONS)
    _attr_translation_key = "operating_mode"

    def __init__(self, coordinator: IrcaCoordinator) -> None:
        super().__init__(coordinator, "mode")

    @property
    def current_option(self) -> str | None:
        status = self.status
        if status is None or status.mode is None:
            return None
        try:
            return _BY_VALUE.get(P.Mode(status.mode))
        except ValueError:
            # Firmware reported a mode outside the documented enum.
            return None

    async def async_select_option(self, option: str) -> None:
        mode = MODE_OPTIONS[option]
        await self.coordinator.async_execute(
            lambda c, m=mode: c.set_mode(m), label=f"Set mode {option}"
        )
