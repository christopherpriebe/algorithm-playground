"""Tests for the binary_format helpers: round trips, range checks and malformed streams."""

import io
import struct
from collections.abc import Callable
from typing import Any, BinaryIO

import pytest

from algorithm_playground.core.binary_format import (
    BinaryFormatError,
    expect_end_of_stream,
    read_f64,
    read_f64_array,
    read_i32,
    read_i32_array,
    read_i64,
    read_i64_array,
    read_record_bytes,
    read_records,
    read_sections,
    read_u8,
    read_u32,
    read_u32_array,
    read_u64,
    write_f64,
    write_f64_array,
    write_i32,
    write_i32_array,
    write_i64,
    write_i64_array,
    write_u8,
    write_u32,
    write_u32_array,
    write_u64,
)

SCALARS = [
    pytest.param(write_u8, read_u8, (0, 1, 255), id="u8"),
    pytest.param(write_u32, read_u32, (0, 1, 42, 2**32 - 1), id="u32"),
    pytest.param(write_u64, read_u64, (0, 1, 2**32, 2**64 - 1), id="u64"),
    pytest.param(write_i32, read_i32, (-(2**31), -1, 0, 1, 2**31 - 1), id="i32"),
    pytest.param(write_i64, read_i64, (-(2**63), -1, 0, 2**40, 2**63 - 1), id="i64"),
    pytest.param(write_f64, read_f64, (0.0, -1.5, 2.5e300), id="f64"),
]
ARRAY_CODECS = [
    pytest.param(write_i32_array, read_i32_array, id="i32"),
    pytest.param(write_u32_array, read_u32_array, id="u32"),
    pytest.param(write_i64_array, read_i64_array, id="i64"),
    pytest.param(write_f64_array, read_f64_array, id="f64"),
]
ARRAYS = [
    pytest.param(write_i32_array, read_i32_array, [-(2**31), -3, 0, 7, 2**31 - 1], id="i32"),
    pytest.param(write_u32_array, read_u32_array, [0, 3, 2**32 - 1], id="u32"),
    pytest.param(write_i64_array, read_i64_array, [-(2**63), 0, 2**63 - 1], id="i64"),
    pytest.param(write_f64_array, read_f64_array, [0.5, -2.25, 1e-300], id="f64"),
]


RECORD_LAYOUT = struct.Struct("<BII")


def pack_records(*rows: tuple[int, int, int]) -> bytes:
    """Pack rows of three integers as records of ``RECORD_LAYOUT``."""
    return b"".join(RECORD_LAYOUT.pack(*row) for row in rows)


def read_numbers(stream: BinaryIO) -> list[int]:
    """Read a section body that holds a count followed by that many 32-bit integers."""
    return read_i32_array(stream, read_u32(stream))


def read_text(stream: BinaryIO) -> bytes:
    """Read a section body that holds a length byte followed by that many bytes."""
    return stream.read(read_u8(stream))


def encode_sections(*sections: tuple[int, bytes]) -> io.BytesIO:
    """Encode sections as a stream of a 32-bit kind followed by the body of each."""
    return io.BytesIO(b"".join(struct.pack("<I", kind) + body for kind, body in sections))


class TestRoundTrip:
    @pytest.mark.parametrize(("write", "read", "values"), SCALARS)
    def test_scalars_round_trip(
        self, write: Callable[..., None], read: Callable[..., Any], values: tuple[Any, ...]
    ) -> None:
        """Test scalars written one after another read back unchanged."""
        buffer = io.BytesIO()
        for value in values:
            write(buffer, value)
        buffer.seek(0)

        read_values = [read(buffer) for _ in values]

        assert read_values == list(values)

    @pytest.mark.parametrize(("write", "read", "values"), ARRAYS)
    def test_arrays_round_trip(
        self, write: Callable[..., None], read: Callable[..., Any], values: list[Any]
    ) -> None:
        """Test an array reads back unchanged when read with its length."""
        buffer = io.BytesIO()
        write(buffer, values)
        buffer.seek(0)

        assert read(buffer, len(values)) == values

    @pytest.mark.parametrize(("write", "read"), ARRAY_CODECS)
    def test_an_empty_array_is_zero_bytes(
        self, write: Callable[..., None], read: Callable[..., Any]
    ) -> None:
        """Test writing an empty array writes nothing and reading zero values reads nothing."""
        buffer = io.BytesIO()

        write(buffer, [])

        assert buffer.getvalue() == b""
        assert read(buffer, 0) == []

    def test_values_are_written_in_little_endian_byte_order(self) -> None:
        """Test multi-byte values are written least significant byte first."""
        buffer = io.BytesIO()

        write_u32(buffer, 0x01020304)
        write_i64(buffer, -2)

        assert buffer.getvalue() == b"\x04\x03\x02\x01" + b"\xfe" + b"\xff" * 7


