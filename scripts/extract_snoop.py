"""Pull the btsnoop HCI log(s) out of an adb bugreport zip.

Usage: python extract_snoop.py <bugreport.zip> [outdir]
"""
import os
import sys
import zipfile

zp = sys.argv[1]
outdir = sys.argv[2] if len(sys.argv) > 2 else os.path.dirname(os.path.abspath(zp))

z = zipfile.ZipFile(zp)
names = z.namelist()

cands = [n for n in names
         if "btsnoop" in n.lower() or "/bluetooth/logs/" in n.lower()]

if not cands:
    print("NO btsnoop ENTRIES FOUND in bugreport.")
    print("\nBluetooth-ish entries present:")
    for n in names:
        if "bluetooth" in n.lower() or "/bt" in n.lower():
            print("   ", n, z.getinfo(n).file_size)
    print(f"\n({len(names)} entries total in zip)")
    sys.exit(1)

base = os.path.splitext(os.path.basename(zp))[0]
for n in cands:
    info = z.getinfo(n)
    safe = os.path.basename(n)
    dest = os.path.join(outdir, f"{base}__{safe}")
    with z.open(n) as src, open(dest, "wb") as dst:
        dst.write(src.read())
    magic_ok = ""
    with open(dest, "rb") as f:
        magic_ok = "btsnoop OK" if f.read(8) == b"btsnoop\x00" else "NOT btsnoop format"
    print(f"{info.file_size:>12,} bytes  {n}")
    print(f"              -> {dest}  [{magic_ok}]")
