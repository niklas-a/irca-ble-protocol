"""Decode an Android btsnoop_hci.log into annotated Olle/Zoppas BLE traffic.

Parses btsnoop -> HCI H4 -> ACL (with L2CAP reassembly) -> ATT, resolves
attribute handles to UUIDs by watching GATT discovery responses, and then
annotates every write/notification against the protocol recovered from the
Olle Connect APK.

Usage:
    python decode_btsnoop.py <btsnoop_hci.log> [--all] [--raw]

    --all   also show ATT traffic that is not on the Zoppas service
    --raw   show raw hex for every decoded frame
"""
import struct
import sys
import datetime

# ----------------------------------------------------------------------------
# Protocol constants recovered from com.sysdata.zoppas.blepoc
# ----------------------------------------------------------------------------
ZOPPAS_SERVICE = "35ba1523-94f5-9052-4cd4-f102b6580adf"
CHARS = {
    "35ba1524-94f5-9052-4cd4-f102b6580adf": "STATUS",
    "35ba1525-94f5-9052-4cd4-f102b6580adf": "CMD",
    "35ba1526-94f5-9052-4cd4-f102b6580adf": "RESULT",
    "35ba1527-94f5-9052-4cd4-f102b6580adf": "MULTIPART_DATA",
    "35ba1528-94f5-9052-4cd4-f102b6580adf": "MULTIPART_RESULT",
    "35ba1529-94f5-9052-4cd4-f102b6580adf": "MODEL_NAME",
    "35ba1530-94f5-9052-4cd4-f102b6580adf": "SERIAL_NUMBER",
    "35ba1531-94f5-9052-4cd4-f102b6580adf": "FIRMWARE_VERSION",
    "35ba1532-94f5-9052-4cd4-f102b6580adf": "DEVICE_NAME",
}

ACTIONS = {
    0x01: "REGISTER_DEVICE", 0x02: "SET_MODE", 0x03: "SET_TEMP_MANUAL",
    0x04: "SET_TEMP_ECO", 0x05: "SET_TEMP_COMFORT", 0x06: "SET_TEMP_ANTIFREEZE",
    0x07: "SET_PERIOD_BOOST", 0x08: "REFRESH_STATUS", 0x09: "READ_STATS",
    0x0A: "READ_CHRONO", 0x0B: "SET_CHRONO", 0x0C: "SET_DATE",
    0x0D: "SET_ON", 0x0E: "SET_OFF", 0x0F: "READ_HOLIDAY", 0x10: "SET_HOLIDAY",
    0x11: "AUTH_DEVICE", 0x12: "SET_MODE_SETTINGS", 0x13: "READ_DIAGNOSTICS",
    0x15: "SET_LOCK", 0x16: "FACTORY_RESET", 0x17: "SET_OPENWINDOW",
    0xFF: "READ_SERIAL_NUMBER", 0xFE: "READ_MODEL_NAME", 0xFD: "READ_DEVICE_NAME",
    0xFC: "SET_DEVICE_NAME", 0xFB: "CONNECTION_CHANGE", 0xFA: "READ_FIRMWARE_VERSION",
}

CMD_STATUS = {
    1: "ERR_INVALID_CRC", 2: "ERR_INVALID_DATA", 3: "ERR_UNABLE_TO_UPDATE",
    4: "OK (OPERATION_PERFORMED)", 5: "ERR_DEVICEID_NOTSUPPORTED",
    6: "ERR_DEVICEID_ALREADYREGISTERED", 0xFF: "ERR_OPERATION_UNDEFINED",
}

MODES = {0: "SPENTO(off)", 1: "BOOST", 2: "COMFORT", 3: "ECO",
         4: "ANTIFREEZE", 5: "PROGRAMMA(schedule)", 6: "MANUALE"}
MODE_SETTINGS = {0x55: "POWER", 0xAA: "CELSIUS", 0xA5: "FAHRENHEIT"}
ALARMS = {0: "OK", 1: "ERR_NTC", 2: "ERR_LOAD", 3: "ERR_DATE", 4: "ERR_EEPROM"}
WINDOW = {0: "DISABLED", 1: "TRIGGER_OFF_WINDOW_CLOSED",
          2: "TRIGGER_ON_WINDOW_CLOSED", 3: "TRIGGER_ON_WINDOW_OPENED"}

