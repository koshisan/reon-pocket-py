"""High-level async client for the Sony Reon Pocket 3."""

from __future__ import annotations

import asyncio
import logging
from typing import Awaitable, Callable

from bleak import BleakClient, BleakScanner
from bleak.backends.characteristic import BleakGATTCharacteristic
from bleak.exc import BleakError

from . import protocol, storage

log = logging.getLogger(__name__)


class ReonError(Exception):
    """Reon-specific error, with the device's ATT code translated where possible."""


def _wrap_bleak_error(e: BleakError) -> ReonError:
    explanation = protocol.explain_att_error(str(e))
    if explanation:
        return ReonError(f"{explanation} (raw: {e})")
    return ReonError(str(e))


async def scan(timeout: float = 8.0) -> list[tuple[str, str | None, int | None]]:
    """Scan for nearby BLE devices. Returns (address, name, rssi) tuples."""
    devices = await BleakScanner.discover(timeout=timeout, return_adv=True)
    out: list[tuple[str, str | None, int | None]] = []
    for addr, (dev, adv) in devices.items():
        out.append((addr, dev.name, adv.rssi if adv else None))
    return out


async def find_reon(timeout: float = 8.0) -> str | None:
    """Return the BLE address of the first Reon found, or None."""
    for addr, name, _ in await scan(timeout):
        if name == protocol.DEVICE_NAME:
            return addr
    return None


class ReonClient:
    """Async context manager wrapping a Bleak connection plus the auth handshake.

    Usage::

        async with ReonClient(address) as r:
            await r.set_cool(3)
            await asyncio.sleep(5)
            await r.stop()
    """

    def __init__(self, address: str, token: bytes | None = None):
        self.address = address
        self._token = token if token is not None else _load_token_or_raise()
        self._bleak = BleakClient(address)

    async def __aenter__(self) -> "ReonClient":
        await self._bleak.__aenter__()
        try:
            await self._authenticate()
        except Exception:
            await self._bleak.__aexit__(None, None, None)
            raise
        return self

    async def __aexit__(self, exc_type, exc, tb):
        await self._bleak.__aexit__(exc_type, exc, tb)

    async def _authenticate(self):
        try:
            await self._bleak.write_gatt_char(protocol.CHAR_AUTH, self._token, response=True)
        except BleakError as e:
            raise _wrap_bleak_error(e) from e

    async def _write_cmd(self, frame: bytes):
        try:
            await self._bleak.write_gatt_char(protocol.CHAR_CMD, frame, response=True)
        except BleakError as e:
            raise _wrap_bleak_error(e) from e

    async def set_cool(self, level: int) -> None:
        await self._write_cmd(protocol.build_command(protocol.Mode.COOL, level))

    async def set_heat(self, level: int) -> None:
        await self._write_cmd(protocol.build_command(protocol.Mode.HEAT, level))

    async def stop(self) -> None:
        await self._write_cmd(protocol.build_command(protocol.Mode.STOP))

    async def on_telemetry(self, callback: Callable[[dict], Awaitable[None] | None]) -> None:
        """Subscribe to the ~1Hz temperature stream. callback receives the decoded dict."""

        async def adapter(_char: BleakGATTCharacteristic, data: bytearray):
            decoded = protocol.decode_telemetry(bytes(data))
            if decoded is None:
                return
            result = callback(decoded)
            if asyncio.iscoroutine(result):
                await result

        await self._bleak.start_notify(protocol.CHAR_TELEM, adapter)

    async def on_state(self, callback: Callable[[dict], Awaitable[None] | None]) -> None:
        """Subscribe to command-channel notifies (state echoes after each command)."""

        async def adapter(_char: BleakGATTCharacteristic, data: bytearray):
            decoded = protocol.decode_command_notify(bytes(data))
            if decoded is None:
                return
            result = callback(decoded)
            if asyncio.iscoroutine(result):
                await result

        await self._bleak.start_notify(protocol.CHAR_CMD, adapter)


def _load_token_or_raise() -> bytes:
    stored = storage.load()
    if stored is None:
        raise ReonError(
            f"No bond token found at {storage.token_path()}.\n"
            "Run `reon pair` while the Reon is in pair mode to create one."
        )
    return stored.token
