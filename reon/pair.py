"""Pairing: write a 17-byte bond token to the Reon's auth slot.

Works only while the device is in pair mode (long-press the button on the unit
until the LED indicates the mode change). The auth slot stays writable in that
state and accepts whatever you send. The stored value is persisted on the device
across power cycles.

Once paired, normal connections that don't replay the same token are rejected
with ATT 0x81. Re-pair from another client (e.g. the Sony app) will overwrite
the token slot, locking out anything that doesn't know the new value.
"""

from __future__ import annotations

import os

from bleak import BleakClient
from bleak.exc import BleakError

from . import protocol, storage
from .client import _wrap_bleak_error, find_reon


def random_token() -> bytes:
    """Generate a fresh 17-byte token.

    The first byte is fixed to 0x01 to match the framing observed in the wild
    (suspected version marker; tokens with different prefixes have not been
    tested, but the official app uses 0x01).
    """
    return bytes([0x01]) + os.urandom(protocol.AUTH_TOKEN_LEN - 1)


async def pair(address: str, token: bytes) -> None:
    """Write `token` to the auth characteristic and persist it locally.

    Raises ReonError if the device rejects the write (e.g. not in pair mode and
    `token` doesn't match the stored value).
    """
    if len(token) != protocol.AUTH_TOKEN_LEN:
        raise ValueError(f"token must be {protocol.AUTH_TOKEN_LEN} bytes")

    async with BleakClient(address) as bc:
        try:
            await bc.write_gatt_char(protocol.CHAR_AUTH, token, response=True)
        except BleakError as e:
            raise _wrap_bleak_error(e) from e

        # Save *before* exercising commands — a backend hiccup during the
        # smoke-test write must not lose the token we just successfully wrote.
        storage.save(address, token)

        # Smoke-test: a stop write should round-trip cleanly when auth is good.
        try:
            await bc.write_gatt_char(
                protocol.CHAR_CMD,
                protocol.build_command(protocol.Mode.STOP),
                response=True,
            )
        except BleakError as e:
            raise _wrap_bleak_error(e) from e


__all__ = ["random_token", "pair", "find_reon"]
