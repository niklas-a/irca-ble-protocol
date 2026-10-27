# Olle / IRCA / Zoppas towel-rail — BLE protocol specification

Reverse-engineered from **Olle Connect v3.6** (`com.ecodomesticheating.olle.app`,
versionCode 3600), pulled from a Galaxy S24+ and decompiled with jadx 1.5.6.

The BLE implementation lives in the package `com.sysdata.zoppas.blepoc` — written
by Sysdata for **Zoppas Industries**, the group that owns **IRCA**. The same
stack is shared by sibling apps (there are build configurators for `Olle`,
`Deltacalor` and `StoneBLE` in the same APK), so this protocol very likely
applies to other IRCA-controlled heaters, not just Somatherm towel rails.

The app's Java is **not obfuscated**, so almost every name below is the
manufacturer's own.

---

## 1. Transport

Bluetooth Low Energy, GATT. No BLE pairing/bonding is required — the device uses
an application-level `AUTH_DEVICE` handshake instead (see §5).

The device also exposes a **Nordic Semiconductor DFU** service (the APK bundles
`no.nordicsemi.android.dfu`), which indicates an nRF5x-class SoC. DFU is out of
scope here and should be left alone.

### 1.1 GATT table

Primary service: **`35ba1523-94f5-9052-4cd4-f102b6580adf`**

| UUID | App name | Direction | Notes |
|---|---|---|---|
| `35ba1524-94f5-9052-4cd4-f102b6580adf` | `STATUS` | notify | Unsolicited device state, 15 bytes (§6) |
| `35ba1525-94f5-9052-4cd4-f102b6580adf` | `CMD` | write | **All commands go here**, always 20 bytes (§3) |
| `35ba1526-94f5-9052-4cd4-f102b6580adf` | `RESULT` | notify | Per-command ack (§7) |
| `35ba1527-94f5-9052-4cd4-f102b6580adf` | `MULTIPART_DATA` | write | Bulk upload (schedules) |
| `35ba1528-94f5-9052-4cd4-f102b6580adf` | `MULTIPART_RESULT` | notify | Bulk download (stats, schedules, diagnostics) |
| `35ba1529-94f5-9052-4cd4-f102b6580adf` | `MODEL_NAME` | read/notify | ASCII, `0xFF`-padded |
| `35ba1530-94f5-9052-4cd4-f102b6580adf` | `SERIAL_NUMBER` | read/notify | ASCII, `0xFF`-padded |
| `35ba1531-94f5-9052-4cd4-f102b6580adf` | `FIRMWARE_VERSION` | read/notify | ASCII, `0xFF`-padded |
| `35ba1532-94f5-9052-4cd4-f102b6580adf` | `DEVICE_NAME` | read/write | User-assigned name |

Also used: standard Generic Access `0x1800` / Device Name `0x2A00`.

**Observed on real hardware** (Olle, fw 3.2.0) — handles will differ per
device, properties should not:

```
[service] 35ba1523-...                                  <- Zoppas service
    0x0015  35ba1524  (notify, read)   STATUS
    0x0018  35ba1525  (write,  read)   CMD
    0x001A  35ba1526  (notify, read)   RESULT
    0x001D  35ba1527  (write,  read)   MULTIPART_DATA
    0x001F  35ba1528  (notify, read)   MULTIPART_RESULT
    0x0022  35ba1529  (read)           MODEL_NAME
    0x0024  35ba1530  (read)           SERIAL_NUMBER
    0x0026  35ba1531  (read)           FIRMWARE_VERSION
    0x0028  35ba1532  (write,  read)   DEVICE_NAME
```

Two corrections to what the app's own code implies:

* `STATUS`, `RESULT` and `MULTIPART_RESULT` are the **only** notifiable
  characteristics. `MODEL_NAME`, `SERIAL_NUMBER` and `FIRMWARE_VERSION` are
  **read-only** — the app tries to subscribe to them and the subscription
  silently fails. Read them instead.
* The device also exposes the Nordic DFU service
  `00001530-1212-efde-1523-785feabcd123`, confirming the nRF5x SoC.

### 1.1.1 Everything is a 20-byte frame

The identity characteristics are **not** bare strings — they are the same
20-byte frame with the same trailing XOR checksum. Verified by reading them:

