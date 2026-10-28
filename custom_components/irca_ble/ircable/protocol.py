"""Pure-Python implementation of the Olle / IRCA / Zoppas BLE towel-rail protocol.

No Bluetooth dependencies -- this module only builds and parses byte frames, so
it can be unit-tested offline and reused unchanged by a Home Assistant
integration.

Protocol recovered from Olle Connect v3.6 (com.ecodomesticheating.olle.app),
BLE layer in com.sysdata.zoppas.blepoc.

Frame (always exactly 20 bytes, written to the CMD characteristic):

    byte  0      opcode   (BLEAction)
    byte  1      sequence id (echoed back in the RESULT notification)
    bytes 2..18  payload, right-padded with 0xFF
    byte  19     checksum = XOR of bytes 0..18
"""
from __future__ import annotations

import datetime
from enum import IntEnum
from typing import NamedTuple, Optional

# ---------------------------------------------------------------------------
# GATT
# ---------------------------------------------------------------------------
SERVICE_UUID = "35ba1523-94f5-9052-4cd4-f102b6580adf"

CHAR_STATUS = "35ba1524-94f5-9052-4cd4-f102b6580adf"   # notify
CHAR_CMD = "35ba1525-94f5-9052-4cd4-f102b6580adf"      # write
CHAR_RESULT = "35ba1526-94f5-9052-4cd4-f102b6580adf"   # notify
CHAR_MULTIPART_DATA = "35ba1527-94f5-9052-4cd4-f102b6580adf"
CHAR_MULTIPART_RESULT = "35ba1528-94f5-9052-4cd4-f102b6580adf"
CHAR_MODEL_NAME = "35ba1529-94f5-9052-4cd4-f102b6580adf"
CHAR_SERIAL_NUMBER = "35ba1530-94f5-9052-4cd4-f102b6580adf"
CHAR_FIRMWARE_VERSION = "35ba1531-94f5-9052-4cd4-f102b6580adf"
CHAR_DEVICE_NAME = "35ba1532-94f5-9052-4cd4-f102b6580adf"

NOTIFY_CHARS = [
    CHAR_STATUS, CHAR_RESULT, CHAR_MULTIPART_RESULT,
    CHAR_MODEL_NAME, CHAR_SERIAL_NUMBER, CHAR_FIRMWARE_VERSION,
]

FRAME_LEN = 20
PAD = 0xFF


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------
class Action(IntEnum):
    REGISTER_DEVICE = 0x01
    SET_MODE = 0x02
    SET_TEMP_MANUAL = 0x03
    SET_TEMP_ECO = 0x04
    SET_TEMP_COMFORT = 0x05
    SET_TEMP_ANTIFREEZE = 0x06
    SET_PERIOD_BOOST = 0x07
    REFRESH_STATUS = 0x08
    READ_STATS = 0x09
    READ_CHRONO = 0x0A
    SET_CHRONO = 0x0B
    SET_DATE = 0x0C
    SET_ON = 0x0D
    SET_OFF = 0x0E
    READ_HOLIDAY = 0x0F
    SET_HOLIDAY = 0x10
    AUTH_DEVICE = 0x11
    SET_MODE_SETTINGS = 0x12
    READ_DIAGNOSTICS = 0x13
    SET_LOCK = 0x15
    FACTORY_RESET = 0x16
    SET_OPENWINDOW = 0x17
    READ_FIRMWARE_VERSION = 0xFA
    CONNECTION_CHANGE = 0xFB
    SET_DEVICE_NAME = 0xFC
    READ_DEVICE_NAME = 0xFD
    READ_MODEL_NAME = 0xFE
    READ_SERIAL_NUMBER = 0xFF


class Mode(IntEnum):
    """ModoOperativo."""
    OFF = 0          # SPENTO
    BOOST = 1
    COMFORT = 2
    ECO = 3
    ANTIFREEZE = 4
    SCHEDULE = 5     # PROGRAMMA
    MANUAL = 6       # MANUALE


