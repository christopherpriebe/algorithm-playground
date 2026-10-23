"""Tests for the binary format of sorting inputs and outputs."""

import struct
from pathlib import Path

import pytest
from hypothesis import given, strategies

from algorithm_playground.core import (
    BinaryFormatError,
)
from algorithm_playground.problems.sorting import (
    I32_MAX,
    I32_MIN,
    SortingProblem,
    read_values,
    write_values,
)


def test_input_is_written_as_a_count_followed_by_i32_values(
    problem: SortingProblem, tmp_path: Path
) -> None:
    """Test an input is written as a u64 count followed by little-endian i32 values."""
    path = tmp_path / "input.bin"

    problem.serialize_input([-3, 0, 7, I32_MAX, I32_MIN], path)

    raw = path.read_bytes()
    assert raw[:8] == struct.pack("<Q", 5)
    values = list(struct.unpack_from("<5i", raw, 8))
    assert values == [-3, 0, 7, I32_MAX, I32_MIN]


def test_input_rejects_value_outside_i32_range(
    problem: SortingProblem, tmp_path: Path
) -> None:
    """Test serializing a value outside the i32 range is rejected."""
    with pytest.raises(ValueError, match="out of i32 range"):
        problem.serialize_input([2**31], tmp_path / "input.bin")


def test_output_is_read_from_a_count_followed_by_i32_values(
    problem: SortingProblem, tmp_path: Path
) -> None:
    """Test an output file holding a count and i32 values is read as a list."""
    path = tmp_path / "output.bin"
    path.write_bytes(struct.pack("<Q3i", 3, -1, 0, 5))

    output = problem.deserialize_output(path)

    assert output == [-1, 0, 5]


def test_input_is_read_back(problem: SortingProblem, tmp_path: Path) -> None:
    """Test a serialized input is read back unchanged."""
    path = tmp_path / "input.bin"
    problem.serialize_input([5, -2, 9], path)

    values = problem.deserialize_input(path)

    assert values == [5, -2, 9]


def test_an_input_file_with_trailing_bytes_is_named_as_such(
    problem: SortingProblem, tmp_path: Path
) -> None:
    """Test an input file with trailing bytes is rejected and called an input file."""
    path = tmp_path / "input.bin"
    path.write_bytes(struct.pack("<Q1i", 1, 3) + b"\x00")

    with pytest.raises(BinaryFormatError, match="The input file has trailing bytes"):
        problem.deserialize_input(path)


def test_the_error_for_a_value_out_of_range_names_its_index(
    problem: SortingProblem, tmp_path: Path
) -> None:
    """Test the error for an out-of-range value names the index of the value."""
    with pytest.raises(ValueError, match=r"Value at index 1 is out of i32 range"):
        problem.serialize_input([1, 2**31, 3], tmp_path / "input.bin")


def test_output_rejects_trailing_bytes(problem: SortingProblem, tmp_path: Path) -> None:
    """Test an output file with trailing bytes is rejected."""
    path = tmp_path / "bad.bin"
    path.write_bytes(struct.pack("<Q3i", 3, 1, 2, 3) + b"\x00")

    with pytest.raises(BinaryFormatError, match="trailing bytes"):
        problem.deserialize_output(path)


def test_output_rejects_a_count_larger_than_the_file(
    problem: SortingProblem, tmp_path: Path
) -> None:
    """Test an output file that declares more values than it holds is rejected."""
    path = tmp_path / "huge.bin"
    path.write_bytes(struct.pack("<Q", 2**64 - 1))

    with pytest.raises(BinaryFormatError, match="Declared"):
        problem.deserialize_output(path)


def test_output_rejects_a_missing_header(
    problem: SortingProblem, tmp_path: Path
) -> None:
    """Test an output file shorter than its count header is rejected."""
    path = tmp_path / "short.bin"
    path.write_bytes(b"\x01\x00")

    with pytest.raises(BinaryFormatError, match="Unexpected end of stream"):
        problem.deserialize_output(path)


I32_VALUES = strategies.lists(strategies.integers(-(2**31), 2**31 - 1))


@given(I32_VALUES)
def test_any_i32_values_are_read_back_from_the_file_unchanged(
    tmp_path_factory: pytest.TempPathFactory, values: list[int]
) -> None:
    """Test every list of i32 values survives a write and a read of the file."""
    path = tmp_path_factory.mktemp("values") / "values.bin"
    write_values(values, path)

    assert read_values(path) == values


@given(I32_VALUES, strategies.data())
def test_a_value_file_cut_short_is_a_format_error(
    tmp_path_factory: pytest.TempPathFactory,
    values: list[int],
    data: strategies.DataObject,
) -> None:
    """Test a value file that lost any of its bytes cannot be read."""
    path = tmp_path_factory.mktemp("values") / "values.bin"
    write_values(values, path)
    whole = path.read_bytes()
    path.write_bytes(whole[: data.draw(strategies.integers(0, len(whole) - 1))])

    with pytest.raises(
        BinaryFormatError, match=r"^Unexpected end of stream|^Declared \d+ i32 values"
    ):
        read_values(path)


@given(I32_VALUES, strategies.binary(min_size=1))
def test_bytes_after_the_values_are_a_format_error(
    tmp_path_factory: pytest.TempPathFactory, values: list[int], extra: bytes
) -> None:
    """Test a value file with anything after its values cannot be read."""
    path = tmp_path_factory.mktemp("values") / "values.bin"
    write_values(values, path)
    path.write_bytes(path.read_bytes() + extra)

    with pytest.raises(
        BinaryFormatError, match=r"^The file has trailing bytes after its last field$"
    ):
        read_values(path)
