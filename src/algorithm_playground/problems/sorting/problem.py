"""The reference sorting problem, wired together from its modules.

The sortable values are 32-bit signed integers. The binary format lives in
:mod:`~algorithm_playground.problems.sorting.codec`,
:mod:`~algorithm_playground.problems.sorting.events` and
:mod:`~algorithm_playground.problems.sorting.trace`, the cases in
:mod:`~algorithm_playground.problems.sorting.fixtures` and
:mod:`~algorithm_playground.problems.sorting.generators`, the verifier in
:mod:`~algorithm_playground.problems.sorting.verification`, and the
stepper frames in :mod:`~algorithm_playground.problems.sorting.frames` and
:mod:`~algorithm_playground.problems.sorting.replay`; this module only
connects them to the :class:`~algorithm_playground.core.problem.Problem`
interface, using the building blocks of the core for the failure reports and
for shrinking. The contract is documented in :doc:`/problems/sorting`.
"""

from __future__ import annotations

from collections.abc import Iterator, Sequence
from pathlib import Path

from algorithm_playground.core.cases import Fixture, InputGenerator
from algorithm_playground.core.description import describe_sequence
from algorithm_playground.core.frames import Frame
from algorithm_playground.core.problem import Problem, VerificationResult
from algorithm_playground.core.registry import register_problem
from algorithm_playground.core.shrinking import shrink_integer_sequence
from algorithm_playground.problems.sorting.codec import read_values, write_values
from algorithm_playground.problems.sorting.fixtures import sorting_fixtures
from algorithm_playground.problems.sorting.frames import (
    sorting_input_output_frame,
    sorting_trace_frames,
)
from algorithm_playground.problems.sorting.generators import sorting_generators
from algorithm_playground.problems.sorting.replay import replay_warnings
from algorithm_playground.problems.sorting.trace import SortingTrace, count_operations, read_trace
from algorithm_playground.problems.sorting.verification import verify_sorted


@register_problem
class SortingProblem(Problem[list[int], list[int], SortingTrace]):
    """Sort an array of i32 values in ascending order."""

    name = "sorting"
    description = "Sort an array of 32-bit signed integers in ascending order."
    # Few distinct values keep the bars of a debug picture readable.
    debug_generator = "small_range"
    operation_names = ("compares", "swaps", "writes")

    # ---- Binary I/O ----------------------------------------------------

    def serialize_input(self, data: list[int], path: Path) -> None:
        write_values(data, path)

    def deserialize_input(self, path: Path) -> list[int]:
        return read_values(path, "The input file")

    def deserialize_output(self, path: Path) -> list[int]:
        return read_values(path, "The output file")

    # ---- Cases ---------------------------------------------------------

    def fixtures(self) -> Iterator[Fixture[list[int]]]:
        return sorting_fixtures()

    def generators(self) -> Sequence[InputGenerator[list[int]]]:
        return sorting_generators()

    # ---- Verification --------------------------------------------------

    def verify(self, input_data: list[int], output: list[int]) -> VerificationResult:
        return verify_sorted(input_data, output)

    # ---- Failure reports and shrinking ---------------------------------

    def expected_output(self, input_data: list[int]) -> list[int]:
        return sorted(input_data)

    def describe_input(self, input_data: list[int], *, limit: int) -> str:
        return describe_sequence(input_data, limit)

    def describe_output(self, output: list[int], *, limit: int, focus: int | None = None) -> str:
        return describe_sequence(output, limit, focus)

    def shrink(self, input_data: list[int]) -> Iterator[list[int]]:
        return shrink_integer_sequence(input_data)

    # ---- Traces ----------------------------------------------------------

    def deserialize_trace(self, path: Path, input_data: list[int]) -> SortingTrace | None:
        return read_trace(path, input_data)

    def operation_counts(
        self, input_data: list[int], output: list[int], trace: SortingTrace
    ) -> dict[str, int] | None:
        return count_operations(trace)

    def trace_warnings(
        self, input_data: list[int], output: list[int], trace: SortingTrace
    ) -> list[str]:
        return replay_warnings(trace, input_data)

    # ---- Visualization -------------------------------------------------

    def input_output_frame(self, input_data: list[int], output: list[int]) -> Frame:
        return sorting_input_output_frame(input_data, output)

    def trace_frames(
        self, input_data: list[int], output: list[int], trace: SortingTrace
    ) -> Sequence[Frame]:
        return sorting_trace_frames(input_data, trace)
