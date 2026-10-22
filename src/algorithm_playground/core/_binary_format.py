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

import io
import struct
from collections.abc import Callable, Mapping
from typing import Any, BinaryIO, TypeVar

from algorithm_playground.core._errors import AlgorithmPlaygroundError

__all__ = [
    "BinaryFormatError",
    "Record",
    "expect_end_of_stream",
    "read_f64",
    "read_f64_array",
    "read_i32",
    "read_i32_array",
    "read_i64",
    "read_i64_array",
    "read_record_bytes",
    "read_records",
    "read_sections",
    "read_u8",
    "read_u32",
    "read_u32_array",
    "read_u64",
    "write_f64",
    "write_f64_array",
    "write_i32",
    "write_i32_array",
    "write_i64",
    "write_i64_array",
    "write_u8",
    "write_u32",
    "write_u32_array",
    "write_u64",
]

SectionT = TypeVar("SectionT")

# The fields of one record. Their types come from the struct format that the caller chose.
Record = tuple[Any, ...]

_U8 = struct.Struct("<B")
_U32 = struct.Struct("<I")
_U64 = struct.Struct("<Q")
_I32 = struct.Struct("<i")
_I64 = struct.Struct("<q")
_F64 = struct.Struct("<d")

_TYPE_NAMES = {
    _U8.format: "u8",
    _U32.format: "u32",
    _U64.format: "u64",
    _I32.format: "i32",
    _I64.format: "i64",
    _F64.format: "f64",
}

_SECTION_KIND_BYTES = _U32.size


def _pack(layout: struct.Struct, value: float) -> bytes:
    try:
        return layout.pack(value)
    except struct.error as error:
        message = f"The value {value!r} cannot be written as {_TYPE_NAMES[layout.format]}: {error}"
        raise ValueError(message) from error


def _write_integer_array(
    stream: BinaryIO, values: list[int], layout: struct.Struct
) -> None:
    if not values:
        return
    bits = layout.size * 8
    is_signed = layout.format[1].islower()
    lowest = -(2 ** (bits - 1)) if is_signed else 0
    highest = 2 ** (bits - 1) - 1 if is_signed else 2**bits - 1
    if min(values) < lowest or max(values) > highest:
        index = next(
            index
            for index, value in enumerate(values)
            if not lowest <= value <= highest
        )
        message = (
            f"Value at index {index} is out of {_TYPE_NAMES[layout.format]} range "
            f"[{lowest}, {highest}]: {values[index]}"
        )
        raise ValueError(message)
    stream.write(struct.pack(f"<{len(values)}{layout.format[1]}", *values))


def _read_exact(stream: BinaryIO, count: int, what: str) -> bytes:
    raw = stream.read(count)
    if len(raw) != count:
        message = f"Unexpected end of stream while reading {what}: expected {count} bytes, got {len(raw)}"
        raise BinaryFormatError(message)
    return raw


def _read_scalar_bytes(stream: BinaryIO, layout: struct.Struct) -> bytes:
    return _read_exact(stream, layout.size, _TYPE_NAMES[layout.format])


def _bytes_remaining(stream: BinaryIO) -> int | None:
    """Return the bytes left in ``stream``, or ``None`` when it cannot seek."""
    try:
        position = stream.tell()
        end = stream.seek(0, io.SEEK_END)
        stream.seek(position)
    except (OSError, ValueError):
        return None
    return end - position


def _read_array_bytes(stream: BinaryIO, count: int, layout: struct.Struct) -> bytes:
    """Read the bytes of ``count`` values of ``layout``, after checking the stream holds them.

    Args:
        stream: The binary stream to read from.
        count: The number of values to read.
        layout: The layout of one value.

    Returns:
        The bytes of the values.

    Raises:
        BinaryFormatError: If the stream holds fewer than ``count`` values.
    """
    if count == 0:
        return b""
    name = _TYPE_NAMES[layout.format]
    available = _bytes_remaining(stream)
    if available is not None and count * layout.size > available:
        message = (
            f"Declared {count} {name} values ({count * layout.size} bytes), but only "
            f"{available} bytes remain in the stream"
        )
        raise BinaryFormatError(message)
    return _read_exact(stream, count * layout.size, f"{name}[{count}]")


