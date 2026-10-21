"""Little-endian binary I/O primitives used by problem serializers.

All multi-byte values are written and read in little-endian byte order. The
helpers operate on open binary streams so that callers can compose them
without juggling buffers themselves. They cover the scalars ``u8``, ``u32``,
``u64``, ``i32``, ``i64`` and ``f64``, arrays of the four common ones,
:func:`expect_end_of_stream` for a file that must end where its header says,
and two readers for the shapes that trace formats are made of: records of a
fixed size (:func:`read_records`) and tagged sections (:func:`read_sections`).

A writer that is given a value outside the range of its type raises
:class:`ValueError` naming the value (and, for an array, its index); a reader
that finds fewer bytes than it needs, or a count that promises more than the
stream holds, raises :class:`BinaryFormatError` before it reads or allocates
anything large.
"""

from __future__ import annotations

import io
import struct
from collections.abc import Callable, Mapping
from typing import Any, BinaryIO, TypeVar

SectionT = TypeVar("SectionT")

_U8 = struct.Struct("<B")
_U32 = struct.Struct("<I")
_U64 = struct.Struct("<Q")
_I32 = struct.Struct("<i")
_I64 = struct.Struct("<q")
_F64 = struct.Struct("<d")

_SECTION_KIND_BYTES = _U32.size


class BinaryFormatError(ValueError):
    """Raised when a binary stream does not match the expected layout."""


# ---- Scalars ----------------------------------------------------------------


def write_u8(stream: BinaryIO, value: int) -> None:
    stream.write(_pack(_U8, "u8", value))


def write_u32(stream: BinaryIO, value: int) -> None:
    stream.write(_pack(_U32, "u32", value))


def write_u64(stream: BinaryIO, value: int) -> None:
    stream.write(_pack(_U64, "u64", value))


def write_i32(stream: BinaryIO, value: int) -> None:
    stream.write(_pack(_I32, "i32", value))


def write_i64(stream: BinaryIO, value: int) -> None:
    stream.write(_pack(_I64, "i64", value))


def write_f64(stream: BinaryIO, value: float) -> None:
    stream.write(_pack(_F64, "f64", value))


def read_u8(stream: BinaryIO) -> int:
    return _U8.unpack(_read_exact(stream, _U8.size, "u8"))[0]


def read_u32(stream: BinaryIO) -> int:
    return _U32.unpack(_read_exact(stream, _U32.size, "u32"))[0]


def read_u64(stream: BinaryIO) -> int:
    return _U64.unpack(_read_exact(stream, _U64.size, "u64"))[0]


def read_i32(stream: BinaryIO) -> int:
    return _I32.unpack(_read_exact(stream, _I32.size, "i32"))[0]


def read_i64(stream: BinaryIO) -> int:
    return _I64.unpack(_read_exact(stream, _I64.size, "i64"))[0]


def read_f64(stream: BinaryIO) -> float:
    return _F64.unpack(_read_exact(stream, _F64.size, "f64"))[0]


# ---- Arrays -----------------------------------------------------------------
#
# Arrays carry no count of their own: the format writes the count first (usually
# a ``u64``) and the caller passes it back to the reader.


def write_i32_array(stream: BinaryIO, values: list[int]) -> None:
    _write_array(stream, values, "<i", "i32", -(2**31), 2**31 - 1)


def write_u32_array(stream: BinaryIO, values: list[int]) -> None:
    _write_array(stream, values, "<I", "u32", 0, 2**32 - 1)


def write_i64_array(stream: BinaryIO, values: list[int]) -> None:
    _write_array(stream, values, "<q", "i64", -(2**63), 2**63 - 1)


def write_f64_array(stream: BinaryIO, values: list[float]) -> None:
    if values:
        stream.write(struct.pack(f"<{len(values)}d", *values))


def read_i32_array(stream: BinaryIO, count: int) -> list[int]:
    """Read ``count`` i32 values; fail before reading when the stream is too short.

    A count that promises more bytes than the stream holds (for example a
    header claiming ``2**64 - 1`` elements) raises :class:`BinaryFormatError`
    instead of attempting an enormous read.
    """
    return _read_array(stream, count, "<i", _I32.size, "i32")


def read_u32_array(stream: BinaryIO, count: int) -> list[int]:
    """Read ``count`` u32 values, checked like :func:`read_i32_array`."""
    return _read_array(stream, count, "<I", _U32.size, "u32")


def read_i64_array(stream: BinaryIO, count: int) -> list[int]:
    """Read ``count`` i64 values, checked like :func:`read_i32_array`."""
    return _read_array(stream, count, "<q", _I64.size, "i64")


def read_f64_array(stream: BinaryIO, count: int) -> list[float]:
    """Read ``count`` f64 values, checked like :func:`read_i32_array`."""
    return _read_array(stream, count, "<d", _F64.size, "f64")


# ---- Ends, records, sections --------------------------------------------------


