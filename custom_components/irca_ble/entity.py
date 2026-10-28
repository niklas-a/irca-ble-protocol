"""Shared entity base for the IRCA BLE Heater integration."""
from __future__ import annotations

from homeassistant.helpers.device_registry import CONNECTION_BLUETOOTH, DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, MANUFACTURER
from .coordinator import IrcaCoordinator
from .ircable import protocol as P


class IrcaEntity(CoordinatorEntity[IrcaCoordinator]):
    """Common device info, availability and naming."""

    _attr_has_entity_name = True

    def __init__(self, coordinator: IrcaCoordinator, key: str) -> None:
        super().__init__(coordinator)
        self._key = key
        self._attr_unique_id = f"{coordinator.address}_{key}"

    @property
    def device_info(self) -> DeviceInfo:
        return DeviceInfo(
            identifiers={(DOMAIN, self.coordinator.address)},
            connections={(CONNECTION_BLUETOOTH, self.coordinator.address)},
            manufacturer=MANUFACTURER,
            model=self.coordinator.model or "BLE heater",
            name=getattr(self.coordinator.entry, "title", None) or "Towel rail",
            serial_number=self.coordinator.serial,
            sw_version=self.coordinator.firmware,
        )

    @property
    def status(self) -> P.Status | None:
        return self.coordinator.data

    @property
    def available(self) -> bool:
        return super().available and self.coordinator.data is not None

    # ------------------------------------------------------------------
    @property
    def _mode_settings(self) -> int:
        """Which value family the device is using (spec §6).

        Defaults to POWER rather than Celsius: guessing Celsius on a power-level
        unit silently produces plausible-but-wrong temperatures, which is the
        worse failure.
        """
        status = self.status
        if status is None or status.mode_settings is None:
            return P.MS_POWER
        return status.mode_settings

    @property
    def _is_on(self) -> bool:
        status = self.status
        return bool(
            status is not None
            and status.mode is not None
            and status.mode != P.Mode.OFF
        )