class BinaryFormatError(AlgorithmPlaygroundError, ValueError):
    """Raised when a binary stream does not match the expected layout."""


# ---- Scalars ----------------------------------------------------------------


def write_u8(stream: BinaryIO, value: int) -> None:
    """Write an unsigned 8-bit integer.

    Raise :class:`ValueError` if ``value`` does not fit in a ``u8``.

    Args:
        stream: The binary stream to write to.
        value: The value, from 0 to 255.
    """
    stream.write(_pack(_U8, value))


def write_u32(stream: BinaryIO, value: int) -> None:
    """Write an unsigned 32-bit integer.

    Raise :class:`ValueError` if ``value`` does not fit in a ``u32``.

    Args:
        stream: The binary stream to write to.
        value: The value, from 0 to ``2**32 - 1``.
    """
    stream.write(_pack(_U32, value))


def write_u64(stream: BinaryIO, value: int) -> None:
    """Write an unsigned 64-bit integer.

    Raise :class:`ValueError` if ``value`` does not fit in a ``u64``.

    Args:
        stream: The binary stream to write to.
        value: The value, from 0 to ``2**64 - 1``.
    """
    stream.write(_pack(_U64, value))


def write_i32(stream: BinaryIO, value: int) -> None:
    """Write a signed 32-bit integer.

    Raise :class:`ValueError` if ``value`` does not fit in an ``i32``.

    Args:
        stream: The binary stream to write to.
        value: The value, from ``-2**31`` to ``2**31 - 1``.
    """
    stream.write(_pack(_I32, value))


def write_i64(stream: BinaryIO, value: int) -> None:
    """Write a signed 64-bit integer.

    Raise :class:`ValueError` if ``value`` does not fit in an ``i64``.

    Args:
        stream: The binary stream to write to.
        value: The value, from ``-2**63`` to ``2**63 - 1``.
    """
    stream.write(_pack(_I64, value))


def write_f64(stream: BinaryIO, value: float) -> None:
    """Write a 64-bit floating-point number.

    Raise :class:`ValueError` if ``value`` cannot be written as an ``f64``.

    Args:
        stream: The binary stream to write to.
        value: The value.
    """
    stream.write(_pack(_F64, value))


def read_u8(stream: BinaryIO) -> int:
    """Read an unsigned 8-bit integer.

    Raise :class:`BinaryFormatError` if the stream ends before the value does.

    Args:
        stream: The binary stream to read from.

    Returns:
        The value.
    """
    return int(_U8.unpack(_read_scalar_bytes(stream, _U8))[0])


def read_u32(stream: BinaryIO) -> int:
    """Read an unsigned 32-bit integer.

    Raise :class:`BinaryFormatError` if the stream ends before the value does.

    Args:
        stream: The binary stream to read from.

    Returns:
        The value.
    """
    return int(_U32.unpack(_read_scalar_bytes(stream, _U32))[0])


def read_u64(stream: BinaryIO) -> int:
    """Read an unsigned 64-bit integer.

    Raise :class:`BinaryFormatError` if the stream ends before the value does.

    Args:
        stream: The binary stream to read from.

    Returns:
        The value.
    """
    return int(_U64.unpack(_read_scalar_bytes(stream, _U64))[0])


def read_i32(stream: BinaryIO) -> int:
    """Read a signed 32-bit integer.

    Raise :class:`BinaryFormatError` if the stream ends before the value does.

    Args:
        stream: The binary stream to read from.

    Returns:
        The value.
    """
    return int(_I32.unpack(_read_scalar_bytes(stream, _I32))[0])


def read_i64(stream: BinaryIO) -> int:
    """Read a signed 64-bit integer.

    Raise :class:`BinaryFormatError` if the stream ends before the value does.

    Args:
        stream: The binary stream to read from.

    Returns:
        The value.
    """
    return int(_I64.unpack(_read_scalar_bytes(stream, _I64))[0])


