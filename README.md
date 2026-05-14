# reon-pocket-py

Unofficial Python BLE control for the Sony **Reon Pocket 3** (RNP-3). Drives
cool/heat modes and levels, reads plate temperatures, and pairs against the
device's own bond-token mechanism — no phone, no Sony app, no sniffing required
after initial setup.

> ⚠️ This is reverse-engineered software. It is not affiliated with or endorsed
> by Sony. The protocol was decoded from observed BLE traffic on an RNP-3 with
> firmware 2.3.6; other models or firmware revisions may differ. Use at your
> own risk.

## What works

- **All four manual levels in both directions** (cool 0–3, heat 0–3) and stop.
- **Live telemetry**: four plate/board/ambient temperatures at ~1 Hz.
- **State notifications** echoing mode and level after each command.
- **First-class pairing**: put the Reon in pair mode, generate a token, you're
  in. Or restore a token captured from the Sony app for coexistence.

## What doesn't (yet)

- Smart mode (the 20-byte variable-length frames on the command channel are
  partially decoded but not exposed). The set point format with `0x0080` deltas
  is in [docs/PROTOCOL.md](docs/PROTOCOL.md).
- Battery / runtime counters (notified on `1584`, format speculative).
- Other Reon Pocket generations. The service layout *looks* generation-stable
  according to public clues but is not verified.

## Install

Requires Python 3.10+, a BLE-capable host (Windows 10+, Linux with BlueZ, macOS).

```bash
pip install bleak
git clone https://github.com/koshisan/reon-pocket-py
cd reon-pocket-py
pip install -e .
```

## Quick start

```bash
# 1. Confirm the device is visible
reon scan

# 2. Put the Reon in pair mode (long-press the button until LED indicates
#    pairing). Then:
reon pair

# 3. Use it
reon cool 3      # cool, max level
reon heat 2      # heat, mid level
reon stop
reon listen 30   # 30s of live telemetry
```

Once paired, the token is persisted at
`%APPDATA%\reon\token.json` (Windows) or `~/.config/reon/token.json` (POSIX)
and reused on every connect.

## Coexistence with the Sony app

The Reon stores exactly **one** bond token. Whichever client wrote it last is
the only one that can talk to the device. Two strategies:

### Strategy A — Python only (simple)

Pair through `reon pair`. The Sony app on your phone will be locked out until
you re-pair through the app, at which point the Sony app overwrites the token
and `reon` is locked out.

### Strategy B — Python + Sony app (coexistence)

If you want both clients live, you need to make them store the *same* token.
The procedure:

1. Pair with the Sony app as normal.
2. Capture an HCI snoop log on Android while the app reconnects to the device
   (Developer Options → "Enable Bluetooth HCI snoop log", toggle BT, open app,
   `adb bugreport bugreport.zip`).
3. Extract the token:
   ```bash
   python tools/parse_btsnoop.py path/to/btsnoop_hci.log
   ```
4. Put the Reon in pair mode and write that exact token:
   ```bash
   reon pair --token 0153...
   ```

Now both the app and the Python client know the value the Reon expects. iPhone
users currently have no equivalent way to pull this token; coexistence is
effectively Android-only.

## Library use

```python
import asyncio
from reon import ReonClient, find_reon

async def main():
    addr = await find_reon()
    async with ReonClient(addr) as r:
        await r.set_cool(3)
        await asyncio.sleep(5)
        await r.stop()

asyncio.run(main())
```

See [`reon/client.py`](reon/client.py) for the full surface, including
`on_telemetry()` / `on_state()` subscriptions.

## Protocol notes

Full technical write-up in [docs/PROTOCOL.md](docs/PROTOCOL.md). The short
version:

- **Custom service** `04ca1501-fd57-404e-8459-c5ef8d765c8d`.
- **Auth**: write a 17-byte bond token to `04ca150a-…`. Strict byte-for-byte
  verification. ATT 0x81 on mismatch, 0x83 if not yet written.
- **Pair mode** (long-press button) unlocks the auth slot for arbitrary writes
  and rewrites the stored token.
- **Commands**: 12-byte writes to `04ca1503-…` of the form
  `00 00 00 <mode> <level> 00 00 00 00 00 00 00`. Modes: `01` cool, `02` heat,
  `03` smart, `04` stop. Levels: 0–3. Anything else returns ATT 0x80.
- **Telemetry**: notifies on `04ca1581-…` carry four big-endian int16
  temperatures in 1/100 °C.

## Acknowledgements / FYI

The RE work was an evening project with significant help from Claude in
debugging captures and probing the auth model. Findings were corroborated by
empirical experiments on a single RNP-3 unit; please file an issue if your
device behaves differently.

## License

MIT — see [LICENSE](LICENSE).
