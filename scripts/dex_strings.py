"""Extract UUID-like and BLE-relevant strings straight out of the APK's dex string pools.

Much faster than waiting for a full decompile, and the dex string pool is the
authoritative list of every string constant the app can use.
"""
import re
import sys
import zipfile

if len(sys.argv) < 2:
    raise SystemExit("usage: python dex_strings.py <app.apk>")
APK = sys.argv[1]

# Pull printable ASCII runs out of the raw dex; the string pool is MUTF-8 so this
# catches everything we care about (UUIDs are pure ASCII).
RUN = re.compile(rb'[\x20-\x7e]{6,}')
UUID128 = re.compile(r'\b[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}\b')

z = zipfile.ZipFile(APK)
blobs = {n: z.read(n) for n in z.namelist() if n.endswith('.dex')}

strings = set()
for name, data in blobs.items():
    for m in RUN.finditer(data):
        try:
            strings.add(m.group().decode('ascii'))
        except UnicodeDecodeError:
            pass

print(f"# extracted {len(strings)} distinct ASCII strings from {len(blobs)} dex files\n")

# --- 1. 128-bit UUIDs ---
uuids = set()
for s in strings:
    uuids.update(UUID128.findall(s))
print("=" * 70)
print("128-BIT UUIDs")
print("=" * 70)
BT_BASE = re.compile(r'^0000([0-9a-fA-F]{4})-0000-1000-8000-00805f9b34fb$', re.I)
std, custom = [], []
for u in sorted(uuids):
    m = BT_BASE.match(u)
    (std if m else custom).append(u)
print(f"\n-- custom / vendor UUIDs ({len(custom)}) --")
for u in custom:
    print("  ", u)
print(f"\n-- standard Bluetooth SIG UUIDs ({len(std)}) --")
for u in std:
    print(f"   {u}   (short 0x{BT_BASE.match(u).group(1).upper()})")

# --- 2. BLE-relevant identifiers and keywords ---
print("\n" + "=" * 70)
print("BLE / PROTOCOL KEYWORDS")
print("=" * 70)
KEYWORDS = [
    'writeCharacteristic', 'readCharacteristic', 'setCharacteristicNotification',
    'BluetoothGatt', 'ScanFilter', 'advertis', 'notifyCharacteristic',
    'checksum', 'crc', 'Crc', 'CRC', 'xor', 'Xor', 'XOR',
    'password', 'passkey', 'pincode', 'pinCode', 'secret', 'token', 'auth',
    'encrypt', 'decrypt', 'AES', 'cipher', 'Cipher',
    'setpoint', 'setPoint', 'temperature', 'boost', 'timer', 'program',
    'comfort', 'eco', 'antifrost', 'frost', 'heat', 'dryer', 'towel',
]
for kw in KEYWORDS:
    hits = sorted(s for s in strings if kw in s and len(s) < 90)
    if hits:
        print(f"\n--- '{kw}' ({len(hits)}) ---")
        for h in hits[:25]:
            print("   ", h)
        if len(hits) > 25:
            print(f"    ... +{len(hits)-25} more")

# --- 3. app package classes ---
print("\n" + "=" * 70)
print("APP CLASS NAMESPACES (Lcom/... prefixes)")
print("=" * 70)
pkgs = {}
for s in strings:
    if s.startswith('Lcom/') or s.startswith('Lfr/') or s.startswith('Lit/'):
        parts = s.strip('L;').split('/')
        if len(parts) >= 3:
            key = '/'.join(parts[:3])
            pkgs[key] = pkgs.get(key, 0) + 1
for k, v in sorted(pkgs.items(), key=lambda x: -x[1])[:40]:
    print(f"   {v:5d}  {k}")