class TestWriteErrors:
    @pytest.mark.parametrize(
        ("write", "value"),
        [
            (write_u8, 256),
            (write_u32, 2**32),
            (write_i32, 2**31),
            (write_i64, 2**63),
            (write_u32, -1),
        ],
        ids=["u8-too-large", "u32-too-large", "i32-too-large", "i64-too-large", "u32-negative"],
    )
    def test_a_scalar_out_of_range_names_the_value_and_the_type(
        self, write: Callable[..., None], value: int
    ) -> None:
        """Test writing a scalar outside its type's range raises an error naming value and type."""
        with pytest.raises(ValueError, match=rf"{value} cannot be written as [iu]\d+"):
            write(io.BytesIO(), value)

    @pytest.mark.parametrize(
        ("write", "values", "index", "name"),
        [
            (write_i32_array, [1, 2**31, 3], 1, "i32"),
            (write_i32_array, [-(2**31) - 1], 0, "i32"),
            (write_u32_array, [0, 5, -1], 2, "u32"),
            (write_i64_array, [2**63], 0, "i64"),
        ],
        ids=["i32-too-large", "i32-too-small", "u32-negative", "i64-too-large"],
    )
    def test_an_array_value_out_of_range_names_its_index(
        self, write: Callable[..., None], values: list[int], index: int, name: str
    ) -> None:
        """Test an out-of-range array item raises an error naming its index and writes nothing."""
        buffer = io.BytesIO()

        with pytest.raises(ValueError, match=rf"Value at index {index} is out of {name} range"):
            write(buffer, values)

        assert buffer.getvalue() == b""


class TestReadErrors:
    @pytest.mark.parametrize("read", [read_u8, read_u32, read_u64, read_i32, read_i64, read_f64])
    def test_reading_a_scalar_past_the_end_raises_a_binary_format_error(
        self, read: Callable[..., Any]
    ) -> None:
        """Test reading a scalar from an empty stream raises an error about the end of stream."""
        with pytest.raises(BinaryFormatError, match="Unexpected end of stream"):
            read(io.BytesIO(b""))

    def test_reading_more_array_values_than_the_stream_holds_raises(self) -> None:
        """Test reading two 32-bit values from a four-byte stream raises an error."""
        buffer = io.BytesIO(b"\x00\x00\x00\x00")

        with pytest.raises(
            BinaryFormatError, match=r"Declared 2 i32 values .* only 4 bytes remain"
        ):
            read_i32_array(buffer, 2)

    @pytest.mark.parametrize(
        "read", [read_i32_array, read_u32_array, read_i64_array, read_f64_array]
    )
    def test_an_array_with_an_absurd_count_fails_before_reading(
        self, read: Callable[..., Any]
    ) -> None:
        """Test an enormous declared count is rejected without consuming any of the stream."""
        buffer = io.BytesIO(b"\x00" * 8)

        with pytest.raises(BinaryFormatError, match="only 8 bytes remain"):
            read(buffer, 2**64 - 1)

        assert buffer.tell() == 0

    def test_an_array_is_checked_against_the_remaining_bytes_not_the_whole_stream(self) -> None:
        """Test the bytes already consumed do not count towards what an array can read."""
        buffer = io.BytesIO(b"\x00" * 12)
        buffer.seek(8)

        with pytest.raises(BinaryFormatError, match="only 4 bytes remain"):
            read_i32_array(buffer, 2)

        assert read_i32_array(buffer, 1) == [0]


