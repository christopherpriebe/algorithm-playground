"""A problem that scores its outputs, to test everything a quality score flows through.

The problem is sorting with a relaxed verifier: any permutation of the input
passes, and the score is the number of inversions left in the output. A correct
sorter scores zero; an implementation that returns its input unchanged passes
with the inversions of the input. Lower is better, which the problem does not
declare: the harness only reports the numbers.
"""

from collections.abc import Callable

from typing_extensions import override

from algorithm_playground.authoring import VerificationResult, register_problem
from algorithm_playground.problems.sorting import SortingProblem

PROBLEM_NAME = "near-sorting"


def count_inversions(values: list[int]) -> int:
    """Count the pairs of positions whose values are out of order."""
    return sum(
        1
        for first in range(len(values))
        for second in range(first + 1, len(values))
        if values[first] > values[second]
    )


class NearSortingProblem(SortingProblem):
    """Sorting where any permutation passes, scored by the inversions left in it."""

    name = PROBLEM_NAME
    description = "Sort an array as well as you can; fewer inversions is better."
    score_name = "inversions"

    @override
    def verify(self, input_data: list[int], output: list[int]) -> VerificationResult:
        score = float(count_inversions(output))
        if sorted(output) != sorted(input_data):
            return VerificationResult(
                False,
                message="The output is not a permutation of the input",
                category="not a permutation",
                score=score,
            )
        return VerificationResult(True, score=score)


def register_near_sorting_problem() -> str:
    """Register the scoring problem for the rest of the test; return its name."""
    register_problem(NearSortingProblem)
    return PROBLEM_NAME


def keep_as_is(values: list[int]) -> list[int]:
    """Return the input unchanged, as a lazy implementation of the scoring problem does."""
    return list(values)


def drop_last_keeping_order(values: list[int]) -> list[int]:
    """Lose the last value and leave the rest as it is: not a permutation, still scorable."""
    return list(values)[:-1]


def build_lazy_then_exact() -> Callable[[list[int]], list[int]]:
    """Build an implementation that leaves an input as it is the first time and sorts it after.

    Returns:
        A function that returns each distinct input unchanged on its first run and
        sorted on every later run, so two repetitions on one input score differently.
    """
    seen: set[tuple[int, ...]] = set()

    def run(values: list[int]) -> list[int]:
        key = tuple(values)
        if key in seen:
            return sorted(values)
        seen.add(key)
        return list(values)

    return run