UUID_BASE_SUFFIX = "-0000-1000-8000-00805f9b34fb"


def uuid_from_bytes(b):
    """ATT UUIDs are little-endian; return canonical string form."""
    if len(b) == 2:
        return f"0000{b[1]:02x}{b[0]:02x}" + UUID_BASE_SUFFIX
    if len(b) == 16:
        r = b[::-1]
        h = r.hex()
        return f"{h[0:8]}-{h[8:12]}-{h[12:16]}-{h[16:20]}-{h[20:32]}"
    return b.hex()


def temp_c(byte_val):
    """Celsius decode: raw = byte + 70, in tenths of a degree."""
    return (byte_val + 70) / 10.0


# ----------------------------------------------------------------------------
# btsnoop container
# ----------------------------------------------------------------------------
def read_btsnoop(path):
    with open(path, "rb") as f:
        hdr = f.read(16)
        if len(hdr) < 16 or not hdr.startswith(b"btsnoop\x00"):
            raise SystemExit(f"{path}: not a btsnoop file (bad magic)")
        version, datalink = struct.unpack(">II", hdr[8:16])
        while True:
            rh = f.read(24)
            if len(rh) < 24:
                return
            olen, ilen, flags, drops, ts = struct.unpack(">IIIIq", rh)
            data = f.read(ilen)
            if len(data) < ilen:
                return
            # btsnoop timestamps: microseconds since 0000-01-01, with a known
            # offset to the unix epoch.
            usec = ts - 0x00E03AB44A676000
            yield usec, flags, data


def fmt_ts(usec):
    try:
        return datetime.datetime.fromtimestamp(
            usec / 1e6, datetime.timezone.utc
        ).strftime("%H:%M:%S.%f")[:-3]
    except (OSError, OverflowError, ValueError):
        return "??:??:??.???"


# ----------------------------------------------------------------------------
# ATT annotation
# ----------------------------------------------------------------------------
def annotate_cmd_frame(data):
    """Annotate a 20-byte frame written to the CMD characteristic."""
    out = []
    if len(data) < 2:
        return ["(short frame)"]
    op, seq = data[0], data[1]
    name = ACTIONS.get(op, f"UNKNOWN(0x{op:02X})")
    out.append(f"action={name}  seq=0x{seq:02X}")
    payload = data[2:-1] if len(data) >= 20 else data[2:]
    if len(data) >= 20:
        calc = 0
        for b in data[:19]:
            calc ^= b
        ok = "OK" if calc == data[19] else f"MISMATCH(calc=0x{calc:02X})"
        out.append(f"checksum=0x{data[19]:02X} [{ok}]")

    if name == "AUTH_DEVICE" or name == "REGISTER_DEVICE":
        raw = bytes(payload[:16])
        txt = raw.rstrip(b"\xff").decode("ascii", "replace")
        out.append(f'deviceId(16B ascii)="{txt}"')
        out.append(f"deviceId hex={raw.hex()}")
    elif name == "SET_MODE":
        out.append(f"mode={MODES.get(payload[0], payload[0])}")
    elif name in ("SET_TEMP_MANUAL", "SET_TEMP_ECO", "SET_TEMP_COMFORT",
                  "SET_TEMP_ANTIFREEZE"):
        b = payload[0]
        out.append(f"temp byte=0x{b:02X} -> {temp_c(b):.1f}degC (if Celsius) "
                   f"| {b} degF (if Fahrenheit)")
    elif name == "SET_PERIOD_BOOST":
        out.append(f"boost={payload[0]} (hours; status reports x60 = minutes)")
    elif name == "SET_LOCK":
        lk = {0x55: "LOCKED", 0xAA: "UNLOCKED"}.get(payload[0], f"0x{payload[0]:02X}?")
        out.append(f"lock={lk}")
    elif name == "SET_OPENWINDOW":
        out.append(f"window_detection={WINDOW.get(payload[0], payload[0])}")
    elif name == "SET_MODE_SETTINGS":
        out.append(f"modeSettings=0x{payload[0]:02X} "
                   f"({MODE_SETTINGS.get(payload[0], '?')})")
    elif name == "SET_DATE":
        out.append(f"datetime payload={bytes(payload[:8]).hex()}")
    return out


