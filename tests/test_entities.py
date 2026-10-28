"""Entity-level tests against a stub coordinator.

These need Home Assistant importable but not running, and no Bluetooth. They
cover the part most likely to be wrong: how a device's value family changes
what the entities report.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

ha = pytest.importorskip(
    "homeassistant.components.number", reason="Home Assistant not installed"
)

from homeassistant.components.number import NumberDeviceClass  # noqa: E402
from homeassistant.const import UnitOfTemperature  # noqa: E402

from custom_components.irca_ble import binary_sensor, number, select, sensor, switch  # noqa: E402
from custom_components.irca_ble.ircable import protocol as P  # noqa: E402


class StubEntry:
    title = "Towel rail"


class StubCoordinator:
    """Just enough surface for CoordinatorEntity and our own base class."""

    def __init__(self, status: P.Status | None):
        self.data = status
        self.address = "AA:BB:CC:DD:EE:FF"
        self.model = "0000AAAABBBB"
        self.serial = "HB000000000"
        self.firmware = "3.2.0"
        self.entry = StubEntry()
        self.last_update_success = True
        self.sent: list[str] = []

    async def async_execute(self, action, *, label):
        self.sent.append(label)

    def async_add_listener(self, *a, **k):
        return lambda: None


def make_status(mode_settings: int, **over) -> P.Status:
    """Build a STATUS from a real frame, overriding selected bytes."""
    body = bytearray([0xFF] * 19)
    body[0] = over.get("setpoint_raw", 0x00)
    body[1], body[2] = 0x00, 0x20
    body[3] = over.get("mode", P.Mode.OFF)
    body[4] = over.get("eco_raw", P.encode_setpoint(
        5 if mode_settings == P.MS_POWER else 18.0, mode_settings))
    body[5] = over.get("comfort_raw", P.encode_setpoint(
        8 if mode_settings == P.MS_POWER else 21.0, mode_settings))
    body[6] = over.get("antifreeze_raw", P.encode_setpoint(
        2 if mode_settings == P.MS_POWER else 7.0, mode_settings))
    body[7] = 0
    body[8] = over.get("alarm", 0)
    body[9] = mode_settings
    body[10] = over.get("holiday", 0)
    body[13] = over.get("lock", 0)
    body[14] = over.get("window", 0xFF)
    body.append(P.checksum(bytes(body)))
    return P.parse_status(bytes(body))


POWER = lambda **k: StubCoordinator(make_status(P.MS_POWER, **k))          # noqa: E731
CELSIUS = lambda **k: StubCoordinator(make_status(P.MS_CELSIUS, **k))      # noqa: E731


# ------------------------------------------------------------------ switch
def test_power_switch_reflects_mode():
    off = switch.IrcaPowerSwitch(POWER())
    assert off.is_on is False
    on = switch.IrcaPowerSwitch(POWER(mode=P.Mode.COMFORT))
    assert on.is_on is True


@pytest.mark.asyncio
async def test_power_switch_sends_commands():
    c = POWER()
    sw = switch.IrcaPowerSwitch(c)
    await sw.async_turn_on()
    await sw.async_turn_off()
    assert c.sent == ["Turn on", "Turn off"]


def test_child_lock_reads_status():
    assert switch.IrcaChildLockSwitch(POWER(lock=1)).is_on is True
    assert switch.IrcaChildLockSwitch(POWER(lock=0)).is_on is False


# ------------------------------------------------------------------ select
def test_mode_select_maps_to_option_names():
    s = select.IrcaModeSelect(POWER(mode=P.Mode.ECO))
    assert s.current_option == "eco"


def test_mode_select_offers_no_off_option():
    """Off belongs to the power switch; two controls would disagree."""
    assert "off" not in select.IrcaModeSelect(POWER()).options


def test_mode_select_handles_undocumented_mode():
    s = select.IrcaModeSelect(POWER(mode=0x7E))
    assert s.current_option is None


# ------------------------------------------------------------------ number
def test_power_unit_number_is_dimensionless():
    n = number.IrcaManualSetpoint(POWER())
    assert n.native_unit_of_measurement is None
    assert n.device_class is None, "a power level is not a temperature"
    assert (n.native_min_value, n.native_max_value, n.native_step) == (1.0, 10.0, 1.0)


def test_celsius_unit_number_is_a_temperature():
    n = number.IrcaPresetSetpoint(CELSIUS(), number.PRESETS[0])
    assert n.native_unit_of_measurement == UnitOfTemperature.CELSIUS
    assert n.device_class == NumberDeviceClass.TEMPERATURE
    assert (n.native_min_value, n.native_max_value, n.native_step) == (15.0, 30.0, 0.5)


def test_preset_numbers_read_the_right_fields():
    c = POWER()
    values = {
        d.key: number.IrcaPresetSetpoint(c, d).native_value for d in number.PRESETS
    }
    assert values == {"comfort": 8.0, "eco": 5.0, "antifreeze": 2.0}


def test_power_level_value():
    n = number.IrcaManualSetpoint(POWER(setpoint_raw=7))
    assert n.native_value == 7.0


@pytest.mark.asyncio
async def test_setting_a_level_dispatches():
    c = POWER()
    await number.IrcaManualSetpoint(c).async_set_native_value(6)
    assert c.sent == ["Set power level"]


def test_family_range_falls_back_to_power():
    """An unknown family must not be guessed as Celsius."""
    assert number.family_range(0x00) == (1.0, 10.0, 1.0)
    assert number.family_unit(0x00) is None


# ------------------------------------------------------------------ sensor
def test_alarm_sensor():
    assert sensor.IrcaAlarmSensor(POWER(alarm=0)).native_value == "ok"
    assert sensor.IrcaAlarmSensor(POWER(alarm=2)).native_value == "load_fault"


def test_window_sensor_tolerates_the_real_0xff_value():
    s = sensor.IrcaWindowDetectionSensor(POWER(window=0xFF))
    assert s.native_value == "unknown"
    assert s.native_value in s.options


def test_window_sensor_known_value():
    assert sensor.IrcaWindowDetectionSensor(POWER(window=1)).native_value == (
        "trigger_off_window_closed"
    )


def test_every_alarm_state_is_declared():
    for raw in range(5):
        value = sensor.IrcaAlarmSensor(POWER(alarm=raw)).native_value
        assert value in sensor.ALARM_STATES


# ----------------------------------------------------------- binary_sensor
def test_problem_sensor():
    assert binary_sensor.IrcaProblemSensor(POWER(alarm=0)).is_on is False
    assert binary_sensor.IrcaProblemSensor(POWER(alarm=3)).is_on is True


def test_holiday_sensor():
    assert binary_sensor.IrcaHolidaySensor(POWER(holiday=1)).is_on is True


# ------------------------------------------------------------- unavailable
@pytest.mark.parametrize(
    "factory",
    [
        lambda c: switch.IrcaPowerSwitch(c),
        lambda c: select.IrcaModeSelect(c),
        lambda c: number.IrcaManualSetpoint(c),
        lambda c: sensor.IrcaAlarmSensor(c),
        lambda c: binary_sensor.IrcaHolidaySensor(c),
    ],
)
def test_entities_are_unavailable_without_data(factory):
    entity = factory(StubCoordinator(None))
    assert entity.available is False


def test_unique_ids_are_distinct():
    c = POWER()
    entities = [
        switch.IrcaPowerSwitch(c),
        switch.IrcaChildLockSwitch(c),
        select.IrcaModeSelect(c),
        number.IrcaManualSetpoint(c),
        *(number.IrcaPresetSetpoint(c, d) for d in number.PRESETS),
        sensor.IrcaAlarmSensor(c),
        sensor.IrcaWindowDetectionSensor(c),
        binary_sensor.IrcaProblemSensor(c),
        binary_sensor.IrcaHolidaySensor(c),
    ]
    ids = [e.unique_id for e in entities]
    assert len(set(ids)) == len(ids), ids
    assert all(i.startswith("AA:BB:CC:DD:EE:FF_") for i in ids)
