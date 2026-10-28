"""Client tests against a protocol-accurate fake heater.

No Bluetooth hardware and no Home Assistant required. These cover the command
path end to end: frame construction, sequence matching, error handling and the
device behaviours that are easy to get wrong.
"""
from __future__ import annotations

import asyncio

import pytest

from fake_device import FakeBleakClient, FakeHeater
from ircable import protocol as P
from ircable import client as client_mod
from ircable.client import IrcaClient, IrcaCommandRejected, IrcaError


@pytest.fixture
def heater() -> FakeHeater:
    return FakeHeater()


@pytest.fixture
def patched(monkeypatch):
    """Make IrcaClient build our fake transport instead of a real one."""
    holder: dict[str, FakeBleakClient] = {}

    def install(heater: FakeHeater, **kwargs) -> FakeBleakClient:
        fake = FakeBleakClient(heater, **kwargs)
        holder["fake"] = fake
        monkeypatch.setattr(client_mod, "BleakClient", lambda *a, **k: fake)
        monkeypatch.setattr(client_mod, "_HAS_RETRY_CONNECTOR", False)
        return fake

    install.holder = holder  # type: ignore[attr-defined]
    return install


# --------------------------------------------------------------- lifecycle
@pytest.mark.asyncio
async def test_connect_and_refresh(heater, patched):
    patched(heater)
    async with IrcaClient(object()) as c:
        status = await c.refresh()
    assert status.mode == P.Mode.OFF
    assert status.mode_settings == P.MS_POWER
    assert status.is_power_level
    assert status.comfort == 8.0


@pytest.mark.asyncio
async def test_disconnects_on_exit(heater, patched):
    fake = patched(heater)
    async with IrcaClient(object()) as c:
        assert c.is_connected
    assert fake.disconnect_calls == 1
    assert not fake.is_connected


@pytest.mark.asyncio
async def test_rejects_device_without_the_service(heater, patched):
    patched(heater, service_present=False)
    with pytest.raises(IrcaError, match="not present"):
        async with IrcaClient(object()):
            pass


# ---------------------------------------------------------------- commands
@pytest.mark.asyncio
async def test_turn_on_resumes_stored_mode(heater, patched):
    """SET_ON is not a neutral 'on' - it restores the configured mode."""
    patched(heater)
    async with IrcaClient(object()) as c:
        before = await c.refresh()
        assert before.mode == P.Mode.OFF
        await c.turn_on()
        after = await c.refresh()

    assert after.mode == P.Mode.COMFORT
    # ...and the live setpoint jumps to the stored comfort level, which is why
    # an optimistic UI would be wrong here.
    assert after.setpoint == after.comfort == 8.0


@pytest.mark.asyncio
async def test_turn_off(heater, patched):
    patched(heater)
    async with IrcaClient(object()) as c:
        await c.turn_on()
        await c.turn_off()
        status = await c.refresh()
    assert status.mode == P.Mode.OFF
    assert status.setpoint == 0.0


@pytest.mark.asyncio
async def test_set_mode(heater, patched):
    patched(heater)
    async with IrcaClient(object()) as c:
        await c.set_mode(P.Mode.ECO)
        status = await c.refresh()
    assert status.mode == P.Mode.ECO


@pytest.mark.asyncio
async def test_power_level_setpoint_is_unbiased(heater, patched):
    patched(heater)
    async with IrcaClient(object()) as c:
        await c.set_manual_setpoint(7, P.MS_POWER)
        status = await c.refresh()
    assert status.setpoint == 7.0
    sent = [f for f in heater.received if f[0] == P.Action.SET_TEMP_MANUAL][-1]
    assert sent[2] == 7, "power levels must travel raw, with no -70 bias"


@pytest.mark.asyncio
async def test_celsius_setpoint_uses_the_bias(patched):
    heater = FakeHeater(mode_settings=P.MS_CELSIUS)
    patched(heater)
    async with IrcaClient(object()) as c:
        await c.set_manual_setpoint(21.5, P.MS_CELSIUS)
        status = await c.refresh()
    assert status.setpoint == pytest.approx(21.5)
    sent = [f for f in heater.received if f[0] == P.Action.SET_TEMP_MANUAL][-1]
    assert sent[2] == 0x91, "21.5C encodes to (215 - 70) = 145"


@pytest.mark.asyncio
async def test_preset_setpoints(heater, patched):
    patched(heater)
    async with IrcaClient(object()) as c:
        await c.set_preset_setpoint(P.Action.SET_TEMP_ECO, 4, P.MS_POWER)
        await c.set_preset_setpoint(P.Action.SET_TEMP_COMFORT, 9, P.MS_POWER)
        status = await c.refresh()
    assert status.eco == 4.0
    assert status.comfort == 9.0


@pytest.mark.asyncio
async def test_preset_setpoint_rejects_wrong_opcode(heater, patched):
    patched(heater)
    async with IrcaClient(object()) as c:
        with pytest.raises(ValueError):
            await c.set_preset_setpoint(P.Action.SET_ON, 5, P.MS_POWER)


