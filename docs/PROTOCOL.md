# Sony Reon Pocket 3 BLE protocol

What follows is what's been observed empirically on a single RNP-3 unit
(firmware 2.3.6) by sniffing traffic from the official Android app and then
probing with Python/Bleak. Treat speculative bits as such; corrections welcome.

## Device identification

| Field | Value |
|---|---|
| Advertised name | `RNP-3` |
| Vendor service UUID | `04ca1501-fd57-404e-8459-c5ef8d765c8d` |
| Device Information service | standard `180a`, exposes name, serial, fw revision |

The third UUID group is `404e`, **not** `4057`. Easy to misread because the
bytes look similar; if your writes get nowhere, double-check this.

## Custom service layout

19 characteristics, all under the `04ca15xx-fd57-404e-8459-c5ef8d765c8d` base.
Only the ones that are actually used (or interesting) are listed below; the
remainder are documented in [docs/characteristics.md](characteristics.md) when
that file appears. *(spoiler: it doesn't yet.)*

| Short UUID | Properties | Function |
|---|---|---|
| `1502` | r/w | App-version tag (6-byte write, role unclear) |
| `1503` | r/w/notify | **Commands + state**. Reads echo current state, writes set mode/level, notifies fire after each state change. |
| `1506` | r/w/notify | Session "hello" — the app writes `02 02 00 00 00 00 00 00 01` here. **Not required** for our purposes. |
| `150a` | r/w | **Auth slot** — 17-byte bond token. Strict comparison against device-stored value. |
| `1581` | r/notify | **Telemetry** — four big-endian int16 temperatures, ~1 Hz. |
| `1582` | r/notify | Status heartbeat (5 bytes, accompanies each command). |
| `1584` | r/notify | Operation status with runtime counters; format partially decoded. |
| `1586` | notify | Notify-only, role unknown. |

The other characteristics (`1504`, `1505`, `1507`-`1509`, `1580`, `1583`,
`1585`, `15b0`, `15b1`, `15f0`) are addressed by the app but their semantics
have not been decoded. Most are gated behind the auth slot and rejected with
ATT 0x83 unless `150a` has been written first.

## Authentication

The Reon stores a single 17-byte secret in non-volatile memory. To talk to any
characteristic in the custom service you must first write this exact secret to
`150a`.

| ATT error | Meaning |
|---|---|
| `0x80` | invalid value (e.g. command level outside 0..3) |
| `0x81` | wrong token written to `150a` |
| `0x83` | no token written this connection yet |

The secret is **not** derived from anything the device exposes — no challenge,
no response, no echo. The auth bytes only ever appear in outbound traffic.
That makes them either app-side state (e.g. SharedPreferences) or persisted
device-side bond memory; we've confirmed it's the latter.

### Pair mode

Long-pressing the button on the unit puts it into a state where the auth slot
is **writable with anything**. Whatever 17-byte value you write becomes the new
stored secret, immediately and persistently. This is how the Sony app pairs in
the first place: on a fresh unit (or one that's been factory-reset / put in
pair mode) it generates a random installation token and writes it.

The 0x01 prefix on the captured Sony token may be a version marker; we've kept
it in `random_token()` defensively. The remaining 16 bytes look uniformly
random and we suspect they are.

### Coexistence

The device has exactly one auth slot. Pairing from a second client overwrites
the first. To make two clients coexist they must hold the same 17 bytes; the
easiest path is to extract the Sony app's token from a btsnoop capture and
restore it via `reon pair --token <hex>` after a pair-mode reset. See
[`tools/parse_btsnoop.py`](../tools/parse_btsnoop.py).

## Commands

Write to `1503`. 12 bytes:

```
00 00 00 <mode> <level> 00 00 00 00 00 00 00
```

| Mode byte | Meaning |
|---|---|
| `0x01` | cool (manual) |
| `0x02` | heat (manual) |
| `0x03` | smart (single-byte mode toggle, no level) |
| `0x04` | stop |

Levels are `0x00` through `0x03` for the manual modes. `0x04` and `0x05` are
both rejected with ATT 0x80 despite earlier external speculation that levels
went up to 5. The Sony app's UI shows levels 1..4 which map one-to-one onto
wire 0..3.

After a successful write, the device fires a notify on `1503` echoing the
state plus a few trailing bytes (likely current plate readings; format
unconfirmed).

### Smart mode

When the app activates smart mode it follows up with a longer 20-byte write to
`1503`:

```
04 00 00 1X xx xx xx xx 00 80 00 80 yy yy yy yy 00 00 00 00
```

The `0x0080` fields look like signed/scaled temperature setpoints. The sub-byte
`X` (e.g. `0x10`, `0x11`) probably distinguishes "smart-on with defaults" vs
"smart configure with new targets". Not exposed in this library yet.

## Telemetry

Notifies on `1581`. 19-byte frames at ~1 Hz:

```
01 T1H T1L T2H T2L T3H T3L T4H T4L  ff ff ff ff ff ff ff ff  00 00
```

Each `T` is a big-endian int16 in 1/100 °C. Empirical channel mapping based on
stress runs of cool L3 → stop → heat L3:

| Channel | Empirical role |
|---|---|
| `T1` | Board sensor near the skin plate (tracks T2 at ~0.4× magnitude) |
| `T2` | **Skin plate** — drops under cool, rises under heat |
| `T3` | **Heatsink** — mirrors T2 in the opposite direction |
| `T4` | Ambient / MCU (drifts least, < ±0.7 °C / minute) |

The first byte appears to be a frame-counter or status indicator; the
all-`ff` block in the middle is presumably reserved/unused.

Cool and heat are asymmetric: in 15 s at L3, T2 changed by about
**−4.0 °C** under cool but **+8.2 °C** under heat. Heat dumps current into a
resistor; cool fights heatsink saturation.

## State / status

`1584` notifies on connection state changes, roughly:

```
<mode> <level> 00 <flag1> <flag2> <byte5> 41c8 15c9 00 00 00 00 4500
```

The `41c8`, `15c9`, `17e9`, `45..` fields drift over time and appear to encode
runtime/fan/battery counters. Decoding is incomplete.

`1582` carries 5-byte status frames (`32 01 00 ff ff` in idle, occasionally
non-`ff` values during transitions) that accompany every command. Role
unclear; useful as a "this connection is alive" heartbeat.

## What's not in this document

- Pre-Pocket-3 / post-Pocket-3 generation compatibility.
- The semantics of `1504`, `1505`, `1507`, `1508`, `1509`, `1580`, `1583`,
  `1585`, `15b0`, `15b1`, `15f0`.
- Smart-mode setpoint format beyond raw byte positions.
- Battery percentage / charging state.
- Any LE pairing / encryption — the link is unencrypted; "auth" here means
  the app-layer token only.

PRs welcome.