class CommandStatus(IntEnum):
    ERR_INVALID_CRC = 1
    ERR_INVALID_DATA = 2
    ERR_UNABLE_TO_UPDATE = 3
    OK = 4                            # ERR_OPERATION_PERFORMED
    ERR_DEVICEID_NOTSUPPORTED = 5
    ERR_DEVICEID_ALREADYREGISTERED = 6
    ERR_OPERATION_UNDEFINED = 0xFF


class Alarm(IntEnum):
    OK = 0
    ERR_NTC = 1
    ERR_LOAD = 2
    ERR_DATE = 3
    ERR_EEPROM = 4


class WindowDetection(IntEnum):
    DISABLED = 0
    TRIGGER_OFF_WINDOW_CLOSED = 1
    TRIGGER_ON_WINDOW_CLOSED = 2
    TRIGGER_ON_WINDOW_OPENED = 3


# ModeSettings / unit selector
MS_POWER = 0x55
MS_CELSIUS = 0xAA
MS_FAHRENHEIT = 0xA5

# Sentinels that replace the setpoint byte in STATUS
SENTINEL_ANTIFREEZE = 0xFD
SENTINEL_STANDBY = 0xFE

# Documented UI limits (Celsius build)
CELSIUS_MIN, CELSIUS_MAX, CELSIUS_STEP = 15.0, 30.0, 0.5
FAHRENHEIT_MIN, FAHRENHEIT_MAX = 45, 90
BOOST_MIN_H, BOOST_MAX_H = 2, 10


# ---------------------------------------------------------------------------
# Encoding helpers
# ---------------------------------------------------------------------------
def checksum(data: bytes) -> int:
    """XOR of every byte (HexUtils.checksum)."""
    c = 0
    for b in data:
        c ^= b
    return c & 0xFF


def encode_temp(value: float, celsius: bool = True) -> int:
    """Encode a setpoint to its single wire byte.

    Celsius is carried in tenths of a degree with a -70 bias:
        21.5 degC -> 215 -> 215 - 70 = 145 (0x91)
    Fahrenheit is carried as whole degrees with no bias.
    """
    if celsius:
        raw = int(round(value * 10))
        b = raw - 70
    else:
        b = int(round(value))
    if not 0 <= b <= 255:
        raise ValueError(
            f"temperature {value} encodes to {b}, outside a single byte"
        )
    return b


def decode_temp(byte_val: int, celsius: bool = True) -> float:
    """Inverse of encode_temp (HexUtils.byteToShortTemperature)."""
    if celsius:
        return (byte_val + 70) / 10.0
    return float(byte_val)


# --- unit-family aware API -------------------------------------------------
# Byte 9 of STATUS says which of three families the device is using, and the
# setpoint bytes mean completely different things in each. Prefer these over
# the celsius-boolean helpers above: passing the raw mode_settings byte makes
# it impossible to forget that POWER units exist.

def encode_setpoint(value: float, mode_settings: int) -> int:
    """Encode a setpoint for whichever family the device reports.

    CELSIUS  -> tenths of a degree, biased by -70
    FAHRENHEIT -> whole degrees, no bias
    POWER    -> abstract level 1..10, no bias
    """
    if mode_settings == MS_CELSIUS:
        b = int(round(value * 10)) - 70
    else:
        b = int(round(value))
    if not 0 <= b <= 255:
        raise ValueError(
            f"setpoint {value} in family 0x{mode_settings:02X} "
            f"encodes to {b}, outside a single byte"
        )
    return b


def decode_setpoint(byte_val: int, mode_settings: int) -> float:
    """Inverse of encode_setpoint."""
    if mode_settings == MS_CELSIUS:
        return (byte_val + 70) / 10.0
    return float(byte_val)


def cmd_set_setpoint(action: "Action", value: float,
                     mode_settings: int, seq: int = 0) -> bytes:
    """Build any of the four setpoint commands for the device's own family."""
    if action not in (Action.SET_TEMP_MANUAL, Action.SET_TEMP_ECO,
                      Action.SET_TEMP_COMFORT, Action.SET_TEMP_ANTIFREEZE):
        raise ValueError(f"{action!r} is not a setpoint command")
    return build_frame(action, bytes([encode_setpoint(value, mode_settings)]), seq)


