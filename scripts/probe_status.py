"""Strictly read-only probe: read STATUS (and friends) without writing anything.

No frames are sent to the CMD characteristic, so the heater's state cannot
change as a result of running this.
"""
import asyncio
import sys

from bleak import BleakClient

import olle_protocol as P

if len(sys.argv) < 2:
    raise SystemExit("usage: python probe_status.py <BLE address>\n"
                     "       (find it with: python olle_scan.py)")
ADDR = sys.argv[1]


def verify20(label, raw: bytes):
    if len(raw) == 20:
        calc = P.checksum(raw[:19])
        ok = "OK" if calc == raw[19] else f"MISMATCH (calc 0x{calc:02X})"
        print(f"   20-byte frame, checksum 0x{raw[19]:02X} [{ok}]")
    else:
        print(f"   {len(raw)} bytes (not a 20-byte frame)")


async def main():
    print(f"connecting (read-only) to {ADDR} ...")
    async with BleakClient(ADDR, timeout=30) as c:
        print(f"connected: {c.is_connected}\n")

        print("== STATUS (direct read, no write) ==")
        raw = bytes(await c.read_gatt_char(P.CHAR_STATUS))
        print(f"   raw: {raw.hex(' ')}")
        verify20("STATUS", raw)
        body = raw[:19] if len(raw) == 20 else raw
        st = P.parse_status(body)
        print(f"   parsed: {st.describe()}")
        print(f"   (mode_settings byte = "
              f"0x{st.mode_settings:02X})" if st.mode_settings is not None else "")

        print("\n== RESULT (direct read) ==")
        r = bytes(await c.read_gatt_char(P.CHAR_RESULT))
        print(f"   raw: {r.hex(' ')}")
        verify20("RESULT", r)

        print("\n== identity characteristics ==")
        for uuid, label, binary in (
                (P.CHAR_MODEL_NAME, "model", False),
                (P.CHAR_SERIAL_NUMBER, "serial", False),
                (P.CHAR_FIRMWARE_VERSION, "firmware", True),
                (P.CHAR_DEVICE_NAME, "name", False)):
            v = bytes(await c.read_gatt_char(uuid))
            payload = v[:19] if len(v) == 20 else v
            payload = payload.rstrip(b"\xff")
            if binary:
                shown = ".".join(str(b) for b in payload)
            else:
                shown = payload.decode("ascii", "replace")
            calc = P.checksum(v[:19]) if len(v) == 20 else None
            tag = "" if calc is None else (
                " [csum OK]" if calc == v[19] else f" [csum BAD {calc:#04x}]")
            print(f"   {label:9s} {v.hex(' ')}")
            print(f"   {'':9s} -> \"{shown}\"{tag}")

        print("\n== live STATUS notifications (15s, still no writes) ==")
        seen = []

        def cb(_ch, data: bytearray):
            raw = bytes(data)
            seen.append(raw)
            b = raw[:19] if len(raw) == 20 else raw
            print(f"   <STATUS> {raw.hex(' ')}")
            print(f"            {P.parse_status(b).describe()}")

        await c.start_notify(P.CHAR_STATUS, cb)
        await asyncio.sleep(15)
        await c.stop_notify(P.CHAR_STATUS)
        print(f"   {len(seen)} unsolicited notification(s) received")

    print("\ndone (nothing was written).")


asyncio.run(main())