| Characteristic | Raw | Decoded |
|---|---|---|
| `MODEL_NAME` | 12 ASCII bytes + `ff` padding + checksum | e.g. `"0000AAAABBBB"` |
| `SERIAL_NUMBER` | 11 ASCII bytes + `ff` padding + checksum | e.g. `"HB000000000"` |
| `FIRMWARE_VERSION` | `03 02 00` + `ff`×16 + `01` | **binary** → `3.2.0` |
| `DEVICE_NAME` | `4f 6c 6c 65` + `ff`×15 + `d5` | `"Olle"` |

(Model and serial are redacted here — they identify a specific physical unit.)

`FIRMWARE_VERSION` is **binary `[major, minor, patch]`, not ASCII** — decoding
it as text yields control characters.

Strip the trailing checksum byte and the `0xFF` padding before interpreting any
of these. The same applies to `STATUS` and `RESULT`, which also arrive as full
20-byte checksummed frames.

### 1.1.2 Advertising

The device advertises as:

```
name: "Olle"     manufacturer data 0xFF00: 00 00 00 00 aa
```

It does **not** advertise its service UUID, so a scanner that filters on
`35ba1523-…` will never see it. Filter on the local name, or on manufacturer ID
`0xFF00`, and confirm by connecting and checking for the service. (`0xFF00` is
not an allocated Bluetooth SIG company ID, so treat it as weak evidence on its
own.) The meaning of the manufacturer bytes is **unconfirmed**; the trailing
`0xAA` is *not* the `mode_settings` byte — the test unit advertises `aa` while
reporting `mode_settings = 0x55` (POWER).

> Note the UUID family is **decimal-looking**: `…1529`, `…1530`, `…1531`, `…1532`.
> `0x1529 + 1` is **not** `…1530`. Treat each UUID as an opaque string; do not
> compute them by incrementing hex.

### 1.2 Connection sequence used by the app

1. Scan, filter on service `35ba1523-…`.
2. Connect, discover services.
3. Enable notifications (write `0x0100` to the CCCD `0x2902`) on `STATUS`,
   `RESULT` and `MULTIPART_RESULT`.
   The app also *attempts* `MODEL_NAME`, `SERIAL_NUMBER` and
   `FIRMWARE_VERSION`, but those are read-only on real hardware and the
   subscriptions fail — read them instead.
   The app writes these descriptors strictly **one at a time**, waiting for each
   `onDescriptorWrite` callback before issuing the next — a classic Android GATT
   serialization workaround. Any reimplementation should serialize GATT
   operations the same way.
4. Send `AUTH_DEVICE` (§5) — optional in practice, see §5.1.
5. Send `SET_DATE`, then `REFRESH_STATUS`, then read model/serial/firmware.

**The device does not push `STATUS` spontaneously.** Fifteen seconds of idle
observation produced zero unsolicited notifications; `STATUS` arrived only in
response to `REFRESH_STATUS`. A client that merely subscribes and waits will sit
there with stale data forever — **poll with `REFRESH_STATUS`**.

---

## 2. Byte order and numeric conventions

* Frames are assembled little-endian (`ByteOrder.LITTLE_ENDIAN`), but in practice
  every multi-byte field in the command set is a byte array, so endianness only
  matters for one field:
* **`CIP` in STATUS is big-endian** (`HexUtils.bytesToShort(..., BIG_ENDIAN)`) —
  an inconsistency in the original firmware, not a transcription error.
* Unused payload bytes are padded with **`0xFF`**, never `0x00`.

### 2.1 Temperature encoding

`HexUtils.shortToByteTemperature(short s, boolean isCelsius)`:

```
celsius:     wire_byte = (degC * 10) - 70
fahrenheit:  wire_byte = degF
```

and the inverse `byteToShortTemperature`:

```
celsius:     degC = (wire_byte + 70) / 10
fahrenheit:  degF = wire_byte
```

So Celsius travels as **tenths of a degree with a −70 bias**, which keeps the
documented 15.0–30.0 °C range inside a single unsigned byte (0x50–0xE6).

| °C | raw (tenths) | wire byte |
|---|---|---|
| 15.0 | 150 | `0x50` |
| 18.5 | 185 | `0x73` |
| 21.0 | 210 | `0x8C` |
| 21.5 | 215 | `0x91` |
| 24.0 | 240 | `0xAA` |
| 30.0 | 300 | `0xE6` |

**Which unit is in force is not a client choice** — it is dictated by the device
and reported in `STATUS` byte 9 (§6). Always read `STATUS[9]` before encoding or
decoding any temperature.