def build_frame(action: Action, payload: bytes = b"", seq: int = 0) -> bytes:
    """Assemble a 20-byte command frame."""
    if len(payload) > 17:
        raise ValueError(f"payload {len(payload)}B exceeds the 17B frame budget")
    body = bytearray([int(action) & 0xFF, seq & 0xFF])
    body += payload
    body += bytes([PAD] * (19 - len(body)))
    body.append(checksum(bytes(body)))
    assert len(body) == FRAME_LEN
    return bytes(body)


def verify_frame(frame: bytes) -> bool:
    return len(frame) == FRAME_LEN and checksum(frame[:19]) == frame[19]


# ---------------------------------------------------------------------------
# Command builders
# ---------------------------------------------------------------------------
def cmd_auth(device_id: str, seq: int = 0) -> bytes:
    """AUTH_DEVICE -- only the first 16 ASCII chars of device_id are sent."""
    raw = device_id.encode("utf-8")[:16]
    raw = raw + bytes([PAD] * (16 - len(raw)))
    return build_frame(Action.AUTH_DEVICE, raw, seq)


def cmd_register(device_id: str, seq: int = 0) -> bytes:
    """REGISTER_DEVICE -- same payload shape as AUTH_DEVICE."""
    raw = device_id.encode("utf-8")[:16]
    raw = raw + bytes([PAD] * (16 - len(raw)))
    return build_frame(Action.REGISTER_DEVICE, raw, seq)


def cmd_on(seq: int = 0) -> bytes:
    return build_frame(Action.SET_ON, b"", seq)


def cmd_off(seq: int = 0) -> bytes:
    return build_frame(Action.SET_OFF, b"", seq)


def cmd_refresh_status(seq: int = 0) -> bytes:
    return build_frame(Action.REFRESH_STATUS, b"", seq)


def cmd_set_mode(mode: Mode, seq: int = 0) -> bytes:
    return build_frame(Action.SET_MODE, bytes([int(mode)]), seq)


def cmd_set_temp_manual(value: float, celsius: bool = True, seq: int = 0) -> bytes:
    return build_frame(Action.SET_TEMP_MANUAL,
                       bytes([encode_temp(value, celsius)]), seq)


def cmd_set_temp_eco(value: float, celsius: bool = True, seq: int = 0) -> bytes:
    return build_frame(Action.SET_TEMP_ECO,
                       bytes([encode_temp(value, celsius)]), seq)


def cmd_set_temp_comfort(value: float, celsius: bool = True, seq: int = 0) -> bytes:
    return build_frame(Action.SET_TEMP_COMFORT,
                       bytes([encode_temp(value, celsius)]), seq)


def cmd_set_temp_antifreeze(value: float, celsius: bool = True, seq: int = 0) -> bytes:
    return build_frame(Action.SET_TEMP_ANTIFREEZE,
                       bytes([encode_temp(value, celsius)]), seq)


def cmd_set_level_manual(level: int, seq: int = 0) -> bytes:
    """Manual setpoint on a POWER-mode ("North Europe") unit: raw level 1-10.

    POWER-mode units carry an abstract power level, not a temperature, so no
    bias is applied -- this is shortToByteTemperature(level, isCelsius=false).
    """
    if not 1 <= level <= 10:
        raise ValueError(f"power level {level} outside 1..10")
    return build_frame(Action.SET_TEMP_MANUAL, bytes([level]), seq)


def cmd_set_level(action: Action, level: int, seq: int = 0) -> bytes:
    """Eco/comfort/antifreeze setpoint on a POWER-mode unit."""
    if not 1 <= level <= 10:
        raise ValueError(f"power level {level} outside 1..10")
    return build_frame(action, bytes([level]), seq)


def cmd_set_boost_hours(hours: int, seq: int = 0) -> bytes:
    """SET_PERIOD_BOOST -- the wire byte is whole hours."""
    return build_frame(Action.SET_PERIOD_BOOST, bytes([hours & 0xFF]), seq)


