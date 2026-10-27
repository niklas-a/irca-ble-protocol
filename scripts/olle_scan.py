"""Scan for the Olle / Zoppas towel-dryer controller over BLE.

Read-only: scans and (optionally) connects to enumerate the GATT table.
Nothing is written to the device.

Usage:
    python olle_scan.py                 # just scan
    python olle_scan.py --enumerate     # scan, then connect and dump GATT
    python olle_scan.py --addr AA:BB:.. # target a specific address
"""
import asyncio
import sys

from bleak import BleakClient, BleakScanner

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


async def scan(timeout=12.0):
    print(f"scanning {timeout:.0f}s ...\n")
    found = await BleakScanner.discover(timeout=timeout, return_adv=True)
    hits = []
    for addr, (dev, adv) in sorted(found.items(), key=lambda x: -(x[1][1].rssi or -999)):
        svcs = [s.lower() for s in (adv.service_uuids or [])]
        is_zoppas = ZOPPAS_SERVICE in svcs
        name = adv.local_name or dev.name or "(no name)"
        mark = "  <== ZOPPAS/OLLE SERVICE" if is_zoppas else ""
        print(f"{addr}  rssi={adv.rssi:>4}  {name}{mark}")
        if svcs:
            for s in svcs:
                tag = f"  [{CHARS.get(s, 'ZOPPAS SERVICE' if s == ZOPPAS_SERVICE else '')}]" if (
                    s == ZOPPAS_SERVICE or s in CHARS) else ""
                print(f"        svc {s}{tag}")
        if adv.manufacturer_data:
            for cid, data in adv.manufacturer_data.items():
                print(f"        mfg 0x{cid:04X}: {data.hex(' ')}")
        if adv.service_data:
            for k, v in adv.service_data.items():
                print(f"        svcdata {k}: {v.hex(' ')}")
        if is_zoppas:
            hits.append(addr)
    print()
    return hits


async def enumerate_gatt(addr):
    print(f"\nconnecting to {addr} ...")
    async with BleakClient(addr, timeout=30) as client:
        print(f"connected: {client.is_connected}\n")
        for svc in client.services:
            tag = "   <== ZOPPAS SERVICE" if svc.uuid.lower() == ZOPPAS_SERVICE else ""
            print(f"[service] {svc.uuid}  {svc.description}{tag}")
            for ch in svc.characteristics:
                label = CHARS.get(ch.uuid.lower(), "")
                props = ",".join(ch.properties)
                print(f"    [char] handle=0x{ch.handle:04X} {ch.uuid} "
                      f"({props}) {label}")
                for d in ch.descriptors:
                    print(f"        [desc] handle=0x{d.handle:04X} {d.uuid}")
                if "read" in ch.properties and label in (
                        "MODEL_NAME", "SERIAL_NUMBER", "FIRMWARE_VERSION",
                        "DEVICE_NAME"):
                    try:
                        val = await client.read_gatt_char(ch)
                        txt = bytes(val).rstrip(b"\xff\x00").decode("ascii", "replace")
                        print(f"        value: {bytes(val).hex(' ')}  -> \"{txt}\"")
                    except Exception as e:
                        print(f"        read failed: {e}")


async def main():
    addr = None
    if "--addr" in sys.argv:
        addr = sys.argv[sys.argv.index("--addr") + 1]
    hits = [] if addr else await scan()
    if addr:
        hits = [addr]
    if "--enumerate" in sys.argv:
        if not hits:
            print("no Zoppas/Olle device found to enumerate.")
            return
        for a in hits:
            try:
                await enumerate_gatt(a)
            except Exception as e:
                print(f"enumerate {a} failed: {e}")


if __name__ == "__main__":
    asyncio.run(main())
