"""Coordinator for the IRCA BLE Heater integration.

Transient connections throughout: connect, do the work, disconnect. The heater
accepts one connection at a time and hangs up on idle links by itself, so a
persistent link would both lock the owner out of the vendor app and fight the
firmware. See docs/BUILDING_AN_INTEGRATION.md §4.
"""
from __future__ import annotations

import logging
from datetime import timedelta
from typing import Any, Callable, Optional

from homeassistant.components import bluetooth
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .ircable import protocol as P
from .ircable.client import IrcaClient, IrcaError
from .ircable.const import DEFAULT_POLL_INTERVAL
from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)


class IrcaCoordinator(DataUpdateCoordinator[P.Status]):
    """Polls the heater and funnels every command through one connection each."""

    def __init__(
        self,
        hass: HomeAssistant,
        entry: Any,
        address: str,
        device_id: Optional[str] = None,
    ) -> None:
        super().__init__(
            hass,
            _LOGGER,
            name=f"{DOMAIN} {address}",
            update_interval=timedelta(seconds=DEFAULT_POLL_INTERVAL),
        )
        # Held explicitly rather than relying on DataUpdateCoordinator's own
        # config_entry attribute, which has moved around across HA versions.
        self.entry = entry
        self.address = address
        self.device_id = device_id
        self.model: Optional[str] = None
        self.serial: Optional[str] = None
        self.firmware: Optional[str] = None
        self._info_read = False

    # ------------------------------------------------------------------
    def _ble_device(self) -> Any:
        device = bluetooth.async_ble_device_from_address(
            self.hass, self.address, connectable=True
        )
        if device is None:
            raise UpdateFailed(
                f"{self.address} is not in range of any Bluetooth adapter "
                "or proxy"
            )
        return device

    async def _async_update_data(self) -> P.Status:
        try:
            async with IrcaClient(
                self._ble_device(), self.device_id, name=self.name
            ) as client:
                status = await client.refresh()
                # Identity never changes; read it once and keep it.
                if not self._info_read:
                    info = await client.read_device_info()
                    self.model = info["model"]
                    self.serial = info["serial"]
                    self.firmware = info["firmware"]
                    self._info_read = True
                return status
        except IrcaError as err:
            raise UpdateFailed(str(err)) from err
        except Exception as err:  # bleak raises a wide variety
            raise UpdateFailed(f"error talking to {self.address}: {err}") from err

    # ------------------------------------------------------------------
    async def async_execute(
        self, action: Callable[[IrcaClient], Any], *, label: str
    ) -> None:
        """Run a command and read the result back over the same connection.

        Never render an optimistic state: SET_ON resumes the device's stored
        mode rather than a neutral one (spec §12.3), so what the user gets is
        not always what a naive UI would predict. Reconnecting just to confirm
        would double the latency, so the read-back shares this connection.
        """
        try:
            async with IrcaClient(
                self._ble_device(), self.device_id, name=self.name
            ) as client:
                await action(client)
                status = await client.refresh()
        except (IrcaError, UpdateFailed) as err:
            raise HomeAssistantError(f"{label} failed: {err}") from err
        except Exception as err:  # bleak raises a wide variety
            raise HomeAssistantError(f"{label} failed: {err}") from err

        # Push the real device state out without scheduling another connection.
        self.async_set_updated_data(status)