def read_f64(stream: BinaryIO) -> float:
    """Read a 64-bit floating-point number.

    Raise :class:`BinaryFormatError` if the stream ends before the value does.

    Args:
        stream: The binary stream to read from.

    Returns:
        The value.
    """
    return float(_F64.unpack(_read_scalar_bytes(stream, _F64))[0])


# ---- Arrays -----------------------------------------------------------------
#
# Arrays carry no count of their own: the format writes the count first (usually
# a ``u64``) and the caller passes it back to the reader.


def write_i32_array(stream: BinaryIO, values: list[int]) -> None:
    """Write signed 32-bit integers back to back, without a count.

    Raise :class:`ValueError` if a value does not fit in an ``i32``. The message names
    its index.

    Args:
        stream: The binary stream to write to.
        values: The values to write; an empty list writes nothing.
    """
    _write_integer_array(stream, values, _I32)


def write_u32_array(stream: BinaryIO, values: list[int]) -> None:
    """Write unsigned 32-bit integers back to back, without a count.

    Raise :class:`ValueError` if a value does not fit in a ``u32``. The message names
    its index.

    Args:
        stream: The binary stream to write to.
        values: The values to write; an empty list writes nothing.
    """
    _write_integer_array(stream, values, _U32)


def write_i64_array(stream: BinaryIO, values: list[int]) -> None:
    """Write signed 64-bit integers back to back, without a count.

    Raise :class:`ValueError` if a value does not fit in an ``i64``. The message names
    its index.

    Args:
        stream: The binary stream to write to.
        values: The values to write; an empty list writes nothing.
    """
    _write_integer_array(stream, values, _I64)


def write_f64_array(stream: BinaryIO, values: list[float]) -> None:
    """Write 64-bit floating-point numbers back to back, without a count.

    Args:
        stream: The binary stream to write to.
        values: The values to write; an empty list writes nothing.
    """
    if values:
        stream.write(struct.pack(f"<{len(values)}d", *values))


def read_i32_array(stream: BinaryIO, count: int) -> list[int]:
    """Read signed 32-bit integers; fail before reading when the stream is too short.

    A count that promises more bytes than the stream holds (for example a
    header claiming ``2**64 - 1`` elements) raises :class:`BinaryFormatError`
    instead of attempting an enormous read.

    Raise :class:`BinaryFormatError` if the stream holds fewer than ``count`` values.

    Args:
        stream: The binary stream to read from.
        count: The number of values to read.

    Returns:
        The values.
    """
    return list(struct.unpack(f"<{count}i", _read_array_bytes(stream, count, _I32)))


def read_u32_array(stream: BinaryIO, count: int) -> list[int]:
    """Read unsigned 32-bit integers, checked like :func:`read_i32_array`.

    Raise :class:`BinaryFormatError` if the stream holds fewer than ``count`` values.

    Args:
        stream: The binary stream to read from.
        count: The number of values to read.

    Returns:
        The values.
    """
    return list(struct.unpack(f"<{count}I", _read_array_bytes(stream, count, _U32)))


def read_i64_array(stream: BinaryIO, count: int) -> list[int]:
    """Read signed 64-bit integers, checked like :func:`read_i32_array`.

    Raise :class:`BinaryFormatError` if the stream holds fewer than ``count`` values.

    Args:
        stream: The binary stream to read from.
        count: The number of values to read.

    Returns:
        The values.
    """
    return list(struct.unpack(f"<{count}q", _read_array_bytes(stream, count, _I64)))


def read_f64_array(stream: BinaryIO, count: int) -> list[float]:
    """Read 64-bit floating-point numbers, checked like :func:`read_i32_array`.

    Raise :class:`BinaryFormatError` if the stream holds fewer than ``count`` values.

    Args:
        stream: The binary stream to read from.
        count: The number of values to read.

    Returns:
        The values.
    """
    return list(struct.unpack(f"<{count}d", _read_array_bytes(stream, count, _F64)))