### 2.2 UI limits (from `res/values/dimens.xml`)

| Build variant | Setpoint range | Step |
|---|---|---|
| Celsius | 15 – 30 °C | 0.5 |
| Fahrenheit | 45 – 90 °F | 1 |
| "North Europe" | 1 – 10 (abstract level) | 1 |

Per-mode defaults (Celsius): comfort 21 (19–24), eco 18 (15–21),
antifreeze 11 (7–14), boost 2 h (2–10 h).

These are **app-side UI clamps**, not necessarily firmware limits. A well-behaved
integration should clamp to the same ranges rather than probing the firmware's
tolerance.

---

## 3. Command frame

Every write to `CMD` is **exactly 20 bytes**:

```
 offset  0        1        2 .............. 18       19
        +--------+--------+------------------------+----------+
        | opcode |  seq   |  payload, 0xFF-padded  | checksum |
        +--------+--------+------------------------+----------+
                          \------- 17 bytes -------/
```

* **opcode** — one of the `BLEAction` values in §4.
* **seq** — a sequence byte echoed back in `RESULT`, used to match reply to
  request. The app increments it per request; `0` is valid.
* **payload** — command-specific, left-aligned, remainder filled with `0xFF`.
* **checksum** — `XOR` of bytes 0..18.

```python
def checksum(data: bytes) -> int:
    c = 0
    for b in data:
        c ^= b
    return c & 0xFF
```

That is the **entire** integrity scheme. There is no CRC, no nonce, no
encryption, no replay protection, and no session key. (The `CRC32`/SHA-256
strings elsewhere in the APK belong to the Nordic DFU library, not to this
protocol.)

---

## 4. Opcodes (`BLEConfig.BLEAction`)

| Opcode | Name | Payload | Meaning |
|---|---|---|---|
| `0x01` | `REGISTER_DEVICE` | 16B ASCII id | Enroll a controller id (pairing mode) |
| `0x02` | `SET_MODE` | 1B mode | Operating mode (§4.1) |
| `0x03` | `SET_TEMP_MANUAL` | 1B temp | Manual setpoint |
| `0x04` | `SET_TEMP_ECO` | 1B temp | Eco setpoint |
| `0x05` | `SET_TEMP_COMFORT` | 1B temp | Comfort setpoint |
| `0x06` | `SET_TEMP_ANTIFREEZE` | 1B temp | Antifreeze setpoint |
| `0x07` | `SET_PERIOD_BOOST` | 1B hours | Boost duration, **whole hours** |
| `0x08` | `REFRESH_STATUS` | — | Ask for a `STATUS` notification |
| `0x09` | `READ_STATS` | date range | Multipart statistics |
| `0x0A` | `READ_CHRONO` | 1B page | Read schedule |
| `0x0B` | `SET_CHRONO` | multipart | Write schedule |
| `0x0C` | `SET_DATE` | 7B | Set RTC (§4.2) |
| `0x0D` | `SET_ON` | — | Power on |
| `0x0E` | `SET_OFF` | — | Power off / standby |
| `0x0F` | `READ_HOLIDAY` | — | Read holiday window |
| `0x10` | `SET_HOLIDAY` | date pair | Set holiday window |
| `0x11` | `AUTH_DEVICE` | 16B ASCII id | Authenticate (§5) |
| `0x12` | `SET_MODE_SETTINGS` | 1B | Display mode: power / °C / °F |
| `0x13` | `READ_DIAGNOSTICS` | 1B page | Multipart diagnostics |
| `0x15` | `SET_LOCK` | 1B | Child lock — **`0x55` = lock, `0xAA` = unlock** |
| `0x16` | `FACTORY_RESET` | — | ⚠ Factory reset |
| `0x17` | `SET_OPENWINDOW` | 1B `0/1` | Open-window detection on/off |
| `0xFA` | `READ_FIRMWARE_VERSION` | — | |
| `0xFB` | `CONNECTION_CHANGE` | — | |
| `0xFC` | `SET_DEVICE_NAME` | ASCII | |
| `0xFD` | `READ_DEVICE_NAME` | — | |
| `0xFE` | `READ_MODEL_NAME` | — | |
| `0xFF` | `READ_SERIAL_NUMBER` | — | |

`0x14` is unused.

