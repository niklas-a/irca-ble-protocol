"""Offline self-test of olle_protocol: frame shape, checksum, round-trips."""
import datetime
import olle_protocol as P

fails = []


def check(label, cond, detail=""):
    if cond:
        print(f"  PASS  {label}")
    else:
        print(f"  FAIL  {label}   {detail}")
        fails.append(label)


print("== frame shape and checksum ==")
for name, f in [
    ("SET_ON", P.cmd_on(0)),
    ("SET_OFF", P.cmd_off(1)),
    ("REFRESH_STATUS", P.cmd_refresh_status(2)),
    ("SET_MODE COMFORT", P.cmd_set_mode(P.Mode.COMFORT, 3)),
    ("SET_TEMP_MANUAL 21.5", P.cmd_set_temp_manual(21.5, True, 4)),
    ("SET_LOCK on", P.cmd_set_lock(True, 5)),
    ("AUTH_DEVICE", P.cmd_auth("0f2a9c1e-4b77-4abc-9d01-aaaa", 6)),
    ("SET_DATE", P.cmd_set_date(datetime.datetime(2026, 10, 27, 16, 45, 30), 7)),
]:
    check(f"{name}: 20 bytes", len(f) == 20, f"got {len(f)}")
    check(f"{name}: checksum valid", P.verify_frame(f), f.hex(" "))

print("\n== known-good byte layouts ==")
on = P.cmd_on(0)
check("SET_ON opcode 0x0D", on[0] == 0x0D, hex(on[0]))
check("SET_ON pads 0xFF", all(b == 0xFF for b in on[2:19]), on.hex(" "))

t = P.cmd_set_temp_manual(21.5, celsius=True, seq=0)
check("21.5C -> 0x91 (215-70=145)", t[2] == 0x91, hex(t[2]))

t30 = P.cmd_set_temp_manual(30.0, celsius=True)
check("30.0C -> 0xE6 (300-70=230)", t30[2] == 0xE6, hex(t30[2]))

t15 = P.cmd_set_temp_manual(15.0, celsius=True)
check("15.0C -> 0x50 (150-70=80)", t15[2] == 0x50, hex(t15[2]))

tf = P.cmd_set_temp_manual(70, celsius=False)
check("70F -> 0x46 (no bias)", tf[2] == 0x46, hex(tf[2]))

lk = P.cmd_set_lock(True)
check("SET_LOCK locked = 0x55", lk[2] == 0x55, hex(lk[2]))
lk2 = P.cmd_set_lock(False)
check("SET_LOCK unlocked = 0xAA", lk2[2] == 0xAA, hex(lk2[2]))

d = P.cmd_set_date(datetime.datetime(2026, 10, 27, 16, 45, 30))
check("SET_DATE = [20,26,10,27,16,45,30]",
      list(d[2:9]) == [20, 26, 10, 27, 16, 45, 30], list(d[2:9]))

a = P.cmd_auth("0f2a9c1e-4b77-4abc-9d01-aaaa")
check("AUTH truncates id to 16 ASCII bytes",
      bytes(a[2:18]) == b"0f2a9c1e-4b77-4a", bytes(a[2:18]))
check("AUTH byte 18 is pad", a[18] == 0xFF, hex(a[18]))

short = P.cmd_auth("abc")
check("AUTH pads short id with 0xFF",
      bytes(short[2:18]) == b"abc" + b"\xff" * 13, bytes(short[2:18]))

print("\n== temperature round-trips ==")
for v in (15.0, 18.5, 21.0, 21.5, 24.0, 30.0):
    enc = P.encode_temp(v, True)
    dec = P.decode_temp(enc, True)
    check(f"{v}C -> 0x{enc:02X} -> {dec}", abs(dec - v) < 1e-9, f"got {dec}")

print("\n== status parsing ==")
# Celsius (0xAA at index 9), setpoint 21.5 (0x91), mode COMFORT(2),
# eco 18.0 (180-70=110=0x6E), comfort 21.0 (210-70=140=0x8C),
# antifreeze 7.0 (70-70=0), boost 2h, alarm OK, holiday off, lock off, window off
raw = bytes([0x91, 0x01, 0x2C, 0x02, 0x6E, 0x8C, 0x00, 0x02, 0x00,
             0xAA, 0x00, 0x00, 0x00, 0x00, 0x00])
st = P.parse_status(raw)
check("celsius detected", st.celsius is True)
check("setpoint 21.5", abs(st.setpoint - 21.5) < 1e-9, st.setpoint)
check("CIP big-endian 300", st.cip == 300, st.cip)
check("mode COMFORT", st.mode == P.Mode.COMFORT, st.mode)
check("eco 18.0", abs(st.eco - 18.0) < 1e-9, st.eco)
check("comfort 21.0", abs(st.comfort - 21.0) < 1e-9, st.comfort)
check("antifreeze 7.0", abs(st.antifreeze - 7.0) < 1e-9, st.antifreeze)
check("boost 2h", st.boost_hours == 2, st.boost_hours)
check("alarm OK", st.alarm == 0, st.alarm)
check("lock off", st.lock is False, st.lock)
print(f"  describe(): {st.describe()}")

