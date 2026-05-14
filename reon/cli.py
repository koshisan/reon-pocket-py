"""Command-line interface for reon-pocket-py.

Entry point ``reon`` (installed via the project's ``[project.scripts]`` table)
or ``python -m reon``. Subcommands:

  scan              List nearby BLE devices, highlighting any Reon found.
  pair              Generate a token, write it while the device is in pair mode.
  pair --token HEX  Restore a specific token (e.g. one extracted from another client).
  info              Connect and dump GATT services + characteristics.
  listen [seconds]  Stream telemetry and state notifications.
  cool LEVEL        Set cool mode at LEVEL (0..3).
  heat LEVEL        Set heat mode at LEVEL (0..3).
  stop              Stop / mode-off.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from datetime import datetime

from . import client, pair as pair_module, protocol, storage


def ts() -> str:
    return datetime.now().strftime("%H:%M:%S")


async def _resolve_address(explicit: str | None) -> str:
    if explicit:
        return explicit
    stored = storage.load()
    if stored is not None:
        return stored.mac
    addr = await client.find_reon()
    if not addr:
        sys.exit(f"[{ts()}] Reon not found via scan, and no stored address. "
                 "Use --mac or run `reon pair`.")
    return addr


async def cmd_scan(args):
    print(f"[{ts()}] scanning {args.timeout}s …")
    found_reon = False
    for addr, name, rssi in await client.scan(args.timeout):
        is_reon = bool(name and name.startswith(protocol.DEVICE_NAME_PREFIX))
        marker = f"  <-- {name}" if is_reon else ""
        print(f"  {addr}  rssi={rssi}  name={name!r}{marker}")
        if is_reon:
            found_reon = True
    if not found_reon:
        print(f"\n[{ts()}] No Reon visible. If the phone's Sony app is currently "
              "connected, it won't advertise.")


async def cmd_pair(args):
    if not args.yes:
        print("Put the Reon in pair mode (long-press the button until the LED "
              "indicates mode change), and turn off Bluetooth on your phone so "
              "the Sony app can't grab it during pairing.")
        input("Press Enter when ready: ")

    addr = args.mac or await client.find_reon()
    if not addr:
        sys.exit(f"[{ts()}] Reon not found.")

    if args.token:
        token = bytes.fromhex(args.token)
        if len(token) != protocol.AUTH_TOKEN_LEN:
            sys.exit(f"--token must be exactly {protocol.AUTH_TOKEN_LEN} bytes")
        print(f"[{ts()}] using supplied token: {token.hex()}")
    else:
        token = pair_module.random_token()
        print(f"[{ts()}] generated random token: {token.hex()}")

    try:
        await pair_module.pair(addr, token)
    except client.ReonError as e:
        sys.exit(f"[{ts()}] pair failed: {e}\n"
                 "Most likely the device is not actually in pair mode. "
                 "Hold the button longer and retry.")

    print(f"[{ts()}] paired with {addr}.")
    print(f"  Token persisted at {storage.token_path()}.")
    if args.token:
        print("  If this token matches the Sony app's stored value, both clients "
              "can now coexist.")
    else:
        print("  This was a fresh random token; the Sony app on your phone is now "
              "locked out until you re-pair through it (which would overwrite this).")


async def cmd_info(args):
    addr = await _resolve_address(args.mac)
    print(f"[{ts()}] connecting {addr} …")
    async with client.ReonClient(addr) as r:
        bleak = r._bleak  # we expose the raw services for inspection here
        print(f"[{ts()}] connected. mtu={bleak.mtu_size}")
        for svc in bleak.services:
            print(f"  service {svc.uuid}")
            for ch in svc.characteristics:
                props = ",".join(ch.properties)
                print(f"    char {ch.uuid}  handle=0x{ch.handle:04x}  [{props}]")


async def cmd_listen(args):
    addr = await _resolve_address(args.mac)
    print(f"[{ts()}] connecting {addr} …")
    async with client.ReonClient(addr) as r:
        def on_telem(t):
            print(f"[{ts()}] TELEM  skin={t['skin_plate']:5.2f}  "
                  f"sink={t['heatsink']:5.2f}  board={t['board']:5.2f}  "
                  f"ambient={t['ambient']:5.2f}")

        def on_state(s):
            print(f"[{ts()}] STATE  mode=0x{s['mode']:02x}  level=0x{s['level']:02x}  "
                  f"tail={s['tail'].hex()}")

        await r.on_telemetry(on_telem)
        await r.on_state(on_state)
        print(f"[{ts()}] listening for {args.seconds}s …")
        await asyncio.sleep(args.seconds)


async def cmd_cool(args):
    addr = await _resolve_address(args.mac)
    async with client.ReonClient(addr) as r:
        await r.set_cool(args.level)
    print(f"[{ts()}] cool L{args.level} set.")


async def cmd_heat(args):
    addr = await _resolve_address(args.mac)
    async with client.ReonClient(addr) as r:
        await r.set_heat(args.level)
    print(f"[{ts()}] heat L{args.level} set.")


async def cmd_stop(args):
    addr = await _resolve_address(args.mac)
    async with client.ReonClient(addr) as r:
        await r.stop()
    print(f"[{ts()}] stopped.")


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="reon", description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--mac", help="explicit BLE MAC (otherwise auto-scan or stored)")
    sub = p.add_subparsers(dest="cmd", required=True)

    sp = sub.add_parser("scan")
    sp.add_argument("--timeout", type=float, default=8.0)
    sp.set_defaults(func=cmd_scan)

    sp = sub.add_parser("pair", help="write a bond token (device must be in pair mode)")
    sp.add_argument("--token", help="restore a specific token (hex); omit for fresh random")
    sp.add_argument("--yes", action="store_true", help="skip the interactive prompt")
    sp.set_defaults(func=cmd_pair)

    sp = sub.add_parser("info")
    sp.set_defaults(func=cmd_info)

    sp = sub.add_parser("listen")
    sp.add_argument("seconds", nargs="?", type=float, default=15.0)
    sp.set_defaults(func=cmd_listen)

    sp = sub.add_parser("cool")
    sp.add_argument("level", type=int)
    sp.set_defaults(func=cmd_cool)

    sp = sub.add_parser("heat")
    sp.add_argument("level", type=int)
    sp.set_defaults(func=cmd_heat)

    sp = sub.add_parser("stop")
    sp.set_defaults(func=cmd_stop)

    return p


def main(argv: list[str] | None = None) -> None:
    p = build_parser()
    args = p.parse_args(argv)
    try:
        asyncio.run(args.func(args))
    except KeyboardInterrupt:
        sys.exit(130)


if __name__ == "__main__":
    main()
