"""Round-trip and error tests for the binary_format helpers."""

from __future__ import annotations

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
ARRAYS = [
    pytest.param(write_i32_array, read_i32_array, [-(2**31), -3, 0, 7, 2**31 - 1], id="i32"),
    pytest.param(write_u32_array, read_u32_array, [0, 3, 2**32 - 1], id="u32"),
    pytest.param(write_i64_array, read_i64_array, [-(2**63), 0, 2**63 - 1], id="i64"),
    pytest.param(write_f64_array, read_f64_array, [0.5, -2.25, 1e-300], id="f64"),
]


class TestRoundTrip:
    @pytest.mark.parametrize(("write", "read", "values"), SCALARS)
    def test_scalars_round_trip(
        self, write: Callable[..., None], read: Callable[..., Any], values: tuple[Any, ...]
    ) -> None:
        buffer = io.BytesIO()
        for value in values:
            write(buffer, value)
        buffer.seek(0)
        assert [read(buffer) for _ in values] == list(values)

    @pytest.mark.parametrize(("write", "read", "values"), ARRAYS)
    def test_arrays_round_trip(
        self, write: Callable[..., None], read: Callable[..., Any], values: list[Any]
    ) -> None:
        buffer = io.BytesIO()
        write(buffer, values)
        buffer.seek(0)
        assert read(buffer, len(values)) == values

    @pytest.mark.parametrize(("write", "read", "values"), ARRAYS)
    def test_an_empty_array_is_zero_bytes(
        self, write: Callable[..., None], read: Callable[..., Any], values: list[Any]
    ) -> None:
        buffer = io.BytesIO()
        write(buffer, [])
        assert buffer.getvalue() == b""
        assert read(buffer, 0) == []

    def test_little_endian_byte_order(self) -> None:
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
    )
    def test_a_scalar_out_of_range_names_the_value_and_the_type(
        self, write: Callable[..., None], value: int
    ) -> None:
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
    )
    def test_an_array_value_out_of_range_names_its_index(
        self, write: Callable[..., None], values: list[int], index: int, name: str
    ) -> None:
        buffer = io.BytesIO()
        with pytest.raises(ValueError, match=rf"Value at index {index} is out of {name} range"):
            write(buffer, values)
        assert buffer.getvalue() == b""


class TestReadErrors:
    @pytest.mark.parametrize("read", [read_u8, read_u32, read_u64, read_i32, read_i64, read_f64])
    def test_read_past_end_raises_binary_format_error(self, read: Callable[..., Any]) -> None:
        with pytest.raises(BinaryFormatError, match="Unexpected end of stream"):
            read(io.BytesIO(b""))

    def test_read_i32_array_short_raises(self) -> None:
        buffer = io.BytesIO(b"\x00\x00\x00\x00")
        with pytest.raises(BinaryFormatError):
            read_i32_array(buffer, 2)

    @pytest.mark.parametrize(
        "read", [read_i32_array, read_u32_array, read_i64_array, read_f64_array]
    )
    def test_an_array_with_an_absurd_count_fails_before_reading(
        self, read: Callable[..., Any]
    ) -> None:
        buffer = io.BytesIO(b"\x00" * 8)
        with pytest.raises(BinaryFormatError, match="only 8 bytes remain"):
            read(buffer, 2**64 - 1)
        assert buffer.tell() == 0

    def test_read_i32_array_checks_against_the_remaining_bytes_not_the_whole_stream(self) -> None:
        buffer = io.BytesIO(b"\x00" * 12)
        buffer.seek(8)
        with pytest.raises(BinaryFormatError):
            read_i32_array(buffer, 2)
        assert read_i32_array(buffer, 1) == [0]


class TestEndOfStream:
    def test_a_stream_that_is_used_up_passes(self) -> None:
        stream = io.BytesIO(b"\x01\x00\x00\x00")
        read_u32(stream)
        expect_end_of_stream(stream, "The output file")

    def test_a_byte_left_over_is_named_after_the_file(self) -> None:
        stream = io.BytesIO(b"\x01\x00\x00\x00\x07")
        read_u32(stream)
        with pytest.raises(BinaryFormatError, match="The output file has trailing bytes"):
            expect_end_of_stream(stream, "The output file")


class TestRecords:
    LAYOUT = struct.Struct("<BII")

    def records(self, *rows: tuple[int, int, int]) -> bytes:
        return b"".join(self.LAYOUT.pack(*row) for row in rows)

    def test_records_are_read_as_tuples_without_padding(self) -> None:
        stream = io.BytesIO(self.records((1, 2, 3), (4, 5, 6)) + b"tail")
        assert read_records(stream, 2, self.LAYOUT) == [(1, 2, 3), (4, 5, 6)]
        assert stream.read() == b"tail"
        assert self.LAYOUT.size == 9

    def test_no_records_is_an_empty_list(self) -> None:
        assert read_records(io.BytesIO(b""), 0, self.LAYOUT) == []

    def test_a_count_that_promises_more_than_remains_fails_before_reading(self) -> None:
        stream = io.BytesIO(self.records((1, 2, 3)))
        with pytest.raises(BinaryFormatError, match=r"Declared 2 probes \(18 bytes\), but only 9"):
            read_records(stream, 2, self.LAYOUT, "probes")
        assert stream.tell() == 0

    def test_the_bytes_of_the_records_can_be_read_as_one_block(self) -> None:
        block = self.records((1, 2, 3), (4, 5, 6))
        assert read_record_bytes(io.BytesIO(block), 2, 9) == block


class TestSections:
    @staticmethod
    def numbers(stream: BinaryIO) -> list[int]:
        return read_i32_array(stream, read_u32(stream))

    @staticmethod
    def text(stream: BinaryIO) -> bytes:
        return stream.read(read_u8(stream))

    def encode(self, *sections: tuple[int, bytes]) -> io.BytesIO:
        return io.BytesIO(b"".join(struct.pack("<I", kind) + body for kind, body in sections))

    def test_sections_are_returned_with_their_kinds_in_file_order(self) -> None:
        stream = self.encode(
            (0, struct.pack("<Iii", 2, 5, 6)), (1, b"\x03abc"), (0, struct.pack("<Ii", 1, 9))
        )
        sections = read_sections(stream, {0: self.numbers, 1: self.text})
        assert sections == [(0, [5, 6]), (1, b"abc"), (0, [9])]

    def test_an_empty_stream_has_no_sections(self) -> None:
        assert read_sections(io.BytesIO(b""), {0: self.numbers}) == []

    def test_an_unknown_kind_lists_the_known_ones(self) -> None:
        with pytest.raises(BinaryFormatError, match=r"Unsupported trace kind: 7\. .* 0, 1"):
            read_sections(self.encode((7, b"")), {0: self.numbers, 1: self.text})

    def test_the_file_is_named_in_the_message(self) -> None:
        with pytest.raises(BinaryFormatError, match="Unsupported graph file kind: 7"):
            read_sections(self.encode((7, b"")), {0: self.numbers}, "graph file")

    def test_a_stream_that_ends_inside_a_kind_raises(self) -> None:
        with pytest.raises(BinaryFormatError, match=r"kind of a trace section.*got 2"):
            read_sections(io.BytesIO(b"\x00\x00"), {0: self.numbers})

    def test_a_body_that_ends_early_raises_from_its_reader(self) -> None:
        with pytest.raises(BinaryFormatError, match="only 4 bytes remain"):
            read_sections(self.encode((0, struct.pack("<Ii", 2, 5))), {0: self.numbers})
