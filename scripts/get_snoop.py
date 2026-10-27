"""Pull the HCI snoop log out of `dumpsys bluetooth_manager` and convert it to
a standard btsnoop file.

Android embeds a compressed snoop summary inline in the bluetooth_manager dump,
between BTSNOOP_LOG_SUMMARY markers, in the "btsnooz" format:

    byte  0       version (1 or 2)
    bytes 1..8    timestamp of the LAST record, microseconds since the epoch
    bytes 9..     zlib stream of records

and each decompressed record is:

    uint16  length         (payload length + 1, the +1 being the type byte)
    uint16  packet_length  (original, possibly truncated, length)
    uint32  delta_time_ms  (since the previous record)
    uint8   type           (0x1x = controller->host, 0x2x = host->controller)
    bytes   payload        (length - 1 bytes, HCI payload without the H4 type byte)

This is much faster than `adb bugreport` (seconds vs minutes) and works on
Samsung One UI, which does not ship /data/misc/bluetooth/logs inside bugreports.

Usage:
    python get_snoop.py <out.log>
"""
import base64
import os
import re
import struct
import subprocess
import sys
import zlib

ADB = os.environ.get("ADB") or os.path.expandvars(
    r"%LOCALAPPDATA%\Microsoft\WinGet\Packages"
    r"\Google.PlatformTools_Microsoft.Winget.Source_8wekyb3d8bbwe"
    r"\platform-tools\adb.exe")

# btsnooz type -> (H4 packet type, is_received, is_cmd_or_evt)
SNOOZ_TYPES = {
    0x10: (0x04, True, True),    # HCI event, controller -> host
    0x11: (0x02, True, False),   # ACL in
    0x12: (0x03, True, False),   # SCO in
    0x17: (0x05, True, False),   # ISO in
    0x20: (0x01, False, True),   # HCI command, host -> controller
    0x21: (0x02, False, False),  # ACL out
    0x22: (0x03, False, False),  # SCO out
    0x27: (0x05, False, False),  # ISO out
}

# btsnoop timestamps are microseconds since year 0; this is the unix epoch in
# that scale.
BTSNOOP_EPOCH_DELTA = 0x00DCDDB30F2F8000


def fetch_section() -> str:
    raw = subprocess.run([ADB, "exec-out", "dumpsys", "bluetooth_manager"],
                         capture_output=True).stdout
    text = raw.decode("utf-8", "replace")
    print(f"dumpsys output: {len(raw):,} bytes")
    m = re.search(
        r"---\s*BEGIN:BTSNOOP_LOG_SUMMARY.*?---(?P<body>.*?)"
        r"---\s*END:BTSNOOP_LOG_SUMMARY\s*---", text, re.S)
    if not m:
        print("No BTSNOOP_LOG_SUMMARY section found.")
        print("Check: settings get global bluetooth_btsnoop_default_mode == full,"
              " then cycle Bluetooth.")
        sys.exit(1)
    return m.group("body")


def decode_snooz(blob: bytes):
    version, last_ts_us = struct.unpack_from("<BQ", blob, 0)
    print(f"btsnooz version {version}, last record ts={last_ts_us}")
    if version not in (1, 2):
        print(f"unsupported btsnooz version {version}")
        sys.exit(1)
    data = zlib.decompress(blob[9:])
    print(f"decompressed: {len(data):,} bytes")

    records = []
    off = 0
    total_delta = 0
    while off + 9 <= len(data):
        length, packet_length, delta_ms, typ = struct.unpack_from("<HHIB", data, off)
        off += 9
        n = length - 1
        if n < 0 or off + n > len(data):
            break
        payload = data[off:off + n]
        off += n
        total_delta += delta_ms
        records.append((total_delta, packet_length, typ, payload))
    print(f"parsed {len(records)} records, span {total_delta/1000:.1f}s")

    # Anchor so the final record lands on last_ts_us.
    base_us = last_ts_us - total_delta * 1000
    return [(base_us + d * 1000, pl, t, p) for (d, pl, t, p) in records]


def write_btsnoop(records, path):
    with open(path, "wb") as f:
        # datalink 1002 = HCI UART (H4)
        f.write(b"btsnoop\x00" + struct.pack(">II", 1, 1002))
        kept = 0
        for ts_us, packet_length, typ, payload in records:
            info = SNOOZ_TYPES.get(typ)
            if info is None:
                continue
            h4, received, is_cmd_evt = info
            pkt = bytes([h4]) + payload
            flags = (1 if received else 0) | (2 if is_cmd_evt else 0)
            f.write(struct.pack(">IIIIq",
                                packet_length + 1, len(pkt), flags, 0,
                                ts_us + BTSNOOP_EPOCH_DELTA))
            f.write(pkt)
            kept += 1
    print(f"wrote {path}: {kept} packets")
    return kept


def main():
    out = sys.argv[1] if len(sys.argv) > 1 else "btsnoop_hci.log"
    body = fetch_section()
    b64 = re.sub(r"\s+", "", body)
    blob = base64.b64decode(b64)
    print(f"base64 {len(b64):,} chars -> {len(blob):,} bytes")
    records = decode_snooz(blob)
    if not records:
        print("no records decoded")
        sys.exit(1)
    n = write_btsnoop(records, out)
    if n == 0:
        sys.exit(1)


if __name__ == "__main__":
    main()