> In the decompiled source these constants appear as jadx-substituted MQTT
> symbols (`MESSAGE_TYPE_UNSUBACK` = 11, `PINGREQ` = 12, `PINGRESP` = 13,
> `DISCONNECT` = 14). They are plain integers; the table above is the resolved
> truth.

### 4.1 Modes (`ModoOperativo`)

| Value | Name | Meaning |
|---|---|---|
| `0` | `SPENTO` | Off |
| `1` | `BOOST` | Timed boost |
| `2` | `COMFORT` | Comfort setpoint |
| `3` | `ECO` | Eco setpoint |
| `4` | `ANTIFREEZE` | Frost protection |
| `5` | `PROGRAMMA` | Follow schedule |
| `6` | `MANUALE` | Manual setpoint |

### 4.2 `SET_DATE` payload

```
payload[0] = year / 100        (e.g. 20)
payload[1] = year % 100        (e.g. 26)
payload[2] = month, 1-12       (Calendar.MONTH + 1)
payload[3] = day of month
payload[4] = hour, 0-23
payload[5] = minute
payload[6] = second
```

### 4.3 Single-byte enum payloads

| Command | `0x55` | `0xAA` | `0xA5` |
|---|---|---|---|
| `SET_MODE_SETTINGS` | POWER | CELSIUS | FAHRENHEIT |
| `SET_LOCK` | locked | unlocked | — |

`SET_OPENWINDOW` is the odd one out: plain `0x01` / `0x00`.

---

## 5. Authentication

`AUTH_DEVICE` (`0x11`) payload is a **16-byte ASCII controller id** at offsets
2..17, with offset 18 left as `0xFF` padding.

The app generates this id once, on first run:

```java
// MainApplication.initializeUniqueDeviceID()
if (PreferencesManager.getUniqueDeviceId() == null) {
    PreferencesManager.storeUniqueDeviceId(UUID.randomUUID().toString());
}
```

…and then **truncates it to 16 bytes** when building the frame:

```java
HexUtils.stringToBytesArray(mDeviceId, 16, (byte) -1);
```

A `UUID.toString()` is 36 characters, so **only the first 16 characters reach the
device** — e.g. `3f7a1c92-0b44-4e...` becomes the ASCII bytes
`33 66 37 61 31 63 39 32 2d 30 62 34 34 2d 34 65`.

Consequences:

* The credential is a **bearer token in cleartext**, transmitted on every
  connect. Anyone in radio range with a sniffer can capture and replay it.
* It is **not derived** from the phone, the account, or the device — it is just
  a random string the board was told to trust.
* The effective entropy is 16 characters of a UUID *string*, which includes
  fixed structure (hyphen at index 8, version nibble `4` at index 14) — so the
  real entropy is roughly 13 hex digits ≈ 52 bits. Weak against an attacker who
  knows the format, though still far too large to brute-force over BLE.

Two ways to obtain a working id:

1. **Capture** the `AUTH_DEVICE` write from the official app (what we did).
2. **Enroll a new one** with `REGISTER_DEVICE` (`0x01`, identical payload shape)
   while the unit is in pairing mode. The app does exactly this during its
   wizard: in pairing mode it skips `AUTH_DEVICE`, reads model + serial, then
   registers. This is the cleaner route for a public integration, since it does
   not require users to sniff their own phone. The number of registration slots
   the board holds is **unknown** — worth establishing before recommending it
   broadly.

Failure codes `ERR_DEVICEID_NOTSUPPORTED` (5) and
`ERR_DEVICEID_ALREADYREGISTERED` (6) both relate to this flow.

### 5.1 Authentication is not actually enforced

**Hardware-verified, and the single most important finding for implementers.**

On the test unit (fw 3.2.0), a client that **never sends `AUTH_DEVICE` at all**
can:

* connect without pairing or bonding,
* read `STATUS`, `RESULT` and every identity characteristic,
* **write to `CMD` and get `status=OK` back**.

`REFRESH_STATUS` was accepted and executed with no prior authentication,
returning `04 08 01 …` and a full `STATUS` notification.

So `AUTH_DEVICE` behaves as a **client-side ritual**, not a server-side access
control — at least on this firmware. Practical consequences:

* An integration **does not need a `device_id`** to read state or issue
  commands. This removes the single biggest obstacle to a clean open-source
  implementation: users never have to sniff their own phone.
* Conversely, **anyone within BLE range can control the heater.** There is no
  pairing, no bonding, no encryption, no authentication in effect. State this
  plainly in any public integration's README.