sent = P.parse_status(bytes([0xFD]) + bytes(14))
check("0xFD setpoint sentinel = ANTIFREEZE",
      sent.setpoint_sentinel == "ANTIFREEZE", sent.setpoint_sentinel)
sent2 = P.parse_status(bytes([0xFE]) + bytes(14))
check("0xFE setpoint sentinel = STANDBY",
      sent2.setpoint_sentinel == "STANDBY", sent2.setpoint_sentinel)

short_st = P.parse_status(bytes([0x91, 0x00]))
check("short status does not crash", short_st.mode is None)

print("\n== real hardware frames (Olle towel rail, fw 3.2.0, POWER variant) ==")
# Captured by direct GATT read, 2026-10-27. Full 20-byte frames with checksum.
# Model and serial frames are redacted (synthetic values, checksums recomputed)
# since they identify one physical unit; every other frame is verbatim.
real_status = bytes.fromhex("0000 1b00 0508 0200 0055 00ff ff00 ffff ffff ffbe".replace(" ", ""))
check("real STATUS is a valid 20-byte frame", P.verify_frame(real_status),
      real_status.hex(" "))
rs = P.parse_status(real_status)
check("strip_frame drops the checksum", len(P.strip_frame(real_status)) == 19)
check("mode_settings = POWER (0x55)", rs.mode_settings == P.MS_POWER,
      rs.mode_settings)
check("is_power_level", rs.is_power_level is True)
check("unit = level", rs.unit == "level", rs.unit)
check("not celsius", rs.celsius is False)
check("mode = OFF", rs.mode == P.Mode.OFF, rs.mode)
check("eco level 5 (matches northeurope default)", rs.eco == 5.0, rs.eco)
check("comfort level 8 (matches northeurope default)", rs.comfort == 8.0, rs.comfort)
check("antifreeze level 2 (matches northeurope default)", rs.antifreeze == 2.0,
      rs.antifreeze)
check("CIP = 27", rs.cip == 27, rs.cip)
check("alarm OK", rs.alarm == 0)
check("lock off", rs.lock is False)
print(f"  describe(): {rs.describe()}")

real_result = bytes.fromhex("0409" + "00" + "ff" * 16 + "0d")
check("real RESULT is a valid frame", P.verify_frame(real_result))
rr = P.parse_result(real_result)
check("real RESULT ok", rr.ok, rr.describe())
check("real RESULT action = READ_STATS (0x09)", rr.action == 0x09, rr.action)
check("real RESULT seq = 0", rr.seq == 0, rr.seq)

# Captured live: we sent REFRESH_STATUS (0x08) with seq 0x01 and got this back.
live_result = bytes.fromhex("040801" + "ff" * 16 + "0d")
check("live RESULT frame valid", P.verify_frame(live_result))
lr = P.parse_result(live_result)
check("live RESULT status OK", lr.ok, lr.describe())
check("live RESULT echoes opcode REFRESH_STATUS",
      lr.action == P.Action.REFRESH_STATUS, lr.action)
check("live RESULT echoes seq 0x01", lr.seq == 0x01, lr.seq)
print(f"  describe(): {lr.describe()}")

redacted_model = bytes.fromhex("303030304141414142424242" + "ff" * 7 + "ff")
check("MODEL_NAME frame checksum verifies", P.verify_frame(redacted_model))
check("MODEL_NAME decodes to its ASCII payload",
      P.strip_frame(redacted_model).rstrip(b"\xff") == b"0000AAAABBBB")

redacted_serial = bytes.fromhex("4842303030303030303030" + "ff" * 8 + "3a")
check("SERIAL_NUMBER frame checksum verifies", P.verify_frame(redacted_serial))
check("SERIAL_NUMBER decodes to its ASCII payload",
      P.strip_frame(redacted_serial).rstrip(b"\xff") == b"HB000000000")

real_fw = bytes.fromhex("030200" + "ff" * 16 + "01")
check("real FIRMWARE checksum verifies", P.verify_frame(real_fw))
check("real FIRMWARE decodes to 3.2.0",
      list(P.strip_frame(real_fw).rstrip(b"\xff")) == [3, 2, 0])

print("\n== power-level command builders ==")
pl = P.cmd_set_level_manual(7, 3)
check("level 7 -> raw byte 0x07 (no bias)", pl[2] == 0x07, hex(pl[2]))
check("level frame valid", P.verify_frame(pl))
try:
    P.cmd_set_level_manual(11)
    check("level 11 rejected", False, "no exception raised")
except ValueError:
    check("level 11 rejected", True)

print("\n== result parsing ==")
r = P.parse_result(bytes([0x04, 0x0D, 0x06]))
check("result OK, action SET_ON, seq 6",
      r.ok and r.action == P.Action.SET_ON and r.seq == 6, r.describe())
r2 = P.parse_result(bytes([0x05, 0x11, 0x02]))
check("result DEVICEID_NOTSUPPORTED not ok", not r2.ok, r2.describe())
r3 = P.parse_result(bytes([0x04]))
check("1-byte result does not crash", r3.ok and r3.seq is None)

print("\n" + "=" * 50)
if fails:
    print(f"{len(fails)} FAILURES: {fails}")
    raise SystemExit(1)
print("all checks passed")
