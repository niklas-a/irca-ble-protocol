"""Fingerprint the Olle Connect APK: framework, dex layout, native libs."""
import zipfile
import sys

if len(sys.argv) < 2:
    raise SystemExit("usage: python apk_fingerprint.py <app.apk>")
p = sys.argv[1]
z = zipfile.ZipFile(p)
names = z.namelist()
print("total entries:", len(names))

marks = {
    'Flutter':       'libflutter.so',
    'ReactNative':   'libreactnative',
    'ReactNative2':  'index.android.bundle',
    'Cordova/Ionic': 'assets/www/',
    'Capacitor':     'assets/public/',
    'Xamarin':       'libmonodroid',
    'Unity':         'libunity',
    'Kotlin':        'kotlin/kotlin.kotlin_builtins',
}
print("\n--- framework fingerprints ---")
for k, v in marks.items():
    hits = [n for n in names if v in n]
    if hits:
        print(f"  {k:14s} -> {len(hits):4d} hits, e.g. {hits[0]}")

print("\n--- dex files ---")
for n in names:
    if n.endswith('.dex'):
        print(f"   {n:20s} {z.getinfo(n).file_size:>12,} bytes")

print("\n--- native libs ---")
for n in sorted(n for n in names if n.startswith('lib/')):
    print(f"   {n:60s} {z.getinfo(n).file_size:>12,}")

print("\n--- assets (top level, first 60) ---")
assets = sorted(set(n for n in names if n.startswith('assets/')))
for n in assets[:60]:
    print("   ", n)
print(f"   ... {len(assets)} asset entries total")
