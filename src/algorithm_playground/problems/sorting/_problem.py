"""The reference sorting problem, wired together from its modules.

The sortable values are 32-bit signed integers. The binary format is read and
written by :func:`~algorithm_playground.problems.sorting.write_values`,
:func:`~algorithm_playground.problems.sorting.read_values` and
:func:`~algorithm_playground.problems.sorting.read_trace`, the cases come from
:func:`~algorithm_playground.problems.sorting.build_sorting_fixtures` and
:func:`~algorithm_playground.problems.sorting.build_sorting_generators`, the verifier
is :func:`~algorithm_playground.problems.sorting.verify_sorted`, and the stepper
frames come from :func:`~algorithm_playground.problems.sorting.draw_sorting_trace_frames`
and :func:`~algorithm_playground.problems.sorting.draw_sorting_input_output_frame`;
this module only connects them to the :class:`~algorithm_playground.core.Problem`
interface, using the building blocks of the core for the failure reports and
for shrinking. The contract is documented in :doc:`/problems/sorting`.
"""

from collections.abc import Iterator, Sequence
from pathlib import Path

from typing_extensions import override

from algorithm_playground.core._cases import Fixture, InputGenerator
from algorithm_playground.core._description import describe_sequence
from algorithm_playground.core._frames import Frame
from algorithm_playground.core._problem import Problem, VerificationResult
from algorithm_playground.core._registry import register_problem
from algorithm_playground.core._shrinking import shrink_integer_sequence
from algorithm_playground.problems.sorting._codec import read_values, write_values
from algorithm_playground.problems.sorting._fixtures import build_sorting_fixtures
from algorithm_playground.problems.sorting._frames import (
    draw_sorting_input_output_frame,
    draw_sorting_trace_frames,
)
from algorithm_playground.problems.sorting._generators import build_sorting_generators
from algorithm_playground.problems.sorting._replay import find_replay_warnings
from algorithm_playground.problems.sorting._trace import (
    SortingTrace,
    count_operations,
    read_trace,
)
from algorithm_playground.problems.sorting._verification import verify_sorted

__all__ = ["SortingProblem"]


@register_problem
class SortingProblem(Problem[list[int], list[int], SortingTrace]):
    """Sort an array of i32 values in ascending order."""

    name = "sorting"
    description = "Sort an array of 32-bit signed integers in ascending order."
    # Few distinct values keep the bars of a debug picture readable.
    debug_generator = "small_range"
    operation_names = ("compares", "swaps", "writes")

    # ---- Binary I/O ----------------------------------------------------

    @override
    def serialize_input(self, data: list[int], path: Path) -> None:
        write_values(data, path)

    @override
    def deserialize_input(self, path: Path) -> list[int]:
        return read_values(path, "The input file")

    @override
    def deserialize_output(self, path: Path) -> list[int]:
        return read_values(path, "The output file")

    # ---- Cases ---------------------------------------------------------

    @override
    def fixtures(self) -> Iterator[Fixture[list[int]]]:
        return build_sorting_fixtures()

    @override
    def generators(self) -> Sequence[InputGenerator[list[int]]]:
        return build_sorting_generators()

    # ---- Verification --------------------------------------------------

    @override
    def verify(self, input_data: list[int], output: list[int]) -> VerificationResult:
        return verify_sorted(input_data, output)

    # ---- Failure reports and shrinking ---------------------------------

    @override
    def expected_output(self, input_data: list[int]) -> list[int]:
        return sorted(input_data)

    @override
    def describe_input(self, input_data: list[int], *, limit: int) -> str:
        return describe_sequence(input_data, limit)

    @override
    def describe_output(
        self, output: list[int], *, limit: int, focus: int | None = None
    ) -> str:
        return describe_sequence(output, limit, focus)

    @override
    def shrink(self, input_data: list[int]) -> Iterator[list[int]]:
        return shrink_integer_sequence(input_data)

    # ---- Traces ----------------------------------------------------------

    @override
    def deserialize_trace(
        self, path: Path, input_data: list[int]
    ) -> SortingTrace | None:
        return read_trace(path, input_data)

    @override
    def operation_counts(
        self, input_data: list[int], output: list[int], trace: SortingTrace
    ) -> dict[str, int] | None:
        return count_operations(trace)

    @override
    def trace_warnings(
        self, input_data: list[int], output: list[int], trace: SortingTrace
    ) -> list[str]:
        return find_replay_warnings(trace, input_data)

    # ---- Visualization -------------------------------------------------

    @override
    def input_output_frame(self, input_data: list[int], output: list[int]) -> Frame:
        return draw_sorting_input_output_frame(input_data, output)

    @override
    def trace_frames(
        self, input_data: list[int], output: list[int], trace: SortingTrace
    ) -> Sequence[Frame]:
        return draw_sorting_trace_frames(input_data, trace)
