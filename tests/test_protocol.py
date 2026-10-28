"""Protocol-layer tests: frame shape, checksum, codecs, parsing.

Pure byte manipulation - no Bluetooth hardware, no Home Assistant.

Frames marked "captured" are verbatim from an Olle towel rail (firmware 3.2.0,
POWER variant) read over BLE on 2026-10-27. The model and serial frames are
synthetic with recomputed checksums, because the real ones identify a specific
physical unit.
"""
from __future__ import annotations

import datetime

import pytest

from ircable import protocol as P


# ----------------------------------------------------------------- framing
ALL_COMMANDS = [
    ("SET_ON", P.cmd_on(0)),
    ("SET_OFF", P.cmd_off(1)),
    ("REFRESH_STATUS", P.cmd_refresh_status(2)),
    ("SET_MODE", P.cmd_set_mode(P.Mode.COMFORT, 3)),
    ("SET_TEMP_MANUAL", P.cmd_set_temp_manual(21.5, True, 4)),
    ("SET_LOCK", P.cmd_set_lock(True, 5)),
    ("AUTH_DEVICE", P.cmd_auth("0f2a9c1e-4b77-4abc-9d01-aaaa", 6)),
    ("SET_DATE", P.cmd_set_date(datetime.datetime(2026, 10, 27, 16, 45, 30), 7)),
    ("SET_BOOST", P.cmd_set_boost_hours(4, 8)),
]


@pytest.mark.parametrize("name,frame", ALL_COMMANDS, ids=[n for n, _ in ALL_COMMANDS])
def test_every_frame_is_twenty_bytes(name, frame):
    assert len(frame) == P.FRAME_LEN


@pytest.mark.parametrize("name,frame", ALL_COMMANDS, ids=[n for n, _ in ALL_COMMANDS])
def test_every_frame_checksum_verifies(name, frame):
    assert P.verify_frame(frame), frame.hex(" ")


def test_checksum_is_xor_of_preceding_bytes():
    frame = P.cmd_on(0)
    expected = 0
    for b in frame[:19]:
        expected ^= b
    assert frame[19] == expected


def test_unused_payload_is_ff_padded():
    frame = P.cmd_on(0)
    assert all(b == 0xFF for b in frame[2:19])


def test_payload_longer_than_seventeen_bytes_is_rejected():
    with pytest.raises(ValueError):
        P.build_frame(P.Action.SET_MODE, bytes(18), 0)


def test_corrupted_frame_fails_verification():
    frame = bytearray(P.cmd_on(0))
    frame[2] ^= 0x01
    assert not P.verify_frame(bytes(frame))


# ----------------------------------------------------------------- opcodes
def test_opcode_values():
    assert P.Action.SET_ON == 0x0D
    assert P.Action.SET_OFF == 0x0E
    assert P.Action.REFRESH_STATUS == 0x08
    assert P.Action.SET_MODE == 0x02
    assert P.Action.SET_TEMP_MANUAL == 0x03
    assert P.Action.SET_LOCK == 0x15
    # One opcode away from SET_LOCK, which is exactly why nothing builds it.
    assert P.Action.FACTORY_RESET == 0x16


def test_set_lock_uses_55_and_aa_not_one_and_zero():
    assert P.cmd_set_lock(True)[2] == 0x55
    assert P.cmd_set_lock(False)[2] == 0xAA


def test_set_date_layout():
    frame = P.cmd_set_date(datetime.datetime(2026, 10, 27, 16, 45, 30))
    assert list(frame[2:9]) == [20, 26, 10, 27, 16, 45, 30]


# -------------------------------------------------------------------- auth
def test_auth_truncates_to_sixteen_ascii_bytes():
    frame = P.cmd_auth("0f2a9c1e-4b77-4abc-9d01-aaaa")
    assert bytes(frame[2:18]) == b"0f2a9c1e-4b77-4a"
    assert frame[18] == 0xFF


def test_auth_pads_a_short_id():
    frame = P.cmd_auth("abc")
    assert bytes(frame[2:18]) == b"abc" + b"\xff" * 13


# ------------------------------------------------------------------ codecs
@pytest.mark.parametrize(
    "celsius,expected",
    [(15.0, 0x50), (18.5, 0x73), (21.0, 0x8C), (21.5, 0x91), (30.0, 0xE6)],
)
def test_celsius_encoding_is_tenths_minus_seventy(celsius, expected):
    assert P.encode_setpoint(celsius, P.MS_CELSIUS) == expected
    assert P.decode_setpoint(expected, P.MS_CELSIUS) == pytest.approx(celsius)