Caveats worth testing before relying on this:

* Only `REFRESH_STATUS` was verified unauthenticated here (the device owner
  declined broader write tests, which was the right call for a first pass).
  It is **possible** that state-changing opcodes are gated differently, though
  nothing in the firmware's behaviour or the app's code suggests a separate
  check — the app treats a failed auth as advisory and the board replies to
  unauthenticated writes normally.
* Other firmware versions may differ. An integration should send `AUTH_DEVICE`
  when it has an id, treat failure as non-fatal, and proceed.

---

## 6. `STATUS` notification (15 bytes)

Port of `DeviceStatus.fromBytesArray`. Every field is length-guarded in the
original, so shorter notifications are legal — parse defensively.

| Offset | Field | Encoding |
|---|---|---|
| 0 | Current setpoint | temperature byte, **or** sentinel `0xFD` = antifreeze, `0xFE` = standby |
| 1–2 | `CIP` | **big-endian** uint16 |
| 3 | Mode | `ModoOperativo` (§4.1) |
| 4 | Eco setpoint | temperature byte |
| 5 | Comfort setpoint | temperature byte |
| 6 | Antifreeze setpoint | temperature byte |
| 7 | Boost duration | hours; app multiplies by 60 to get minutes |
| 8 | Alarm | `0` OK, `1` ERR_NTC, `2` ERR_LOAD, `3` ERR_DATE, `4` ERR_EEPROM |
| 9 | Mode settings | `0x55` POWER, `0xAA` CELSIUS, `0xA5` FAHRENHEIT |
| 10 | Holiday active | `0` / non-zero |
| 11–12 | Boost remaining | build-specific decode (`BuildManager.readBoostRemainValue`) |
| 13 | Child lock | `>0` = locked |
| 14 | Open-window detection | `0` disabled, `1` trigger-off-window-closed, `2` trigger-on-window-closed, `3` trigger-on-window-opened |

**Byte 9 gates bytes 0, 4, 5 and 6.** There are three distinct families, and
getting this wrong silently produces plausible-but-wrong temperatures:

| Byte 9 | Family | How to decode bytes 0/4/5/6 |
|---|---|---|
| `0xAA` | CELSIUS | `(b + 70) / 10` → °C |
| `0xA5` | FAHRENHEIT | `b` → °F |
| `0x55` | **POWER** | `b` → abstract **power level 1–10**, *not a temperature* |

The `0x55` POWER family is the "North Europe" build. Such units have no
temperature concept at all — the user picks a power level 1–10. **The test unit
here (fw 3.2.0) is a POWER unit**, and its values matched the app's
`northeurope` defaults exactly (eco 5, comfort 8, antifreeze 2). An integration
written on the assumption that every unit is Celsius will report `L5` as
`12.0 °C` and be wrong in a way users may not notice.

Encoding follows the same split: for POWER units the setpoint byte is the raw
level with **no bias** (`shortToByteTemperature(level, isCelsius=false)`).

`CIP` is not labelled in the app beyond the abbreviation; it is plausibly an
instantaneous power/current figure, but **this is unconfirmed** — do not expose
it as a power sensor without validating it against a real meter.

---

## 7. `RESULT` notification

```
 byte 0  command status
 byte 1  opcode echo   (the BLEAction that was executed)
 byte 2  sequence echo (the seq byte from the request)
 byte 3+ command-specific payload
```

**Hardware-verified.** Writing `08 01 ff…` (REFRESH_STATUS, seq `0x01`) returns:

```
04 08 01 ff ff ff ff ff ff ff ff ff ff ff ff ff ff ff ff 0d
^^ status OK
   ^^ opcode echo = 0x08 REFRESH_STATUS
      ^^ sequence echo = 0x01
```

The vendor app agrees — `DeviceBLEManager.fireBusResultResponse` dispatches on
`BLEConfig.BLEAction.fromByte(bArr[1])`. Note that `ResponseBuilder` then calls
`setSequenceId(byteArray[1])`, i.e. it stores the **opcode** as the sequence id.
That is a latent bug in the vendor app; it is harmless there because requests are
matched by command id rather than by sequence. Do not copy it — read the
sequence from **byte 2**.

This also explains why `READ_HOLIDAY` slices its payload from index **3**.

