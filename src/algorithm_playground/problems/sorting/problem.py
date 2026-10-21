"""The reference v1 sorting problem.

The sortable values are 32-bit signed integers. The binary format is
documented in :mod:`docs.problems.sorting`; in brief:

* Input/output: ``u64 count`` followed by ``count`` little-endian ``i32`` values.
* Trace (optional): ``u32 kind`` (``0`` = state snapshots), then ``u32
  snapshot_count`` and that many array snapshots in the same layout as the
  input/output bodies.
"""

from __future__ import annotations

import random
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

from algorithm_playground.core.binary_io import (
    BinaryFormatError,
    read_i32_array,
    read_u32,
    read_u64,
    write_i32_array,
    write_u64,
)
from algorithm_playground.core.problem import (
    BenchmarkCase,
    Problem,
    TestCase,
    VerificationResult,
)
from algorithm_playground.core.registry import register_problem
from algorithm_playground.visualization import (
    StepperOptions,
    bar_chart,
    side_by_side_bar_charts,
    step_through,
)

I32_MIN = -(2**31)
I32_MAX = 2**31 - 1
SNAPSHOT_TRACE_KIND = 0


@dataclass(frozen=True)
class SortingTrace:
    """A trace produced by an executable running in snapshot mode."""

    snapshots: tuple[tuple[int, ...], ...]


@register_problem
class SortingProblem(Problem[list[int], list[int], SortingTrace]):
    """Sort an array of i32 values in ascending order."""

    name = "sorting"
    description = "Sort an array of 32-bit signed integers in ascending order."

    # ---- Binary I/O ----------------------------------------------------

    def serialize_input(self, data: list[int], path: Path) -> None:
        _validate_i32_range(data)
        with path.open("wb") as stream:
            write_u64(stream, len(data))
            write_i32_array(stream, data)

    def deserialize_output(self, path: Path) -> list[int]:
        with path.open("rb") as stream:
            count = read_u64(stream)
            values = read_i32_array(stream, count)
            remainder = stream.read(1)
        if remainder:
            raise BinaryFormatError(
                "Output file contains trailing bytes beyond the declared element count"
            )
        return values

    def deserialize_trace(self, path: Path) -> SortingTrace | None:
        with path.open("rb") as stream:
            try:
                kind = read_u32(stream)
            except BinaryFormatError:
                return None
            if kind != SNAPSHOT_TRACE_KIND:
                raise BinaryFormatError(
                    f"Unsupported trace kind: {kind}. v1 only understands kind "
                    f"{SNAPSHOT_TRACE_KIND} (state snapshots)."
                )
            snapshot_count = read_u32(stream)
            snapshots: list[tuple[int, ...]] = []
            for _ in range(snapshot_count):
                element_count = read_u64(stream)
                snapshots.append(tuple(read_i32_array(stream, element_count)))
        if not snapshots:
            return None
        return SortingTrace(snapshots=tuple(snapshots))

    # ---- Cases ---------------------------------------------------------

    def test_cases(self) -> Iterator[TestCase[list[int]]]:
        yield TestCase("empty", [])
        yield TestCase("single", [42])
        yield TestCase("two_sorted", [1, 2])
        yield TestCase("two_unsorted", [2, 1])
        yield TestCase("already_sorted", list(range(10)))
        yield TestCase("reverse_sorted", list(range(9, -1, -1)))
        yield TestCase("duplicates", [3, 1, 4, 1, 5, 9, 2, 6, 5, 3])
        yield TestCase("all_equal", [7] * 8)
        yield TestCase("negatives_mixed", [-1, -5, 3, 0, -10, 7, -3, 8])
        yield TestCase(
            "i32_extremes",
            [I32_MAX, I32_MIN, 0, I32_MAX - 1, I32_MIN + 1, -1, 1],
        )

    def benchmark_case(self, seed: int, size: int) -> BenchmarkCase[list[int]]:
        if size < 0:
            raise ValueError(f"Benchmark size must be non-negative, got {size}")
        random_generator = random.Random(seed)
        data = [random_generator.randint(I32_MIN, I32_MAX) for _ in range(size)]
        return BenchmarkCase(name=f"random[seed={seed},size={size}]", size=size, input_data=data)

    # ---- Verification --------------------------------------------------

    def verify(self, input_data: list[int], output: list[int]) -> VerificationResult:
        if len(output) != len(input_data):
            return VerificationResult(
                passed=False,
                message=(
                    f"Output length {len(output)} does not match input length {len(input_data)}"
                ),
            )
        expected = sorted(input_data)
        if output != expected:
            first_difference = _first_difference_index(expected, output)
            return VerificationResult(
                passed=False,
                message=(
                    f"Output is not sorted ascending; first mismatch at index "
                    f"{first_difference}: expected {expected[first_difference]}, "
                    f"got {output[first_difference]}"
                ),
            )
        return VerificationResult(passed=True)

    # ---- Visualization -------------------------------------------------

    def visualize_io(self, input_data: list[int], output: list[int]) -> None:
        if not input_data:
            print("(empty input)")
            return
        side_by_side_bar_charts(
            input_data,
            output,
            left_title="input",
            right_title="output (sorted)",
        )

    def visualize_trace(
        self,
        trace: SortingTrace,
        *,
        auto_advance: bool = False,
        delay_milliseconds: int = 250,
    ) -> None:
        snapshots = trace.snapshots
        if not snapshots:
            print("(empty trace)")
            return
        frames = [
            (
                lambda snapshot=snapshot, index=index: bar_chart(
                    snapshot,
                    title=f"snapshot {index + 1} / {len(snapshots)}",
                )
            )
            for index, snapshot in enumerate(snapshots)
        ]
        step_through(
            frames,
            options=StepperOptions(
                auto_advance=auto_advance,
                delay_milliseconds=delay_milliseconds,
            ),
            header="sorting trace",
        )


def _validate_i32_range(values: list[int]) -> None:
    for index, value in enumerate(values):
        if value < I32_MIN or value > I32_MAX:
            raise ValueError(
                f"Value at index {index} is out of i32 range [{I32_MIN}, {I32_MAX}]: {value}"
            )


def _first_difference_index(expected: list[int], actual: list[int]) -> int:
    for index, (expected_value, actual_value) in enumerate(zip(expected, actual, strict=False)):
        if expected_value != actual_value:
            return index
    return min(len(expected), len(actual))
