"""Extract the Reon Pocket 3's bond token from a btsnoop HCI capture.

Useful only for the **co-existence** workflow: if you've already paired the
Reon with the Sony app and you want both clients to keep working, you need to
know the exact token the app stored. Capture an HCI snoop log while the app
connects, run this, and feed the token into ``reon pair --token <hex>``.

Capture how-to (Android, no root):
  1. Enable "Developer options" on your phone.
  2. Toggle on "Enable Bluetooth HCI snoop log" in developer options.
  3. Toggle Bluetooth off and on.
  4. Open the Sony Reon Pocket app; let it connect to the device.
  5. Pull the log via:  adb bugreport bugreport.zip
     and extract FS/data/log/bt/btsnoop_hci.log from the archive.

Run::

    python tools/parse_btsnoop.py path/to/btsnoop_hci.log
"""

from __future__ import annotations

import struct
import sys
from pathlib import Path

# Handle 0x002b on the Reon is the value of the 04ca150a auth characteristic.
# The app writes the 17-byte token there exactly once per connection.
AUTH_HANDLE = 0x002b
AUTH_LEN = 17


def parse_btsnoop(path: Path):
    """Yield (timestamp_us, direction, hci_packet) for each record."""
    with open(path, "rb") as f:
        header = f.read(16)
        if header[:8] != b"btsnoop\0":
            raise ValueError("not a btsnoop file")
        while True:
            rec_hdr = f.read(24)
            if len(rec_hdr) < 24:
                return
            _, incl_len, flags, _, ts_us = struct.unpack(">IIIIQ", rec_hdr)
            data = f.read(incl_len)
            if len(data) < incl_len:
                return
            yield ts_us, ("rx" if (flags & 0x01) else "tx"), data


def find_auth_writes(path: Path):
    """Return all ATT writes that target the auth handle. Each entry is
    (timestamp_us, direction, value_bytes).
    """
    frag = {}
    hits = []

    for ts_us, direction, data in parse_btsnoop(path):
        # only ACL data packets
        if not data or data[0] != 0x02 or len(data) < 5:
            continue
        handle_flags, total_len = struct.unpack("<HH", data[1:5])
        conn = handle_flags & 0x0fff
        pb = (handle_flags >> 12) & 0x3
        payload = data[5:5 + total_len]

        # reassemble L2CAP fragments
        if pb in (0x00, 0x02):
            if len(payload) >= 2:
                l2_len = struct.unpack("<H", payload[:2])[0]
                if len(payload) < l2_len + 4:
                    frag[conn] = {"buf": bytes(payload), "target": l2_len + 4}
                    continue
            full = bytes(payload)
        elif pb == 0x01:
            if conn not in frag:
                continue
            frag[conn]["buf"] += payload
            if len(frag[conn]["buf"]) < frag[conn]["target"]:
                continue
            full = frag.pop(conn)["buf"]
        else:
            continue

        if len(full) < 4:
            continue
        l2_len, cid = struct.unpack("<HH", full[:4])
        att = full[4:4 + l2_len]
        # ATT WRITE_REQ (0x12) or WRITE_CMD (0x52)
        if not att or att[0] not in (0x12, 0x52) or len(att) < 3:
            continue
        handle = struct.unpack("<H", att[1:3])[0]
        if handle != AUTH_HANDLE:
            continue
        value = att[3:]
        if len(value) == AUTH_LEN:
            hits.append((ts_us, direction, bytes(value)))

    return hits


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)
    path = Path(sys.argv[1])
    if not path.exists():
        sys.exit(f"file not found: {path}")

    hits = find_auth_writes(path)
    if not hits:
        sys.exit("no 17-byte writes to the auth handle (0x002b) found. "
                 "Is this a capture of a successful Sony app connect?")

    seen_tokens = {}
    for ts_us, direction, value in hits:
        seen_tokens.setdefault(value, []).append((ts_us, direction))

    print(f"found {len(hits)} auth-handle write(s), {len(seen_tokens)} unique token(s):\n")
    for tok, occurrences in seen_tokens.items():
        print(f"  token: {tok.hex()}")
        for ts_us, d in occurrences:
            print(f"    seen {d} at ts_us={ts_us}")
    print(f"\nMost likely your token is the most-recent value above.")
    print(f"To replay it:  reon pair --token {next(iter(seen_tokens)).hex()}")


if __name__ == "__main__":
    main()
