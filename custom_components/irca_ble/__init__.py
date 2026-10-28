"""The IRCA BLE Heater integration."""
from __future__ import annotations

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_ADDRESS
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryNotReady

from .const import CONF_DEVICE_ID, DOMAIN, PLATFORMS
from .coordinator import IrcaCoordinator

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up a heater from a config entry."""
    address: str = entry.data[CONF_ADDRESS]
    device_id: str | None = entry.data.get(CONF_DEVICE_ID) or None

    coordinator = IrcaCoordinator(hass, entry, address, device_id)

    # One connection attempt up front so a heater that is out of range shows
    # as "retrying" rather than silently producing unavailable entities.
    await coordinator.async_config_entry_first_refresh()

    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = coordinator
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(_async_update_listener))
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    unloaded = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unloaded:
        hass.data[DOMAIN].pop(entry.entry_id, None)
    return unloaded


async def _async_update_listener(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Reload when options change.

    The device's unit family (°C / °F / power level) decides which entities
    exist, so a change there needs a reload rather than live mutation.
    """
    await hass.config_entries.async_reload(entry.entry_id)
