"""Little-endian binary I/O primitives used by problem serializers.

All multi-byte values are written and read in little-endian byte order. The
helpers operate on open binary streams so that callers can compose them
without juggling buffers themselves.
"""

from __future__ import annotations

import struct
from typing import BinaryIO

_U32 = struct.Struct("<I")
_U64 = struct.Struct("<Q")
_I32 = struct.Struct("<i")


class BinaryFormatError(ValueError):
    """Raised when a binary stream does not match the expected layout."""


def write_u32(stream: BinaryIO, value: int) -> None:
    stream.write(_U32.pack(value))


def write_u64(stream: BinaryIO, value: int) -> None:
    stream.write(_U64.pack(value))


def write_i32(stream: BinaryIO, value: int) -> None:
    stream.write(_I32.pack(value))


def write_i32_array(stream: BinaryIO, values: list[int]) -> None:
    if not values:
        return
    stream.write(struct.pack(f"<{len(values)}i", *values))


def read_u32(stream: BinaryIO) -> int:
    raw = _read_exact(stream, _U32.size, "u32")
    return _U32.unpack(raw)[0]


def read_u64(stream: BinaryIO) -> int:
    raw = _read_exact(stream, _U64.size, "u64")
    return _U64.unpack(raw)[0]


def read_i32(stream: BinaryIO) -> int:
    raw = _read_exact(stream, _I32.size, "i32")
    return _I32.unpack(raw)[0]


def read_i32_array(stream: BinaryIO, count: int) -> list[int]:
    if count == 0:
        return []
    raw = _read_exact(stream, count * _I32.size, f"i32[{count}]")
    return list(struct.unpack(f"<{count}i", raw))


def _read_exact(stream: BinaryIO, count: int, what: str) -> bytes:
    raw = stream.read(count)
    if len(raw) != count:
        raise BinaryFormatError(
            f"Unexpected end of stream while reading {what}: expected {count} bytes, got {len(raw)}"
        )
    return raw