def expect_end_of_stream(stream: BinaryIO, what: str) -> None:
    """Raise :class:`BinaryFormatError` if any byte is left in ``stream``.

    Call it after the last field of a file whose size the header determines, so
    that a file with extra bytes is rejected instead of half read. ``what``
    names the file in the message, for example ``"The output file"``.
    """
    if stream.read(1):
        raise BinaryFormatError(f"{what} has trailing bytes after its last field")


def read_record_bytes(
    stream: BinaryIO, count: int, record_size: int, what: str = "records"
) -> bytes:
    """Read ``count`` records of ``record_size`` bytes each and return their bytes as one block.

    The count is checked against the bytes left in the stream before anything
    is read, so a corrupt count cannot make a reader allocate a huge buffer.
    Use it instead of :func:`read_records` when there are millions of records and
    the problem keeps them in a compact form of its own.
    """
    needed = count * record_size
    available = _bytes_remaining(stream)
    if available is not None and needed > available:
        raise BinaryFormatError(
            f"Declared {count} {what} ({needed} bytes), but only {available} bytes remain "
            "in the stream"
        )
    return _read_exact(stream, needed, f"{count} {what}")


def read_records(
    stream: BinaryIO, count: int, record: struct.Struct, what: str = "records"
) -> list[tuple[Any, ...]]:
    """Read ``count`` records laid out as ``record`` and return each one as a tuple.

    ``record`` is a :class:`struct.Struct`; give it a ``"<"`` prefix so that the
    fields are packed without padding, little-endian (``struct.Struct("<BII")``
    is nine bytes). The count is checked like in :func:`read_record_bytes`.
    """
    return list(record.iter_unpack(read_record_bytes(stream, count, record.size, what)))


def read_sections(
    stream: BinaryIO,
    readers_by_kind: Mapping[int, Callable[[BinaryIO], SectionT]],
    what: str = "trace",
) -> list[tuple[int, SectionT]]:
    """Read tagged sections until the end of ``stream``.

    A section is a ``u32`` kind followed by a body whose layout the kind
    decides; there is no total length, so the reader for the kind must consume
    exactly the body. ``readers_by_kind`` maps each known kind to that reader,
    which receives the stream positioned at the start of the body. The result
    lists ``(kind, body)`` in file order, and a kind may appear more than once.
    An empty stream has no sections. Raise :class:`BinaryFormatError` for an
    unknown kind (the message lists the known ones) and for a stream that ends
    inside a kind. ``what`` names the file in messages.
    """
    sections: list[tuple[int, SectionT]] = []
    while header := stream.read(_SECTION_KIND_BYTES):
        if len(header) != _SECTION_KIND_BYTES:
            raise BinaryFormatError(
                f"Unexpected end of stream while reading the kind of a {what} section: "
                f"expected {_SECTION_KIND_BYTES} bytes, got {len(header)}"
            )
        kind = _U32.unpack(header)[0]
        reader = readers_by_kind.get(kind)
        if reader is None:
            known = ", ".join(str(known_kind) for known_kind in sorted(readers_by_kind))
            raise BinaryFormatError(
                f"Unsupported {what} kind: {kind}. The known kinds are {known}."
            )
        sections.append((kind, reader(stream)))
    return sections


# ---- Helpers ------------------------------------------------------------------


def _pack(layout: struct.Struct, name: str, value: float) -> bytes:
    try:
        return layout.pack(value)
    except struct.error as error:
        raise ValueError(f"The value {value!r} cannot be written as {name}: {error}") from error


def _write_array(
    stream: BinaryIO, values: list[int], layout: str, name: str, lowest: int, highest: int
) -> None:
    if not values:
        return
    if min(values) < lowest or max(values) > highest:
        index = next(index for index, value in enumerate(values) if not lowest <= value <= highest)
        raise ValueError(
            f"Value at index {index} is out of {name} range [{lowest}, {highest}]: {values[index]}"
        )
    stream.write(struct.pack(f"{layout[0]}{len(values)}{layout[1]}", *values))


def _read_array(stream: BinaryIO, count: int, layout: str, size: int, name: str) -> list[Any]:
    if count == 0:
        return []
    available = _bytes_remaining(stream)
    if available is not None and count * size > available:
        raise BinaryFormatError(
            f"Declared {count} {name} values ({count * size} bytes), but only "
            f"{available} bytes remain in the stream"
        )
    raw = _read_exact(stream, count * size, f"{name}[{count}]")
    return list(struct.unpack(f"{layout[0]}{count}{layout[1]}", raw))


def _read_exact(stream: BinaryIO, count: int, what: str) -> bytes:
    raw = stream.read(count)
    if len(raw) != count:
        raise BinaryFormatError(
            f"Unexpected end of stream while reading {what}: expected {count} bytes, got {len(raw)}"
        )
    return raw


def _bytes_remaining(stream: BinaryIO) -> int | None:
    """Return the bytes left in ``stream``, or ``None`` when it cannot seek."""
    try:
        position = stream.tell()
        end = stream.seek(0, io.SEEK_END)
        stream.seek(position)
    except (OSError, ValueError):
        return None
    return end - position
