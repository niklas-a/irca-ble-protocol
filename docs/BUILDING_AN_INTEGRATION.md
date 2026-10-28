# Turning this into a Home Assistant integration (or a standalone app)

This document is the bridge between `OLLE_BLE_PROTOCOL.md` (what the device
speaks) and a shippable product. Read the protocol spec first; everything here
assumes it.

The reference code in `scripts/` is deliberately split so the useful half can be
lifted out unchanged:

| File | Role | Reusable? |
|---|---|---|
| `olle_protocol.py` | Pure frame building/parsing, **no I/O, no deps** | ✅ This becomes the library |
| `test_protocol.py` | 62 offline assertions incl. real-hardware frames | ✅ Becomes the library's test suite |
| `olle_ctl.py` | bleak CLI | Reference only — HA manages its own connections |
| `olle_scan.py`, `probe_status.py` | Discovery / read-only probing | Debug tooling |
| `get_snoop.py`, `decode_btsnoop.py`, `snoop_stats.py` | Android btsnooz → ATT decoding | Only needed for further RE |

---

## 1. Decide the entity model first

This is the decision that most shapes the integration, and it is easy to get
wrong because **the device has three different value families** (protocol spec
§6). Byte 9 of `STATUS` tells you which:

| `mode_settings` | Family | Natural HA entity |
|---|---|---|
| `0xAA` CELSIUS | Real °C setpoints, 15–30 | `climate` |
| `0xA5` FAHRENHEIT | Real °F setpoints, 45–90 | `climate` |
| `0x55` POWER | Abstract **level 1–10** — *not a temperature* | `number` + `select`, **not** `climate` |

**Do not model a POWER unit as a `climate` entity.** HA's climate platform is
built around a target temperature in real units; feeding it a 1–10 level
produces a thermostat card claiming "5 °C" and a UI that lets users request
physically meaningless values. The unit this protocol was verified against is a
POWER unit, so this is the common case in Nordic markets, not an edge case.

A clean mapping that covers all three:

```
switch.<name>                  SET_ON / SET_OFF
select.<name>_mode             SET_MODE -> OFF/BOOST/COMFORT/ECO/ANTIFREEZE/SCHEDULE/MANUAL
sensor.<name>_alarm            STATUS[8]   (diagnostic)
binary_sensor.<name>_window    STATUS[14]  (diagnostic)
switch.<name>_child_lock       SET_LOCK    (0x55 / 0xAA)
sensor.<name>_firmware         read once   (diagnostic, entity_category=diagnostic)

# Celsius / Fahrenheit units only:
climate.<name>                 target temp = SET_TEMP_MANUAL, presets = modes

# POWER units only:
number.<name>_level            1..10, step 1, SET_TEMP_MANUAL with the raw level
number.<name>_eco              1..10, SET_TEMP_ECO
number.<name>_comfort          1..10, SET_TEMP_COMFORT
```

Decide this at runtime from the first `STATUS` read, not from config. A user can
change the unit on the device itself (`SET_MODE_SETTINGS`), so the integration
should re-evaluate and, if it changes, ask the user to reload rather than
silently reinterpreting values.

### Do not expose

* `FACTORY_RESET` (`0x16`) — no UI affordance should exist for this.
* Anything touching the Nordic DFU service.
* `CIP` as a power sensor until someone validates it against a real meter
  (protocol spec §9). Shipping an unvalidated `device_class: power` sensor
  pollutes users' energy dashboards with fiction.

---

## 2. Repository layout

Two packages, because the protocol library is useful to people who are not
running Home Assistant (and because HA's quality scale expects device I/O to
live in an external library):

```
irca-ble-protocol/
├─ docs/
│  ├─ OLLE_BLE_PROTOCOL.md
│  └─ BUILDING_AN_INTEGRATION.md
├─ ircable/                      # the PyPI library
│  ├─ __init__.py
│  ├─ protocol.py                # <- olle_protocol.py, unchanged
│  ├─ client.py                  # bleak wrapper: connect, auth, send, poll
│  └─ const.py
├─ tests/
│  └─ test_protocol.py           # <- test_protocol.py, unchanged
├─ custom_components/irca_ble/   # the HA integration
│  ├─ __init__.py
│  ├─ manifest.json
│  ├─ config_flow.py
│  ├─ coordinator.py
│  ├─ entity.py
│  ├─ switch.py  number.py  select.py  sensor.py  binary_sensor.py
│  └─ strings.json
└─ scripts/                      # the CLI/debug tools from this repo
```

---

## 3. The library layer (`ircable/client.py`)

Keep `protocol.py` pure. Put all Bluetooth behaviour in a client class whose
job is: hold a connection, serialize requests, match responses by sequence,
and expose `async` methods.

Three things the protocol forces on you:

**a) Poll — the device never pushes.** Verified: 15 s idle produced zero
unsolicited `STATUS`. Subscribe to `STATUS`/`RESULT`, then drive updates with
`REFRESH_STATUS`.

