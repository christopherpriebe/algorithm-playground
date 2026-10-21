"""Unit tests for the SortingProblem: format, verifier, fixtures, generators."""

from __future__ import annotations

import struct
from pathlib import Path

import pytest

from algorithm_playground.core.binary_io import BinaryFormatError
from algorithm_playground.problems.sorting import (
    SNAPSHOT_TRACE_KIND,
    SortingProblem,
    SortingTrace,
)
from algorithm_playground.problems.sorting.problem import I32_MAX, I32_MIN


@pytest.fixture
def problem() -> SortingProblem:
    return SortingProblem()


class TestSerialization:
    def test_input_round_trips_through_disk(self, problem: SortingProblem, tmp_path: Path) -> None:
        path = tmp_path / "input.bin"
        problem.serialize_input([-3, 0, 7, I32_MAX, I32_MIN], path)
        raw = path.read_bytes()
        # u64 count = 5, then 5 i32 values
        assert raw[:8] == struct.pack("<Q", 5)
        values = list(struct.unpack_from("<5i", raw, 8))
        assert values == [-3, 0, 7, I32_MAX, I32_MIN]

    def test_input_rejects_value_outside_i32_range(
        self, problem: SortingProblem, tmp_path: Path
    ) -> None:
        with pytest.raises(ValueError, match="out of i32 range"):
            problem.serialize_input([2**31], tmp_path / "input.bin")

    def test_output_round_trip(self, problem: SortingProblem, tmp_path: Path) -> None:
        path = tmp_path / "output.bin"
        path.write_bytes(struct.pack("<Q3i", 3, -1, 0, 5))
        assert problem.deserialize_output(path) == [-1, 0, 5]

    def test_output_rejects_trailing_bytes(self, problem: SortingProblem, tmp_path: Path) -> None:
        path = tmp_path / "bad.bin"
        path.write_bytes(struct.pack("<Q3i", 3, 1, 2, 3) + b"\x00")
        with pytest.raises(BinaryFormatError, match="trailing bytes"):
            problem.deserialize_output(path)


class TestTraceDecoding:
    def test_state_snapshot_trace_decodes(self, problem: SortingProblem, tmp_path: Path) -> None:
        path = tmp_path / "trace.bin"
        snapshots = [[3, 1, 2], [1, 3, 2], [1, 2, 3]]
        buffer = bytearray(struct.pack("<II", SNAPSHOT_TRACE_KIND, len(snapshots)))
        for snapshot in snapshots:
            buffer.extend(struct.pack("<Q", len(snapshot)))
            buffer.extend(struct.pack(f"<{len(snapshot)}i", *snapshot))
        path.write_bytes(bytes(buffer))

        trace = problem.deserialize_trace(path)
        assert isinstance(trace, SortingTrace)
        assert trace.snapshots == ((3, 1, 2), (1, 3, 2), (1, 2, 3))

    def test_empty_trace_returns_none(self, problem: SortingProblem, tmp_path: Path) -> None:
        path = tmp_path / "trace.bin"
        path.write_bytes(b"")
        assert problem.deserialize_trace(path) is None

    def test_unknown_trace_kind_raises(self, problem: SortingProblem, tmp_path: Path) -> None:
        path = tmp_path / "trace.bin"
        path.write_bytes(struct.pack("<I", 99))
        with pytest.raises(BinaryFormatError, match="Unsupported trace kind"):
            problem.deserialize_trace(path)


class TestVerification:
    def test_correct_output_passes(self, problem: SortingProblem) -> None:
        result = problem.verify([3, 1, 2], [1, 2, 3])
        assert result.passed
        assert result.message == ""

    def test_length_mismatch_fails(self, problem: SortingProblem) -> None:
        result = problem.verify([3, 1, 2], [1, 2])
        assert not result.passed
        assert "length" in result.message.lower()

    def test_unsorted_output_fails_with_index(self, problem: SortingProblem) -> None:
        result = problem.verify([3, 1, 2], [1, 3, 2])
        assert not result.passed
        assert "index 1" in result.message


class TestCases:
    def test_test_cases_cover_intended_corner_cases(self, problem: SortingProblem) -> None:
        names = {case.name for case in problem.test_cases()}
        for expected in (
            "empty",
            "single",
            "already_sorted",
            "reverse_sorted",
            "duplicates",
            "all_equal",
            "negatives_mixed",
            "i32_extremes",
        ):
            assert expected in names

    def test_benchmark_case_is_deterministic(self, problem: SortingProblem) -> None:
        first = problem.benchmark_case(seed=123, size=64)
        second = problem.benchmark_case(seed=123, size=64)
        assert first.input_data == second.input_data
        assert all(I32_MIN <= value <= I32_MAX for value in first.input_data)

    def test_benchmark_case_different_seeds_differ(self, problem: SortingProblem) -> None:
        first = problem.benchmark_case(seed=1, size=64)
        second = problem.benchmark_case(seed=2, size=64)
        assert first.input_data != second.input_data

    def test_baseline_case_is_empty(self, problem: SortingProblem) -> None:
        assert problem.baseline_case(seed=5).input_data == []

    def test_negative_benchmark_size_rejected(self, problem: SortingProblem) -> None:
        with pytest.raises(ValueError):
            problem.benchmark_case(seed=0, size=-1)