def annotate_status(data):
    """Annotate a STATUS characteristic notification (DeviceStatus.fromBytesArray)."""
    out = []
    n = len(data)
    ms = MODE_SETTINGS.get(data[9], "?") if n >= 10 else "?"
    celsius = (n >= 10 and data[9] == 0xAA)
    if n >= 1:
        b = data[0]
        if b == 0xFD:
            out.append("setpoint=ANTIFREEZE (sentinel 0xFD)")
        elif b == 0xFE:
            out.append("setpoint=STANDBY (sentinel 0xFE)")
        else:
            out.append(f"setpoint={temp_c(b):.1f}degC" if celsius
                       else f"setpoint={b} (raw, non-Celsius)")
    if n >= 3:
        out.append(f"CIP={struct.unpack('>H', bytes(data[1:3]))[0]} (big-endian)")
    if n >= 4:
        out.append(f"mode={MODES.get(data[3], data[3])}")
    if n >= 5:
        out.append(f"eco={temp_c(data[4]):.1f}degC" if celsius else f"eco={data[4]}")
    if n >= 6:
        out.append(f"comfort={temp_c(data[5]):.1f}degC" if celsius else f"comfort={data[5]}")
    if n >= 7:
        out.append(f"antifreeze={temp_c(data[6]):.1f}degC" if celsius else f"antifreeze={data[6]}")
    if n >= 8:
        out.append(f"boost={data[7]}h ({data[7]*60} min)")
    if n >= 9:
        out.append(f"alarm={ALARMS.get(data[8], data[8])}")
    if n >= 10:
        out.append(f"modeSettings=0x{data[9]:02X} ({ms})")
    if n >= 11:
        out.append(f"holiday={'ACTIVE' if data[10] else 'off'}")
    if n >= 13:
        out.append(f"boostRemain bytes={bytes(data[11:13]).hex()}")
    if n >= 14:
        out.append(f"lock={'ON' if data[13] else 'off'}")
    if n >= 15:
        out.append(f"windowDetection={WINDOW.get(data[14], data[14])}")
    return out


def annotate_result(data):
    """RESULT: [status][opcode echo][seq echo][payload...] (hardware-verified)."""
    out = []
    if len(data) >= 1:
        out.append(f"status=0x{data[0]:02X} ({CMD_STATUS.get(data[0], '?')})")
    if len(data) >= 2:
        out.append(f"action={ACTIONS.get(data[1], f'0x{data[1]:02X}?')}")
    if len(data) >= 3:
        out.append(f"seq=0x{data[2]:02X}")
    if len(data) >= 4:
        out.append(f"payload={bytes(data[3:]).hex()}")
    return out


