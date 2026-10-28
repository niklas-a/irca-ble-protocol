"""A fake IRCA heater that speaks the real protocol over a fake GATT client.

This models the firmware's observed behaviour rather than merely echoing what
the client sends, so the tests exercise the parts that actually bit us:

* RESULT is [status][opcode echo][seq echo], not [status][seq]
* SET_ON resumes the stored mode instead of a neutral state
* STATUS only ever arrives in response to REFRESH_STATUS
* every frame carries a trailing XOR checksum
"""
from __future__ import annotations

import asyncio

from ircable import protocol as P


class FakeHeater:
    """Protocol-accurate stand-in for the device."""

    def __init__(self, mode_settings: int = P.MS_POWER, *, reject: bool = False):
        self.mode_settings = mode_settings
        self.reject = reject
        self.received: list[bytes] = []

        # STATUS payload, 19 bytes, laid out per spec §6.
        self.state = bytearray([0xFF] * 19)
        self.state[0] = 0x00                       # setpoint
        self.state[1] = 0x00                       # CIP hi
        self.state[2] = 0x20                       # CIP lo  (32)
        self.state[3] = P.Mode.OFF                 # mode
        self.state[4] = self._enc(5 if mode_settings == P.MS_POWER else 18.0)
        self.state[5] = self._enc(8 if mode_settings == P.MS_POWER else 21.0)
        self.state[6] = self._enc(2 if mode_settings == P.MS_POWER else 7.0)
        self.state[7] = 0x00                       # boost hours
        self.state[8] = 0x00                       # alarm OK
        self.state[9] = mode_settings
        self.state[10] = 0x00                      # holiday
        self.state[13] = 0x00                      # lock
        self.state[14] = 0xFF                      # window: real units report 0xFF

    def _enc(self, value: float) -> int:
        return P.encode_setpoint(value, self.mode_settings)

    # ------------------------------------------------------------------
    def status_frame(self) -> bytes:
        body = bytearray(self.state)
        body.append(P.checksum(bytes(body)))
        return bytes(body)

    def _result(self, status: int, opcode: int, seq: int) -> bytes:
        body = bytearray([status, opcode, seq] + [0xFF] * 16)
        body.append(P.checksum(bytes(body)))
        return bytes(body)

    def handle(self, frame: bytes) -> tuple[bytes, bytes | None]:
        """Apply a command frame. Returns (result_frame, status_frame|None)."""
        self.received.append(bytes(frame))

        if not P.verify_frame(frame):
            return self._result(P.CommandStatus.ERR_INVALID_CRC, frame[0], frame[1]), None

        opcode, seq, payload = frame[0], frame[1], frame[2:19]

        if self.reject:
            return self._result(P.CommandStatus.ERR_INVALID_DATA, opcode, seq), None

        send_status = False
        if opcode == P.Action.REFRESH_STATUS:
            send_status = True
        elif opcode == P.Action.SET_ON:
            # Resumes the stored mode and pulls the setpoint to it.
            self.state[3] = P.Mode.COMFORT
            self.state[0] = self.state[5]
        elif opcode == P.Action.SET_OFF:
            self.state[3] = P.Mode.OFF
            self.state[0] = 0x00
        elif opcode == P.Action.SET_MODE:
            self.state[3] = payload[0]
        elif opcode == P.Action.SET_TEMP_MANUAL:
            self.state[0] = payload[0]
        elif opcode == P.Action.SET_TEMP_ECO:
            self.state[4] = payload[0]
        elif opcode == P.Action.SET_TEMP_COMFORT:
            self.state[5] = payload[0]
        elif opcode == P.Action.SET_TEMP_ANTIFREEZE:
            self.state[6] = payload[0]
        elif opcode == P.Action.SET_PERIOD_BOOST:
            self.state[7] = payload[0]
        elif opcode == P.Action.SET_LOCK:
            self.state[13] = 1 if payload[0] == 0x55 else 0
        elif opcode == P.Action.AUTH_DEVICE:
            pass
        else:
            return self._result(P.CommandStatus.ERR_OPERATION_UNDEFINED, opcode, seq), None

        result = self._result(P.CommandStatus.OK, opcode, seq)
        return result, (self.status_frame() if send_status else None)

    def read(self, uuid: str) -> bytes:
        if uuid == P.CHAR_STATUS:
            return self.status_frame()
        if uuid == P.CHAR_MODEL_NAME:
            return _text_frame(b"0000AAAABBBB")
        if uuid == P.CHAR_SERIAL_NUMBER:
            return _text_frame(b"HB000000000")
        if uuid == P.CHAR_FIRMWARE_VERSION:
            return _text_frame(bytes([3, 2, 0]))
        raise KeyError(uuid)


def _text_frame(payload: bytes) -> bytes:
    body = bytearray(payload) + bytearray([0xFF] * (19 - len(payload)))
    body.append(P.checksum(bytes(body)))
    return bytes(body)


# ---------------------------------------------------------------- transport
class _FakeServices:
    def __init__(self, present: bool):
        self._present = present

    def get_service(self, uuid: str):
        return object() if self._present else None


class FakeBleakClient:
    """Minimal stand-in for BleakClient wired to a FakeHeater."""

    def __init__(self, heater: FakeHeater, *, service_present: bool = True,
                 notify_delay: float = 0.0):
        self.heater = heater
        self.services = _FakeServices(service_present)
        self.is_connected = False
        self._notify: dict[str, callable] = {}
        self._notify_delay = notify_delay
        self.disconnect_calls = 0

    async def connect(self):
        self.is_connected = True

    async def disconnect(self):
        self.is_connected = False
        self.disconnect_calls += 1

    async def start_notify(self, uuid: str, callback):
        self._notify[uuid] = callback

    async def stop_notify(self, uuid: str):
        self._notify.pop(uuid, None)

    async def read_gatt_char(self, uuid: str) -> bytearray:
        return bytearray(self.heater.read(uuid))

    async def write_gatt_char(self, uuid: str, data: bytes, response: bool = True):
        assert uuid == P.CHAR_CMD, f"unexpected write to {uuid}"
        result, status = self.heater.handle(bytes(data))
        if self._notify_delay:
            await asyncio.sleep(self._notify_delay)
        if status is not None and P.CHAR_STATUS in self._notify:
            self._notify[P.CHAR_STATUS](None, bytearray(status))
        if P.CHAR_RESULT in self._notify:
            self._notify[P.CHAR_RESULT](None, bytearray(result))