class TestEndOfStream:
    def test_a_stream_that_is_used_up_passes(self) -> None:
        """Test a stream with nothing left over is accepted."""
        stream = io.BytesIO(b"\x01\x00\x00\x00")
        read_u32(stream)

        expect_end_of_stream(stream, "The output file")

    def test_a_byte_left_over_is_named_after_the_file(self) -> None:
        """Test a trailing byte raises an error that begins with the name of the file."""
        stream = io.BytesIO(b"\x01\x00\x00\x00\x07")
        read_u32(stream)

        with pytest.raises(BinaryFormatError, match="The output file has trailing bytes"):
            expect_end_of_stream(stream, "The output file")


class TestRecords:
    def test_records_are_read_as_tuples_without_padding(self) -> None:
        """Test records are read as tuples from packed bytes and the bytes after them remain."""
        stream = io.BytesIO(pack_records((1, 2, 3), (4, 5, 6)) + b"tail")

        records = read_records(stream, 2, RECORD_LAYOUT)

        assert records == [(1, 2, 3), (4, 5, 6)]
        assert stream.read() == b"tail"
        assert RECORD_LAYOUT.size == 9

    def test_no_records_is_an_empty_list(self) -> None:
        """Test reading zero records returns an empty list."""
        assert read_records(io.BytesIO(b""), 0, RECORD_LAYOUT) == []

    def test_a_count_that_promises_more_than_remains_fails_before_reading(self) -> None:
        """Test a record count larger than the stream holds is rejected without reading."""
        stream = io.BytesIO(pack_records((1, 2, 3)))

        with pytest.raises(BinaryFormatError, match=r"Declared 2 probes \(18 bytes\), but only 9"):
            read_records(stream, 2, RECORD_LAYOUT, "probes")

        assert stream.tell() == 0

    def test_the_bytes_of_the_records_can_be_read_as_one_block(self) -> None:
        """Test the raw bytes of several records can be read without decoding them."""
        block = pack_records((1, 2, 3), (4, 5, 6))

        assert read_record_bytes(io.BytesIO(block), 2, 9) == block


class TestSections:
    def test_sections_are_returned_with_their_kinds_in_file_order(self) -> None:
        """Test each section is decoded by the reader of its kind and returned in file order."""
        stream = encode_sections(
            (0, struct.pack("<Iii", 2, 5, 6)), (1, b"\x03abc"), (0, struct.pack("<Ii", 1, 9))
        )

        sections = read_sections(stream, {0: read_numbers, 1: read_text})

        assert sections == [(0, [5, 6]), (1, b"abc"), (0, [9])]

    def test_an_empty_stream_has_no_sections(self) -> None:
        """Test a stream without bytes holds no sections."""
        assert read_sections(io.BytesIO(b""), {0: read_numbers}) == []

    def test_an_unknown_kind_lists_the_known_ones(self) -> None:
        """Test an unsupported kind raises an error that lists the supported kinds."""
        stream = encode_sections((7, b""))

        with pytest.raises(BinaryFormatError, match=r"Unsupported trace kind: 7\. .* 0, 1"):
            read_sections(stream, {0: read_numbers, 1: read_text})

    def test_the_file_is_named_in_the_message(self) -> None:
        """Test the error for an unsupported kind names the kind of file given by the caller."""
        stream = encode_sections((7, b""))

        with pytest.raises(BinaryFormatError, match="Unsupported graph file kind: 7"):
            read_sections(stream, {0: read_numbers}, "graph file")

    def test_a_stream_that_ends_inside_a_kind_raises(self) -> None:
        """Test a stream that stops partway through a kind raises an error."""
        with pytest.raises(BinaryFormatError, match=r"kind of a trace section.*got 2"):
            read_sections(io.BytesIO(b"\x00\x00"), {0: read_numbers})

    def test_a_body_that_ends_early_raises_from_its_reader(self) -> None:
        """Test a section body shorter than it declares raises the error of the body reader."""
        stream = encode_sections((0, struct.pack("<Ii", 2, 5)))

        with pytest.raises(BinaryFormatError, match="only 4 bytes remain"):
            read_sections(stream, {0: read_numbers})