def cmd_set_lock(locked: bool, seq: int = 0) -> bytes:
    """SET_LOCK -- 0x55 locks, 0xAA unlocks (not 1/0)."""
    return build_frame(Action.SET_LOCK,
                       bytes([MS_POWER if locked else MS_CELSIUS]), seq)


def cmd_set_window_detection(enabled: bool, seq: int = 0) -> bytes:
    return build_frame(Action.SET_OPENWINDOW, bytes([1 if enabled else 0]), seq)


def cmd_set_mode_settings(power: bool, celsius: bool, seq: int = 0) -> bytes:
    """SET_MODE_SETTINGS -- selects POWER / CELSIUS / FAHRENHEIT display mode."""
    if power:
        b = MS_POWER
    else:
        b = MS_CELSIUS if celsius else MS_FAHRENHEIT
    return build_frame(Action.SET_MODE_SETTINGS, bytes([b]), seq)


def cmd_set_date(when: Optional[datetime.datetime] = None, seq: int = 0) -> bytes:
    """SET_DATE -- [century, year%100, month(1-12), day, hour, minute, second]."""
    when = when or datetime.datetime.now()
    century, yy = divmod(when.year, 100)
    payload = bytes([century, yy, when.month, when.day,
                     when.hour, when.minute, when.second])
    return build_frame(Action.SET_DATE, payload, seq)


def cmd_read_model_name(seq: int = 0) -> bytes:
    return build_frame(Action.READ_MODEL_NAME, b"", seq)


def cmd_read_serial_number(seq: int = 0) -> bytes:
    return build_frame(Action.READ_SERIAL_NUMBER, b"", seq)


def cmd_read_firmware_version(seq: int = 0) -> bytes:
    return build_frame(Action.READ_FIRMWARE_VERSION, b"", seq)


# ---------------------------------------------------------------------------
# Status parsing
# ---------------------------------------------------------------------------
class Status(NamedTuple):
    setpoint: Optional[float]
    setpoint_sentinel: Optional[str]
    cip: Optional[int]
    mode: Optional[int]
    eco: Optional[float]
    comfort: Optional[float]
    antifreeze: Optional[float]
    boost_hours: Optional[int]
    alarm: Optional[int]
    mode_settings: Optional[int]
    celsius: bool
    holiday: Optional[bool]
    boost_remain_raw: Optional[bytes]
    lock: Optional[bool]
    window_detection: Optional[int]
    raw: bytes

    @property
    def unit(self) -> str:
        """Display unit implied by the device's mode_settings byte."""
        if self.mode_settings == MS_CELSIUS:
            return "degC"
        if self.mode_settings == MS_FAHRENHEIT:
            return "degF"
        if self.mode_settings == MS_POWER:
            return "level"      # abstract 1-10 power level ("North Europe")
        return "?"

    @property
    def is_power_level(self) -> bool:
        return self.mode_settings == MS_POWER

    def _fmt(self, v: float) -> str:
        """Render a setpoint with the unit the device is actually using."""
        if self.is_power_level:
            return f"L{v:.0f}"          # power level 1-10, no decimals
        return f"{v:.1f}{self.unit}"

    def describe(self) -> str:
        parts = []
        if self.setpoint_sentinel:
            parts.append(f"setpoint={self.setpoint_sentinel}")
        elif self.setpoint is not None:
            parts.append(f"setpoint={self._fmt(self.setpoint)}")
        if self.mode is not None:
            try:
                parts.append(f"mode={Mode(self.mode).name}")
            except ValueError:
                parts.append(f"mode=0x{self.mode:02X}?")
        for nm, v in (("eco", self.eco), ("comfort", self.comfort),
                      ("antifreeze", self.antifreeze)):
            if v is not None:
                parts.append(f"{nm}={self._fmt(v)}")
        if self.boost_hours is not None:
            parts.append(f"boost={self.boost_hours}h")
        if self.cip is not None:
            parts.append(f"CIP={self.cip}")
        if self.alarm is not None:
            try:
                parts.append(f"alarm={Alarm(self.alarm).name}")
            except ValueError:
                parts.append(f"alarm=0x{self.alarm:02X}?")
        if self.holiday is not None:
            parts.append(f"holiday={'on' if self.holiday else 'off'}")
        if self.lock is not None:
            parts.append(f"lock={'on' if self.lock else 'off'}")
        if self.window_detection is not None:
            try:
                parts.append(f"window={WindowDetection(self.window_detection).name}")
            except ValueError:
                parts.append(f"window=0x{self.window_detection:02X}?")
        return "  ".join(parts)