| Value | Name | Meaning |
|---|---|---|
| `1` | `ERR_INVALID_CRC` | Checksum rejected |
| `2` | `ERR_INVALID_DATA` | Malformed payload |
| `3` | `ERR_UNABLE_TO_UPDATE` | Write failed |
| `4` | `ERR_OPERATION_PERFORMED` | **Success** |
| `5` | `ERR_DEVICEID_NOTSUPPORTED` | Unknown controller id |
| `6` | `ERR_DEVICEID_ALREADYREGISTERED` | Id already enrolled |
| `0xFF` | `ERR_OPERATION_UNDEFINED` | Catch-all |

Note the naming quirk: **success is called `ERR_OPERATION_PERFORMED` and equals
`4`**. Treat `4` as OK; everything else is a failure.

Some responses carry payload from offset 3 rather than 2 (e.g. `READ_HOLIDAY`
does `copyOfRange(bytes, 3, ...)`), so per-command response offsets should be
confirmed against a capture before relying on them.

---

## 8. Reference implementation

`scripts/olle_protocol.py` in this repo is a dependency-free Python module
implementing everything above: frame building, checksum, temperature codec,
`STATUS` and `RESULT` parsing. `scripts/test_protocol.py` exercises it offline
(40 assertions, all passing) with no hardware.

`scripts/olle_ctl.py` is a bleak-based CLI that connects, subscribes, performs
`AUTH_DEVICE` and issues commands — useful as both a test harness and a
worked example.

---

## 9. Verification status