# ---- Ends, records, sections --------------------------------------------------


def expect_end_of_stream(stream: BinaryIO, what: str) -> None:
    """Require that no byte is left in a stream.

    Call it after the last field of a file whose size the header determines, so
    that a file with extra bytes is rejected instead of half read.

    Args:
        stream: The binary stream to check.
        what: Names the file in the message, for example ``"The output file"``.

    Raises:
        BinaryFormatError: If any byte is left in ``stream``.
    """
    if stream.read(1):
        message = f"{what} has trailing bytes after its last field"
        raise BinaryFormatError(message)


def read_record_bytes(
    stream: BinaryIO, count: int, record_size: int, what: str = "records"
) -> bytes:
    """Read records of a fixed size and return their bytes as one block.

    The count is checked against the bytes left in the stream before anything
    is read, so a corrupt count cannot make a reader allocate a huge buffer.
    Use it instead of :func:`read_records` when there are millions of records and
    the problem keeps them in a compact form of its own.

    Args:
        stream: The binary stream to read from.
        count: The number of records to read.
        record_size: The size of one record in bytes.
        what: Names the records in messages.

    Returns:
        The ``count * record_size`` bytes of the records.

    Raises:
        BinaryFormatError: If the stream holds fewer bytes than the records need.
    """
    needed = count * record_size
    available = _bytes_remaining(stream)
    if available is not None and needed > available:
        message = (
            f"Declared {count} {what} ({needed} bytes), but only {available} bytes remain "
            "in the stream"
        )
        raise BinaryFormatError(message)
    return _read_exact(stream, needed, f"{count} {what}")


def read_records(
    stream: BinaryIO, count: int, record: struct.Struct, what: str = "records"
) -> list[Record]:
    """Read records laid out as a :class:`struct.Struct` and return each one as a tuple.

    Raise :class:`BinaryFormatError` if the stream holds fewer bytes than the records
    need, checked like in :func:`read_record_bytes`.

    Args:
        stream: The binary stream to read from.
        count: The number of records to read.
        record: The layout of one record. Give it a ``"<"`` prefix so that the
            fields are packed without padding, little-endian
            (``struct.Struct("<BII")`` is nine bytes).
        what: Names the records in messages.

    Returns:
        One tuple of fields per record.
    """
    return list(record.iter_unpack(read_record_bytes(stream, count, record.size, what)))


def read_sections(
    stream: BinaryIO,
    readers_by_kind: Mapping[int, Callable[[BinaryIO], SectionT]],
    what: str = "trace",
) -> list[tuple[int, SectionT]]:
    """Read tagged sections until the end of a stream.

    A section is a ``u32`` kind followed by a body whose layout the kind
    decides; there is no total length, so the reader for the kind must consume
    exactly the body. A kind may appear more than once, and an empty stream has
    no sections.

    Args:
        stream: The binary stream to read from.
        readers_by_kind: Maps each known kind to the function that reads its
            body. The function receives the stream positioned at the start of
            the body.
        what: Names the file in messages.

    Returns:
        ``(kind, body)`` for each section, in file order.

    Raises:
        BinaryFormatError: If a kind is unknown (the message lists the known
            ones) or the stream ends inside a kind.
    """
    sections: list[tuple[int, SectionT]] = []
    while header := stream.read(_SECTION_KIND_BYTES):
        if len(header) != _SECTION_KIND_BYTES:
            message = (
                f"Unexpected end of stream while reading the kind of a {what} section: "
                f"expected {_SECTION_KIND_BYTES} bytes, got {len(header)}"
            )
            raise BinaryFormatError(message)
        kind = _U32.unpack(header)[0]
        reader = readers_by_kind.get(kind)
        if reader is None:
            known = ", ".join(str(known_kind) for known_kind in sorted(readers_by_kind))
            message = f"Unsupported {what} kind: {kind}. The known kinds are {known}."
            raise BinaryFormatError(message)
        sections.append((kind, reader(stream)))
    return sections
