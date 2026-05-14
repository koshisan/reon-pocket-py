"""Sony Reon Pocket BLE protocol constants and frame builders.

Verified empirically against RNP-3 (firmware 2.3.6) and RNP-P1 (firmware
2.2.1). The two devices speak the same custom service with the same
characteristic UUIDs and handle layout. They differ in:
  - cool level range: RNP-3 caps at L3, RNP-P1 at L4
  - heat level range: both cap at L3
  - telemetry frame: RNP-P1 emits 18 bytes with 7 active 16-bit sensor
    readings instead of 4, plus a 0xffff sentinel where no sensor is wired
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import IntEnum

# Advertised name prefix used to recognise the device during scan. Sony's
# wearable Reon line ships as "RNP-3" today; future generations are expected
# to follow the same prefix ("RNP-4", "RNP-5", …). Whether the wire protocol
# below applies to them is unverified — discovery is loose, command logic is not.
DEVICE_NAME = "RNP-3"  # back-compat alias; prefer DEVICE_NAME_PREFIX
DEVICE_NAME_PREFIX = "RNP-"

# Custom GATT service and the characteristics we actually use.
# Note: UUID group 3 is `404e`, NOT `4057` — easy to misread.
SERVICE_UUID = "04ca1501-fd57-404e-8459-c5ef8d765c8d"
CHAR_AUTH    = "04ca150a-fd57-404e-8459-c5ef8d765c8d"  # 17-byte bond token gate
CHAR_CMD     = "04ca1503-fd57-404e-8459-c5ef8d765c8d"  # 12-byte command + state notify
CHAR_TELEM   = "04ca1581-fd57-404e-8459-c5ef8d765c8d"  # 4× int16 temperatures, ~1 Hz
CHAR_STATUS  = "04ca1584-fd57-404e-8459-c5ef8d765c8d"  # mode + runtime counters

AUTH_TOKEN_LEN = 17
COMMAND_FRAME_LEN = 12

# Standard BLE Device Information service — used to identify the device model
# at connect time so we can pick the right capability profile.
MODEL_NUMBER_UUID = "00002a24-0000-1000-8000-00805f9b34fb"


class Mode(IntEnum):
    COOL = 0x01
    HEAT = 0x02
    SMART = 0x03
    STOP = 0x04


# Wire levels are 0..LEVEL_MAX_ABSOLUTE inclusive across all known models;
# per-direction caps live in Capabilities (looked up by model).
LEVEL_MIN = 0
LEVEL_MAX_ABSOLUTE = 4
LEVEL_MAX = LEVEL_MAX_ABSOLUTE  # backwards-compat alias


@dataclass(frozen=True)
class Capabilities:
    """Per-model command-range caps. Both cool and heat min at 0."""
    cool_max: int
    heat_max: int


DEFAULT_CAPABILITIES = Capabilities(cool_max=3, heat_max=3)

CAPABILITIES_BY_MODEL: dict[str, Capabilities] = {
    "RNP-3":  Capabilities(cool_max=3, heat_max=3),
    "RNP-P1": Capabilities(cool_max=4, heat_max=3),
}


def capabilities_for(model: str | None) -> Capabilities:
    """Look up capabilities by model string (e.g. from BLE Model Number).
    Falls back to the conservative default if unknown."""
    if not model:
        return DEFAULT_CAPABILITIES
    return CAPABILITIES_BY_MODEL.get(model.strip(), DEFAULT_CAPABILITIES)


def build_command(mode: Mode | int, level: int = 0) -> bytes:
    """Return the 12-byte command frame for a mode/level write to CHAR_CMD."""
    if mode != Mode.STOP and not (LEVEL_MIN <= level <= LEVEL_MAX_ABSOLUTE):
        raise ValueError(f"level {level} out of range {LEVEL_MIN}..{LEVEL_MAX_ABSOLUTE}")
    return bytes([0, 0, 0, int(mode), level, 0, 0, 0, 0, 0, 0, 0])


def _read_temp(raw: bytes) -> float | None:
    """Decode one 16-bit big-endian temperature field, returning None for the
    0xffff sentinel that the Reon uses to indicate an unwired sensor slot."""
    v = int.from_bytes(raw, "big")
    return None if v == 0xffff else v / 100.0


def decode_telemetry(data: bytes) -> dict | None:
    """Decode a notify frame from CHAR_TELEM.

    Both generations emit a 0x01 marker followed by big-endian int16 fields
    in 1/100 °C. RNP-3 sends 4 sensors; RNP-P1 sends 7 (one slot is the
    0xffff sentinel and one is humidity/zero). We only surface the first 4
    here — the rest are model-specific and not currently mapped.

    Empirical channel mapping on RNP-3:
      board / skin_plate / heatsink / ambient
    On RNP-P1 the same slots are populated by different sensors; the
    'ambient' slot tends to be 0xffff (None).
    """
    if len(data) < 9:
        return None
    return {
        "board":      _read_temp(data[1:3]),
        "skin_plate": _read_temp(data[3:5]),
        "heatsink":   _read_temp(data[5:7]),
        "ambient":    _read_temp(data[7:9]),
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
