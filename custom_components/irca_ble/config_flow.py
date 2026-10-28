"""Config flow for the IRCA BLE Heater integration."""
from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol
from homeassistant.components.bluetooth import (
    BluetoothServiceInfoBleak,
    async_discovered_service_info,
)
from homeassistant.config_entries import ConfigFlow, ConfigFlowResult
from homeassistant.const import CONF_ADDRESS

from .const import CONF_DEVICE_ID, DOMAIN
from .ircable import protocol as P
from .ircable.client import IrcaClient, IrcaError
from .ircable.const import KNOWN_LOCAL_NAMES

_LOGGER = logging.getLogger(__name__)


def _looks_like_heater(info: BluetoothServiceInfoBleak) -> bool:
    """Cheap pre-filter on the advertisement.

    The device does not advertise its service UUID (spec §1.1.2), so the local
    name is all we have to go on. It is a weak signal, which is why the flow
    always confirms by connecting before creating an entry.
    """
    name = (info.name or "").lower()
    return any(name.startswith(known) for known in KNOWN_LOCAL_NAMES)


class IrcaConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle discovery and manual setup."""

    VERSION = 1

    def __init__(self) -> None:
        self._discovered: dict[str, str] = {}
        self._address: str | None = None
        self._title: str | None = None

    # ------------------------------------------------------- bluetooth
    async def async_step_bluetooth(
        self, discovery_info: BluetoothServiceInfoBleak
    ) -> ConfigFlowResult:
        """Handle an automatically discovered device."""
        await self.async_set_unique_id(discovery_info.address)
        self._abort_if_unique_id_configured()

        if not _looks_like_heater(discovery_info):
            return self.async_abort(reason="not_supported")

        self._address = discovery_info.address
        self._title = discovery_info.name or discovery_info.address
        self.context["title_placeholders"] = {"name": self._title}
        return await self.async_step_confirm()

    async def async_step_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Confirm, verifying the device really speaks this protocol."""
        assert self._address is not None

        if user_input is not None:
            error = await self._async_verify(self._address)
            if error:
                return self.async_show_form(
                    step_id="confirm",
                    errors={"base": error},
                    description_placeholders={"name": self._title or self._address},
                    data_schema=vol.Schema(
                        {vol.Optional(CONF_DEVICE_ID, default=""): str}
                    ),
                )
            return self.async_create_entry(
                title=self._title or self._address,
                data={
                    CONF_ADDRESS: self._address,
                    CONF_DEVICE_ID: (user_input.get(CONF_DEVICE_ID) or "").strip(),
                },
            )

        return self.async_show_form(
            step_id="confirm",
            description_placeholders={"name": self._title or self._address},
            data_schema=vol.Schema({vol.Optional(CONF_DEVICE_ID, default=""): str}),
        )

    # ------------------------------------------------------------ manual
    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Pick from the devices Bluetooth has seen."""
        if user_input is not None:
            address = user_input[CONF_ADDRESS]
            await self.async_set_unique_id(address, raise_on_progress=False)
            self._abort_if_unique_id_configured()

            error = await self._async_verify(address)
            if error:
                return self.async_show_form(
                    step_id="user",
                    data_schema=self._user_schema(),
                    errors={"base": error},
                )
            return self.async_create_entry(
                title=self._discovered.get(address, address),
                data={
                    CONF_ADDRESS: address,
                    CONF_DEVICE_ID: (user_input.get(CONF_DEVICE_ID) or "").strip(),
                },
            )

        current = self._async_current_ids()
        self._discovered = {
            info.address: f"{info.name or 'Unknown'} ({info.address})"
            for info in async_discovered_service_info(self.hass, connectable=True)
            if info.address not in current
        }
        if not self._discovered:
            return self.async_abort(reason="no_devices_found")

        return self.async_show_form(step_id="user", data_schema=self._user_schema())

    def _user_schema(self) -> vol.Schema:
        # Every connectable device is offered, not just name matches: the
        # advertisement is a weak signal and siblings of this product may use
        # other names. The connect check below is what actually decides.
        return vol.Schema(
            {
                vol.Required(CONF_ADDRESS): vol.In(self._discovered),
                vol.Optional(CONF_DEVICE_ID, default=""): str,
            }
        )

    # ------------------------------------------------------------ verify
    async def _async_verify(self, address: str) -> str | None:
        """Connect and check the Zoppas service is present.

        Returns an error key, or None on success.
        """
        from homeassistant.components import bluetooth

        device = bluetooth.async_ble_device_from_address(
            self.hass, address, connectable=True
        )
        if device is None:
            return "cannot_connect"
        try:
            async with IrcaClient(device, name="irca-setup") as client:
                await client.refresh()
        except IrcaError as err:
            _LOGGER.debug("verification of %s failed: %s", address, err)
            if P.SERVICE_UUID in str(err):
                return "not_supported"
            return "cannot_connect"
        except Exception as err:  # noqa: BLE001 - bleak raises broadly
            _LOGGER.debug("verification of %s errored: %s", address, err)
            return "cannot_connect"
        return None