@pytest.mark.parametrize("value", [45, 60, 70, 90])
def test_fahrenheit_has_no_bias(value):
    assert P.encode_setpoint(value, P.MS_FAHRENHEIT) == value


@pytest.mark.parametrize("level", [1, 5, 8, 10])
def test_power_levels_have_no_bias(level):
    assert P.encode_setpoint(level, P.MS_POWER) == level
    assert P.decode_setpoint(level, P.MS_POWER) == level


def test_setpoint_outside_a_byte_is_rejected():
    with pytest.raises(ValueError):
        P.encode_setpoint(500.0, P.MS_CELSIUS)


def test_cmd_set_setpoint_rejects_non_setpoint_opcodes():
    with pytest.raises(ValueError):
        P.cmd_set_setpoint(P.Action.SET_ON, 21.0, P.MS_CELSIUS)


# ------------------------------------------------------------ status parse
CELSIUS_STATUS = bytes(
    [0x91, 0x01, 0x2C, 0x02, 0x6E, 0x8C, 0x00, 0x02, 0x00,
     0xAA, 0x00, 0x00, 0x00, 0x00, 0x00]
)


def test_celsius_status_decodes():
    s = P.parse_status(CELSIUS_STATUS)
    assert s.celsius is True
    assert s.setpoint == pytest.approx(21.5)
    assert s.cip == 300, "CIP is big-endian, unlike everything else"
    assert s.mode == P.Mode.COMFORT
    assert s.eco == pytest.approx(18.0)
    assert s.comfort == pytest.approx(21.0)
    assert s.antifreeze == pytest.approx(7.0)
    assert s.boost_hours == 2
    assert s.alarm == 0
    assert s.lock is False


@pytest.mark.parametrize(
    "sentinel,label", [(0xFD, "ANTIFREEZE"), (0xFE, "STANDBY")]
)
def test_setpoint_sentinels(sentinel, label):
    s = P.parse_status(bytes([sentinel]) + bytes(14))
    assert s.setpoint_sentinel == label


@pytest.mark.parametrize("length", range(0, 16))
def test_short_status_never_raises(length):
    P.parse_status(bytes(length))


def test_status_tolerates_values_outside_the_documented_enums():
    # Real hardware reported window_detection = 0xFF, outside the 0..3 enum.
    s = P.parse_status(bytes([0] * 14 + [0xFF]))
    assert s.window_detection == 0xFF


# ---------------------------------------------------- captured from device
CAPTURED_STATUS = bytes.fromhex(
    "0000 1b00 0508 0200 0055 00ff ff00 ffff ffff ffbe".replace(" ", "")
)
CAPTURED_RESULT = bytes.fromhex("040801" + "ff" * 16 + "0d")
CAPTURED_FIRMWARE = bytes.fromhex("030200" + "ff" * 16 + "01")


def test_captured_status_is_a_valid_frame():
    assert P.verify_frame(CAPTURED_STATUS), CAPTURED_STATUS.hex(" ")


def test_captured_status_is_a_power_unit_matching_vendor_defaults():
    s = P.parse_status(CAPTURED_STATUS)
    assert s.mode_settings == P.MS_POWER
    assert s.is_power_level
    assert s.unit == "level"
    assert s.mode == P.Mode.OFF
    # These match modesettings_northeurope_default_* in the vendor APK, which
    # is what identifies the family.
    assert (s.eco, s.comfort, s.antifreeze) == (5.0, 8.0, 2.0)


def test_strip_frame_removes_only_a_valid_checksum():
    assert len(P.strip_frame(CAPTURED_STATUS)) == 19
    payload = CAPTURED_STATUS[:19]
    assert P.strip_frame(payload) is payload or len(P.strip_frame(payload)) == 19


def test_captured_result_echoes_opcode_then_sequence():
    """The layout the vendor app itself gets wrong."""
    r = P.parse_result(CAPTURED_RESULT)
    assert r.ok
    assert r.action == P.Action.REFRESH_STATUS, "byte 1 is the opcode echo"
    assert r.seq == 0x01, "byte 2 is the sequence echo"


def test_firmware_is_binary_not_ascii():
    payload = P.strip_frame(CAPTURED_FIRMWARE).rstrip(b"\xff")
    assert list(payload) == [3, 2, 0]


# ------------------------------------------------------------------ result
def test_result_ok_is_four():
    assert P.CommandStatus.OK == 4


def test_result_failure_statuses():
    r = P.parse_result(bytes([0x05, 0x11, 0x02]))
    assert not r.ok
    assert r.status == P.CommandStatus.ERR_DEVICEID_NOTSUPPORTED


@pytest.mark.parametrize("length", [0, 1, 2, 3])
def test_short_result_never_raises(length):
    P.parse_result(bytes(length))