# ----------------------------------------------------------------------------
# Main decode loop
# ----------------------------------------------------------------------------
ATT_OPS = {
    0x01: "ERROR_RSP", 0x02: "EXCHANGE_MTU_REQ", 0x03: "EXCHANGE_MTU_RSP",
    0x04: "FIND_INFO_REQ", 0x05: "FIND_INFO_RSP", 0x08: "READ_BY_TYPE_REQ",
    0x09: "READ_BY_TYPE_RSP", 0x0A: "READ_REQ", 0x0B: "READ_RSP",
    0x10: "READ_BY_GROUP_TYPE_REQ", 0x11: "READ_BY_GROUP_TYPE_RSP",
    0x12: "WRITE_REQ", 0x13: "WRITE_RSP", 0x52: "WRITE_CMD",
    0x1B: "NOTIFICATION", 0x1D: "INDICATION", 0x1E: "CONFIRMATION",
}


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    show_all = "--all" in sys.argv
    show_raw = "--raw" in sys.argv
    if not args:
        raise SystemExit(__doc__)
    path = args[0]

    handle_uuid = {}      # att handle -> uuid string
    pending_read = {}     # conn -> att handle of outstanding READ_REQ
    frag = {}             # conn handle -> partial l2cap buffer
    nshown = 0
    stats = {}

    for usec, flags, pkt in read_btsnoop(path):
        if not pkt:
            continue
        h4 = pkt[0]
        if h4 != 0x02:           # ACL data only
            continue
        body = pkt[1:]
        if len(body) < 4:
            continue
        hdr, dlen = struct.unpack("<HH", body[:4])
        conn = hdr & 0x0FFF
        pb = (hdr >> 12) & 0x03
        payload = body[4:4 + dlen]
        sent = (flags & 0x01) == 0   # bit0: 0 = host -> controller (outgoing)

        if pb == 0x01:                       # continuation fragment
            frag[conn] = frag.get(conn, b"") + payload
        else:                                # first fragment
            frag[conn] = payload
        buf = frag.get(conn, b"")
        if len(buf) < 4:
            continue
        l2len, cid = struct.unpack("<HH", buf[:4])
        if len(buf) < 4 + l2len:
            continue                          # still fragmented
        att = buf[4:4 + l2len]
        frag[conn] = b""
        if cid != 0x0004 or not att:
            continue

        op = att[0]
        opname = ATT_OPS.get(op, f"ATT_0x{op:02X}")

        # --- build handle -> uuid map from discovery traffic ---
        if op == 0x09 and len(att) >= 2:                 # READ_BY_TYPE_RSP
            ln = att[1]
            for i in range(2, len(att) - ln + 1, ln):
                e = att[i:i + ln]
                if ln in (7, 21) and len(e) == ln:
                    vh = struct.unpack("<H", e[3:5])[0]
                    handle_uuid[vh] = uuid_from_bytes(e[5:])
        elif op == 0x05 and len(att) >= 2:               # FIND_INFO_RSP
            fmt = att[1]
            step = 4 if fmt == 1 else 18
            for i in range(2, len(att) - step + 1, step):
                e = att[i:i + step]
                hh = struct.unpack("<H", e[0:2])[0]
                handle_uuid[hh] = uuid_from_bytes(e[2:])
        elif op == 0x0A and len(att) >= 3:               # READ_REQ
            pending_read[conn] = struct.unpack("<H", att[1:3])[0]
        elif op == 0x0B and conn in pending_read:        # READ_RSP
            pass

        # --- extract (handle, value) for the ops we care about ---
        ah, val = None, None
        if op in (0x12, 0x52) and len(att) >= 3:
            ah = struct.unpack("<H", att[1:3])[0]
            val = att[3:]
        elif op in (0x1B, 0x1D) and len(att) >= 3:
            ah = struct.unpack("<H", att[1:3])[0]
            val = att[3:]
        elif op == 0x0B and conn in pending_read:
            ah = pending_read.pop(conn)
            val = att[1:]

        if ah is None:
            continue

        uuid = handle_uuid.get(ah)
        label = CHARS.get(uuid) if uuid else None

        if label is None and not show_all:
            continue

        arrow = "APP -> DEVICE" if sent else "DEVICE -> APP"
        name = label or (uuid or f"handle 0x{ah:04X}")
        stats[(name, opname)] = stats.get((name, opname), 0) + 1

        print(f"\n[{fmt_ts(usec)}] {arrow}  {opname}  handle=0x{ah:04X}  {name}")
        if show_raw or label is None:
            print(f"    raw: {bytes(val).hex(' ')}")
        else:
            print(f"    raw: {bytes(val).hex(' ')}")

        lines = []
        if label == "CMD":
            lines = annotate_cmd_frame(val)
        elif label == "STATUS":
            lines = annotate_status(val)
        elif label in ("RESULT", "MULTIPART_RESULT"):
            lines = annotate_result(val)
        elif label in ("MODEL_NAME", "SERIAL_NUMBER", "FIRMWARE_VERSION",
                       "DEVICE_NAME"):
            txt = bytes(val).rstrip(b"\xff\x00").decode("ascii", "replace")
            lines = [f'text="{txt}"']
        for ln in lines:
            print(f"      {ln}")
        nshown += 1

    print("\n" + "=" * 70)
    print(f"decoded {nshown} relevant ATT frames")
    print(f"handles resolved: {len(handle_uuid)}")
    if stats:
        print("\nsummary:")
        for (name, opn), c in sorted(stats.items(), key=lambda x: -x[1]):
            print(f"   {c:5d}  {name:18s} {opn}")
    zoppas = {h: u for h, u in handle_uuid.items() if u in CHARS}
    if zoppas:
        print("\nZoppas handle map:")
        for h, u in sorted(zoppas.items()):
            print(f"   0x{h:04X}  {CHARS[u]:18s} {u}")


if __name__ == "__main__":
    main()