@pytest.mark.asyncio
async def test_child_lock_uses_55_and_aa(heater, patched):
    patched(heater)
    async with IrcaClient(object()) as c:
        await c.set_child_lock(True)
        assert (await c.refresh()).lock is True
        locked = [f for f in heater.received if f[0] == P.Action.SET_LOCK][-1]
        assert locked[2] == 0x55
        await c.set_child_lock(False)
        assert (await c.refresh()).lock is False
        unlocked = [f for f in heater.received if f[0] == P.Action.SET_LOCK][-1]
        assert unlocked[2] == 0xAA


# ------------------------------------------------------------------ errors
@pytest.mark.asyncio
async def test_rejection_raises(patched):
    heater = FakeHeater(reject=True)
    patched(heater)
    async with IrcaClient(object()) as c:
        with pytest.raises(IrcaCommandRejected) as excinfo:
            await c.turn_on()
    assert excinfo.value.result.status == P.CommandStatus.ERR_INVALID_DATA


@pytest.mark.asyncio
async def test_timeout_when_device_never_answers(heater, patched, monkeypatch):
    fake = patched(heater)
    monkeypatch.setattr(client_mod, "COMMAND_TIMEOUT", 0.05)

    async def silent(uuid, data, response=True):
        heater.handle(bytes(data))      # apply it, but send nothing back

    fake.write_gatt_char = silent
    async with IrcaClient(object()) as c:
        with pytest.raises(IrcaError, match="no RESULT"):
            await c.turn_on()


# ------------------------------------------------------- sequence matching
@pytest.mark.asyncio
async def test_every_command_gets_a_distinct_sequence(heater, patched):
    patched(heater)
    async with IrcaClient(object()) as c:
        for _ in range(5):
            await c.refresh()
    seqs = [f[1] for f in heater.received]
    assert len(set(seqs)) == len(seqs), f"sequence reused: {seqs}"


@pytest.mark.asyncio
async def test_result_is_matched_on_sequence_not_opcode(heater, patched):
    """Two commands of the same opcode must not be confused for each other."""
    patched(heater)
    async with IrcaClient(object()) as c:
        await c.refresh()
        await c.refresh()
    refreshes = [f for f in heater.received if f[0] == P.Action.REFRESH_STATUS]
    assert refreshes[0][1] != refreshes[1][1]


@pytest.mark.asyncio
async def test_concurrent_commands_are_serialised(heater, patched):
    """The device drops overlapping GATT operations, so we must not overlap."""
    patched(heater, notify_delay=0.01)
    async with IrcaClient(object()) as c:
        await asyncio.gather(
            c.set_mode(P.Mode.ECO),
            c.set_mode(P.Mode.COMFORT),
            c.set_child_lock(True),
        )
        status = await c.refresh()
    assert status is not None
    assert len(heater.received) == 4
    seqs = [f[1] for f in heater.received]
    assert len(set(seqs)) == 4


# ------------------------------------------------------------------- frames
@pytest.mark.asyncio
async def test_all_frames_are_twenty_bytes_with_valid_checksums(heater, patched):
    patched(heater)
    async with IrcaClient(object()) as c:
        await c.turn_on()
        await c.set_mode(P.Mode.ECO)
        await c.set_manual_setpoint(3, P.MS_POWER)
        await c.set_child_lock(True)
        await c.refresh()
    assert heater.received
    for frame in heater.received:
        assert len(frame) == 20
        assert P.verify_frame(frame), frame.hex(" ")


@pytest.mark.asyncio
async def test_no_factory_reset_is_ever_sent(heater, patched):
    """0x16 must not be reachable from the client API."""
    patched(heater)
    async with IrcaClient(object()) as c:
        await c.turn_on()
        await c.turn_off()
        await c.set_mode(P.Mode.BOOST)
        await c.refresh()
    assert all(f[0] != 0x16 for f in heater.received)
    assert not hasattr(c, "factory_reset")


@pytest.mark.asyncio
async def test_device_info(heater, patched):
    patched(heater)
    async with IrcaClient(object()) as c:
        info = await c.read_device_info()
    assert info["model"] == "0000AAAABBBB"
    assert info["serial"] == "HB000000000"
    assert info["firmware"] == "3.2.0"


@pytest.mark.asyncio
async def test_auth_failure_is_not_fatal(patched):
    """AUTH_DEVICE is not enforced by tested firmware; rejection must not stop us."""
    heater = FakeHeater()
    original = heater.handle

    def reject_auth(frame):
        if frame[0] == P.Action.AUTH_DEVICE:
            heater.received.append(bytes(frame))
            return (
                heater._result(P.CommandStatus.ERR_DEVICEID_NOTSUPPORTED,
                               frame[0], frame[1]),
                None,
            )
        return original(frame)

    heater.handle = reject_auth
    patched(heater)
    async with IrcaClient(object(), device_id="0f2a9c1e-4b77-4") as c:
        status = await c.refresh()          # still works
    assert status is not None
    assert any(f[0] == P.Action.AUTH_DEVICE for f in heater.received)