| Area | Evidence | Status |
|---|---|---|
| Service + characteristic UUIDs | APK strings **+ live GATT enumeration** | ✅ Hardware-confirmed |
| Characteristic properties / which are notifiable | **live GATT enumeration** | ✅ Hardware-confirmed |
| 20-byte frame + trailing XOR checksum | APK **+ 6 real frames, all checksums verified** | ✅ Hardware-confirmed |
| Identity chars are checksummed frames; firmware is binary | **live reads** | ✅ Hardware-confirmed |
| `RESULT` = `[status][opcode][seq][payload]` | **live round-trip** (corrects the APK's own mislabelling) | ✅ Hardware-confirmed |
| `STATUS` field layout | `DeviceStatus.fromBytesArray` **+ live read matching app defaults** | ✅ Hardware-confirmed |
| POWER (`0x55`) level family exists and is in use | **live read**, matched `northeurope` defaults | ✅ Hardware-confirmed |
| `REFRESH_STATUS` accepted **without** `AUTH_DEVICE` | **live write, `status=OK`** | ✅ Hardware-confirmed |
| Device does not push `STATUS` unsolicited | **15 s idle observation** | ✅ Hardware-confirmed |
| Advertising: name only, no service UUID | **live scan** | ✅ Hardware-confirmed |
| Opcode table | `BLEConfig.BLEAction` enum | High (only `0x08` exercised) |
| Celsius `×10 − 70` codec | `HexUtils` + MQTT path (`value/10.0f`) | High — **untested**, test unit is POWER |
| `SET_LOCK` `0x55`/`0xAA` | `SetLockRequest` | High — untested |
| Auth payload = 16 ASCII chars of a random UUID | `AuthDeviceRequest` + `MainApplication` | High — untested |
| State-changing writes (`SET_ON`/`SET_OFF`/…) | spec only | ⚠ **Not tested against hardware** |
| `CIP` semantics | abbreviation only; read `27` on an idle OFF unit | ⚠ **Unconfirmed** |
| Boost-remaining decode (bytes 11–12) | build-variant specific; read `ff ff` when idle | ⚠ **Unconfirmed** |
| Multipart (stats/schedule/diagnostics) framing | not analysed in depth | ⚠ **Unconfirmed** |
| Advertising manufacturer-data meaning | `0xFF00: 00 00 00 00 aa`, not `mode_settings` | ⚠ **Unconfirmed** |

---

## 10. Safety notes for implementers

* **`FACTORY_RESET` is `0x16`.** It is one byte away from `SET_LOCK` (`0x15`).
  Do not build opcodes by arithmetic; use the enum.
* Do not touch the Nordic DFU service. A failed firmware write can brick the unit.
* The app serializes GATT writes behind a semaphore and writes CCCDs one at a
  time. Android and some BlueZ versions silently drop concurrent GATT ops.
* The device is a **heater**. An integration that can set temperature and enable
  boost should respect the app's documented clamps (§2.2) and should not expose
  `FACTORY_RESET` in normal UI.
* There is no encryption or replay protection. Anyone in radio range who has
  observed one connection can control the heater indefinitely. That is a
  property of the product, not of this document — but it is worth stating
  plainly in any public integration's README so users can judge the risk.

---

## 11. Legal / ethical framing

This specification was produced by analysing an application the device owner
installed on their own phone, to interoperate with hardware they own. In the EU,
decompilation for interoperability is specifically permitted under Article 6 of
Directive 2009/24/EC, and Sweden implements this in 26 g § of the Copyright Act
(URL 1960:729).

Guidance for anyone publishing work derived from this document:

* Publish **the protocol description and a clean-room implementation**, not the
  decompiled sources, not the APK, and not any Olle/IRCA/Somatherm artwork,
  strings or trademarks.
* Do not reuse the vendor's code. Everything in `scripts/` here was written from
  the specification, not copied.
* Name the project so it does not imply endorsement (e.g. `ha-irca-ble`, not
  `Olle Connect for HA`).
* Never commit a real `device_id` — it is a working credential for a physical
  heater.

---

## 12. Verification log

Test unit: **Olle** towel rail, firmware `3.2.0`, POWER-mode variant. Verified
2026-10-27 from a Windows laptop over bleak 3.0.2 — i.e. by a clean-room
client, not by observing the vendor app.

> The unit's BLE address, model id and serial number are redacted throughout.
> They identify one physical heater that, per §5.1, **anyone in radio range can
> control without authentication**.

### 12.1 Why not a sniffed capture

The original plan was to decode ATT writes from the phone's HCI snoop log. That
turned out to be impossible on this handset without root:

* `bluetooth_btsnoop_default_mode` was `empty`; setting it to `full` and cycling
  Bluetooth did enable logging.
* Samsung One UI does **not** include `/data/misc/bluetooth/logs/` in
  `adb bugreport` output (checked twice, 466 and 461 zip entries, no btsnoop).
* `/data/misc/bluetooth/` is unreadable without root, and the app is not
  debuggable, so `run-as` is unavailable.
* `dumpsys bluetooth_manager` *does* embed a snoop log inline as base64+zlib
  (`BTSNOOP_LOG_SUMMARY`), in Android's **btsnooz** format. We wrote a decoder
  for it (`scripts/get_snoop.py`) and recovered 6,990 packets — but btsnooz is a
  *summary* containing **only HCI commands and events, no ACL payloads**, and
  ATT lives in ACL. Confirmed by packet census: 5,858 events, 1,132 commands,
  **0 ACL**.

The tooling is kept because it is reusable on a rooted or AOSP device; on this
phone, direct interrogation from the laptop was both possible and strictly
better evidence.

### 12.2 Frames captured

All six are complete 20-byte frames whose XOR checksum verifies:

```
STATUS   (read)   00 00 1b 00 05 08 02 00 00 55 00 ff ff 00 ff ff ff ff ff be
RESULT   (read)   04 09 00 ff ff ff ff ff ff ff ff ff ff ff ff ff ff ff ff 0d
MODEL    (read)   <12 ASCII bytes> ff ff ff ff ff ff ff <csum>    (redacted)
SERIAL   (read)   <11 ASCII bytes> ff ff ff ff ff ff ff ff <csum> (redacted)
FIRMWARE (read)   03 02 00 ff ff ff ff ff ff ff ff ff ff ff ff ff ff ff ff 01
NAME     (read)   4f 6c 6c 65 ff ff ff ff ff ff ff ff ff ff ff ff ff ff ff d5

CMD      (write)  08 01 ff ff ff ff ff ff ff ff ff ff ff ff ff ff ff ff ff f6
RESULT   (notify) 04 08 01 ff ff ff ff ff ff ff ff ff ff ff ff ff ff ff ff 0d
STATUS   (notify) 00 00 1b 00 05 08 02 00 00 55 00 ff ff 00 ff ff ff ff ff be
```

Decoded `STATUS`:

```
setpoint=L0  mode=OFF  eco=L5  comfort=L8  antifreeze=L2
boost=0h  CIP=27  alarm=OK  holiday=off  lock=off  window=0xFF
```

`eco/comfort/antifreeze = 5/8/2` match `modesettings_northeurope_default_*`
exactly, which is what identifies this as a POWER-family unit.

Note `window_detection` reads `0xFF`, which is **not** a valid
`WindowDetection` value — the app maps unknown values to `DISABLED` via a null
check. Parsers must tolerate it rather than assume `0..3`.

These frames are encoded as regression tests in `scripts/test_protocol.py`
(62 assertions, all passing).

### 12.3 Write path (confirmed)

`SET_ON` / `SET_OFF` round-trip, **with no `AUTH_DEVICE` sent at any point**:

```
-> 0d 01 ff…ff f3                     SET_ON, seq 0x01
<- 04 0d 01 ff…ff 08    RESULT        status=OK, opcode echo 0x0D, seq echo 0x01
<- 08 00 1f 02 05 08 02 00 00 55 …    STATUS  mode 0x00 OFF -> 0x02 COMFORT
                                              setpoint 0x00 -> 0x08

-> 0e 02 ff…ff f3                     SET_OFF, seq 0x02
<- 04 0e 02 ff…ff 08    RESULT        status=OK, opcode echo 0x0E, seq echo 0x02
<- 00 00 1f 00 05 08 02 00 00 55 …    STATUS  mode back to 0x00 OFF, setpoint 0x00
```

This confirms, on hardware: the frame format, the XOR checksum, the opcode
values, the `[status][opcode][seq]` result layout, **and** that state-changing
writes are accepted without authentication.

#### `SET_ON` resumes a mode — it is not a neutral "on"

Note what `SET_ON` actually did: mode went `OFF → COMFORT`, and the setpoint
byte went `0x00 → 0x08`, which is exactly the unit's stored **comfort** level
(`STATUS[5] = 8`). So `SET_ON` means "resume operating in the configured mode",
not "energise at some generic setting".

Implementers should therefore:

* not assume `SET_ON` leaves the device in a known state — **read `STATUS`
  back** rather than optimistically rendering "on";
* treat `SET_MODE` as the real control surface. `SET_ON` followed immediately
  by `SET_MODE` is the reliable way to reach a specific state.

Conversely `SET_OFF` cleanly returned mode to `0x00` and setpoint to `0x00`.

#### `CIP` is not instantaneous power

`CIP` read `27` in one session and `31` about twenty minutes later, and **did
not change at all** across the `SET_ON` → `SET_OFF` cycle — it stayed `31` while
the unit was off, on, and off again.

That is strong evidence against the natural guess that `CIP` is an
instantaneous current/power figure. It behaves like a slowly-incrementing
counter (operating hours, cycle count, or similar). **Do not expose it as a
power sensor.** Its true meaning remains unconfirmed.

### 12.3.1 The heater hangs up on idle links

Observed repeatedly: after roughly one to two minutes with no GATT traffic, the
device drops the connection. Android surfaces this as
`onConnectionStateChange` with **status 59 (`0x3B`)**, i.e. the controller
reporting unacceptable connection parameters, rather than a clean remote
disconnect.

Two things follow for any client:

* **Keep the link busy.** Polling `REFRESH_STATUS` every ~20 s both refreshes
  state and prevents the drop. In testing, a polling client stayed connected
  for 150 s and counting, where an idle one had already been dropped. This is
  the effective mitigation.
* **Reconnect with `autoConnect = true`** (on Android) or the platform's
  equivalent "connect when it next appears". The heater is typically *not*
  advertising in the moments right after it hangs up, so a direct one-shot
  reconnect fails immediately.

Honest caveat on the second point: `autoConnect` retries did **not** reliably
recover within a couple of minutes in testing, whereas an explicit
user-triggered reconnect succeeded immediately every time. So treat automatic
recovery as best-effort and always keep a manual reconnect affordance in the
UI. Preventing the drop by polling is far more dependable than recovering from
it.

A naive client that connects, subscribes, and then waits for notifications will
appear to work for about a minute and then silently stop updating — with no
error, because it never asked for anything.

### 12.4 Still to verify

A future session with owner consent should confirm, in this order:

1. `SET_ON` / `SET_OFF` round-trip, reading `STATUS` back to see `mode` change.
2. Whether state-changing writes are gated by `AUTH_DEVICE` (only
   `REFRESH_STATUS` was exercised unauthenticated).
3. `SET_TEMP_MANUAL` on a POWER unit — confirm the raw level byte is accepted
   and reflected in `STATUS[0]`.
4. `boost_remain` bytes 11–12 while a boost is actually running.
5. Whether `CIP` tracks real power draw (needs a meter).
6. A Celsius-family unit, to confirm the `×10 − 70` codec on hardware.
