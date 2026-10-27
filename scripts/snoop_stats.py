"""Summarise what is actually inside a btsnoop file (packet types, L2CAP CIDs)."""
import collections
import struct
import sys

path = sys.argv[1]
H4 = {0x01: "HCI_CMD", 0x02: "ACL", 0x03: "SCO", 0x04: "HCI_EVT", 0x05: "ISO"}

types = collections.Counter()
cids = collections.Counter()
acl_lens = collections.Counter()
total = 0

with open(path, "rb") as f:
    hdr = f.read(16)
    print("magic:", hdr[:8], "version/datalink:", struct.unpack(">II", hdr[8:16]))
    while True:
        rh = f.read(24)
        if len(rh) < 24:
            break
        olen, ilen, flags, drops, ts = struct.unpack(">IIIIq", rh)
        data = f.read(ilen)
        if len(data) < ilen:
            break
        total += 1
        if not data:
            continue
        t = data[0]
        types[H4.get(t, f"0x{t:02X}")] += 1
        if t == 0x02 and len(data) >= 5:
            acl = data[1:]
            acl_lens[len(acl)] += 1
            if len(acl) >= 8:
                l2len, cid = struct.unpack("<HH", acl[4:8])
                cids[f"0x{cid:04X}"] += 1
            else:
                cids["(truncated, no L2CAP header)"] += 1

print(f"\ntotal records: {total}")
print("\npacket types:")
for k, v in types.most_common():
    print(f"   {v:6d}  {k}")
print("\nACL payload sizes (bytes after H4 type):")
for k, v in sorted(acl_lens.items())[:15]:
    print(f"   {v:6d}  {k} bytes")
print("\nL2CAP CIDs seen on ACL:")
for k, v in cids.most_common(12):
    print(f"   {v:6d}  {k}")