**b) Match responses on `[status][opcode][seq]`.** Byte 1 is the opcode echo,
byte 2 is your sequence (spec §7 — the vendor app gets this wrong). Matching on
the opcode alone breaks the moment two commands of the same type are in flight.

**c) Serialize everything.** The vendor app holds a semaphore around writes and
writes CCCDs one at a time. Concurrent GATT operations are dropped by several
stacks.

```python
class IrcaClient:
    def __init__(self, ble_device, device_id: str | None = None):
        self._dev = ble_device
        self._device_id = device_id
        self._lock = asyncio.Lock()          # (c) one command at a time
        self._seq = 0
        self._pending: dict[int, asyncio.Future] = {}
        self.status: protocol.Status | None = None

    def _on_result(self, _char, data: bytearray):
        r = protocol.parse_result(bytes(data))
        fut = self._pending.pop(r.seq, None)   # (b) match on byte 2
        if fut and not fut.done():
            fut.set_result(r)

    async def _command(self, frame: bytes, timeout: float = 5.0):
        async with self._lock:
            seq = frame[1]
            fut = asyncio.get_running_loop().create_future()
            self._pending[seq] = fut
            try:
                await self._client.write_gatt_char(protocol.CHAR_CMD, frame, response=True)
                return await asyncio.wait_for(fut, timeout)
            finally:
                self._pending.pop(seq, None)

    async def refresh(self) -> protocol.Status:
        await self._command(protocol.cmd_refresh_status(self._next_seq()))
        return self.status                      # (a) updated by the STATUS callback
```

Sequence numbers wrap at 256 and `0` is legal; just make sure a pending
sequence is never reused while in flight.

### Authentication

Per spec §5.1, `AUTH_DEVICE` is **not enforced** on tested firmware — reads and
at least `REFRESH_STATUS` work without it. So:

* Make `device_id` **optional** in config.
* If present, send `AUTH_DEVICE` after connecting and log the result.
* Treat auth failure as a **warning, not a connection failure**.

This matters a lot for usability: requiring a `device_id` would force every user
to root their phone or sniff BLE, which is exactly the barrier that kills
integrations like this. (That barrier is real — see spec §12.1 for how hard it
was to extract one from a stock Samsung.)

If you later find firmware that *does* enforce auth, the recovery path is
`REGISTER_DEVICE` (`0x01`) while the unit is in pairing mode, which lets the
integration enroll its own id rather than borrowing the phone's.

---

## 4. The Home Assistant layer

### Discovery (`manifest.json`)

The device **does not advertise its service UUID** (spec §1.1.2), so a
`service_uuid` matcher will never fire. Match on the local name:

```json
{
  "domain": "irca_ble",
  "name": "IRCA BLE Heater",
  "bluetooth": [{ "local_name": "Olle" }],
  "config_flow": true,
  "dependencies": ["bluetooth_adapters"],
  "iot_class": "local_polling",
  "requirements": ["ircable==0.1.0"]
}
```

`local_name: "Olle"` is broad, so the config flow **must** confirm by connecting
and checking that service `35ba1523-…` is present before offering the device.
Sibling products (Deltacalor, StoneBLE) likely advertise different names but
share the stack — add matchers as they're confirmed, don't guess.

`iot_class` is `local_polling`, not `local_push` — the device does not push.

### Connection management

Never construct `BleakClient` yourself in HA. Use the shared adapter and the
retry wrapper, which handles the ESPHome-proxy and BlueZ edge cases:

```python
from homeassistant.components import bluetooth
from bleak_retry_connector import establish_connection

ble_device = bluetooth.async_ble_device_from_address(hass, address, connectable=True)
client = await establish_connection(BleakClient, ble_device, address)
```

### Connection lifetime: transient, not persistent

**Recommendation: connect per operation and disconnect afterwards.** Do not
hold the link open between polls.

Three reasons, in order of weight:

1. **The heater accepts one connection at a time.** A persistent HA connection
   means the owner can never open the vendor app — or this project's Android
   app — without first disabling the integration. That is a daily annoyance,
   not a theoretical one.
2. **The firmware doesn't want a persistent link anyway.** It hangs up on idle
   connections after a minute or two (spec §12.3.1). Keeping one alive costs a
   `REFRESH_STATUS` every ~20 s *purely as a keepalive* — pointless traffic for
   a device whose state changes a few times a day.
3. **Recovery is the unreliable path.** Automatic reconnection after a drop
   proved flaky in testing, while a fresh connect succeeded immediately every
   time. Transient connections never enter the failure mode at all.

So the idle-drop behaviour is an argument *for* transient connections, not a
problem to engineer around.

```python
class IrcaCoordinator(DataUpdateCoordinator[protocol.Status]):
    def __init__(self, hass, address, device_id=None):
        super().__init__(hass, _LOGGER, name="irca_ble",
                         update_interval=timedelta(seconds=90))

    async def _async_update_data(self) -> protocol.Status:
        async with IrcaClient(self._ble_device(), self._device_id) as c:
            return await c.refresh()
```

