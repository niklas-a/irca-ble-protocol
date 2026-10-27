"""Talk to an Olle / IRCA / Zoppas towel-rail controller over BLE using bleak.

Read-only by default: commands that change device state require an explicit
subcommand, and --dry-run prints the frame without sending it.

Typical use:
    python olle_ctl.py --scan
    python olle_ctl.py --addr AA:BB:CC:DD:EE:FF --device-id "0f2a9c1e-4b77-4" info
    python olle_ctl.py --addr ... --device-id ... status
    python olle_ctl.py --addr ... --device-id ... monitor --seconds 60
    python olle_ctl.py --addr ... --device-id ... on
    python olle_ctl.py --addr ... --device-id ... temp 21.5
    python olle_ctl.py --addr ... --device-id ... mode COMFORT
"""
from __future__ import annotations

import argparse
import asyncio
import sys

from bleak import BleakClient, BleakScanner

import olle_protocol as P


def hexs(b) -> str:
    return bytes(b).hex(" ")


class Olle:
    def __init__(self, client: BleakClient, device_id: str | None, verbose=True):
        self.c = client
        self.device_id = device_id
        self.verbose = verbose
        self.seq = 0
        self.last_status: P.Status | None = None
        self.results: list[P.Result] = []
        self._result_evt = asyncio.Event()

    def next_seq(self) -> int:
        self.seq = (self.seq + 1) & 0xFF
        return self.seq

    # -- notifications -----------------------------------------------------
    def _on_status(self, _ch, data: bytearray):
        st = P.parse_status(bytes(data))
        self.last_status = st
        print(f"  <STATUS>  {hexs(data)}")
        print(f"            {st.describe()}")

    def _on_result(self, _ch, data: bytearray):
        r = P.parse_result(bytes(data))
        self.results.append(r)
        self._result_evt.set()
        print(f"  <RESULT>  {hexs(data)}   {r.describe()}")

    def _on_other(self, label):
        def cb(_ch, data: bytearray):
            txt = bytes(data).rstrip(b"\xff\x00").decode("ascii", "replace")
            print(f"  <{label}>  {hexs(data)}   \"{txt}\"")
        return cb

    async def subscribe(self):
        labels = {
            P.CHAR_STATUS: ("STATUS", self._on_status),
            P.CHAR_RESULT: ("RESULT", self._on_result),
        }
        for uuid in P.NOTIFY_CHARS:
            name = {
                P.CHAR_MULTIPART_RESULT: "MPRESULT",
                P.CHAR_MODEL_NAME: "MODEL",
                P.CHAR_SERIAL_NUMBER: "SERIAL",
                P.CHAR_FIRMWARE_VERSION: "FIRMWARE",
            }.get(uuid)
            try:
                if uuid in labels:
                    await self.c.start_notify(uuid, labels[uuid][1])
                else:
                    await self.c.start_notify(uuid, self._on_other(name or "NOTIFY"))
            except Exception as e:
                print(f"  (could not subscribe {uuid}: {e})")

    # -- writes ------------------------------------------------------------
    async def send(self, frame: bytes, what: str, dry_run=False,
                   wait_result=True, timeout=5.0):
        print(f"\n-> {what}")
        print(f"   frame: {hexs(frame)}")
        if not P.verify_frame(frame):
            print("   !! checksum self-check FAILED, refusing to send")
            return None
        if dry_run:
            print("   (dry run - not sent)")
            return None
        self._result_evt.clear()
        before = len(self.results)
        await self.c.write_gatt_char(P.CHAR_CMD, frame, response=True)
        if not wait_result:
            return None
        try:
            await asyncio.wait_for(self._result_evt.wait(), timeout)
        except asyncio.TimeoutError:
            print(f"   (no RESULT within {timeout:.0f}s)")
            return None
        return self.results[before] if len(self.results) > before else None

    async def authenticate(self, dry_run=False) -> bool:
        if not self.device_id:
            print("\n!! no --device-id given; skipping AUTH_DEVICE.")
            print("   Reads may still work; writes will likely be rejected.")
            return False
        frame = P.cmd_auth(self.device_id, self.next_seq())
        r = await self.send(frame, f'AUTH_DEVICE  id="{self.device_id[:16]}"',
                            dry_run=dry_run)
        if r is None:
            return False
        if r.ok:
            print("   AUTHENTICATED")
            return True
        print(f"   AUTH FAILED: {r.describe()}")
        return False


async def read_info(client: BleakClient):
    for uuid, label in ((P.CHAR_MODEL_NAME, "model"),
                        (P.CHAR_SERIAL_NUMBER, "serial"),
                        (P.CHAR_FIRMWARE_VERSION, "firmware"),
                        (P.CHAR_DEVICE_NAME, "device name")):
        try:
            v = await client.read_gatt_char(uuid)
            txt = bytes(v).rstrip(b"\xff\x00").decode("ascii", "replace")
            print(f"  {label:12s} {hexs(v)}  -> \"{txt}\"")
        except Exception as e:
            print(f"  {label:12s} read failed: {e}")


