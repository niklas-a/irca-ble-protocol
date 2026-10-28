"""Constants for the IRCA BLE Heater integration."""
from __future__ import annotations

from homeassistant.const import Platform

DOMAIN = "irca_ble"

# CONF_ADDRESS comes from homeassistant.const; only this one is ours.
CONF_DEVICE_ID = "device_id"

MANUFACTURER = "IRCA / Zoppas"

# climate is loaded too, but only creates an entity on Celsius/Fahrenheit
# units; POWER units get number entities instead. See entity docs.
PLATFORMS: list[Platform] = [
    Platform.BINARY_SENSOR,
    Platform.CLIMATE,
    Platform.NUMBER,
    Platform.SELECT,
    Platform.SENSOR,
    Platform.SWITCH,
]
