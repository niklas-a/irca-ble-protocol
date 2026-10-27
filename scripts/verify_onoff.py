"""Verify the write path: SET_ON -> read back -> SET_OFF -> read back.

Deliberately conservative:
  * records the mode the device was in before we touched it
  * only sends SET_ON / SET_OFF / REFRESH_STATUS (no setpoint changes)
  * always attempts to restore the original mode, even on error or Ctrl-C
  * reports exactly what the device echoed, with no optimistic assumptions

Usage:  python verify_onoff.py <BLE address> [--on-seconds 10]
"""
import asyncio
import sys

from bleak import BleakClient

import olle_protocol as P

if len(sys.argv) < 2:
    raise SystemExit("usage: python verify_onoff.py <BLE address> [--on-seconds N]")
ADDR = sys.argv[1]
ON_SECONDS = 10.0
if "--on-seconds" in sys.argv:
    ON_SECONDS = float(sys.argv[sys.argv.index("--on-seconds") + 1])


class Session:
    def __init__(self, client):
        self.c = client
        self.seq = 0
        self.status = None
        self.results = []
        self._evt = asyncio.Event()

    def next_seq(self):
        self.seq = (self.seq + 1) & 0xFF
        return self.seq

    def _on_status(self, _ch, data):
        self.status = P.parse_status(bytes(data))
        print(f"      <STATUS> {bytes(data).hex(' ')}")
        print(f"               {self.status.describe()}")

    def _on_result(self, _ch, data):
        r = P.parse_result(bytes(data))
        self.results.append(r)
        self._evt.set()
        print(f"      <RESULT> {bytes(data).hex(' ')}")
        print(f"               {r.describe()}")

    async def subscribe(self):
        await self.c.start_notify(P.CHAR_STATUS, self._on_status)
        await self.c.start_notify(P.CHAR_RESULT, self._on_result)

    async def send(self, frame, label, timeout=6.0):
        if not P.verify_frame(frame):
            raise RuntimeError("refusing to send: checksum self-check failed")
        print(f"\n   -> {label}")
        print(f"      frame:   {frame.hex(' ')}")
        self._evt.clear()
        n = len(self.results)
        await self.c.write_gatt_char(P.CHAR_CMD, frame, response=True)
        try:
            await asyncio.wait_for(self._evt.wait(), timeout)
        except asyncio.TimeoutError:
            print(f"      (no RESULT within {timeout:.0f}s)")
            return None
        return self.results[n] if len(self.results) > n else None

    async def read_status(self, label):
        raw = bytes(await self.c.read_gatt_char(P.CHAR_STATUS))
        st = P.parse_status(raw)
        print(f"\n   {label}")
        print(f"      raw:     {raw.hex(' ')}")
        print(f"      decoded: {st.describe()}")
        return st


async def main():
    print(f"connecting to {ADDR} ...")
    async with BleakClient(ADDR, timeout=30) as c:
        print(f"connected: {c.is_connected}")
        s = Session(c)
        await s.subscribe()
        await asyncio.sleep(0.4)

        before = await s.read_status("BEFORE (baseline)")
        original_mode = before.mode
        print(f"\n   baseline mode = {original_mode} "
              f"({P.Mode(original_mode).name if original_mode is not None else '?'})")

        restored = False
        try:
            r_on = await s.send(P.cmd_on(s.next_seq()), "SET_ON (0x0D)")
            await asyncio.sleep(2.5)
            during = await s.read_status(f"AFTER SET_ON")

            print(f"\n   holding ON for {ON_SECONDS:.0f}s ...")
            await asyncio.sleep(ON_SECONDS)

            r_off = await s.send(P.cmd_off(s.next_seq()), "SET_OFF (0x0E)")
            restored = True
            await asyncio.sleep(2.5)
            after = await s.read_status("AFTER SET_OFF")

            print("\n" + "=" * 62)
            print("VERDICT")
            print("=" * 62)

            def verdict(label, res, st, expect_on):
                ack = "no RESULT" if res is None else (
                    "ACK ok" if res.ok else f"ACK {res.describe()}")
                echo = ""
                if res is not None and res.action is not None:
                    want = P.Action.SET_ON if expect_on else P.Action.SET_OFF
                    echo = (" opcode echo OK" if res.action == want
                            else f" opcode echo MISMATCH (0x{res.action:02X})")
                changed = (st.mode != original_mode) if st else None
                print(f"  {label:10s} {ack}{echo}")
                print(f"  {'':10s} mode now = "
                      f"{P.Mode(st.mode).name if st and st.mode is not None else '?'}"
                      f"   (changed from baseline: {changed})")

            verdict("SET_ON", r_on, during, True)
            verdict("SET_OFF", r_off, after, False)

            ok = (r_on is not None and r_on.ok
                  and during is not None and during.mode != original_mode)
            print()
            if ok:
                print("  => WRITE PATH CONFIRMED: the device accepted SET_ON and")
                print("     its reported mode changed.")
            elif r_on is not None and r_on.ok:
                print("  => PARTIAL: command was acknowledged OK but the reported")
                print("     mode did not change. The ack may be optimistic, or the")
                print("     unit may need a setpoint/mode before it will run.")
            else:
                print("  => NOT CONFIRMED: see the RESULT status above.")
            print(f"\n  restored to baseline mode: "
                  f"{after.mode == original_mode if after else 'unknown'}")
        finally:
            if not restored:
                print("\n   !! restoring: sending SET_OFF")
                try:
                    await s.send(P.cmd_off(s.next_seq()), "SET_OFF (restore)")
                except Exception as e:
                    print(f"   restore failed: {e}")
    print("\ndisconnected.")


asyncio.run(main())
