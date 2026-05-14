"""Sony Reon Pocket 3 BLE protocol constants and frame builders."""

from __future__ import annotations

from enum import IntEnum

# Advertised name used to recognise the device during scan.
DEVICE_NAME = "RNP-3"

# Custom GATT service and the characteristics we actually use.
# Note: UUID group 3 is `404e`, NOT `4057` — easy to misread.
SERVICE_UUID = "04ca1501-fd57-404e-8459-c5ef8d765c8d"
CHAR_AUTH    = "04ca150a-fd57-404e-8459-c5ef8d765c8d"  # 17-byte bond token gate
CHAR_CMD     = "04ca1503-fd57-404e-8459-c5ef8d765c8d"  # 12-byte command + state notify
CHAR_TELEM   = "04ca1581-fd57-404e-8459-c5ef8d765c8d"  # 4× int16 temperatures, ~1 Hz
CHAR_STATUS  = "04ca1584-fd57-404e-8459-c5ef8d765c8d"  # mode + runtime counters

AUTH_TOKEN_LEN = 17
COMMAND_FRAME_LEN = 12


class Mode(IntEnum):
    COOL = 0x01
    HEAT = 0x02
    SMART = 0x03
    STOP = 0x04


# Wire-level levels are 0..3 inclusive (four steps). The Sony app's UI shows 1..4
# which maps one-to-one onto wire 0..3. Stop is a separate mode, not "level 0".
LEVEL_MIN = 0
LEVEL_MAX = 3


def build_command(mode: Mode | int, level: int = 0) -> bytes:
    """Return the 12-byte command frame for a mode/level write to CHAR_CMD."""
    if mode != Mode.STOP and not (LEVEL_MIN <= level <= LEVEL_MAX):
        raise ValueError(f"level {level} out of range {LEVEL_MIN}..{LEVEL_MAX}")
    return bytes([0, 0, 0, int(mode), level, 0, 0, 0, 0, 0, 0, 0])


def decode_telemetry(data: bytes) -> dict | None:
    """Decode a notify frame from CHAR_TELEM. Returns a dict of named float temps.

    Frame: 01 T1 T2 T3 T4 ff*8 00 00, with each T as int16 big-endian in 1/100 °C.
    Empirical channel mapping:
      skin_plate    — the user-facing plate (changes sign with mode)
      heatsink      — the outer plate (mirrors skin_plate)
      board         — board sensor near the skin plate (tracks skin_plate at ~0.4×)
      ambient       — slowest-drifting sensor, presumed ambient/MCU
    """
    if len(data) < 9:
        return None
    raw = [int.from_bytes(data[1 + 2 * i:3 + 2 * i], "big") / 100.0 for i in range(4)]
    # The Reon ships T1..T4 in a fixed order; the labels below are empirical guesses
    # that should be revisited if you have access to Sony's datasheet.
    return {
        "board":      raw[0],
        "skin_plate": raw[1],
        "heatsink":   raw[2],
        "ambient":    raw[3],
    }


def decode_command_notify(data: bytes) -> dict | None:
    """Decode the device's state-notify on CHAR_CMD. Echoes the last command's
    mode and level, followed by a few status bytes whose meaning is not yet
    fully understood (likely current plate temps).
    """
    if len(data) < 5:
        return None
    return {
        "mode": data[3],
        "level": data[4],
        "tail": bytes(data[5:]),
    }


# ATT error codes returned by the Reon. These are all vendor-defined application
# errors (BLE spec reserves 0x80..0xff for that purpose); they are NOT standard
# ATT errors. Discovered empirically.
ATT_ERROR_NAMES = {
    0x80: "invalid value (e.g. level out of range)",
    0x81: "authentication failed (wrong bond token on 150a)",
    0x83: "authorization missing (no token written this connection)",
}


def explain_att_error(message: str) -> str | None:
    """Try to identify a Reon-specific ATT error code in a Bleak exception message."""
    import re
    m = re.search(r"Protocol Error 0x([0-9a-fA-F]{2})", message)
    if not m:
        return None
    code = int(m.group(1), 16)
    return ATT_ERROR_NAMES.get(code)