async def find_device(timeout=12.0):
    print(f"scanning {timeout:.0f}s for the Zoppas service ...")
    found = await BleakScanner.discover(timeout=timeout, return_adv=True)
    for addr, (dev, adv) in found.items():
        if P.SERVICE_UUID in [s.lower() for s in (adv.service_uuids or [])]:
            print(f"found {addr}  rssi={adv.rssi}  {adv.local_name or dev.name}")
            return addr
    return None


async def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--addr")
    ap.add_argument("--device-id", help="16-char auth id (from the capture)")
    ap.add_argument("--scan", action="store_true", help="scan and exit")
    ap.add_argument("--dry-run", action="store_true",
                    help="print frames without sending")
    ap.add_argument("--no-auth", action="store_true",
                    help="skip AUTH_DEVICE (to test what works unauthenticated)")
    ap.add_argument("--celsius", action="store_true", default=True)
    ap.add_argument("--fahrenheit", dest="celsius", action="store_false")
    sub = ap.add_subparsers(dest="cmd")

    sub.add_parser("info")
    sub.add_parser("status")
    m = sub.add_parser("monitor"); m.add_argument("--seconds", type=float, default=60)
    sub.add_parser("on")
    sub.add_parser("off")
    t = sub.add_parser("temp"); t.add_argument("value", type=float)
    md = sub.add_parser("mode"); md.add_argument("name")
    b = sub.add_parser("boost"); b.add_argument("hours", type=int)
    lk = sub.add_parser("lock"); lk.add_argument("state", choices=["on", "off"])
    for nm in ("eco", "comfort", "antifreeze"):
        s = sub.add_parser(nm); s.add_argument("value", type=float)

    args = ap.parse_args()

    if args.scan or not args.addr:
        addr = await find_device()
        if args.scan:
            return
        if not addr:
            print("no device found; pass --addr explicitly")
            return 1
        args.addr = addr

    print(f"\nconnecting to {args.addr} ...")
    async with BleakClient(args.addr, timeout=30) as client:
        print(f"connected: {client.is_connected}\n")

        svc_uuids = [s.uuid.lower() for s in client.services]
        if P.SERVICE_UUID not in svc_uuids:
            print(f"!! {P.SERVICE_UUID} not present on this device.")
            print("   services:", ", ".join(svc_uuids))
            return 1

        o = Olle(client, args.device_id)
        await o.subscribe()
        await asyncio.sleep(0.5)

        if not args.no_auth:
            await o.authenticate(dry_run=args.dry_run)
            await asyncio.sleep(0.5)

        c = args.cmd
        if c == "info":
            await read_info(client)
        elif c in (None, "status"):
            await o.send(P.cmd_refresh_status(o.next_seq()), "REFRESH_STATUS",
                         dry_run=args.dry_run)
            await asyncio.sleep(2.0)
            if o.last_status:
                print(f"\nstatus: {o.last_status.describe()}")
        elif c == "monitor":
            print(f"listening {args.seconds:.0f}s (Ctrl-C to stop) ...")
            await o.send(P.cmd_refresh_status(o.next_seq()), "REFRESH_STATUS",
                         dry_run=args.dry_run)
            await asyncio.sleep(args.seconds)
        elif c == "on":
            await o.send(P.cmd_on(o.next_seq()), "SET_ON", dry_run=args.dry_run)
        elif c == "off":
            await o.send(P.cmd_off(o.next_seq()), "SET_OFF", dry_run=args.dry_run)
        elif c == "temp":
            await o.send(P.cmd_set_temp_manual(args.value, args.celsius, o.next_seq()),
                         f"SET_TEMP_MANUAL {args.value}", dry_run=args.dry_run)
        elif c == "mode":
            mode = P.Mode[args.name.upper()]
            await o.send(P.cmd_set_mode(mode, o.next_seq()),
                         f"SET_MODE {mode.name}", dry_run=args.dry_run)
        elif c == "boost":
            await o.send(P.cmd_set_boost_hours(args.hours, o.next_seq()),
                         f"SET_PERIOD_BOOST {args.hours}h", dry_run=args.dry_run)
        elif c == "lock":
            await o.send(P.cmd_set_lock(args.state == "on", o.next_seq()),
                         f"SET_LOCK {args.state}", dry_run=args.dry_run)
        elif c in ("eco", "comfort", "antifreeze"):
            fn = {"eco": P.cmd_set_temp_eco, "comfort": P.cmd_set_temp_comfort,
                  "antifreeze": P.cmd_set_temp_antifreeze}[c]
            await o.send(fn(args.value, args.celsius, o.next_seq()),
                         f"SET_TEMP_{c.upper()} {args.value}", dry_run=args.dry_run)

        await asyncio.sleep(1.5)
    print("\ndisconnected.")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()) or 0)
