"""Round-trip and error tests for the binary_io helpers."""

from __future__ import annotations

import io
import struct

import pytest

from algorithm_playground.core.binary_io import (
    BinaryFormatError,
    read_i32,
    read_i32_array,
    read_u32,
    read_u64,
    write_i32,
    write_i32_array,
    write_u32,
    write_u64,
)


class TestRoundTrip:
    def test_u32_round_trips(self) -> None:
        buffer = io.BytesIO()
        for value in (0, 1, 42, 2**32 - 1):
            write_u32(buffer, value)
        buffer.seek(0)
        assert [read_u32(buffer) for _ in range(4)] == [0, 1, 42, 2**32 - 1]

    def test_u64_round_trips(self) -> None:
        buffer = io.BytesIO()
        for value in (0, 1, 2**32, 2**64 - 1):
            write_u64(buffer, value)
        buffer.seek(0)
        assert [read_u64(buffer) for _ in range(4)] == [0, 1, 2**32, 2**64 - 1]

    def test_i32_round_trips(self) -> None:
        buffer = io.BytesIO()
        for value in (-(2**31), -1, 0, 1, 2**31 - 1):
            write_i32(buffer, value)
        buffer.seek(0)
        assert [read_i32(buffer) for _ in range(5)] == [-(2**31), -1, 0, 1, 2**31 - 1]

    def test_i32_array_round_trips(self) -> None:
        values = [-(2**31), -3, 0, 7, 2**31 - 1]
        buffer = io.BytesIO()
        write_i32_array(buffer, values)
        buffer.seek(0)
        assert read_i32_array(buffer, len(values)) == values

    def test_empty_i32_array_is_zero_bytes(self) -> None:
        buffer = io.BytesIO()
        write_i32_array(buffer, [])
        assert buffer.getvalue() == b""
        assert read_i32_array(buffer, 0) == []

    def test_little_endian_byte_order(self) -> None:
        buffer = io.BytesIO()
        write_u32(buffer, 0x01020304)
        assert buffer.getvalue() == b"\x04\x03\x02\x01"


class TestErrors:
    def test_overflow_u32_raises(self) -> None:
        with pytest.raises(struct.error):
            write_u32(io.BytesIO(), 2**32)

    def test_overflow_i32_raises(self) -> None:
        with pytest.raises(struct.error):
            write_i32(io.BytesIO(), 2**31)

    def test_read_past_end_raises_binary_format_error(self) -> None:
        buffer = io.BytesIO(b"\x01\x02")
        with pytest.raises(BinaryFormatError):
            read_u32(buffer)

    def test_read_i32_array_short_raises(self) -> None:
        buffer = io.BytesIO(b"\x00\x00\x00\x00")
        with pytest.raises(BinaryFormatError):
            read_i32_array(buffer, 2)