**Batch the write and the read-back into one connection.** A command should be
connect → (optional auth) → write → await `RESULT` → `REFRESH_STATUS` → read
`STATUS` → disconnect. Doing the command and the confirmation as two separate
connections doubles the latency for no benefit:

```python
async def async_set_mode(self, mode: protocol.Mode) -> protocol.Status:
    async with IrcaClient(self._ble_device(), self._device_id) as c:
        await c.set_mode(mode)
        return await c.refresh()          # same connection
    # coordinator.async_set_updated_data(status) afterwards - no second connect
```

Then call `coordinator.async_set_updated_data(...)` with what you read, rather
than `async_request_refresh()`, which would open a third connection. Always
reflect what the device reported, never an optimistic guess — `SET_ON` resumes
the stored mode rather than a neutral state (spec §12.3), so an optimistic UI
will be wrong.

**Cost of a transient connect.** Roughly 1–3 s including service discovery.
`bleak-retry-connector` caches the GATT service table per address, so repeat
connections skip discovery and land at the lower end. For a towel rail that is
entirely acceptable; if it ever isn't, the fix is a short-lived connection that
lingers a few seconds after the last command, not a permanently open one.

**Poll slowly.** 60–120 s is plenty. BLE polling costs airtime and, on an
ESPHome proxy, contention with every other device that proxy serves.

> **Why the Android app in this repo does the opposite.** It holds the
> connection open and polls every 20 s, because it is a foreground interactive
> UI: the user is looking at it and expects the dial to respond immediately.
> That trade-off is right for a screen someone is actively using and wrong for
> a background integration. Don't copy `Controller.java`'s lifetime model into
> Home Assistant.

---

## 5. Testing

The protocol library is pure, so it tests without hardware. `tests/` already
contains 62 assertions, including real captured frames as regressions. Add:

* Round-trip tests for every command builder (build → parse → compare).
* A fuzz test asserting `parse_status` never raises on arbitrary 0–20 byte
  inputs. The device returned `window_detection = 0xFF`, which is outside the
  documented `0..3` enum — defensive parsing is not optional here.
* Golden-frame tests for a Celsius unit **once someone with one contributes a
  capture**. The `×10 − 70` codec is derived from two independent places in the
  app but has never been seen on hardware.

For the HA layer, `pytest-homeassistant-custom-component` with a mocked client;
don't put real BLE in CI.

---

## 6. Publishing checklist

**Legal** (see spec §11 for the full framing):

- [ ] Ship **no** decompiled source, **no** APK, **no** vendor strings or art.
- [ ] Clean-room only: everything written from the spec.
- [ ] Name avoids implying endorsement. `irca-ble-protocol` is fine;
      "Olle Connect for HA" is not.
- [ ] Note in the README that this is unaffiliated with IRCA / Zoppas /
      Somatherm.

**Security disclosure.** The spec documents that these heaters accept commands
from anyone in radio range with no authentication. That is worth telling the
vendor before it becomes widely known. Reasonable approach: email IRCA/Zoppas
with the finding and a date you intend to publish (90 days is the usual
courtesy), and keep the repo private until then. If you've already published,
tell them anyway — the README should state the limitation plainly so owners can
make their own call about where they put the device.

**Housekeeping:**

- [ ] `hacs.json` + topics `home-assistant`, `hacs`, `bluetooth` for discovery.
- [ ] Never commit a real `device_id`, BLE address, or serial number.
- [ ] `.gitignore` must exclude `apk/`, `decompiled/`, `captures/` — bugreport
      zips in particular contain the phone owner's installed apps, accounts and
      system logs.
- [ ] State clearly which commands are hardware-verified and which are
      spec-only (spec §9). Users deserve to know they're running the first test.

---

## 7. Roadmap

Roughly in order of value per unit of effort:

1. **Verify the write path.** `SET_ON`/`SET_OFF` round-trip, then setpoints.
   Everything downstream assumes these work; nothing has confirmed it.
2. **Ship read-only first.** A sensors-only integration is genuinely useful,
   carries near-zero risk, and gets real users generating real `STATUS` frames
   from Celsius and Fahrenheit units.
3. **Add control** once (1) is confirmed on more than one unit.
4. **Multipart.** `READ_STATS`, `READ_CHRONO`/`SET_CHRONO`, `READ_DIAGNOSTICS`
   use the `MULTIPART_DATA`/`MULTIPART_RESULT` pair with a delegate/paging
   scheme that this project has not analysed. Scheduling and energy history
   live here — the largest remaining chunk of unmapped protocol.
5. **Sibling products.** The same APK carries `Deltacalor` and `StoneBLE` build
   configurators, so the stack almost certainly covers more IRCA hardware.
   Someone with one of those devices can confirm cheaply with `olle_scan.py`.