def strip_frame(data: bytes) -> bytes:
    """Drop the trailing XOR checksum if this looks like a full 20-byte frame.

    Real hardware returns STATUS/RESULT/identity values as complete 20-byte
    frames (19 payload bytes + checksum), but notifications may also arrive as
    bare payloads, so accept both.
    """
    if len(data) == FRAME_LEN and checksum(data[:19]) == data[19]:
        return data[:19]
    return data


def parse_status(data: bytes) -> Status:
    """Port of DeviceStatus.fromBytesArray -- every field is length-guarded."""
    data = strip_frame(data)
    n = len(data)

    def at(i):
        return data[i] if n > i else None

    ms = at(9)
    celsius = (ms == MS_CELSIUS)

    setpoint = sentinel = None
    if n >= 1:
        b = data[0]
        if b == SENTINEL_ANTIFREEZE:
            sentinel = "ANTIFREEZE"
        elif b == SENTINEL_STANDBY:
            sentinel = "STANDBY"
        else:
            setpoint = decode_temp(b, celsius)

    cip = int.from_bytes(data[1:3], "big") if n >= 3 else None

    return Status(
        setpoint=setpoint,
        setpoint_sentinel=sentinel,
        cip=cip,
        mode=at(3),
        eco=decode_temp(data[4], celsius) if n >= 5 else None,
        comfort=decode_temp(data[5], celsius) if n >= 6 else None,
        antifreeze=decode_temp(data[6], celsius) if n >= 7 else None,
        boost_hours=at(7),
        alarm=at(8),
        mode_settings=ms,
        celsius=celsius,
        holiday=(data[10] != 0) if n >= 11 else None,
        boost_remain_raw=bytes(data[11:13]) if n >= 13 else None,
        lock=(data[13] > 0) if n >= 14 else None,
        window_detection=at(14),
        raw=bytes(data),
    )


class Result(NamedTuple):
    status: Optional[int]
    action: Optional[int]
    seq: Optional[int]
    payload: bytes
    raw: bytes

    @property
    def ok(self) -> bool:
        return self.status == CommandStatus.OK

    def describe(self) -> str:
        try:
            s = CommandStatus(self.status).name
        except ValueError:
            s = f"0x{self.status:02X}?" if self.status is not None else "?"
        parts = [f"status={s}"]
        if self.action is not None:
            try:
                parts.append(f"action={Action(self.action).name}")
            except ValueError:
                parts.append(f"action=0x{self.action:02X}?")
        if self.seq is not None:
            parts.append(f"seq=0x{self.seq:02X}")
        if self.payload:
            parts.append(f"payload={self.payload.hex()}")
        return " ".join(parts)


def parse_result(data: bytes) -> Result:
    """RESULT notification: [status][opcode echo][seq echo][payload...].

    Verified against hardware (fw 3.2.0): sending opcode 0x08 with seq 0x01
    returns `04 08 01 ...`. The vendor app agrees -- DeviceBLEManager does
    `BLEAction.fromByte(bArr[1])` -- even though its own ResponseBuilder then
    mislabels bArr[1] as the sequence id.
    """
    data = strip_frame(data)
    return Result(
        status=data[0] if len(data) >= 1 else None,
        action=data[1] if len(data) >= 2 else None,
        seq=data[2] if len(data) >= 3 else None,
        payload=bytes(data[3:]),
        raw=bytes(data),
    )
