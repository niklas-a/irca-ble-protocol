"""Bleak client for IRCA / Zoppas heaters.

Designed for **transient** use: connect, do the work, disconnect. The heater
accepts one connection at a time and hangs up on idle links by itself, so
holding a connection open is both antisocial and fragile. See
docs/BUILDING_AN_INTEGRATION.md §4.

    async with IrcaClient(ble_device) as c:
        await c.set_mode(Mode.COMFORT)
        status = await c.refresh()        # same connection, no reconnect
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any, Optional

from bleak import BleakClient

from . import protocol as P
from .const import COMMAND_TIMEOUT, CONNECT_TIMEOUT

_LOGGER = logging.getLogger(__name__)

try:  # Home Assistant ships this; standalone use does not require it.
    from bleak_retry_connector import (
        BleakClientWithServiceCache,
        establish_connection,
    )

    _HAS_RETRY_CONNECTOR = True
except ImportError:  # pragma: no cover - exercised only outside HA
    _HAS_RETRY_CONNECTOR = False


class IrcaError(Exception):
    """A command was rejected, timed out, or the device could not be reached."""


class IrcaCommandRejected(IrcaError):
    """The device replied, but with a non-OK status."""

    def __init__(self, result: P.Result):
        self.result = result
        super().__init__(
            f"device rejected command: {result.describe()}"
        )


class IrcaClient:
    """One short-lived conversation with a heater."""

    def __init__(
        self,
        ble_device: Any,
        device_id: Optional[str] = None,
        *,
        name: str = "irca",
    ) -> None:
        self._ble_device = ble_device
        self._device_id = device_id
        self._name = name
        self._client: Optional[BleakClient] = None
        # The device drops overlapping GATT operations, exactly as the vendor
        # app's semaphore implies, so only one command is ever in flight.
        self._lock = asyncio.Lock()
        self._seq = 0
        self._pending: dict[int, asyncio.Future] = {}
        self.status: Optional[P.Status] = None
        self.model: Optional[str] = None
        self.serial: Optional[str] = None
        self.firmware: Optional[str] = None

    # ---------------------------------------------------------------- setup
    async def __aenter__(self) -> "IrcaClient":
        await self.connect()
        return self

    async def __aexit__(self, *exc: Any) -> None:
        await self.disconnect()

    @property
    def is_connected(self) -> bool:
        return self._client is not None and self._client.is_connected

    async def connect(self) -> None:
        if self.is_connected:
            return
        if _HAS_RETRY_CONNECTOR:
            # Caches the GATT service table per address, so repeat transient
            # connections skip discovery entirely.
            self._client = await establish_connection(
                BleakClientWithServiceCache,
                self._ble_device,
                self._name,
            )
        else:
            self._client = BleakClient(self._ble_device, timeout=CONNECT_TIMEOUT)
            await self._client.connect()

        if self._client.services.get_service(P.SERVICE_UUID) is None:
            await self.disconnect()
            raise IrcaError(
                f"{P.SERVICE_UUID} not present - this is not an IRCA heater"
            )

        await self._client.start_notify(P.CHAR_STATUS, self._on_status)
        await self._client.start_notify(P.CHAR_RESULT, self._on_result)

        if self._device_id:
            # AUTH_DEVICE is not enforced by tested firmware (spec §5.1), so a
            # rejection is informational: carry on and let the real command
            # fail if it is going to.
            try:
                await self._command(P.cmd_auth(self._device_id, self._next_seq()))
            except IrcaError as err:
                _LOGGER.info("AUTH_DEVICE not accepted (%s); continuing", err)

    async def disconnect(self) -> None:
        client, self._client = self._client, None
        for fut in self._pending.values():
            if not fut.done():
                fut.cancel()
        self._pending.clear()
        if client is not None:
            try:
                await client.disconnect()
            except Exception:  # pragma: no cover - teardown is best-effort
                _LOGGER.debug("error during disconnect", exc_info=True)

    # ------------------------------------------------------------ internals
    def _next_seq(self) -> int:
        self._seq = (self._seq + 1) & 0xFF
        return self._seq

    def _on_status(self, _char: Any, data: bytearray) -> None:
        self.status = P.parse_status(bytes(data))

    def _on_result(self, _char: Any, data: bytearray) -> None:
        result = P.parse_result(bytes(data))
        # Match on the echoed sequence (byte 2), not the opcode. Matching on
        # opcode alone breaks as soon as two commands of a type overlap.
        fut = self._pending.pop(result.seq, None)
        if fut is not None and not fut.done():
            fut.set_result(result)

    async def _command(self, frame: bytes) -> P.Result:
        if not P.verify_frame(frame):
            raise IrcaError("refusing to send a frame that fails its own checksum")
        if not self.is_connected:
            raise IrcaError("not connected")

        seq = frame[1]
        async with self._lock:
            loop = asyncio.get_running_loop()
            fut: asyncio.Future = loop.create_future()
            self._pending[seq] = fut
            try:
                await self._client.write_gatt_char(P.CHAR_CMD, frame, response=True)
                result = await asyncio.wait_for(fut, COMMAND_TIMEOUT)
            except asyncio.TimeoutError as err:
                raise IrcaError(
                    f"no RESULT for {P.Action(frame[0]).name} within "
                    f"{COMMAND_TIMEOUT:.0f}s"
                ) from err
            finally:
                self._pending.pop(seq, None)

        if not result.ok:
            raise IrcaCommandRejected(result)
        return result

    # ------------------------------------------------------------- commands
    async def refresh(self) -> P.Status:
        """Ask for a STATUS notification and return the parsed result.

        The device never pushes STATUS unsolicited, so this is the only way to
        learn anything (spec §1.2).
        """
        self.status = None
        await self._command(P.cmd_refresh_status(self._next_seq()))
        for _ in range(20):                       # STATUS arrives just after RESULT
            if self.status is not None:
                return self.status
            await asyncio.sleep(0.05)
        # Fall back to a direct read; STATUS is readable as well as notifiable.
        raw = await self._client.read_gatt_char(P.CHAR_STATUS)
        self.status = P.parse_status(bytes(raw))
        return self.status

    async def read_device_info(self) -> dict[str, Optional[str]]:
        async def _read(uuid: str, binary: bool = False) -> Optional[str]:
            try:
                raw = P.strip_frame(bytes(await self._client.read_gatt_char(uuid)))
            except Exception:  # pragma: no cover - optional metadata
                return None
            payload = raw.rstrip(b"\xff")
            if binary:
                return ".".join(str(b) for b in payload) or None
            return payload.decode("ascii", "replace").strip() or None

        self.model = await _read(P.CHAR_MODEL_NAME)
        self.serial = await _read(P.CHAR_SERIAL_NUMBER)
        self.firmware = await _read(P.CHAR_FIRMWARE_VERSION, binary=True)
        return {
            "model": self.model,
            "serial": self.serial,
            "firmware": self.firmware,
        }

    async def turn_on(self) -> None:
        """SET_ON resumes the *stored* mode, not a neutral state (spec §12.3).

        Callers must re-read status rather than assuming anything.
        """
        await self._command(P.cmd_on(self._next_seq()))

    async def turn_off(self) -> None:
        await self._command(P.cmd_off(self._next_seq()))

    async def set_mode(self, mode: P.Mode) -> None:
        await self._command(P.cmd_set_mode(mode, self._next_seq()))

    async def set_manual_setpoint(self, value: float, mode_settings: int) -> None:
        await self._command(
            P.cmd_set_setpoint(P.Action.SET_TEMP_MANUAL, value,
                               mode_settings, self._next_seq())
        )

    async def set_preset_setpoint(
        self, action: P.Action, value: float, mode_settings: int
    ) -> None:
        if action not in (
            P.Action.SET_TEMP_ECO,
            P.Action.SET_TEMP_COMFORT,
            P.Action.SET_TEMP_ANTIFREEZE,
        ):
            raise ValueError(f"{action!r} is not a preset setpoint")
        await self._command(
            P.cmd_set_setpoint(action, value, mode_settings, self._next_seq())
        )

    async def set_child_lock(self, locked: bool) -> None:
        await self._command(P.cmd_set_lock(locked, self._next_seq()))

    async def set_boost_hours(self, hours: int) -> None:
        await self._command(P.cmd_set_boost_hours(hours, self._next_seq()))

    # FACTORY_RESET (0x16) is intentionally absent. There is no safe way to
    # surface it in a Home Assistant UI, and it is one opcode away from
    # SET_LOCK.
